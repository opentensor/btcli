import asyncio

from bittensor_wallet import Wallet
from rich.prompt import Confirm
from rich.table import Column, Table, box

from bittensor_cli.src import COLORS
from bittensor_cli.src.bittensor.subtensor_interface import SubtensorInterface
from bittensor_cli.src.commands.crowd.view import show_crowdloan_details
from bittensor_cli.src.bittensor.utils import (
    blocks_to_duration,
    console,
    print_extrinsic_id,
    print_error,
    unlock_key,
    format_error_message,
)


async def dissolve_crowdloan(
    subtensor: SubtensorInterface,
    wallet: Wallet,
    crowdloan_id: int,
    wait_for_inclusion: bool = True,
    wait_for_finalization: bool = False,
    prompt: bool = True,
) -> tuple[bool, str]:
    """Dissolve a non-finalized crowdloan after refunding contributors.

    The creator can reclaim their deposit once every other contribution has been
    refunded (i.e., the raised amount equals the creator's contribution).

    Args:
        subtensor: SubtensorInterface object for chain interaction.
        wallet: Wallet object containing the creator's coldkey.
        crowdloan_id: ID of the crowdloan to dissolve.
        wait_for_inclusion: Wait for transaction inclusion.
        wait_for_finalization: Wait for transaction finalization.
        prompt: Whether to prompt for confirmation.

    Returns:
        tuple[bool, str]: Success status and message.
    """

    creator_ss58 = wallet.coldkeypub.ss58_address

    crowdloan, current_block = await asyncio.gather(
        subtensor.get_single_crowdloan(crowdloan_id),
        subtensor.substrate.get_block_number(None),
    )

    if not crowdloan:
        print_error(f"[red]Crowdloan #{crowdloan_id} not found.[/red]")
        return False, f"Crowdloan #{crowdloan_id} not found."

    if crowdloan.finalized:
        print_error(
            f"[red]Crowdloan #{crowdloan_id} is already finalized and cannot be dissolved.[/red]"
        )
        return False, f"Crowdloan #{crowdloan_id} is finalized."

    if creator_ss58 != crowdloan.creator:
        print_error(
            f"[red]Only the creator can dissolve this crowdloan.[/red]\n"
            f"Creator: [blue]{crowdloan.creator}[/blue]\n"
            f"Your address: [blue]{creator_ss58}[/blue]"
        )
        return False, "Only the creator can dissolve this crowdloan."

    creator_contribution = await subtensor.get_crowdloan_contribution(
        crowdloan_id, crowdloan.creator
    )

    if creator_contribution != crowdloan.raised:
        print_error(
            f"[red]Crowdloan still holds funds from other contributors.[/red]\n"
            f"Raised amount: [yellow]{crowdloan.raised}[/yellow]\n"
            f"Creator's contribution: [yellow]{creator_contribution}[/yellow]\n"
            "Run [cyan]btcli crowd refund[/cyan] until only the creator's funds remain."
        )
        return False, "Crowdloan not ready to dissolve."

    await show_crowdloan_details(
        subtensor=subtensor,
        crowdloan_id=crowdloan_id,
        wallet=wallet,
        verbose=False,
        crowdloan=crowdloan,
        current_block=current_block,
    )

    summary = Table(
        Column("Field", style=COLORS.G.SUBHEAD),
        Column("Value", style=COLORS.G.TEMPO),
        box=box.SIMPLE,
        show_header=False,
    )
    summary.add_row("Crowdloan ID", f"#{crowdloan_id}")
    summary.add_row("Raised", str(crowdloan.raised))
    summary.add_row("Creator Contribution", str(creator_contribution))
    summary.add_row(
        "Remaining Contributors",
        str(max(0, crowdloan.contributors_count - 1)),
    )
    time_remaining = crowdloan.end - current_block
    summary.add_row(
        "Time Remaining",
        blocks_to_duration(time_remaining) if time_remaining > 0 else "Ended",
    )

    console.print("\n[bold cyan]Crowdloan Dissolution Summary[/bold cyan]")
    console.print(summary)

    if prompt and not Confirm.ask(
        f"\n[bold]Proceed with dissolving crowdloan #{crowdloan_id}?[/bold]",
        default=False,
    ):
        console.print("[yellow]Dissolution cancelled.[/yellow]")
        return False, "Dissolution cancelled by user."

    unlock_status = unlock_key(wallet)
    if not unlock_status.success:
        print_error(f"[red]{unlock_status.message}[/red]")
        return False, unlock_status.message

    with console.status(
        ":satellite: Submitting dissolve transaction...", spinner="aesthetic"
    ):
        call = await subtensor.substrate.compose_call(
            call_module="Crowdloan",
            call_function="dissolve",
            call_params={"crowdloan_id": crowdloan_id},
        )
        extrinsic = await subtensor.substrate.create_signed_extrinsic(
            call=call,
            keypair=wallet.coldkey,
        )
        response = await subtensor.substrate.submit_extrinsic(
            extrinsic,
            wait_for_inclusion=wait_for_inclusion,
            wait_for_finalization=wait_for_finalization,
        )

    if not wait_for_finalization and not wait_for_inclusion:
        console.print("[green]Dissolve transaction submitted.[/green]")
        return True, "Dissolve transaction submitted."

    await response.process_events()

    if not await response.is_success:
        print_error(
            f"[red]Failed to dissolve crowdloan.[/red]\n{format_error_message(await response.error_message)}"
        )
        return False, format_error_message(await response.error_message)

    await print_extrinsic_id(response)

    console.print("[green]Crowdloan dissolved successfully![/green]")

    return True, "Crowdloan dissolved successfully."
