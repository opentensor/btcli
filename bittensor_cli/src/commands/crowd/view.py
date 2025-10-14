from typing import Optional

import asyncio
from bittensor_wallet import Wallet
from rich.table import Table

from bittensor_cli.src import COLOR_PALETTE, COLORS
from bittensor_cli.src.bittensor.balances import Balance
from bittensor_cli.src.bittensor.chain_data import CrowdloanData
from bittensor_cli.src.bittensor.subtensor_interface import SubtensorInterface
from bittensor_cli.src.bittensor.utils import (
    blocks_to_duration,
    console,
    err_console,
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
) -> bool:
    """List all crowdloans in a tabular format."""

    current_block, loans = await asyncio.gather(
        subtensor.substrate.get_block_number(None),
        subtensor.get_crowdloans(),
    )
    if not loans:
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

    if not verbose:
        funding_string = f"τ {millify_tao(total_raised)}/{millify_tao(total_cap)} ({formatted_percentage})"
    else:
        funding_string = (
            f"τ {total_raised:.1f}/{total_cap:.1f} ({formatted_percentage})"
        )

    table = Table(
        title=f"\n[{COLOR_PALETTE['GENERAL']['HEADER']}]Crowdloans"
        f"\nNetwork: [{COLOR_PALETTE['GENERAL']['SUBHEADING']}]{subtensor.network}\n\n",
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
        style=COLOR_PALETTE["POOLS"]["EMISSION"],
        justify="left",
    )
    table.add_column(
        "[bold white]Ends (Block)", style=COLOR_PALETTE["STAKE"]["TAO"], justify="left"
    )
    table.add_column(
        "[bold white]Time Remaining",
        style=COLOR_PALETTE["STAKE"]["STAKE_ALPHA"],
        justify="left",
    )
    table.add_column(
        "[bold white]Contributors",
        style=COLOR_PALETTE["POOLS"]["ALPHA_IN"],
        justify="center",
        footer=str(total_contributors),
    )
    table.add_column(
        "[bold white]Creator",
        style=COLOR_PALETTE["GENERAL"]["TEMPO"],
        justify="left",
        overflow="fold",
    )
    table.add_column(
        "[bold white]Target",
        style=COLOR_PALETTE["GENERAL"]["SUBHEADING_EXTRA_1"],
        justify="center",
    )
    table.add_column(
        "[bold white]Funds Account",
        style=COLOR_PALETTE["GENERAL"]["SUBHEADING_EXTRA_2"],
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
            "Finalized": COLOR_PALETTE["GENERAL"]["SUCCESS"],
            "Funded": COLOR_PALETTE["POOLS"]["EMISSION"],
            "Closed": COLOR_PALETTE["GENERAL"]["SYMBOL"],
            "Active": COLOR_PALETTE["GENERAL"]["HINT"],
        }
        status_color = status_color_map.get(status, "white")
        status_cell = f"[{status_color}]{status}[/{status_color}]"

        if "Closed" in time_label:
            time_cell = f"[{COLOR_PALETTE['GENERAL']['SYMBOL']}]{time_label}[/{COLOR_PALETTE['GENERAL']['SYMBOL']}]"
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

        call_cell = (
            f"[{COLOR_PALETTE['GENERAL']['SUCCESS']}]Yes[/{COLOR_PALETTE['GENERAL']['SUCCESS']}]"
            if loan.has_call
            else f"[{COLOR_PALETTE['GENERAL']['SYMBOL']}]No[/{COLOR_PALETTE['GENERAL']['SYMBOL']}]"
        )

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
    wallet: Optional[Wallet] = None,
    verbose: bool = False,
) -> tuple[bool, str]:
    """Display detailed information about a specific crowdloan."""

    current_block, loan = await asyncio.gather(
        subtensor.substrate.get_block_number(None),
        subtensor.get_single_crowdloan(crowdloan_id),
    )
    if not loan:
        err_console.print(f"[red]Crowdloan #{crowdloan_id} not found.[/red]")
        return False, f"Crowdloan #{crowdloan_id} not found."

    user_contribution = None
    if wallet and wallet.coldkeypub:
        user_contribution = await subtensor.get_crowdloan_contribution(
            crowdloan_id, wallet.coldkeypub.ss58_address
        )

    # Overview section
    status = _status(loan, current_block)
    status_color_map = {
        "Finalized": COLOR_PALETTE["GENERAL"]["SUCCESS"],
        "Funded": COLOR_PALETTE["POOLS"]["EMISSION"],
        "Closed": COLOR_PALETTE["GENERAL"]["SYMBOL"],
        "Active": COLOR_PALETTE["GENERAL"]["HINT"],
    }
    status_color = status_color_map.get(status, "white")
    header = f"[bold white]CROWDLOAN #{crowdloan_id}[/bold white] - [{status_color}]{status.upper()}[/{status_color}]"
    sections = []
    overview_lines = [
        f"[bold white]Status:[/bold white]\t\t[{status_color}]{status}[/{status_color}]",
    ]

    if status == "Active":
        overview_lines.append("\t\t\t[dim](accepting contributions)[/dim]")
    elif status == "Funded":
        overview_lines.append("\t\t\t[yellow](awaiting finalization)[/yellow]")
    elif status == "Closed":
        overview_lines.append("\t\t\t[dim](failed to reach cap)[/dim]")
    elif status == "Finalized":
        overview_lines.append("\t\t\t[green](successfully completed)[/green]")

    creator_display = loan.creator
    funds_display = loan.funds_account

    overview_lines.extend(
        [
            f"[bold white]Creator:[/bold white]\t\t[{COLOR_PALETTE['GENERAL']['TEMPO']}]{creator_display}[/{COLOR_PALETTE['GENERAL']['TEMPO']}]",
            f"[bold white]Funds Account:[/bold white]\t[{COLOR_PALETTE['GENERAL']['SUBHEADING_EXTRA_2']}]{funds_display}[/{COLOR_PALETTE['GENERAL']['SUBHEADING_EXTRA_2']}]",
        ]
    )
    sections.append(("\n[bold cyan]OVERVIEW[/bold cyan]", "\n".join(overview_lines)))

    # Funding Progress section
    raised_pct = (loan.raised.tao / loan.cap.tao * 100) if loan.cap.tao > 0 else 0
    progress_filled = int(raised_pct / 100 * 16)
    progress_empty = 16 - progress_filled
    progress_bar = f"[dark_sea_green]{'█' * progress_filled}[/dark_sea_green][grey35]{'░' * progress_empty}[/grey35]"

    if verbose:
        raised_str = f"τ {loan.raised.tao:,.4f} / τ {loan.cap.tao:,.4f}"
        deposit_str = f"τ {loan.deposit.tao:,.4f}"
        min_contrib_str = f"τ {loan.min_contribution.tao:,.4f}"
    else:
        raised_str = f"τ {millify_tao(loan.raised.tao)} / τ {millify_tao(loan.cap.tao)}"
        deposit_str = f"τ {millify_tao(loan.deposit.tao)}"
        min_contrib_str = f"τ {millify_tao(loan.min_contribution.tao)}"

    funding_lines = [
        f"[bold white]Raised/Cap:[/bold white]\t{raised_str}",
        f"[bold white]Progress:[/bold white]\t\t[{progress_bar}] [dark_sea_green]{raised_pct:.2f}%[/dark_sea_green]",
        f"[bold white]Deposit:[/bold white]\t\t{deposit_str}",
        f"[bold white]Min Contribution:[/bold white]\t{min_contrib_str}",
    ]

    sections.append(
        ("\n[bold cyan]FUNDING PROGRESS[/bold cyan]", "\n".join(funding_lines))
    )

    # Timeline section
    time_label = _time_remaining(loan, current_block)
    if "Closed" in time_label:
        time_display = f"[{COLOR_PALETTE['GENERAL']['SYMBOL']}]{time_label}[/{COLOR_PALETTE['GENERAL']['SYMBOL']}]"
    elif time_label == "due":
        time_display = "[red]Due now[/red]"
    else:
        time_display = f"[{COLOR_PALETTE['STAKE']['STAKE_ALPHA']}]{time_label}[/{COLOR_PALETTE['STAKE']['STAKE_ALPHA']}]"

    timeline_lines = [
        f"[bold white]Ends at Block:[/bold white]\t{loan.end}",
        f"[bold white]Current Block:[/bold white]\t{current_block}",
        f"[bold white]Time Remaining:[/bold white]\t{time_display}",
    ]
    sections.append(("\n[bold cyan]TIMELINE[/bold cyan]", "\n".join(timeline_lines)))

    # Participation section
    participation_lines = [
        f"[bold white]Contributors:[/bold white]\t{loan.contributors_count}",
    ]

    if loan.contributors_count > 0:
        net_contributions = loan.raised.tao - loan.deposit.tao
        avg_contribution = (
            net_contributions / (loan.contributors_count - 1)
            if loan.contributors_count > 1
            else loan.deposit.tao
        )
        if verbose:
            avg_contrib_str = f"τ {avg_contribution:,.4f}"
        else:
            avg_contrib_str = f"τ {millify_tao(avg_contribution)}"
        participation_lines.append(
            f"[bold white]Avg Contribution:[/bold white]\t{avg_contrib_str}"
        )

    if user_contribution:
        is_creator = wallet.coldkeypub.ss58_address == loan.creator
        if verbose:
            user_contrib_str = f"τ {user_contribution.tao:,.4f}"
        else:
            user_contrib_str = f"τ {millify_tao(user_contribution.tao)}"

        contrib_status = ""
        if status == "Active" and not loan.finalized:
            if is_creator and user_contribution.tao > loan.deposit.tao:
                withdrawable = user_contribution.tao - loan.deposit.tao
                if verbose:
                    withdrawable_str = f"τ {withdrawable:,.4f}"
                else:
                    withdrawable_str = f"τ {millify_tao(withdrawable)}"
                contrib_status = (
                    f" [yellow](τ {withdrawable_str} withdrawable)[/yellow]"
                )
            elif not is_creator:
                contrib_status = " [yellow](withdrawable)[/yellow]"
        elif status == "Closed":
            contrib_status = " [green](refundable)[/green]"

        participation_lines.append(
            f"[bold white]Your Contribution:[/bold white]\t{user_contrib_str}{contrib_status}"
        )

        if is_creator:
            participation_lines.append("\t\t\t[dim](You are the creator)[/dim]")

    sections.append(
        ("\n[bold cyan]PARTICIPATION[/bold cyan]", "\n".join(participation_lines))
    )

    # Target section
    target_lines = []

    if loan.target_address:
        target_display = loan.target_address
        target_lines.append(f"[bold white]Address:[/bold white]\t\t{target_display}")
    else:
        target_lines.append(
            f"[bold white]Address:[/bold white]\t\t[{COLORS.G.SUBHEAD_MAIN}]Not specified[/{COLORS.G.SUBHEAD_MAIN}]"
        )

    has_call_display = (
        f"[{COLOR_PALETTE['GENERAL']['SUCCESS']}]Yes[/{COLOR_PALETTE['GENERAL']['SUCCESS']}]"
        if loan.has_call
        else f"[{COLOR_PALETTE['GENERAL']['SYMBOL']}]No[/{COLOR_PALETTE['GENERAL']['SYMBOL']}]"
    )
    target_lines.append(f"[bold white]Has Call:[/bold white]\t\t{has_call_display}")

    sections.append(("\n[bold cyan]TARGET[/bold cyan]", "\n".join(target_lines)))

    # All sections
    divider_width = 63
    divider = "═" * divider_width
    header_text = f"CROWDLOAN #{crowdloan_id} - {status.upper()}"
    padding_needed = (divider_width - len(header_text)) // 2
    centered_header = " " * padding_needed + header

    console.print(f"\n[bright_black]{divider}[/bright_black]")
    console.print(centered_header)
    console.print(f"[bright_black]{divider}[/bright_black]")

    for section_title, section_content in sections:
        console.print(section_title)
        console.print(section_content)

    console.print(f"[bright_black]{divider}[/bright_black]\n")

    return True, f"Displayed info for crowdloan #{crowdloan_id}"
