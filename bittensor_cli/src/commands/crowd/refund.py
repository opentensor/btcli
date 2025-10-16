import asyncio

from bittensor_wallet import Wallet
from rich.prompt import Confirm
from rich.table import Table, Column, box

from bittensor_cli.src import COLORS
from bittensor_cli.src.bittensor.subtensor_interface import SubtensorInterface
from bittensor_cli.src.bittensor.utils import (
    blocks_to_duration,
    console,
    print_extrinsic_id,
    print_error,
    unlock_key,
)
from bittensor_cli.src.commands.crowd.view import show_crowdloan_details
from bittensor_cli.src.commands.crowd.utils import get_constant


async def refund_crowdloan(
    subtensor: SubtensorInterface,
    wallet: Wallet,
    crowdloan_id: int,
    wait_for_inclusion: bool = True,
    wait_for_finalization: bool = False,
    prompt: bool = True,
) -> tuple[bool, str]:
    """Refund contributors of a non-finalized crowdloan.

    This extrinsic refunds all contributors (excluding the creator) up to the
    RefundContributorsLimit. If there are more contributors than the limit,
    this call may need to be executed multiple times until all contributors
    are refunded.

    Anyone can call this function - it does not need to be the creator.

    Args:
        subtensor: SubtensorInterface object for chain interaction
        wallet: Wallet object containing coldkey (any wallet can call this)
        crowdloan_id: ID of the crowdloan to refund
        wait_for_inclusion: Wait for transaction inclusion
        wait_for_finalization: Wait for transaction finalization
        prompt: Whether to prompt for confirmation

    Returns:
        tuple[bool, str]: Success status and message
    """
    crowdloan, current_block = await asyncio.gather(
        subtensor.get_single_crowdloan(crowdloan_id),
        subtensor.substrate.get_block_number(None),
    )

    if not crowdloan:
        print_error(f"[red]Crowdloan #{crowdloan_id} not found.[/red]")
        return False, f"Crowdloan #{crowdloan_id} not found."

    if crowdloan.finalized:
        print_error(
            f"[red]Crowdloan #{crowdloan_id} is already finalized. "
            "Finalized crowdloans cannot be refunded.[/red]"
        )
        return False, f"Crowdloan #{crowdloan_id} is already finalized."
    if crowdloan.end > current_block:
        print_error(
            f"[red]Crowdloan #{crowdloan_id} is not yet ended. "
            f"End block: [cyan]{crowdloan.end:,}[/cyan] ([dim]{blocks_to_duration(crowdloan.end - current_block)} remaining[/dim])[/red]"
        )
        return False, f"Crowdloan #{crowdloan_id} is not yet ended."

    await show_crowdloan_details(
        subtensor=subtensor,
        crowdloan_id=crowdloan_id,
        wallet=wallet,
        verbose=False,
        crowdloan=crowdloan,
        current_block=current_block,
    )

    refund_limit = await get_constant(subtensor, "RefundContributorsLimit")

    console.print("\n[bold cyan]Crowdloan Refund Information[/bold cyan]\n")

    info_table = Table(
        Column("[bold white]Property", style=COLORS.G.SUBHEAD),
        Column("[bold white]Value", style=COLORS.G.TEMPO),
        show_footer=False,
        show_header=False,
        width=None,
        pad_edge=False,
        box=box.SIMPLE,
        show_edge=True,
        border_style="bright_black",
    )

    info_table.add_row("Crowdloan ID", f"#{crowdloan_id}")
    info_table.add_row("Total Contributors", f"{crowdloan.contributors_count:,}")
    info_table.add_row("Refund Limit (per call)", f"{refund_limit:,} contributors")
    info_table.add_row("Amount to Refund", crowdloan.raised - crowdloan.deposit)

    if current_block >= crowdloan.end:
        if crowdloan.raised < crowdloan.cap:
            status = "[red]Failed[/red] (Cap not reached)"
        else:
            status = "[yellow]Ended but not finalized[/yellow]"
    else:
        status = "[green]Active[/green] (Still accepting contributions)"

    info_table.add_row("Status", status)

    refundable_contributors = max(0, crowdloan.contributors_count)
    estimated_calls = (
        (refundable_contributors + refund_limit) // refund_limit
        if refund_limit > 0
        else 0
    )

    if estimated_calls > 1:
        info_table.add_row(
            "Estimated Calls Needed",
            f"[yellow]~{estimated_calls}[/yellow] (due to contributor limit)",
        )

    console.print(info_table)
