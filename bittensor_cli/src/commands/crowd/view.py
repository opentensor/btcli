from typing import Optional

import asyncio
import json
from bittensor_wallet import Wallet
from rich import box
from rich.table import Column, Table

from bittensor_cli.src import COLORS
from bittensor_cli.src.bittensor.balances import Balance
from bittensor_cli.src.bittensor.chain_data import CrowdloanData
from bittensor_cli.src.bittensor.subtensor_interface import SubtensorInterface
from bittensor_cli.src.bittensor.utils import (
    blocks_to_duration,
    console,
    json_console,
    print_error,
    millify_tao,
)


def _shorten(account: str | None) -> str:
    if not account:
        return "-"
    return f"{account[:6]}…{account[-6:]}"


def _status(loan: CrowdloanData, current_block: int) -> str:
    if loan.finalized:
        return "Finalized"
    if loan.raised >= loan.cap:
        return "Funded"
    if current_block >= loan.end:
        return "Closed"
    return "Active"


def _time_remaining(loan: CrowdloanData, current_block: int) -> str:
    diff = loan.end - current_block
    if diff > 0:
        return blocks_to_duration(diff)
    if diff == 0:
        return "due"
    return f"Closed {blocks_to_duration(abs(diff))} ago"


async def list_crowdloans(
    subtensor: SubtensorInterface,
    verbose: bool = False,
    json_output: bool = False,
) -> bool:
    """List all crowdloans in a tabular format or JSON output."""

    current_block, loans = await asyncio.gather(
        subtensor.substrate.get_block_number(None),
        subtensor.get_crowdloans(),
    )
    if not loans:
        if json_output:
            json_console.print(
                json.dumps(
                    {
                        "success": True,
                        "error": None,
                        "data": {
                            "crowdloans": [],
                            "total_count": 0,
                            "total_raised": 0,
                            "total_cap": 0,
                            "total_contributors": 0,
                        },
                    }
                )
            )
        else:
            console.print("[yellow]No crowdloans found.[/yellow]")
        return True

    total_raised = sum(loan.raised.tao for loan in loans.values())
    total_cap = sum(loan.cap.tao for loan in loans.values())
    total_loans = len(loans)
    total_contributors = sum(loan.contributors_count for loan in loans.values())

    funding_percentage = (total_raised / total_cap * 100) if total_cap > 0 else 0
    percentage_color = "dark_sea_green" if funding_percentage < 100 else "red"
    formatted_percentage = (
        f"[{percentage_color}]{funding_percentage:.2f}%[/{percentage_color}]"
    )

    if json_output:
        crowdloans_list = []
        for loan_id, loan in loans.items():
            status = _status(loan, current_block)
            time_remaining = _time_remaining(loan, current_block)

            call_info = None
            if loan.call_details:
                pallet = loan.call_details.get("pallet", "")
                method = loan.call_details.get("method", "")
                if pallet == "SubtensorModule" and method == "register_leased_network":
                    call_info = "Subnet Leasing"
                else:
                    call_info = (
                        f"{pallet}.{method}"
                        if pallet and method
                        else method or pallet or "Unknown"
                    )
            elif loan.has_call:
                call_info = "Unknown"

            crowdloan_data = {
                "id": loan_id,
                "status": status,
                "raised": loan.raised.tao,
                "cap": loan.cap.tao,
                "deposit": loan.deposit.tao,
                "min_contribution": loan.min_contribution.tao,
                "end_block": loan.end,
                "time_remaining": time_remaining,
                "contributors_count": loan.contributors_count,
                "creator": loan.creator,
                "target_address": loan.target_address,
                "funds_account": loan.funds_account,
                "call": call_info,
                "finalized": loan.finalized,
            }
            crowdloans_list.append(crowdloan_data)

        crowdloans_list.sort(
            key=lambda x: (
                x["status"] != "Active",
                -x["raised"],
            )
        )

        output_dict = {
            "success": True,
            "error": None,
            "data": {
                "crowdloans": crowdloans_list,
                "total_count": total_loans,
                "total_raised": total_raised,
                "total_cap": total_cap,
                "total_contributors": total_contributors,
                "funding_percentage": funding_percentage,
                "current_block": current_block,
                "network": subtensor.network,
            },
        }
        json_console.print(json.dumps(output_dict))
        return True

    if not verbose:
        funding_string = f"τ {millify_tao(total_raised)}/{millify_tao(total_cap)} ({formatted_percentage})"
    else:
        funding_string = (
            f"τ {total_raised:.1f}/{total_cap:.1f} ({formatted_percentage})"
        )

    table = Table(
        title=f"\n[{COLORS.G.HEADER}]Crowdloans"
        f"\nNetwork: [{COLORS.G.SUBHEAD}]{subtensor.network}\n\n",
        show_footer=True,
        show_edge=False,
        header_style="bold white",
        border_style="bright_black",
        style="bold",
        title_justify="center",
        show_lines=False,
        pad_edge=True,
    )

    table.add_column(
        "[bold white]ID", style="grey89", justify="center", footer=str(total_loans)
    )
    table.add_column("[bold white]Status", style="cyan", justify="center")
    table.add_column(
        f"[bold white]Raised / Cap\n({Balance.get_unit(0)})",
        style="dark_sea_green2",
        justify="left",
        footer=funding_string,
    )
    table.add_column(
        f"[bold white]Deposit\n({Balance.get_unit(0)})",
        style="steel_blue3",
        justify="left",
    )
    table.add_column(
        f"[bold white]Min Contribution\n({Balance.get_unit(0)})",
        style=COLORS.P.EMISSION,
        justify="left",
    )
    table.add_column("[bold white]Ends (Block)", style=COLORS.S.TAO, justify="left")
    table.add_column(
        "[bold white]Time Remaining",
        style=COLORS.S.ALPHA,
        justify="left",
    )
    table.add_column(
        "[bold white]Contributors",
        style=COLORS.P.ALPHA_IN,
        justify="center",
        footer=str(total_contributors),
    )
    table.add_column(
        "[bold white]Creator",
        style=COLORS.G.TEMPO,
        justify="left",
        overflow="fold",
    )
    table.add_column(
        "[bold white]Target",
        style=COLORS.G.SUBHEAD_EX_1,
        justify="center",
    )
    table.add_column(
        "[bold white]Funds Account",
        style=COLORS.G.SUBHEAD_EX_2,
        justify="left",
        overflow="fold",
    )
    table.add_column("[bold white]Call", style="grey89", justify="center")

    sorted_loans = sorted(
        loans.items(),
        key=lambda x: (
            _status(x[1], current_block) != "Active",  # Active loans first
            -x[1].raised.tao,  # Then by raised amount (descending)
        ),
    )

    for loan_id, loan in sorted_loans:
        status = _status(loan, current_block)
        time_label = _time_remaining(loan, current_block)

        raised_cell = (
            f"τ {loan.raised.tao:,.4f} / τ {loan.cap.tao:,.4f}"
            if verbose
            else f"τ {millify_tao(loan.raised.tao)} / τ {millify_tao(loan.cap.tao)}"
        )

        deposit_cell = (
            f"τ {loan.deposit.tao:,.4f}"
            if verbose
            else f"τ {millify_tao(loan.deposit.tao)}"
        )

        min_contrib_cell = (
            f"τ {loan.min_contribution.tao:,.4f}"
            if verbose
            else f"τ {millify_tao(loan.min_contribution.tao)}"
        )

        status_color_map = {
            "Finalized": COLORS.G.SUCCESS,
            "Funded": COLORS.P.EMISSION,
            "Closed": COLORS.G.SYM,
            "Active": COLORS.G.HINT,
        }
        status_color = status_color_map.get(status, "white")
        status_cell = f"[{status_color}]{status}[/{status_color}]"

        if "Closed" in time_label:
            time_cell = f"[{COLORS.G.SYM}]{time_label}[/{COLORS.G.SYM}]"
        elif time_label == "due":
            time_cell = f"[red]{time_label}[/red]"
        else:
            time_cell = time_label

        creator_cell = loan.creator if verbose else _shorten(loan.creator)
        target_cell = (
            loan.target_address
            if loan.target_address
            else f"[{COLORS.G.SUBHEAD_MAIN}]Not specified[/{COLORS.G.SUBHEAD_MAIN}]"
        )
        if not verbose and loan.target_address:
            target_cell = _shorten(loan.target_address)

        funds_account_cell = (
            loan.funds_account if verbose else _shorten(loan.funds_account)
        )

        if loan.call_details:
            pallet = loan.call_details.get("pallet", "")
            method = loan.call_details.get("method", "")

            if pallet == "SubtensorModule" and method == "register_leased_network":
                call_label = "[magenta]Subnet Leasing[/magenta]"
            else:
                call_label = (
                    f"{pallet}.{method}"
                    if pallet and method
                    else method or pallet or "Unknown"
                )

            call_cell = call_label
        elif loan.has_call:
            call_cell = f"[{COLORS.G.SYM}]Unknown[/{COLORS.G.SYM}]"
        else:
            call_cell = "-"

        table.add_row(
            str(loan_id),
            status_cell,
            raised_cell,
            deposit_cell,
            min_contrib_cell,
            str(loan.end),
            time_cell,
            str(loan.contributors_count),
            creator_cell,
            target_cell,
            funds_account_cell,
            call_cell,
        )

    console.print(table)

    return True


async def show_crowdloan_details(
    subtensor: SubtensorInterface,
    crowdloan_id: int,
    crowdloan: Optional[CrowdloanData] = None,
    current_block: Optional[int] = None,
    wallet: Optional[Wallet] = None,
    verbose: bool = False,
    json_output: bool = False,
) -> tuple[bool, str]:
    """Display detailed information about a specific crowdloan."""

    if not crowdloan or not current_block:
        current_block, crowdloan = await asyncio.gather(
            subtensor.substrate.get_block_number(None),
            subtensor.get_single_crowdloan(crowdloan_id),
        )
    if not crowdloan:
        error_msg = f"Crowdloan #{crowdloan_id} not found."
        if json_output:
            json_console.print(json.dumps({"success": False, "error": error_msg}))
        else:
            print_error(f"[red]{error_msg}[/red]")
        return False, error_msg

    user_contribution = None
    if wallet and wallet.coldkeypub:
        user_contribution = await subtensor.get_crowdloan_contribution(
            crowdloan_id, wallet.coldkeypub.ss58_address
        )

    status = _status(crowdloan, current_block)
    status_color_map = {
        "Finalized": COLORS.G.SUCCESS,
        "Funded": COLORS.P.EMISSION,
        "Closed": COLORS.G.SYM,
        "Active": COLORS.G.HINT,
    }
    status_color = status_color_map.get(status, "white")

    if json_output:
        time_remaining = _time_remaining(crowdloan, current_block)

        avg_contribution = None
        if crowdloan.contributors_count > 0:
            net_contributions = crowdloan.raised.tao - crowdloan.deposit.tao
            avg_contribution = (
                net_contributions / (crowdloan.contributors_count - 1)
                if crowdloan.contributors_count > 1
                else crowdloan.deposit.tao
            )

        call_info = None
        if crowdloan.has_call and crowdloan.call_details:
            pallet = crowdloan.call_details.get("pallet", "Unknown")
            method = crowdloan.call_details.get("method", "Unknown")
            args = crowdloan.call_details.get("args", {})

            if pallet == "SubtensorModule" and method == "register_leased_network":
                call_info = {
                    "type": "Subnet Leasing",
                    "pallet": pallet,
                    "method": method,
                    "emissions_share": args.get("emissions_share", {}).get("value"),
                    "end_block": args.get("end_block", {}).get("value"),
                }
            else:
                call_info = {"pallet": pallet, "method": method, "args": args}

        user_contribution_info = None
        if user_contribution:
            is_creator = (
                wallet
                and wallet.coldkeypub
                and wallet.coldkeypub.ss58_address == crowdloan.creator
            )
            withdrawable_amount = None

            if status == "Active" and not crowdloan.finalized:
                if is_creator and user_contribution.tao > crowdloan.deposit.tao:
                    withdrawable_amount = user_contribution.tao - crowdloan.deposit.tao
                elif not is_creator:
                    withdrawable_amount = user_contribution.tao

            user_contribution_info = {
                "amount": user_contribution.tao,
                "is_creator": is_creator,
                "withdrawable": withdrawable_amount,
                "refundable": status == "Closed",
            }

        output_dict = {
            "success": True,
            "error": None,
            "data": {
                "crowdloan_id": crowdloan_id,
                "status": status,
                "finalized": crowdloan.finalized,
                "creator": crowdloan.creator,
                "funds_account": crowdloan.funds_account,
                "raised": crowdloan.raised.tao,
                "cap": crowdloan.cap.tao,
                "raised_percentage": (crowdloan.raised.tao / crowdloan.cap.tao * 100)
                if crowdloan.cap.tao > 0
                else 0,
                "deposit": crowdloan.deposit.tao,
                "min_contribution": crowdloan.min_contribution.tao,
                "end_block": crowdloan.end,
                "current_block": current_block,
                "time_remaining": time_remaining,
                "contributors_count": crowdloan.contributors_count,
                "average_contribution": avg_contribution,
                "target_address": crowdloan.target_address,
                "has_call": crowdloan.has_call,
                "call_details": call_info,
                "user_contribution": user_contribution_info,
                "network": subtensor.network,
            },
        }
        json_console.print(json.dumps(output_dict))
        return True, f"Displayed info for crowdloan #{crowdloan_id}"

    table = Table(
        Column(
            "Field",
            style=COLORS.G.SUBHEAD,
            min_width=20,
            no_wrap=True,
        ),
        Column("Value", style=COLORS.G.TEMPO),
        title=f"\n[underline][{COLORS.G.HEADER}]CROWDLOAN #{crowdloan_id}[/underline][/{COLORS.G.HEADER}] - [{status_color} underline]{status.upper()}[/{status_color} underline]",
        show_header=False,
        show_footer=False,
        width=None,
        pad_edge=False,
        box=box.SIMPLE,
        show_edge=True,
        border_style="bright_black",
        expand=False,
    )

    # OVERVIEW Section
    table.add_row("[cyan underline]OVERVIEW[/cyan underline]", "")
    table.add_section()

    status_detail = ""
    if status == "Active":
        status_detail = " [dim](accepting contributions)[/dim]"
    elif status == "Funded":
        status_detail = " [yellow](awaiting finalization)[/yellow]"
    elif status == "Closed":
        status_detail = " [dim](failed to reach cap)[/dim]"
    elif status == "Finalized":
        status_detail = " [green](successfully completed)[/green]"

    table.add_row("Status", f"[{status_color}]{status}[/{status_color}]{status_detail}")
    table.add_row(
        "Creator",
        f"[{COLORS.G.TEMPO}]{crowdloan.creator}[/{COLORS.G.TEMPO}]",
    )
    table.add_row(
        "Funds Account",
        f"[{COLORS.G.SUBHEAD_EX_2}]{crowdloan.funds_account}[/{COLORS.G.SUBHEAD_EX_2}]",
    )

    # FUNDING PROGRESS Section
    table.add_section()
    table.add_row("[cyan underline]FUNDING PROGRESS[/cyan underline]", "")
    table.add_section()

    raised_pct = (
        (crowdloan.raised.tao / crowdloan.cap.tao * 100) if crowdloan.cap.tao > 0 else 0
    )
    progress_filled = int(raised_pct / 100 * 16)
    progress_empty = 16 - progress_filled
    progress_bar = f"[dark_sea_green]{'█' * progress_filled}[/dark_sea_green][grey35]{'░' * progress_empty}[/grey35]"

    if verbose:
        raised_str = f"τ {crowdloan.raised.tao:,.4f} / τ {crowdloan.cap.tao:,.4f}"
        deposit_str = f"τ {crowdloan.deposit.tao:,.4f}"
        min_contrib_str = f"τ {crowdloan.min_contribution.tao:,.4f}"
    else:
        raised_str = f"τ {millify_tao(crowdloan.raised.tao)} / τ {millify_tao(crowdloan.cap.tao)}"
        deposit_str = f"τ {millify_tao(crowdloan.deposit.tao)}"
        min_contrib_str = f"τ {millify_tao(crowdloan.min_contribution.tao)}"

    table.add_row("Raised/Cap", raised_str)
    table.add_row(
        "Progress", f"{progress_bar} [dark_sea_green]{raised_pct:.2f}%[/dark_sea_green]"
    )
    table.add_row("Deposit", deposit_str)
    table.add_row("Min Contribution", min_contrib_str)

    # TIMELINE Section
    table.add_section()
    table.add_row("[cyan underline]TIMELINE[/cyan underline]", "")
    table.add_section()

    time_label = _time_remaining(crowdloan, current_block)
    if "Closed" in time_label:
        time_display = f"[{COLORS.G.SYM}]{time_label}[/{COLORS.G.SYM}]"
    elif time_label == "due":
        time_display = "[red]Due now[/red]"
    else:
        time_display = f"[{COLORS.S.ALPHA}]{time_label}[/{COLORS.S.ALPHA}]"

    table.add_row("Ends at Block", f"{crowdloan.end}")
    table.add_row("Current Block", f"{current_block}")
    table.add_row("Time Remaining", time_display)

    # PARTICIPATION Section
    table.add_section()
    table.add_row("[cyan underline]PARTICIPATION[/cyan underline]", "")
    table.add_section()

    table.add_row("Contributors", f"{crowdloan.contributors_count}")

    if crowdloan.contributors_count > 0:
        net_contributions = crowdloan.raised.tao - crowdloan.deposit.tao
        avg_contribution = (
            net_contributions / (crowdloan.contributors_count - 1)
            if crowdloan.contributors_count > 1
            else crowdloan.deposit.tao
        )
        if verbose:
            avg_contrib_str = f"τ {avg_contribution:,.4f}"
        else:
            avg_contrib_str = f"τ {millify_tao(avg_contribution)}"
        table.add_row("Avg Contribution", avg_contrib_str)

    if user_contribution:
        is_creator = wallet.coldkeypub.ss58_address == crowdloan.creator
        if verbose:
            user_contrib_str = f"τ {user_contribution.tao:,.4f}"
        else:
            user_contrib_str = f"τ {millify_tao(user_contribution.tao)}"

        contrib_status = ""
        if status == "Active" and not crowdloan.finalized:
            if is_creator and user_contribution.tao > crowdloan.deposit.tao:
                withdrawable = user_contribution.tao - crowdloan.deposit.tao
                if verbose:
                    withdrawable_str = f"{withdrawable:,.4f}"
                else:
                    withdrawable_str = f"{millify_tao(withdrawable)}"
                contrib_status = (
                    f" [yellow](τ {withdrawable_str} withdrawable)[/yellow]"
                )
            elif not is_creator:
                contrib_status = " [yellow](withdrawable)[/yellow]"
        elif status == "Closed":
            contrib_status = " [green](refundable)[/green]"

        your_contrib_value = f"{user_contrib_str}{contrib_status}"
        if is_creator:
            your_contrib_value += " [dim](You are the creator)[/dim]"
        table.add_row("Your Contribution", your_contrib_value)

    # TARGET Section
    table.add_section()
    table.add_row("[cyan underline]TARGET[/cyan underline]", "")
    table.add_section()

    if crowdloan.target_address:
        target_display = crowdloan.target_address
    else:
        target_display = (
            f"[{COLORS.G.SUBHEAD_MAIN}]Not specified[/{COLORS.G.SUBHEAD_MAIN}]"
        )

    table.add_row("Address", target_display)

    table.add_section()
    table.add_row("[cyan underline]CALL DETAILS[/cyan underline]", "")
    table.add_section()

    has_call_display = (
        f"[{COLORS.G.SUCCESS}]Yes[/{COLORS.G.SUCCESS}]"
        if crowdloan.has_call
        else f"[{COLORS.G.SYM}]No[/{COLORS.G.SYM}]"
    )
    table.add_row("Has Call", has_call_display)

    if crowdloan.has_call and crowdloan.call_details:
        pallet = crowdloan.call_details.get("pallet", "Unknown")
        method = crowdloan.call_details.get("method", "Unknown")
        args = crowdloan.call_details.get("args", {})

        if pallet == "SubtensorModule" and method == "register_leased_network":
            table.add_row("Type", "[magenta]Subnet Leasing[/magenta]")
            emissions_share = args.get("emissions_share", {}).get("value")
            if emissions_share is not None:
                table.add_row("Emissions Share", f"[cyan]{emissions_share}%[/cyan]")

            end_block = args.get("end_block", {}).get("value")
            if end_block:
                table.add_row("Lease Ends", f"Block {end_block}")
            else:
                table.add_row("Lease Duration", "[green]Perpetual[/green]")
        else:
            table.add_row("Pallet", pallet)
            table.add_row("Method", method)
            if args:
                for arg_name, arg_data in args.items():
                    if isinstance(arg_data, dict):
                        display_value = arg_data.get("value")
                        arg_type = arg_data.get("type")
                    else:
                        display_value = arg_data
                        arg_type = None

                    if arg_type:
                        table.add_row(
                            f"{arg_name} [{arg_type}]",
                            str(display_value),
                        )
                    else:
                        table.add_row(arg_name, str(display_value))

    console.print(table)
    return True, f"Displayed info for crowdloan #{crowdloan_id}"
