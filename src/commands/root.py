import numpy as np
import typer
from bittensor_wallet import Wallet
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

        rn: list[NeuronInfoLite] = await subtensor.neurons_lite(netuid=0)
        if not rn:
            return None, None, None, None

        di: dict[str, DelegatesDetails] = await get_delegates_details_from_github(
            url=Constants.delegates_detail_url
        )
        ts: dict[str, ScaleType] = await subtensor.substrate.query_multiple(
            [n.hotkey for n in rn],
            module="SubtensorModule",
            storage_function="TotalHotkeyStake",
            reuse_block_hash=True,
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
        ),
        title="[white]Root Network",
        show_footer=True,
        box=None,
        pad_edge=False,
        width=None,
    )
    with console.status(
            f":satellite: Syncing with chain: [white]{subtensor}[/white] ..."
    ):
        senate_members, root_neurons, delegate_info, total_stakes = await _get_list()

    await subtensor.substrate.close()

    if not root_neurons:
        err_console.print(
            f"[red]Error: No neurons detected on network:[/red] [white]{subtensor}"
        )
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


async def set_weights(
        wallet: Wallet,
        subtensor: SubtensorInterface,
        netuids_: list[int],
        weights_: list[float],
):
    """Set weights for root network."""
    netuids_ = np.array(netuids_, dtype=np.int64)
    weights_ = np.array(weights_, dtype=np.float32)

    # Run the set weights operation.
    subtensor.root_set_weights(
        wallet=wallet,
        netuids=netuids_,
        weights=weights_,
        version_key=0,
        prompt=True,
        wait_for_finalization=True,
        wait_for_inclusion=True,
    )


async def get_weights(subtensor: SubtensorInterface):
    """Get weights for root network."""
    with console.status(":satellite: Synchronizing with chain..."):
        async with subtensor:
            weights = subtensor.weights(0)

    await subtensor.substrate.close()

    uid_to_weights = {}
    netuids = set()
    for matrix in weights:
        [uid, weights_data] = matrix

        if not len(weights_data):
            uid_to_weights[uid] = {}
            normalized_weights = []
        else:
            normalized_weights = np.array(weights_data)[:, 1] / max(
                np.sum(weights_data, axis=0)[1], 1
            )

        for weight_data, normalized_weight in zip(weights_data, normalized_weights):
            [netuid, _] = weight_data
            netuids.add(netuid)
            if uid not in uid_to_weights:
                uid_to_weights[uid] = {}

            uid_to_weights[uid][netuid] = normalized_weight

    table = Table(
        show_footer=True,
        box=None,
        pad_edge=False,
        width=None,
        title="[white]Root Network Weights",
    )
    table.add_column(
        "[white]UID",
        header_style="overline white",
        footer_style="overline white",
        style="rgb(50,163,219)",
        no_wrap=True,
    )
    for netuid in netuids:
        table.add_column(
            f"[white]{netuid}",
            header_style="overline white",
            footer_style="overline white",
            justify="right",
            style="green",
            no_wrap=True,
        )

    for uid in uid_to_weights:
        row = [str(uid)]

        uid_weights = uid_to_weights[uid]
        for netuid in netuids:
            if netuid in uid_weights:
                row.append("{:0.2f}%".format(uid_weights[netuid] * 100))
            else:
                row.append("~")
        table.add_row(*row)

    return console.print(table)


async def set_boots(wallet: Wallet, subtensor: SubtensorInterface, netuid: int, amount: float):
    """Set weights for root network."""

    root = subtensor.metagraph(0, lite=False)
    try:
        my_uid = root.hotkeys.index(wallet.hotkey.ss58_address)
    except ValueError:
        err_console.print(
            "Wallet hotkey: {} not found in root metagraph".format(wallet.hotkey)
        )
        raise typer.Exit()

    my_weights = root.weights[my_uid]
    prev_weight = my_weights[netuid]
    new_weight = prev_weight + amount

    console.print(
        f"Boosting weight for netuid {netuid} from {prev_weight} -> {new_weight}"
    )
    my_weights[netuid] = new_weight
    all_netuids = np.arange(len(my_weights))

    with console.status("Setting root weights..."):
        subtensor.root_set_weights(
            wallet=wallet,
            netuids=all_netuids,
            weights=my_weights,
            version_key=0,
            prompt=True,
            wait_for_finalization=True,
            wait_for_inclusion=True,
        )
