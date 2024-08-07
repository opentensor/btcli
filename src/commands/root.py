import asyncio
from typing import TypedDict, Optional

import numpy as np
from numpy.typing import NDArray
import typer
from bittensor_wallet import Wallet
from rich.prompt import Confirm
from rich.table import Table, Column
from scalecodec import ScaleType

from src import DelegatesDetails
from src.bittensor.balances import Balance
from src.bittensor.chain_data import NeuronInfoLite
from src.bittensor.extrinsics.root import set_root_weights_extrinsic
from src.subtensor_interface import SubtensorInterface
from src.utils import (
    console,
    err_console,
    get_delegates_details_from_github,
    convert_weight_uids_and_vals_to_tensor,
    format_error_message,
)
from src import Constants


class ProposalVoteData(TypedDict):
    index: int
    threshold: int
    ayes: list[str]
    nays: list[str]
    end: int


async def _get_senate_members(subtensor: SubtensorInterface) -> list[str]:
    """
    Gets all members of the senate on the given subtensor's network

    :param subtensor: SubtensorInterface object to use for the query

    :return: list of the senate members' ss58 addresses
    """
    senate_members = await subtensor.substrate.query(
        module="SenateMembers", storage_function="Members", params=None
    )
    if not hasattr(senate_members, "serialize"):
        raise TypeError("Senate Members cannot be serialized.")

    return senate_members.serialize()


async def _is_senate_member(subtensor: SubtensorInterface, hotkey_ss58: str) -> bool:
    """
    Checks if a given neuron (identified by its hotkey SS58 address) is a member of the Bittensor senate.
    The senate is a key governance body within the Bittensor network, responsible for overseeing and
    approving various network operations and proposals.

    :param subtensor: SubtensorInterface object to use for the query
    :param hotkey_ss58: The `SS58` address of the neuron's hotkey.

    :return: `True` if the neuron is a senate member at the given block, `False` otherwise.

    This function is crucial for understanding the governance dynamics of the Bittensor network and for
    identifying the neurons that hold decision-making power within the network.
    """

    senate_members = await _get_senate_members(subtensor)

    if not hasattr(senate_members, "count"):
        return False

    return senate_members.count(hotkey_ss58) > 0


async def _get_vote_data(
    subtensor: SubtensorInterface,
    proposal_hash: str,
    block_hash: Optional[str] = None,
    reuse_block: bool = False,
) -> Optional[ProposalVoteData]:
    """
    Retrieves the voting data for a specific proposal on the Bittensor blockchain. This data includes
    information about how senate members have voted on the proposal.

    :param subtensor: The SubtensorInterface object to use for the query
    :param proposal_hash: The hash of the proposal for which voting data is requested.
    :param block_hash: The hash of the blockchain block number to query the voting data.
    :param reuse_block: Whether to reuse the last-used blockchain block hash.

    :return: An object containing the proposal's voting data, or `None` if not found.

    This function is important for tracking and understanding the decision-making processes within
    the Bittensor network, particularly how proposals are received and acted upon by the governing body.
    """
    vote_data = await subtensor.substrate.query(
        module="Triumvirate",
        storage_function="Voting",
        params=[proposal_hash],
        block_hash=block_hash,
        reuse_block_hash=reuse_block,
    )
    if not hasattr(vote_data, "serialize"):
        return None
    return vote_data.serialize() if vote_data is not None else None


async def vote_senate_extrinsic(
    subtensor: SubtensorInterface,
    wallet: Wallet,
    proposal_hash: str,
    proposal_idx: int,
    vote: bool,
    wait_for_inclusion: bool = False,
    wait_for_finalization: bool = True,
    prompt: bool = False,
) -> bool:
    """Votes ayes or nays on proposals.

    :param subtensor: The SubtensorInterface object to use for the query
    :param wallet: Bittensor wallet object, with coldkey and hotkey unlocked.
    :param proposal_hash: The hash of the proposal for which voting data is requested.
    :param proposal_idx: The index of the proposal to vote.
    :param vote: Whether to vote aye or nay.
    :param wait_for_inclusion: If set, waits for the extrinsic to enter a block before returning `True`, or returns
                               `False` if the extrinsic fails to enter the block within the timeout.
    :param wait_for_finalization: If set, waits for the extrinsic to be finalized on the chain before returning `True`,
                                  or returns `False` if the extrinsic fails to be finalized within the timeout.
    :param prompt: If `True`, the call waits for confirmation from the user before proceeding.

    :return: Flag is `True` if extrinsic was finalized or included in the block. If we did not wait for
             finalization/inclusion, the response is `True`.
    """

    if prompt:
        # Prompt user for confirmation.
        if not Confirm.ask(f"Cast a vote of {vote}?"):
            return False

    with console.status(":satellite: Casting vote.."):
        call = await subtensor.substrate.compose_call(
            call_module="SubtensorModule",
            call_function="vote",
            call_params={
                "hotkey": wallet.hotkey.ss58_address,
                "proposal": proposal_hash,
                "index": proposal_idx,
                "approve": vote,
            },
        )
        extrinsic = await subtensor.substrate.create_signed_extrinsic(
            call=call, keypair=wallet.coldkey
        )
        response = await subtensor.substrate.submit_extrinsic(
            extrinsic,
            wait_for_inclusion=wait_for_inclusion,
            wait_for_finalization=wait_for_finalization,
        )

        # We only wait here if we expect finalization.
        if not wait_for_finalization and not wait_for_inclusion:
            return True

        # process if vote successful
        response.process_events()
        if not response.is_success:
            err_console.print(
                f":cross_mark: [red]Failed[/red]: {format_error_message(response.error_message)}"
            )
            await asyncio.sleep(0.5)
            return False

        # Successful vote, final check for data
        else:
            vote_data = await _get_vote_data(subtensor, proposal_hash)
            has_voted = (
                vote_data["ayes"].count(wallet.hotkey.ss58_address) > 0
                or vote_data["nays"].count(wallet.hotkey.ss58_address) > 0
            )

            if has_voted:
                console.print(":white_heavy_check_mark: [green]Vote cast.[/green]")
                return True
            else:
                # hotkey not found in ayes/nays
                err_console.print(
                    ":cross_mark: [red]Unknown error. Couldn't find vote.[/red]"
                )
                return False


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
    with console.status("Setting root weights..."):
        async with subtensor:
            await set_root_weights_extrinsic(
                subtensor=subtensor,
                wallet=wallet,
                netuids=netuids_,
                weights=weights_,
                version_key=0,
                prompt=True,
                wait_for_finalization=True,
                wait_for_inclusion=True,
            )
    await subtensor.substrate.close()


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


async def _get_my_weights(
    subtensor: SubtensorInterface, ss58_address: str
) -> NDArray[np.float32]:
    """Retrieves the weight array for a given hotkey SS58 address."""
    async with subtensor:
        my_uid = (
            await subtensor.substrate.query(
                "SubtensorModule", "Uids", [0, ss58_address]
            )
        ).value
        print("uid", my_uid)
        my_weights_, total_subnets_ = await asyncio.gather(
            subtensor.substrate.query(
                "SubtensorModule", "Weights", [0, my_uid], reuse_block_hash=True
            ),
            subtensor.substrate.query(
                "SubtensorModule", "TotalNetworks", reuse_block_hash=True
            ),
        )
    my_weights: list[tuple[int, int]] = my_weights_.value
    for i, w in enumerate(my_weights):
        if w:
            print(i, w)
    total_subnets: int = total_subnets_.value

    uids, values = zip(*my_weights)
    weight_array = convert_weight_uids_and_vals_to_tensor(total_subnets, uids, values)
    return weight_array


async def set_boost(
    wallet: Wallet, subtensor: SubtensorInterface, netuid: int, amount: float
):
    """Boosts weight of a given netuid for root network."""

    my_weights = await _get_my_weights(subtensor, wallet.hotkey.ss58_address)
    prev_weight = my_weights[netuid]
    new_weight = prev_weight + amount

    console.print(
        f"Boosting weight for netuid {netuid} from {prev_weight} -> {new_weight}"
    )
    my_weights[netuid] = new_weight
    all_netuids = np.arange(len(my_weights))

    console.print("all netuids", all_netuids)
    with console.status("Setting root weights..."):
        await set_root_weights_extrinsic(
            subtensor=subtensor,
            wallet=wallet,
            netuids=all_netuids,
            weights=my_weights,
            version_key=0,
            wait_for_inclusion=True,
            wait_for_finalization=True,
            prompt=True,
        )
    await subtensor.substrate.close()


async def set_slash(
    wallet: Wallet, subtensor: SubtensorInterface, netuid: int, amount: float
):
    """Slashes weight I think"""
    my_weights = await _get_my_weights(subtensor, wallet.hotkey.ss58_address)
    prev_weights = my_weights.copy()
    my_weights[netuid] -= amount
    my_weights[my_weights < 0] = 0  # Ensure weights don't go negative
    all_netuids = np.arange(len(my_weights))

    console.print(f"Slash weights from {prev_weights} -> {my_weights}")

    with console.status("Setting root weights..."):
        await set_root_weights_extrinsic(
            subtensor=subtensor,
            wallet=wallet,
            netuids=all_netuids,
            weights=my_weights,
            version_key=0,
            wait_for_inclusion=True,
            wait_for_finalization=True,
            prompt=True,
        )
    await subtensor.substrate.close()


async def senate_vote(
    wallet: Wallet, subtensor: SubtensorInterface, proposal_hash: str
) -> bool:
    """Vote in Bittensor's governance protocol proposals"""

    if not proposal_hash:
        console.print(
            'Aborting: Proposal hash not specified. View all proposals with the "proposals" command.'
        )
        return False

    async with subtensor:
        if not await _is_senate_member(
            subtensor, hotkey_ss58=wallet.hotkey.ss58_address
        ):
            err_console.print(
                f"Aborting: Hotkey {wallet.hotkey.ss58_address} isn't a senate member."
            )
            return False

        # Unlock the wallet.
        wallet.unlock_hotkey()
        wallet.unlock_coldkey()

        vote_data = await _get_vote_data(subtensor, proposal_hash, reuse_block=True)
        if not vote_data:
            err_console.print(":cross_mark: [red]Failed[/red]: Proposal not found.")
            return False

        vote: bool = Confirm.ask("Desired vote for proposal")
        success = await vote_senate_extrinsic(
            subtensor=subtensor,
            wallet=wallet,
            proposal_hash=proposal_hash,
            proposal_idx=vote_data["index"],
            vote=vote,
            wait_for_inclusion=True,
            wait_for_finalization=False,
            prompt=True,
        )

    await subtensor.substrate.close()
    return success


async def get_senate(subtensor: SubtensorInterface):
    """View Bittensor's governance protocol proposals"""
    console.print(f":satellite: Syncing with chain: [white]{subtensor}[/white] ...")
    async with subtensor:
        senate_members = await _get_senate_members(subtensor)

    delegate_info: Optional[
        dict[str, DelegatesDetails]
    ] = await get_delegates_details_from_github(Constants.delegates_detail_url)

    await subtensor.substrate.close()

    table = Table(
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
        title="[white]Senate",
        show_footer=True,
        box=None,
        pad_edge=False,
        width=None,
    )

    for ss58_address in senate_members:
        table.add_row(
            (delegate_info[ss58_address].name if ss58_address in delegate_info else ""),
            ss58_address,
        )

    return console.print(table)
