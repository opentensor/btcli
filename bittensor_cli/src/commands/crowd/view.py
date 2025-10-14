import asyncio
from rich.table import Table

from bittensor_cli.src import COLOR_PALETTE, COLORS
from bittensor_cli.src.bittensor.balances import Balance
from bittensor_cli.src.bittensor.chain_data import CrowdloanData
from bittensor_cli.src.bittensor.subtensor_interface import SubtensorInterface
from bittensor_cli.src.bittensor.utils import (
    blocks_to_duration,
    console,
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
