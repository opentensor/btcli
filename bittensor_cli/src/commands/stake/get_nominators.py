import asyncio
from typing import TYPE_CHECKING, Optional

from rich.table import Table
from rich import box

from bittensor_cli.src import COLOR_PALETTE
from bittensor_cli.src.bittensor.balances import Balance
from bittensor_cli.src.bittensor.utils import (
    console,
    print_error,
    millify_tao,
    get_subnet_name,
    json_console,
    is_valid_ss58_address,
)

if TYPE_CHECKING:
    from bittensor_cli.src.bittensor.subtensor_interface import SubtensorInterface


async def get_nominators(
    hotkey_ss58: str,
    subtensor: "SubtensorInterface",
    json_output: bool = False,
):
    """
    Fetches and displays the nominators for a delegate hotkey.
    Args:
        hotkey_ss58: The SS58 address of the delegate's hotkey.
        subtensor: The SubtensorInterface instance.
        json_output: Whether to output the results in JSON format.
    """
    if not is_valid_ss58_address(hotkey_ss58):
        print_error("Invalid hotkey SS58 address")
        return

    # Fetch delegate information
    delegate_info = await subtensor.get_delegate_by_hotkey(hotkey_ss58=hotkey_ss58)

    if delegate_info is None:
        print_error(f"No delegate found for hotkey: {hotkey_ss58}")
        return

    # Fetch identities for all nominators in parallel
    with console.status(
        ":satellite: [bold green]Fetching nominator identities...", spinner="earth"
    ):
        identity_tasks = [
            subtensor.query_identity(nominator_ss58)
            for nominator_ss58, _ in delegate_info.nominators
        ]
        identities = await asyncio.gather(*identity_tasks)

    # Create a mapping of nominator address to identity
    nominator_identities = {}
    for (nominator_ss58, _), identity in zip(delegate_info.nominators, identities):
        if identity:
            # Get name or display field from identity
            identity_name = identity.get("name") or identity.get("display") or "~"
            nominator_identities[nominator_ss58] = identity_name
        else:
            nominator_identities[nominator_ss58] = "~"

    if json_output:
        # Output as JSON
        nominators_data = [
            {
                "nominator_ss58": nominator_ss58,
                "identity": nominator_identities.get(nominator_ss58, "~"),
                "stake_tao": float(stake.tao),
                "stake_rao": stake.rao,
                "stake_percentage": (
                    float(stake.tao / delegate_info.total_stake.tao * 100)
                    if delegate_info.total_stake.tao > 0
                    else 0
                ),
            }
            for nominator_ss58, stake in delegate_info.nominators
        ]
        json_console.print(
            {
                "hotkey_ss58": delegate_info.hotkey_ss58,
                "owner_ss58": delegate_info.owner_ss58,
                "total_stake_tao": float(delegate_info.total_stake.tao),
                "total_stake_rao": delegate_info.total_stake.rao,
                "take": delegate_info.take,
                "nominators": nominators_data,
                "nominator_count": len(delegate_info.nominators),
            }
        )
        return

    # Create table for display
    table = Table(
        title=f"\n[{COLOR_PALETTE['GENERAL']['HEADER']}]Nominators for Delegate: {hotkey_ss58}\nNetwork: {subtensor.network}\n",
        show_header=True,
        header_style="bold white",
        border_style="bright_black",
        box=box.ROUNDED,
        show_lines=False,
        pad_edge=True,
    )

    table.add_column(
        "[white]#",
        style="grey89",
        justify="right",
        width=5,
    )
    table.add_column(
        "[white]Identity",
        style="yellow",
        justify="left",
        no_wrap=False,
        width=25,
    )
    table.add_column(
        "[white]Nominator Address",
        style="cyan",
        justify="left",
        no_wrap=False,
    )
    table.add_column(
        "[white]Stake (TAO)",
        style="green",
        justify="right",
        width=15,
    )
    table.add_column(
        "[white]Stake %",
        style="magenta",
        justify="right",
        width=10,
    )

    # Sort nominators by stake (descending)
    sorted_nominators = sorted(
        delegate_info.nominators, key=lambda x: x[1].tao, reverse=True
    )

    for idx, (nominator_ss58, stake) in enumerate(sorted_nominators, 1):
        identity_name = nominator_identities.get(nominator_ss58, "~")
        # Calculate percentage of total stake
        stake_percentage = (
            (stake.tao / delegate_info.total_stake.tao * 100)
            if delegate_info.total_stake.tao > 0
            else 0
        )
        table.add_row(
            str(idx),
            identity_name,
            nominator_ss58,
            millify_tao(stake.tao),
            f"{stake_percentage:.2f}%",
        )

    # Add summary footer
    table.show_footer = True
    table.columns[0].footer = f"[white]{len(sorted_nominators)}"
    table.columns[1].footer = "[white]"
    table.columns[2].footer = "[white]Total"
    table.columns[3].footer = f"[green]{millify_tao(delegate_info.total_stake.tao)}"
    table.columns[4].footer = ""

    console.print(table)

    # Print additional delegate information
    info_table = Table(
        title=f"[{COLOR_PALETTE['GENERAL']['HEADER']}]Delegate Information",
        show_header=False,
        box=box.SIMPLE,
        show_lines=False,
    )
    info_table.add_column(style="bold white", width=25)
    info_table.add_column(style="cyan")

    info_table.add_row("Owner (Coldkey):", delegate_info.owner_ss58)
    info_table.add_row("Take:", f"{delegate_info.take * 100:.2f}%")
    info_table.add_row(
        "Total Stake:",
        f"{millify_tao(delegate_info.total_stake.tao)} TAO",
    )
    info_table.add_row("Number of Nominators:", str(len(delegate_info.nominators)))
    info_table.add_row(
        "Registrations:",
        ", ".join(map(str, delegate_info.registrations))
        if delegate_info.registrations
        else "None",
    )
    info_table.add_row(
        "Validator Permits:",
        ", ".join(map(str, delegate_info.validator_permits))
        if delegate_info.validator_permits
        else "None",
    )

    console.print("\n")
    console.print(info_table)
