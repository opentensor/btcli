import asyncio
import json
from typing import Optional, TYPE_CHECKING

from bittensor_wallet import Wallet
from rich import box
from rich.table import Table
from rich.prompt import Confirm

from bittensor_cli.src import COLOR_PALETTE
from bittensor_cli.src.bittensor.utils import (
    console,
    json_console,
    get_subnet_name,
    is_valid_ss58_address,
    print_error,
    err_console,
    unlock_key,
)

if TYPE_CHECKING:
    from bittensor_cli.src.bittensor.subtensor_interface import SubtensorInterface


async def show_auto_destinations(
    wallet: Optional[Wallet],
    subtensor: "SubtensorInterface",
    coldkey_ss58: Optional[str] = None,
    json_output: bool = False,
    verbose: bool = False,
) -> Optional[dict[int, dict[str, Optional[str]]]]:
    """Display auto-stake destinations for the supplied wallet."""

    wallet_name: Optional[str] = wallet.name if wallet else None
    coldkey_ss58 = coldkey_ss58 or (wallet.coldkeypub.ss58_address if wallet else None)
    if not coldkey_ss58:
        raise ValueError("A wallet or coldkey SS58 address must be provided")

    with console.status(
        f"Retrieving auto-stake configuration from {subtensor.network}...",
        spinner="earth",
    ):
        chain_head = await subtensor.substrate.get_chain_head()
        (
            subnet_info,
            auto_destinations,
            identities,
            delegate_identities,
        ) = await asyncio.gather(
            subtensor.all_subnets(block_hash=chain_head),
            subtensor.get_auto_stake_destinations(
                coldkey_ss58=coldkey_ss58,
                block_hash=chain_head,
                reuse_block=True,
            ),
            subtensor.fetch_coldkey_hotkey_identities(block_hash=chain_head),
            subtensor.get_delegate_identities(block_hash=chain_head),
        )

    subnet_map = {info.netuid: info for info in subnet_info}
    auto_destinations = auto_destinations or {}
    identities = identities or {}
    delegate_identities = delegate_identities or {}
    hotkey_identities = identities.get("hotkeys", {})

    def resolve_identity(hotkey: str) -> Optional[str]:
        if not hotkey:
            return None

        identity_entry = hotkey_identities.get(hotkey, {}).get("identity")
        if identity_entry:
            display_name = identity_entry.get("name") or identity_entry.get("display")
            if display_name:
                return display_name

        delegate_info = delegate_identities.get(hotkey)
        if delegate_info and getattr(delegate_info, "display", ""):
            return delegate_info.display

        return None

    coldkey_display = wallet_name
    if not coldkey_display:
        coldkey_identity = identities.get("coldkeys", {}).get(coldkey_ss58, {})
        if identity_data := coldkey_identity.get("identity"):
            coldkey_display = identity_data.get("name") or identity_data.get("display")
        if not coldkey_display:
            coldkey_display = f"{coldkey_ss58[:6]}...{coldkey_ss58[-6:]}"

    rows = []
    data_output: dict[int, dict[str, Optional[str]]] = {}

    for netuid in sorted(subnet_map):
        subnet = subnet_map[netuid]
        subnet_name = get_subnet_name(subnet)
        hotkey_ss58 = auto_destinations.get(netuid)
        identity_str = resolve_identity(hotkey_ss58) if hotkey_ss58 else None
        is_custom = hotkey_ss58 is not None

        data_output[netuid] = {
            "subnet_name": subnet_name,
            "status": "custom" if is_custom else "default",
            "destination": hotkey_ss58,
            "identity": identity_str,
        }

        if json_output:
            continue

        status_text = (
            f"[{COLOR_PALETTE['STAKE']['STAKE_ALPHA']}]Custom[/{COLOR_PALETTE['STAKE']['STAKE_ALPHA']}]"
            if is_custom
            else f"[{COLOR_PALETTE['GENERAL']['HINT']}]Default[/{COLOR_PALETTE['GENERAL']['HINT']}]"
        )

        rows.append(
            (
                str(netuid),
                subnet_name,
                status_text,
                hotkey_ss58,
                identity_str or "",
            )
        )

    if json_output:
        json_console.print(json.dumps(data_output))
        return data_output

    table = Table(
        title=(
            f"\n[{COLOR_PALETTE['GENERAL']['HEADER']}]Auto Stake Destinations"
            f" for [bold]{coldkey_display}[/bold]\n"
            f"Network: {subtensor.network}\n"
            f"Coldkey: {coldkey_ss58}\n"
            f"[/{COLOR_PALETTE['GENERAL']['HEADER']}]"
        ),
        show_edge=False,
        header_style="bold white",
        border_style="bright_black",
        style="bold",
        title_justify="center",
        show_lines=False,
        pad_edge=True,
        box=box.SIMPLE_HEAD,
    )

    table.add_column(
        "Netuid", style=COLOR_PALETTE["GENERAL"]["SYMBOL"], justify="center"
    )
    table.add_column("Subnet", style="cyan", justify="left")
    table.add_column("Status", style="white", justify="center")
    table.add_column(
        "Destination Hotkey", style=COLOR_PALETTE["GENERAL"]["HOTKEY"], justify="center"
    )
    table.add_column(
        "Identity", style=COLOR_PALETTE["GENERAL"]["SUBHEADING"], justify="left"
    )

    for row in rows:
        table.add_row(*row)

    console.print(table)
    console.print(
        f"\n[{COLOR_PALETTE['GENERAL']['SUBHEADING']}]Total subnets:[/] {len(subnet_map)}  "
        f"[{COLOR_PALETTE['GENERAL']['SUBHEADING']}]Custom destinations:[/] {len(auto_destinations)}"
    )

    return None
