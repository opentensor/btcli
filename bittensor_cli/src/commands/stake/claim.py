import asyncio
import json
from typing import TYPE_CHECKING, Optional

from bittensor_wallet import Wallet
from rich.prompt import Confirm, Prompt
from rich.table import Table, Column
from rich import box

from bittensor_cli.src import COLORS
from bittensor_cli.src.bittensor.balances import Balance
from bittensor_cli.src.bittensor.utils import (
    console,
    err_console,
    unlock_key,
    print_extrinsic_id,
    json_console,
)

if TYPE_CHECKING:
    from bittensor_cli.src.bittensor.subtensor_interface import SubtensorInterface


async def set_claim_type(
    wallet: Wallet,
    subtensor: "SubtensorInterface",
    prompt: bool = True,
    json_output: bool = False,
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
        json_output: Whether to output JSON

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
        msg = f"Root claim type is already set to '{current_type}'. No change needed."
        console.print(f"[yellow]{msg}[/yellow]")
        if json_output:
            json_console.print(
                json.dumps(
                    {
                        "success": True,
                        "message": msg,
                        "extrinsic_identifier": None,
                        "old_type": current_type,
                        "new_type": current_type,
                    }
                )
            )
        return True, msg, None

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
            msg = "Operation cancelled."
            console.print(f"[yellow]{msg}[/yellow]")
            if json_output:
                json_console.print(
                    json.dumps(
                        {
                            "success": False,
                            "message": msg,
                            "extrinsic_identifier": None,
                            "old_type": current_type,
                            "new_type": new_type,
                        }
                    )
                )
            return False, msg, None

    if not (unlock := unlock_key(wallet)).success:
        msg = f"Failed to unlock wallet: {unlock.message}"
        err_console.print(f":cross_mark: [red]{msg}[/red]")
        if json_output:
            json_console.print(
                json.dumps(
                    {
                        "success": False,
                        "message": msg,
                        "extrinsic_identifier": None,
                        "old_type": current_type,
                        "new_type": new_type,
                    }
                )
            )
        return False, msg, None

    with console.status(
        f":satellite: Setting root claim type to '{new_type}'...", spinner="earth"
    ):
        call = await subtensor.substrate.compose_call(
            call_module="SubtensorModule",
            call_function="set_root_claim_type",
            call_params={"new_root_claim_type": new_type},
        )
        success, err_msg, ext_receipt = await subtensor.sign_and_send_extrinsic(
            call, wallet
        )
        if success:
            ext_id = await ext_receipt.get_extrinsic_identifier()
            msg = f"Successfully set root claim type to '{new_type}'"
            console.print(f":white_heavy_check_mark: [green]{msg}[/green]")
            await print_extrinsic_id(ext_receipt)
            if json_output:
                json_console.print(
                    json.dumps(
                        {
                            "success": True,
                            "message": msg,
                            "extrinsic_identifier": ext_id,
                            "old_type": current_type,
                            "new_type": new_type,
                        }
                    )
                )
            return True, msg, ext_id

        else:
            msg = f"Failed to set root claim type: {err_msg}"
            err_console.print(f":cross_mark: [red]{msg}[/red]")
            if json_output:
                json_console.print(
                    json.dumps(
                        {
                            "success": False,
                            "message": msg,
                            "extrinsic_identifier": None,
                            "old_type": current_type,
                            "new_type": new_type,
                        }
                    )
                )
            return False, msg, None


async def process_pending_claims(
    wallet: Wallet,
    subtensor: "SubtensorInterface",
    netuids: Optional[list[int]] = None,
    prompt: bool = True,
) -> tuple[bool, str, Optional[str]]:
    """Claims root network emissions for the coldkey across specified subnets"""

    with console.status(":satellite: Discovering claimable emissions..."):
        all_stakes, identities = await asyncio.gather(
            subtensor.get_stake_for_coldkey(
                coldkey_ss58=wallet.coldkeypub.ss58_address
            ),
            subtensor.query_all_identities(),
        )
        if not all_stakes:
            console.print("[yellow]No stakes found for this coldkey[/yellow]")
            return True, "No stakes found", None

        current_stakes = {
            (stake.hotkey_ss58, stake.netuid): stake for stake in all_stakes
        }
        claimable_by_hotkey = await subtensor.get_claimable_stakes_batch(
            coldkey_ss58=wallet.coldkeypub.ss58_address,
            stakes_info=all_stakes,
        )
        hotkey_owner_tasks = [
            subtensor.get_hotkey_owner(hotkey, check_exists=False)
            for hotkey in claimable_by_hotkey.keys()
        ]
        hotkey_owners = await asyncio.gather(*hotkey_owner_tasks)
        hotkey_to_owner = dict(zip(claimable_by_hotkey.keys(), hotkey_owners))

        # Consolidate data
        claimable_stake_info = {}
        for vali_hotkey, claimable_stakes in claimable_by_hotkey.items():
            vali_coldkey = hotkey_to_owner.get(vali_hotkey, "~")
            vali_identity = identities.get(vali_coldkey, {}).get("name", "~")
            for netuid, claimable_stake in claimable_stakes.items():
                if claimable_stake.rao > 0:
                    if netuid not in claimable_stake_info:
                        claimable_stake_info[netuid] = {}
                    current_stake = (
                        stake_info.stake
                        if (stake_info := current_stakes.get((vali_hotkey, netuid)))
                        else Balance.from_rao(0).set_unit(netuid)
                    )
                    claimable_stake_info[netuid][vali_hotkey] = {
                        "claimable": claimable_stake,
                        "stake": current_stake,
                        "coldkey": vali_coldkey,
                        "identity": vali_identity,
                    }

    if netuids:
        claimable_stake_info = {
            netuid: hotkeys_info
            for netuid, hotkeys_info in claimable_stake_info.items()
            if netuid in netuids
        }

    if not claimable_stake_info:
        console.print("[yellow]No claimable emissions found[/yellow]")
        return True, "No claimable emissions found", None

    _print_claimable_table(wallet, claimable_stake_info)
    selected_netuids = (
        netuids if netuids else _prompt_claim_selection(claimable_stake_info)
    )

    call = await subtensor.substrate.compose_call(
        call_module="SubtensorModule",
        call_function="claim_root",
        call_params={"subnets": selected_netuids},
    )
    extrinsic_fee = await subtensor.get_extrinsic_fee(call, wallet.coldkeypub)
    console.print(f"\n[dim]Estimated extrinsic fee: {extrinsic_fee.tao:.9f} τ[/dim]")

    if prompt:
        if not Confirm.ask("Do you want to proceed?"):
            console.print("[yellow]Operation cancelled.[/yellow]")
            return False, "Operation cancelled by user", None

    if not (unlock := unlock_key(wallet)).success:
        err_console.print(
            f":cross_mark: [red]Failed to unlock wallet: {unlock.message}[/red]"
        )
        return False, f"Failed to unlock wallet: {unlock.message}", None

    with console.status(
        f":satellite: Claiming root emissions for {len(selected_netuids)} subnet(s)...",
        spinner="earth",
    ):
        success, err_msg, ext_receipt = await subtensor.sign_and_send_extrinsic(
            call, wallet
        )
        if success:
            console.print(
                f"[dark_sea_green3]Successfully claimed root emissions for {len(selected_netuids)} subnet(s)[/dark_sea_green3]"
            )
            ext_id = await ext_receipt.get_extrinsic_identifier()
            await print_extrinsic_id(ext_receipt)
            return (
                True,
                f"Successfully claimed root emissions for {len(selected_netuids)} subnet(s)",
                ext_id,
            )
        else:
            err_console.print(
                f":cross_mark: [red]Failed to claim root emissions: {err_msg}[/red]"
            )
            return False, f"Failed to claim root emissions: {err_msg}", None


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
