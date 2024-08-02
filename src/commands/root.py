import typer
from rich.table import Table, Column
from scalecodec import ScaleType

from src import DelegatesDetails
from src.bittensor.balances import Balance
from src.bittensor.chain_data import NeuronInfoLite
from src.subtensor_interface import SubtensorInterface
from src.utils import console, err_console, get_delegates_details_from_github
from src import Constants


async def root_list(subtensor: SubtensorInterface):
    """List the root network"""
    async def _get_list() -> tuple:
        async with subtensor:
            senate_query = await subtensor.substrate.query(
                module="SenateMembers",
                storage_function="Members",
                params=None,
            )
        sm = senate_query.serialize() if hasattr(senate_query, "serialize") else None

        rn: list[NeuronInfoLite] = await subtensor.neurons_lite(
            netuid=0
        )
        if not rn:
            return None, None, None, None

        di: dict[str, DelegatesDetails] = await get_delegates_details_from_github(
            url=Constants.delegates_detail_url
        )
        ts: dict[str, ScaleType] = await subtensor.substrate.query_multiple(
            [n.hotkey for n in rn],
            module="SubtensorModule",
            storage_function="TotalHotkeyStake",
            reuse_block_hash=True
        )
        return sm, rn, di, ts

    table = Table(
        Column(
            "[overline white]UID",
            footer_style="overline white",
            style="rgb(50,163,219)",
            no_wrap=True,
        ),
        Column(
            "[overline white]NAME",
            footer_style="overline white",
            style="rgb(50,163,219)",
            no_wrap=True,
        ),
        Column(
            "[overline white]ADDRESS",
            footer_style="overline white",
            style="yellow",
            no_wrap=True,
        ),
        Column(
            "[overline white]STAKE(\u03c4)",
            footer_style="overline white",
            justify="right",
            style="green",
            no_wrap=True,
        ),
        Column(
            "[overline white]SENATOR",
            footer_style="overline white",
            style="green",
            no_wrap=True,
        ), title="[white]Root Network",
        show_footer=True,
        box=None,
        pad_edge=False,
        width=None
    )
    with console.status(f":satellite: Syncing with chain: [white]{subtensor}[/white] ..."):
        senate_members, root_neurons, delegate_info, total_stakes = await _get_list()

    await subtensor.substrate.close()

    if not root_neurons:
        err_console.print(f"[red]Error: No neurons detected on network:[/red] [white]{subtensor}")
        raise typer.Exit()

    for neuron_data in root_neurons:
        table.add_row(
            str(neuron_data.uid),
            (
                delegate_info[neuron_data.hotkey].name
                if neuron_data.hotkey in delegate_info
                else ""
            ),
            neuron_data.hotkey,
            "{:.5f}".format(
                float(Balance.from_rao(total_stakes[neuron_data.hotkey].value))
            ),
            "Yes" if neuron_data.hotkey in senate_members else "No",
        )

    return console.print(table)
