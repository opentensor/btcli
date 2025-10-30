from typing import TYPE_CHECKING, Optional

from bittensor_wallet import Wallet
from rich.prompt import Confirm, Prompt

from bittensor_cli.src.bittensor.utils import (
    console,
    err_console,
    unlock_key,
    print_extrinsic_id,
)

if TYPE_CHECKING:
    from bittensor_cli.src.bittensor.subtensor_interface import SubtensorInterface


async def set_claim_type(
    wallet: Wallet,
    subtensor: "SubtensorInterface",
    prompt: bool = True,
) -> tuple[bool, str, Optional[str]]:
    """
    Sets the root claim type for the coldkey.

    Root claim types control how staking emissions are handled on the ROOT network (subnet 0):
        - "Swap": Future Root Alpha Emissions are swapped to TAO at claim time and added to root stake
        - "Keep": Future Root Alpha Emissions are kept as Alpha tokens

    Args:
        wallet: Bittensor wallet object
        subtensor: SubtensorInterface object
        prompt: Whether to prompt for user confirmation

    Returns:
        tuple[bool, str, Optional[str]]: Tuple containing:
            - bool: True if successful, False otherwise
            - str: Error message if failed
            - Optional[str]: Extrinsic identifier if successful
    """

    current_type = await subtensor.get_root_claim_type(
        coldkey_ss58=wallet.coldkeypub.ss58_address
    )
    console.print(
        f"\nCurrent root claim type for coldkey:\n"
        f"  Coldkey: [cyan]{wallet.coldkeypub.ss58_address}[/cyan]\n"
        f"  Current type: [yellow]{current_type}[/yellow]\n"
    )
    new_type = Prompt.ask(
        "Select new root claim type", choices=["Swap", "Keep"], default=current_type
    )
    if new_type == current_type:
        console.print(
            f"[yellow]Root claim type is already set to '{current_type}'. No change needed.[/yellow]"
        )
        return (
            True,
            "Root claim type is already set to '{current_type}'. No change needed.",
            None,
        )

    if prompt:
        console.print(
            f"\n[bold]You are about to change the root claim type:[/bold]\n"
            f"  [yellow]{current_type}[/yellow] -> [dark_sea_green3]{new_type}[/dark_sea_green3]\n"
        )

        if new_type == "Swap":
            console.print(
                "[yellow]Note:[/yellow] With 'Swap', future root alpha emissions will be swapped to TAO and added to root stake."
            )
        else:
            console.print(
                "[yellow]Note:[/yellow] With 'Keep', future root alpha emissions will be kept as Alpha tokens."
            )

        if not Confirm.ask("\nDo you want to proceed?"):
            console.print("[yellow]Operation cancelled.[/yellow]")
            return False, "Operation cancelled.", None

    if not (unlock := unlock_key(wallet)).success:
        err_console.print(
            f":cross_mark: [red]Failed to unlock wallet: {unlock.message}[/red]"
        )
        return False, f"Failed to unlock wallet: {unlock.message}", None

    with console.status(
        f":satellite: Setting root claim type to '{new_type}'...", spinner="earth"
    ):
        try:
            call = await subtensor.substrate.compose_call(
                call_module="SubtensorModule",
                call_function="set_root_claim_type",
                call_params={"new_root_claim_type": new_type},
            )
            success, err_msg, ext_receipt = await subtensor.sign_and_send_extrinsic(
                call, wallet
            )
            if success:
                console.print(
                    f":white_heavy_check_mark: [green]Successfully set root claim type to '{new_type}'[/green]"
                )
                ext_id = await ext_receipt.get_extrinsic_identifier()
                await print_extrinsic_id(ext_receipt)
                return True, f"Successfully set root claim type to '{new_type}'", ext_id
            else:
                err_console.print(
                    f":cross_mark: [red]Failed to set root claim type: {err_msg}[/red]"
                )
                return False, f"Failed to set root claim type: {err_msg}", None

        except Exception as e:
            err_console.print(
                f":cross_mark: [red]Error setting root claim type: {e}[/red]"
            )
            return False, f"Error setting root claim type: {e}", None
