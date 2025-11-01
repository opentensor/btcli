import asyncio
from typing import TYPE_CHECKING, Optional

from bittensor_wallet import Wallet
from rich.prompt import Confirm, Prompt
from rich.table import Table, Column
from rich import box

from bittensor_cli.src import COLORS
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

    current_type = await subtensor.get_coldkey_claim_type(
        coldkey_ss58=wallet.coldkeypub.ss58_address
    )

    claim_table = Table(
        Column(
            "[bold white]Coldkey",
            style=COLORS.GENERAL.COLDKEY,
            justify="left",
        ),
        Column(
            "[bold white]Root Claim Type",
            style=COLORS.GENERAL.SUBHEADING,
            justify="center",
        ),
        show_header=True,
        show_footer=False,
        show_edge=True,
        border_style="bright_black",
        box=box.SIMPLE,
        pad_edge=False,
        width=None,
        title=f"\n[{COLORS.GENERAL.HEADER}]Current root claim type:[/{COLORS.GENERAL.HEADER}]",
    )
    claim_table.add_row(
        wallet.coldkeypub.ss58_address, f"[yellow]{current_type}[/yellow]"
    )
    console.print(claim_table)
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
            f"\n[bold]Changing root claim type from '{current_type}' -> '{new_type}'[/bold]\n"
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


def _prompt_claim_selection(claimable_stake: dict) -> Optional[list[int]]:
    """Prompts user to select up to 5 netuids to claim from"""

    available_netuids = sorted(claimable_stake.keys())
    while True:
        netuid_input = Prompt.ask(
            "Enter up to 5 netuids to claim from (comma-separated)",
            default=",".join(str(n) for n in available_netuids),
        )

        try:
            if "," in netuid_input:
                selected = [int(n.strip()) for n in netuid_input.split(",")]
            else:
                selected = [int(netuid_input.strip())]
        except ValueError:
            err_console.print(
                ":cross_mark: [red]Invalid input. Please enter numbers only.[/red]"
            )
            continue

        if len(selected) > 5:
            err_console.print(
                f":cross_mark: [red]You selected {len(selected)} netuids. Maximum is 5. Please try again.[/red]"
            )
            continue

        if len(selected) == 0:
            err_console.print(
                ":cross_mark: [red]Please select at least one netuid.[/red]"
            )
            continue

        invalid_netuids = [n for n in selected if n not in available_netuids]
        if invalid_netuids:
            err_console.print(
                f":cross_mark: [red]Invalid netuids: {', '.join(map(str, invalid_netuids))}[/red]"
            )
            continue

        selected = list(dict.fromkeys(selected))

        return selected


def _print_claimable_table(wallet: Wallet, claimable_stake: dict):
    """Prints claimable stakes table grouped by netuid"""

    table = Table(
        show_header=True,
        show_footer=False,
        show_edge=True,
        border_style="bright_black",
        box=box.SIMPLE,
        pad_edge=False,
        title=f"\n[{COLORS.GENERAL.HEADER}]Claimable emissions for coldkey: {wallet.coldkeypub.ss58_address}",
    )

    table.add_column("Netuid", style=COLORS.GENERAL.NETUID, justify="center")
    table.add_column("Current Stake", style=COLORS.GENERAL.SUBHEADING, justify="right")
    table.add_column("Claimable", style=COLORS.GENERAL.SUCCESS, justify="right")
    table.add_column("Hotkey", style=COLORS.GENERAL.HOTKEY, justify="left")
    table.add_column("Identity", style=COLORS.GENERAL.SUBHEADING, justify="left")

    for netuid in sorted(claimable_stake.keys()):
        hotkeys_info = claimable_stake[netuid]
        first_row = True

        for hotkey, info in hotkeys_info.items():
            stake_display = info["stake"]
            claimable_display = info["claimable"]
            hotkey_display = f"{hotkey[:8]}...{hotkey[-8:]}"
            netuid_display = str(netuid) if first_row else ""
            table.add_row(
                netuid_display,
                f"{stake_display.tao:.4f} {stake_display.unit}",
                f"{claimable_display.tao:.4f} {claimable_display.unit}",
                hotkey_display,
                info.get("identity", "~"),
            )
            first_row = False

    console.print(table)
