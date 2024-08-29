import asyncio
import json
from typing import TypedDict, Optional, cast
from rich import box
import numpy as np
from numpy.typing import NDArray
import typer
from bittensor_wallet import Wallet
from rich.prompt import Confirm
from rich.table import Table, Column
from rich.text import Text
from scalecodec import ScaleType, GenericCall
from substrateinterface.exceptions import SubstrateRequestException

from bittensor_cli.src import DelegatesDetails
from bittensor_cli.src.bittensor.balances import Balance
from bittensor_cli.src.bittensor.chain_data import NeuronInfoLite, DelegateInfo
from bittensor_cli.src.bittensor.extrinsics.root import (
    set_root_weights_extrinsic,
    root_register_extrinsic,
)
from bittensor_cli.src.commands.wallets import (
    get_coldkey_wallets_for_path,
    set_id,
    set_id_prompts,
)
from bittensor_cli.src.subtensor_interface import SubtensorInterface
from bittensor_cli.src.utils import (
    console,
    err_console,
    get_delegates_details_from_github,
    convert_weight_uids_and_vals_to_tensor,
    ss58_to_vec_u8,
    create_table,
    render_table,
    update_metadata_table,
    get_metadata_table,
)
from bittensor_cli.src import Constants


# helpers


def display_votes(
    vote_data: "ProposalVoteData", delegate_info: dict[str, DelegatesDetails]
) -> str:
    vote_list = list()

    for address in vote_data["ayes"]:
        vote_list.append(
            "{}: {}".format(
                delegate_info[address].name if address in delegate_info else address,
                "[bold green]Aye[/bold green]",
            )
        )

    for address in vote_data["nays"]:
        vote_list.append(
            "{}: {}".format(
                delegate_info[address].name if address in delegate_info else address,
                "[bold red]Nay[/bold red]",
            )
        )

    return "\n".join(vote_list)


def format_call_data(call_data: GenericCall) -> str:
    human_call_data = list()

    for arg in call_data["call_args"]:
        arg_value = arg["value"]

        # If this argument is a nested call
        func_args = (
            format_call_data(
                {
                    "call_function": arg_value["call_function"],
                    "call_args": arg_value["call_args"],
                }
            )
            if isinstance(arg_value, dict) and "call_function" in arg_value
            else str(arg_value)
        )

        human_call_data.append("{}: {}".format(arg["name"], func_args))

    return "{}({})".format(call_data["call_function"], ", ".join(human_call_data))


class ProposalVoteData(TypedDict):
    index: int
    threshold: int
    ayes: list[str]
    nays: list[str]
    end: int


async def _get_senate_members(
    subtensor: SubtensorInterface, block_hash: Optional[str] = None
) -> list[str]:
    """
    Gets all members of the senate on the given subtensor's network

    :param subtensor: SubtensorInterface object to use for the query

    :return: list of the senate members' ss58 addresses
    """
    senate_members = await subtensor.substrate.query(
        module="SenateMembers",
        storage_function="Members",
        params=None,
        block_hash=block_hash,
    )
    if not hasattr(senate_members, "serialize"):
        raise TypeError("Senate Members cannot be serialized.")

    return senate_members.serialize()


async def _get_proposals(
    subtensor: SubtensorInterface, block_hash: str
) -> dict[str, tuple[GenericCall, ProposalVoteData]]:
    async def get_proposal_call_data(p_hash: str) -> Optional[GenericCall]:
        proposal_data = await subtensor.substrate.query(
            module="Triumvirate",
            name="ProposalOf",
            block_hash=block_hash,
            params=[p_hash],
        )
        return getattr(proposal_data, "serialize", lambda: None)()

    async def get_proposal_vote_data(p_hash: str) -> Optional[ProposalVoteData]:
        vote_data = await subtensor.substrate.query(
            module="Triumvirate", name="Voting", block_hash=block_hash, params=[p_hash]
        )
        return getattr(vote_data, "serialize", lambda: None)()

    ph = await subtensor.substrate.query(
        module="Triumvirate",
        storage_function="Proposals",
        params=None,
        block_hash=block_hash,
    )

    try:
        proposal_hashes: list[str] = ph.serialize()
    except AttributeError:
        err_console.print("Unable to retrieve proposal vote data")
        raise typer.Exit()

    call_data_, vote_data_ = await asyncio.gather(
        asyncio.gather(*[get_proposal_call_data(h) for h in proposal_hashes]),
        asyncio.gather(*[get_proposal_vote_data(h) for h in proposal_hashes]),
    )
    return {
        proposal_hash: (cd, vd)
        for cd, vd, proposal_hash in zip(call_data_, vote_data_, proposal_hashes)
    }


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
        success, err_msg = await subtensor.sign_and_send_extrinsic(
            call, wallet, wait_for_inclusion, wait_for_finalization
        )
        if not success:
            err_console.print(f":cross_mark: [red]Failed[/red]: {err_msg}")
            await asyncio.sleep(0.5)
            return False

        # Successful vote, final check for data
        else:
            if vote_data := await _get_vote_data(subtensor, proposal_hash):
                if (
                    vote_data["ayes"].count(wallet.hotkey.ss58_address) > 0
                    or vote_data["nays"].count(wallet.hotkey.ss58_address) > 0
                ):
                    console.print(":white_heavy_check_mark: [green]Vote cast.[/green]")
                    return True
                else:
                    # hotkey not found in ayes/nays
                    err_console.print(
                        ":cross_mark: [red]Unknown error. Couldn't find vote.[/red]"
                    )
                    return False
            else:
                return False


async def burned_register_extrinsic(
    subtensor: SubtensorInterface,
    wallet: Wallet,
    netuid: int,
    recycle_amount: Balance,
    old_balance: Balance,
    wait_for_inclusion: bool = False,
    wait_for_finalization: bool = True,
    prompt: bool = False,
) -> bool:
    """Registers the wallet to chain by recycling TAO.

    :param subtensor: The SubtensorInterface object to use for the call, initialized
    :param wallet: Bittensor wallet object.
    :param netuid: The `netuid` of the subnet to register on.
    :param recycle_amount: The amount of TAO required for this burn.
    :param old_balance: The wallet balance prior to the registration burn.
    :param wait_for_inclusion: If set, waits for the extrinsic to enter a block before returning `True`, or returns
                               `False` if the extrinsic fails to enter the block within the timeout.
    :param wait_for_finalization: If set, waits for the extrinsic to be finalized on the chain before returning `True`,
                                  or returns `False` if the extrinsic fails to be finalized within the timeout.
    :param prompt: If `True`, the call waits for confirmation from the user before proceeding.

    :return: Flag is `True` if extrinsic was finalized or included in the block. If we did not wait for
             finalization/inclusion, the response is `True`.
    """

    if not await subtensor.subnet_exists(netuid):
        err_console.print(
            f":cross_mark: [red]Failed[/red]: error: [bold white]subnet:{netuid}[/bold white] does not exist."
        )
        return False

    wallet.unlock_coldkey()

    with console.status(
        f":satellite: Checking Account on [bold]subnet:{netuid}[/bold]..."
    ):
        my_uid = await subtensor.substrate.query(
            "SubtensorModule", "Uids", [netuid, wallet.hotkey.ss58_address]
        )

        neuron = await subtensor.neuron_for_uid(
            uid=my_uid.value,
            netuid=netuid,
            block_hash=subtensor.substrate.last_block_hash,
        )

        if not neuron.is_null:
            console.print(
                ":white_heavy_check_mark: [green]Already Registered[/green]:\n"
                f"uid: [bold white]{neuron.uid}[/bold white]\n"
                f"netuid: [bold white]{neuron.netuid}[/bold white]\n"
                f"hotkey: [bold white]{neuron.hotkey}[/bold white]\n"
                f"coldkey: [bold white]{neuron.coldkey}[/bold white]"
            )
            return True

    with console.status(":satellite: Recycling TAO for Registration..."):
        call = await subtensor.substrate.compose_call(
            call_module="SubtensorModule",
            call_function="burned_register",
            call_params={
                "netuid": netuid,
                "hotkey": wallet.hotkey.ss58_address,
            },
        )
        success, err_msg = await subtensor.sign_and_send_extrinsic(
            call, wallet, wait_for_inclusion, wait_for_finalization
        )

    if not success:
        err_console.print(f":cross_mark: [red]Failed[/red]: {err_msg}")
        await asyncio.sleep(0.5)
        return False
    # Successful registration, final check for neuron and pubkey
    else:
        with console.status(":satellite: Checking Balance..."):
            block_hash = await subtensor.substrate.get_chain_head()
            new_balance, netuids_for_hotkey = await asyncio.gather(
                subtensor.get_balance(
                    wallet.coldkeypub.ss58_address,
                    block_hash=block_hash,
                    reuse_block=False,
                ),
                subtensor.get_netuids_for_hotkey(
                    wallet.hotkey.ss58_address, block_hash=block_hash
                ),
            )

        console.print(
            "Balance:\n"
            f"  [blue]{old_balance}[/blue] :arrow_right: [green]{new_balance[wallet.coldkey.ss58_address]}[/green]"
        )

        if len(netuids_for_hotkey) > 0:
            console.print(":white_heavy_check_mark: [green]Registered[/green]")
            return True
        else:
            # neuron not found, try again
            err_console.print(
                ":cross_mark: [red]Unknown error. Neuron not found.[/red]"
            )
            return False


async def set_take_extrinsic(
    subtensor: SubtensorInterface,
    wallet: Wallet,
    delegate_ss58: str,
    take: float = 0.0,
    wait_for_inclusion: bool = True,
    wait_for_finalization: bool = False,
) -> bool:
    """
    Set delegate hotkey take

    :param subtensor: SubtensorInterface (initialized)
    :param wallet: The wallet containing the hotkey to be nominated.
    :param delegate_ss58:  Hotkey
    :param take: Delegate take on subnet ID
    :param wait_for_finalization:  If `True`, waits until the transaction is finalized on the
                                   blockchain.
    :param wait_for_inclusion:  If `True`, waits until the transaction is included in a block.

    :return: `True` if the process is successful, `False` otherwise.

    This function is a key part of the decentralized governance mechanism of Bittensor, allowing for the
    dynamic selection and participation of validators in the network's consensus process.
    """

    async def _get_delegate_by_hotkey(ss58: str) -> Optional[DelegateInfo]:
        """Retrieves the delegate info for a given hotkey's ss58 address"""
        encoded_hotkey = ss58_to_vec_u8(ss58)
        json_body = await subtensor.substrate.rpc_request(
            method="delegateInfo_getDelegate",  # custom rpc method
            params=([encoded_hotkey, subtensor.substrate.last_block_hash]),
        )
        if not (result := json_body.get("result", None)):
            return None
        else:
            return DelegateInfo.from_vec_u8(result)

    # Calculate u16 representation of the take
    take_u16 = int(take * 0xFFFF)

    # Check if the new take is greater or lower than existing take or if existing is set
    delegate = await _get_delegate_by_hotkey(delegate_ss58)
    current_take = None
    if delegate is not None:
        current_take = int(
            float(delegate.take) * 65535.0
        )  # TODO verify this, why not u16_float_to_int?

    if take_u16 == current_take:
        console.print("Nothing to do, take hasn't changed")
        return True
    if current_take is None or current_take < take_u16:
        console.print(
            "Current take is either not set or is lower than the new one. Will use increase_take"
        )
        with console.status(
            f":satellite: Sending decrease_take_extrinsic call on [white]{subtensor}[/white] ..."
        ):
            call = await subtensor.substrate.compose_call(
                call_module="SubtensorModule",
                call_function="increase_take",
                call_params={
                    "hotkey": delegate_ss58,
                    "take": take_u16,
                },
            )
            success, err = await subtensor.sign_and_send_extrinsic(call, wallet)

    else:
        console.print("Current take is higher than the new one. Will use decrease_take")
        with console.status(
            f":satellite: Sending increase_take_extrinsic call on [white]{subtensor}[/white] ..."
        ):
            call = await subtensor.substrate.compose_call(
                call_module="SubtensorModule",
                call_function="decrease_take",
                call_params={
                    "hotkey": delegate_ss58,
                    "take": take_u16,
                },
            )
            success, err = await subtensor.sign_and_send_extrinsic(call, wallet)

    if not success:
        err_console.print(err)
    else:
        console.print(":white_heavy_check_mark: [green]Finalized[/green]")
    return success


async def delegate_extrinsic(
    subtensor: SubtensorInterface,
    wallet: Wallet,
    delegate_ss58: str,
    amount: Balance,
    wait_for_inclusion: bool = True,
    wait_for_finalization: bool = False,
    prompt: bool = False,
    delegate: bool = True,
) -> bool:
    """Delegates the specified amount of stake to the passed delegate.

    :param subtensor: The SubtensorInterface used to perform the delegation, initialized.
    :param wallet: Bittensor wallet object.
    :param delegate_ss58: The `ss58` address of the delegate.
    :param amount: Amount to stake as bittensor balance
    :param wait_for_inclusion: If set, waits for the extrinsic to enter a block before returning `True`, or returns
                              `False` if the extrinsic fails to enter the block within the timeout.
    :param wait_for_finalization: If set, waits for the extrinsic to be finalized on the chain before returning `True`,
                                  or returns `False` if the extrinsic fails to be finalized within the timeout.
    :param prompt: If `True`, the call waits for confirmation from the user before proceeding.
    :param delegate: whether to delegate (`True`) or undelegate (`False`)

    :return: `True` if extrinsic was finalized or included in the block. If we did not wait for finalization/inclusion,
             the response is `True`.
    """

    async def _do_delegation() -> tuple[bool, str]:
        """Performs the delegation extrinsic call to the chain."""
        if delegate:
            call = await subtensor.substrate.compose_call(
                call_module="SubtensorModule",
                call_function="add_stake",
                call_params={"hotkey": delegate_ss58, "amount_staked": amount.rao},
            )
        else:
            call = await subtensor.substrate.compose_call(
                call_module="SubtensorModule",
                call_function="remove_stake",
                call_params={"hotkey": delegate_ss58, "amount_unstaked": amount.rao},
            )
        return await subtensor.sign_and_send_extrinsic(
            call, wallet, wait_for_inclusion, wait_for_finalization
        )

    async def get_hotkey_owner(ss58: str, block_hash_: str):
        """Returns the coldkey owner of the passed hotkey."""
        if not await subtensor.does_hotkey_exist(ss58, block_hash=block_hash_):
            return None
        _result = await subtensor.substrate.query(
            module="SubtensorModule",
            storage_function="Owner",
            params=[ss58],
            block_hash=block_hash_,
        )
        return getattr(_result, "value", None)

    async def get_stake_for_coldkey_and_hotkey(
        hotkey_ss58: str, coldkey_ss58: str, block_hash_: str
    ):
        """Returns the stake under a coldkey - hotkey pairing."""
        _result = await subtensor.substrate.query(
            module="SubtensorModule",
            storage_function="Stake",
            params=[hotkey_ss58, coldkey_ss58],
            block_hash=block_hash_,
        )
        return (
            Balance.from_rao(_result.value) if getattr(_result, "value", None) else None
        )

    delegate_string = "delegate" if delegate else "undelegate"

    # Decrypt key
    wallet.unlock_coldkey()
    if not await subtensor.is_hotkey_delegate(delegate_ss58):
        err_console.print(f"Hotkey: {delegate_ss58} is not a delegate.")
        return False

    # Get state.
    with console.status(
        f":satellite: Syncing with [bold white]{subtensor}[/bold white] ..."
    ):
        initial_block_hash = await subtensor.substrate.get_chain_head()
        (
            my_prev_coldkey_balance_,
            delegate_owner,
            my_prev_delegated_stake,
        ) = await asyncio.gather(
            subtensor.get_balance(
                wallet.coldkey.ss58_address, block_hash=initial_block_hash
            ),
            get_hotkey_owner(delegate_ss58, block_hash_=initial_block_hash),
            get_stake_for_coldkey_and_hotkey(
                coldkey_ss58=wallet.coldkeypub.ss58_address,
                hotkey_ss58=delegate_ss58,
                block_hash_=initial_block_hash,
            ),
        )

    my_prev_coldkey_balance = my_prev_coldkey_balance_[wallet.coldkey.ss58_address]

    # Convert to bittensor.Balance
    if amount is None:
        # Stake it all.
        staking_balance = Balance.from_tao(my_prev_coldkey_balance.tao)
    else:
        staking_balance = amount

    if delegate:
        # Remove existential balance to keep key alive.
        if staking_balance > (b1k := Balance.from_rao(1000)):
            staking_balance = staking_balance - b1k
        else:
            staking_balance = staking_balance

    # Check enough balance to stake.
    if staking_balance > my_prev_coldkey_balance:
        err_console.print(
            ":cross_mark: [red]Not enough balance[/red]:[bold white]\n"
            f"  balance:{my_prev_coldkey_balance}\n"
            f"  amount: {staking_balance}\n"
            f"  coldkey: {wallet.name}[/bold white]"
        )
        return False

    if delegate_string == "undelegate" and (
        my_prev_delegated_stake is None or staking_balance > my_prev_delegated_stake
    ):
        err_console.print(
            "\n:cross_mark: [red]Not enough balance to unstake[/red]:\n"
            f"  [bold blue]current stake[/bold blue]: {my_prev_delegated_stake}\n"
            f"  [bold red]amount unstaking[/bold red]: {staking_balance}\n"
            f"  [bold white]coldkey: {wallet.name}[/bold white]\n\n"
        )
        return False

    # Ask before moving on.
    if prompt:
        if not Confirm.ask(
            f"\n[bold blue]Current stake[/bold blue]: [blue]{my_prev_delegated_stake}[/blue]\n"
            f"[bold white]Do you want to {delegate_string}:[/bold white]\n"
            f"  [bold red]amount[/bold red]: [red]{staking_balance}\n[/red]"
            f"  [bold yellow]to hotkey[/bold yellow]: [yellow]{delegate_ss58}\n[/yellow]"
            f"  [bold green]hotkey owner[/bold green]: [green]{delegate_owner}[/green]"
        ):
            return False

    with console.status(
        f":satellite: Staking to: [bold white]{subtensor}[/bold white] ..."
    ):
        staking_response, err_msg = await _do_delegation()

    if staking_response is True:  # If we successfully staked.
        # We only wait here if we expect finalization.
        if not wait_for_finalization and not wait_for_inclusion:
            return True

        console.print(":white_heavy_check_mark: [green]Finalized[/green]\n")
        with console.status(
            f":satellite: Checking Balance on: [white]{subtensor}[/white] ..."
        ):
            block_hash = await subtensor.substrate.get_chain_head()
            new_balance, new_delegate_stake = await asyncio.gather(
                subtensor.get_balance(
                    wallet.coldkey.ss58_address, block_hash=block_hash
                ),
                get_stake_for_coldkey_and_hotkey(
                    coldkey_ss58=wallet.coldkeypub.ss58_address,
                    hotkey_ss58=delegate_ss58,
                    block_hash_=block_hash,
                ),
            )

        console.print(
            "Balance:\n"
            f"  [blue]{my_prev_coldkey_balance}[/blue] :arrow_right: [green]{new_balance[wallet.coldkey.ss58_address]}[/green]\n"
            "Stake:\n"
            f"  [blue]{my_prev_delegated_stake}[/blue] :arrow_right: [green]{new_delegate_stake}[/green]"
        )
        return True
    else:
        err_console.print(f":cross_mark: [red]Failed[/red]: {err_msg}")
        return False


async def nominate_extrinsic(
    subtensor: SubtensorInterface,
    wallet: Wallet,
    wait_for_finalization: bool = False,
    wait_for_inclusion: bool = True,
) -> bool:
    """Becomes a delegate for the hotkey.

    :param wallet: The unlocked wallet to become a delegate for.
    :param subtensor: The SubtensorInterface to use for the transaction
    :param wait_for_finalization: Wait for finalization or not
    :param wait_for_inclusion: Wait for inclusion or not

    :return: success
    """
    with console.status(
        ":satellite: Sending nominate call on [white]{}[/white] ...".format(
            subtensor.network
        )
    ):
        call = await subtensor.substrate.compose_call(
            call_module="SubtensorModule",
            call_function="become_delegate",
            call_params={"hotkey": wallet.hotkey.ss58_address},
        )
        success, err_msg = await subtensor.sign_and_send_extrinsic(
            call,
            wallet,
            wait_for_inclusion=wait_for_inclusion,
            wait_for_finalization=wait_for_finalization,
        )

        if success is True:
            console.print(":white_heavy_check_mark: [green]Finalized[/green]")

        else:
            err_console.print(f":cross_mark: [red]Failed[/red]: error:{err_msg}")
        return success


# Commands


async def root_list(subtensor: SubtensorInterface):
    """List the root network"""

    async def _get_list() -> tuple:
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
            "[bold white]UID",
            style="dark_orange",
            no_wrap=True,
        ),
        Column(
            "[bold white]NAME",
            style="bright_cyan",
            no_wrap=True,
        ),
        Column(
            "[bold white]ADDRESS",
            style="bright_magenta",
            no_wrap=True,
        ),
        Column(
            "[bold white]STAKE(\u03c4)",
            justify="right",
            style="light_goldenrod2",
            no_wrap=True,
        ),
        Column(
            "[bold white]SENATOR",
            style="dark_sea_green",
            no_wrap=True,
        ),
        title="[underline dark_orange]Root Network",
        show_footer=True,
        show_edge=False,
        expand=False,
        border_style="bright_black",
    )
    with console.status(
        f":satellite: Syncing with chain: [white]{subtensor}[/white] ..."
    ):
        senate_members, root_neurons, delegate_info, total_stakes = await _get_list()

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
    netuids: list[int],
    weights: list[float],
    prompt: bool,
):
    """Set weights for root network."""
    netuids_ = np.array(netuids, dtype=np.int64)
    weights_ = np.array(weights, dtype=np.float32)

    # Run the set weights operation.

    await set_root_weights_extrinsic(
        subtensor=subtensor,
        wallet=wallet,
        netuids=netuids_,
        weights=weights_,
        version_key=0,
        prompt=prompt,
        wait_for_finalization=True,
        wait_for_inclusion=True,
    )


async def get_weights(
    subtensor: SubtensorInterface,
    limit_min_col: Optional[int],
    limit_max_col: Optional[int],
    reuse_last: bool,
    html_output: bool,
    no_cache: bool,
):
    """Get weights for root network."""
    if not reuse_last:
        with console.status(":satellite: Synchronizing with chain..."):
            weights = await subtensor.weights(0)

        uid_to_weights: dict[int, dict] = {}
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
        rows: list[list[str]] = []
        for uid in uid_to_weights:
            row = [str(uid)]

            uid_weights = uid_to_weights[uid]
            for netuid in netuids:
                if netuid in uid_weights:
                    row.append("{:0.2f}%".format(uid_weights[netuid] * 100))
                else:
                    row.append("~")
            rows.append(row)

        if not no_cache:
            db_cols = [("UID", "INTEGER")]
            for netuid in netuids:
                db_cols.append((f"_{netuid}", "TEXT"))
            create_table("rootgetweights", db_cols, rows)
            netuids = list(netuids)
            update_metadata_table(
                "rootgetweights",
                {"rows": json.dumps(rows), "netuids": json.dumps(netuids)},
            )
    else:
        metadata = get_metadata_table("rootgetweights")
        rows = json.loads(metadata["rows"])
        netuids = json.loads(metadata["netuids"])

    _min_lim = limit_min_col if limit_min_col is not None else 0
    _max_lim = limit_max_col + 1 if limit_max_col is not None else len(netuids)
    _max_lim = min(_max_lim, len(netuids))

    if _min_lim is not None and _min_lim > len(netuids):
        err_console.print("Minimum limit greater than number of netuids")
        return

    if not html_output:
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

        for netuid in cast(list, netuids)[_min_lim:_max_lim]:
            table.add_column(
                f"[white]{netuid}",
                header_style="overline white",
                footer_style="overline white",
                justify="right",
                style="green",
                no_wrap=True,
            )

        # Adding rows
        for row in rows:
            new_row = [row[0]] + row[_min_lim:_max_lim]
            table.add_row(*new_row)

        return console.print(table)

    else:
        html_cols = [{"title": "UID", "field": "UID"}]
        for netuid in netuids[_min_lim:_max_lim]:
            html_cols.append({"title": str(netuid), "field": f"_{netuid}"})
        render_table(
            "rootgetweights",
            "Root Network Weights",
            html_cols,
        )


async def _get_my_weights(
    subtensor: SubtensorInterface, ss58_address: str, my_uid: str
) -> NDArray[np.float32]:
    """Retrieves the weight array for a given hotkey SS58 address."""

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
    wallet: Wallet,
    subtensor: SubtensorInterface,
    netuid: int,
    amount: float,
    prompt: bool,
):
    """Boosts weight of a given netuid for root network."""

    my_uid = (
        await subtensor.substrate.query(
            "SubtensorModule", "Uids", [0, wallet.hotkey.ss58_address]
        )
    ).value
    if my_uid is None:
        err_console.print("Your hotkey is not registered to the root network")
        return False

    my_weights = await _get_my_weights(subtensor, wallet.hotkey.ss58_address, my_uid)
    prev_weight = my_weights[netuid]
    new_weight = prev_weight + amount

    console.print(
        f"Boosting weight for netuid {netuid} from {prev_weight} -> {new_weight}"
    )
    my_weights[netuid] = new_weight
    all_netuids = np.arange(len(my_weights))

    console.print("all netuids", all_netuids)
    await set_root_weights_extrinsic(
        subtensor=subtensor,
        wallet=wallet,
        netuids=all_netuids,
        weights=my_weights,
        version_key=0,
        wait_for_inclusion=True,
        wait_for_finalization=True,
        prompt=prompt,
    )


async def set_slash(
    wallet: Wallet,
    subtensor: SubtensorInterface,
    netuid: int,
    amount: float,
    prompt: bool,
):
    """Slashes weight I think"""

    my_uid = (
        await subtensor.substrate.query(
            "SubtensorModule", "Uids", [0, wallet.hotkey.ss58_address]
        )
    ).value
    if my_uid is None:
        err_console.print("Your hotkey is not registered to the root network")
        return False

    my_weights = await _get_my_weights(subtensor, wallet.hotkey.ss58_address, my_uid)
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
            prompt=prompt,
        )


async def senate_vote(
    wallet: Wallet,
    subtensor: SubtensorInterface,
    proposal_hash: str,
    prompt: bool,
) -> bool:
    """Vote in Bittensor's governance protocol proposals"""

    if not proposal_hash:
        console.print(
            'Aborting: Proposal hash not specified. View all proposals with the "proposals" command.'
        )
        return False

    if not await _is_senate_member(subtensor, hotkey_ss58=wallet.hotkey.ss58_address):
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
        prompt=prompt,
    )

    return success


async def get_senate(subtensor: SubtensorInterface):
    """View Bittensor's governance protocol proposals"""
    with console.status(
        f":satellite: Syncing with chain: [white]{subtensor}[/white] ..."
    ):
        senate_members = await _get_senate_members(subtensor)

    delegate_info: dict[
        str, DelegatesDetails
    ] = await get_delegates_details_from_github(Constants.delegates_detail_url)

    table = Table(
        Column(
            "[bold white]NAME",
            style="bright_cyan",
            no_wrap=True,
        ),
        Column(
            "[bold white]ADDRESS",
            style="bright_magenta",
            no_wrap=True,
        ),
        title="[dark_orange]Senate",
        show_footer=True,
        show_edge=False,
        expand=False,
        border_style="bright_black",
    )

    for ss58_address in senate_members:
        table.add_row(
            (delegate_info[ss58_address].name if ss58_address in delegate_info else ""),
            ss58_address,
        )

    return console.print(table)


async def register(wallet: Wallet, subtensor: SubtensorInterface, prompt: bool):
    """Register neuron by recycling some TAO."""

    # Check current recycle amount
    recycle_call, balance_ = await asyncio.gather(
        subtensor.get_hyperparameter(param_name="Burn", netuid=0, reuse_block=True),
        subtensor.get_balance(wallet.coldkeypub.ss58_address, reuse_block=True),
    )
    try:
        current_recycle = Balance.from_rao(int(recycle_call))
        balance: Balance = balance_[wallet.coldkeypub.ss58_address]
    except TypeError:
        err_console.print("Unable to retrieve current recycle.")
        return False
    except KeyError:
        err_console.print("Unable to retrieve current balance.")
        return False

    # Check balance is sufficient
    if balance < current_recycle:
        err_console.print(
            f"[red]Insufficient balance {balance} to register neuron. "
            f"Current recycle is {current_recycle} TAO[/red]"
        )
        return False

    if prompt:
        if not Confirm.ask(
            f"Your balance is: [bold green]{balance}[/bold green]\n"
            f"The cost to register by recycle is [bold red]{current_recycle}[/bold red]\n"
            f"Do you want to continue?",
            default=False,
        ):
            return False

    await root_register_extrinsic(
        subtensor,
        wallet,
        wait_for_inclusion=True,
        wait_for_finalization=True,
        prompt=prompt,
    )


async def proposals(subtensor: SubtensorInterface):
    console.print(
        ":satellite: Syncing with chain: [white]{}[/white] ...".format(
            subtensor.network
        )
    )
    block_hash = await subtensor.substrate.get_chain_head()
    senate_members, all_proposals = await asyncio.gather(
        _get_senate_members(subtensor, block_hash),
        _get_proposals(subtensor, block_hash),
    )

    registered_delegate_info: dict[
        str, DelegatesDetails
    ] = await get_delegates_details_from_github(Constants.delegates_detail_url)

    table = Table(
        Column(
            "[overline white]HASH",
            footer_style="overline white",
            style="yellow",
            no_wrap=True,
        ),
        Column(
            "[overline white]THRESHOLD", footer_style="overline white", style="white"
        ),
        Column("[overline white]AYES", footer_style="overline white", style="green"),
        Column("[overline white]NAYS", footer_style="overline white", style="red"),
        Column(
            "[overline white]VOTES",
            footer_style="overline white",
            style="rgb(50,163,219)",
        ),
        Column("[overline white]END", footer_style="overline white", style="blue"),
        Column(
            "[overline white]CALLDATA", footer_style="overline white", style="white"
        ),
        title=f"[white]Proposals\t\tActive Proposals: {len(all_proposals)}\t\tSenate Size: {len(senate_members)}",
        show_footer=True,
        box=None,
        pad_edge=False,
        width=None,
    )

    for hash_ in all_proposals:
        call_data, vote_data = all_proposals[hash_]

        table.add_row(
            hash_,
            str(vote_data["threshold"]),
            str(len(vote_data["ayes"])),
            str(len(vote_data["nays"])),
            display_votes(vote_data, registered_delegate_info),
            str(vote_data["end"]),
            format_call_data(call_data),
        )

    return console.print(table)


async def set_take(wallet: Wallet, subtensor: SubtensorInterface, take: float) -> bool:
    """Set delegate take."""

    async def _do_set_take() -> bool:
        """
        Just more easily allows an early return and to close the substrate interface after the logic
        """

        # Check if the hotkey is not a delegate.
        if not await subtensor.is_hotkey_delegate(wallet.hotkey.ss58_address):
            err_console.print(
                f"Aborting: Hotkey {wallet.hotkey.ss58_address} is NOT a delegate."
            )
            return False

        if take > 0.18 or take < 0.08:
            err_console.print("ERROR: Take value should not exceed 18% or be below 8%")
            return False

        result: bool = await set_take_extrinsic(
            subtensor=subtensor,
            wallet=wallet,
            delegate_ss58=wallet.hotkey.ss58_address,
            take=take,
        )

        if not result:
            err_console.print("Could not set the take")
            return False
        else:
            # Check if we are a delegate.
            is_delegate: bool = await subtensor.is_hotkey_delegate(
                wallet.hotkey.ss58_address
            )
            if not is_delegate:
                err_console.print(
                    "Could not set the take [white]{}[/white]".format(subtensor.network)
                )
                return False
            else:
                console.print(
                    "Successfully set the take on [white]{}[/white]".format(
                        subtensor.network
                    )
                )
                return True

    # Unlock the wallet.
    wallet.unlock_hotkey()
    wallet.unlock_coldkey()

    result_ = await _do_set_take()

    return result_


async def delegate_stake(
    wallet: Wallet,
    subtensor: SubtensorInterface,
    amount: float,
    delegate_ss58key: str,
    prompt: bool,
):
    """Delegates stake to a chain delegate."""

    await delegate_extrinsic(
        subtensor,
        wallet,
        delegate_ss58key,
        Balance.from_tao(amount),
        wait_for_inclusion=True,
        prompt=prompt,
        delegate=True,
    )


async def delegate_unstake(
    wallet: Wallet,
    subtensor: SubtensorInterface,
    amount: float,
    delegate_ss58key: str,
    prompt: bool,
):
    """Undelegates stake from a chain delegate."""
    await delegate_extrinsic(
        subtensor,
        wallet,
        delegate_ss58key,
        Balance.from_tao(amount),
        wait_for_inclusion=True,
        prompt=prompt,
        delegate=False,
    )


async def my_delegates(
    wallet: Wallet, subtensor: SubtensorInterface, all_wallets: bool
):
    """Delegates stake to a chain delegate."""

    async def wallet_to_delegates(
        w: Wallet, bh: str
    ) -> tuple[Optional[Wallet], Optional[list[tuple[DelegateInfo, Balance]]]]:
        """Helper function to retrieve the validity of the wallet (if it has a coldkeypub on the device)
        and its delegate info."""
        if not w.coldkeypub_file.exists_on_device():
            return None, None
        else:
            delegates_ = await subtensor.get_delegated(
                w.coldkeypub.ss58_address, block_hash=bh
            )
            return w, delegates_

    wallets = get_coldkey_wallets_for_path(wallet.path) if all_wallets else [wallet]

    table = Table(
        Column("[white]Wallet", style="bright_magenta"),
        Column(
            "[white]OWNER",
            style="bold bright_cyan",
            no_wrap=True,
            justify="left",
        ),
        Column("[white]SS58", style="#d7d7ff", justify="center"),
        Column(
            "[white]Delegation",
            style="dark_orange",
        ),
        Column(
            "[white]\u03c4/24h",
            style="bold green",
        ),
        Column("[white]NOMS", justify="center", style="rgb(42,161,152)", no_wrap=True),
        Column(
            "[white]OWNER STAKE(\u03c4)",
            justify="right",
            style="light_goldenrod2",
            no_wrap=True,
        ),
        Column(
            "[white]TOTAL STAKE(\u03c4)",
            justify="right",
            style="light_goldenrod2",
            no_wrap=True,
        ),
        Column("[white]SUBNETS", justify="right", style="white", no_wrap=True),
        Column("[white]VPERMIT", justify="right", no_wrap=True),
        Column("[white]24h/k\u03c4", style="rgb(42,161,152)", justify="center"),
        Column("[white]Desc", style="rgb(50,163,219)"),
        title="[underline dark_orange]My Delegates\n",
        show_footer=True,
        show_edge=False,
        expand=False,
        box=box.SIMPLE_HEAVY,
        border_style="bright_black",
    )

    total_delegated = 0

    # TODO: this doesnt work when passed to wallets_with_delegates
    # block_hash = await subtensor.substrate.get_chain_head()

    registered_delegate_info: dict[str, DelegatesDetails]
    wallets_with_delegates: tuple[
        tuple[Optional[Wallet], Optional[list[tuple[DelegateInfo, Balance]]]]
    ]
    wallets_with_delegates, registered_delegate_info = await asyncio.gather(
        asyncio.gather(*[wallet_to_delegates(wallet_, None) for wallet_ in wallets]),
        get_delegates_details_from_github(Constants.delegates_detail_url),
    )
    if not registered_delegate_info:
        console.print(
            ":warning:[yellow]Could not get delegate info from chain.[/yellow]"
        )

    for wall, delegates in wallets_with_delegates:
        if not wall or not delegates:
            continue

        my_delegates_ = {}  # hotkey, amount
        for delegate in delegates:
            for coldkey_addr, staked in delegate[0].nominators:
                if coldkey_addr == wall.coldkeypub.ss58_address and staked.tao > 0:
                    my_delegates_[delegate[0].hotkey_ss58] = staked

        delegates.sort(key=lambda d: d[0].total_stake, reverse=True)
        total_delegated += sum(my_delegates_.values())

        for i, delegate in enumerate(delegates):
            owner_stake = next(
                (
                    stake
                    for owner, stake in delegate[0].nominators
                    if owner == delegate[0].owner_ss58
                ),
                Balance.from_rao(0),  # default to 0 if no owner stake.
            )
            if delegate[0].hotkey_ss58 in registered_delegate_info:
                delegate_name = registered_delegate_info[delegate[0].hotkey_ss58].name
                delegate_url = registered_delegate_info[delegate[0].hotkey_ss58].url
                delegate_description = registered_delegate_info[
                    delegate[0].hotkey_ss58
                ].description
            else:
                delegate_name = ""
                delegate_url = ""
                delegate_description = ""

            if delegate[0].hotkey_ss58 in my_delegates_:
                twenty_four_hour = delegate[0].total_daily_return.tao * (
                    my_delegates_[delegate[0].hotkey_ss58] / delegate[0].total_stake.tao
                )
                table.add_row(
                    wall.name,
                    Text(delegate_name, style=f"link {delegate_url}"),
                    f"{delegate[0].hotkey_ss58}",
                    f"{my_delegates_[delegate[0].hotkey_ss58]!s:13.13}",
                    f"{twenty_four_hour!s:6.6}",
                    str(len(delegate[0].nominators)),
                    f"{owner_stake!s:13.13}",
                    f"{delegate[0].total_stake!s:13.13}",
                    str(delegate[0].registrations),
                    str(
                        [
                            "*" if subnet in delegate[0].validator_permits else ""
                            for subnet in delegate[0].registrations
                        ]
                    ),
                    f"{delegate[0].total_daily_return.tao * (1000 / (0.001 + delegate[0].total_stake.tao))!s:6.6}",
                    str(delegate_description),
                )

    console.print(table)
    console.print(f"Total delegated Tao: {total_delegated}")


async def list_delegates(subtensor: SubtensorInterface):
    """List all delegates on the network."""

    with console.status(":satellite: Loading delegates..."):
        block_hash, registered_delegate_info = await asyncio.gather(
            subtensor.substrate.get_chain_head(),
            get_delegates_details_from_github(Constants.delegates_detail_url),
        )
        block_number = await subtensor.substrate.get_block_number(block_hash)
        delegates: list[DelegateInfo] = await subtensor.get_delegates(
            block_hash=block_hash
        )

        # try:
        #     prev_block_hash = await subtensor.substrate.get_block_hash(
        #         max(0, block_number - 1200)
        #     )
        #     prev_delegates = await subtensor.get_delegates(block_hash=prev_block_hash)
        # except SubstrateRequestException:
        prev_delegates = None

    if prev_delegates is None:
        err_console.print(
            ":warning: [yellow]Could not fetch delegates history[/yellow]"
        )

    delegates.sort(key=lambda d: d.total_stake, reverse=True)
    prev_delegates_dict = {}
    if prev_delegates is not None:
        for prev_delegate in prev_delegates:
            prev_delegates_dict[prev_delegate.hotkey_ss58] = prev_delegate

    if not registered_delegate_info:
        console.print(
            ":warning:[yellow]Could not get delegate info from chain.[/yellow]"
        )

    table = Table(
        Column(
            "[white]INDEX",
            str(len(delegates)),
            footer_style="overline white",
            style="bold white",
        ),
        Column(
            "[white]DELEGATE",
            style="bold bright_cyan",
            no_wrap=True,
            justify="left",
        ),
        Column(
            "[white]SS58",
            str(len(delegates)),
            footer_style="overline white",
            style="bright_magenta",
        ),
        Column(
            "[white]NOMINATORS", justify="center", style="dark_sea_green", no_wrap=True
        ),
        Column(
            "[white]DELEGATE STAKE(\u03c4)",
            justify="right",
            style="orange1",
            no_wrap=True,
        ),
        Column(
            "[white]TOTAL STAKE(\u03c4)",
            justify="right",
            style="light_goldenrod2",
            no_wrap=True,
        ),
        Column("[white]CHANGE/(4h)", style="grey0", justify="center"),
        Column("[white]VPERMIT", justify="right", no_wrap=False),
        Column("[white]TAKE", style="white", no_wrap=True),
        Column(
            "[white]NOMINATOR/(24h)/k\u03c4", style="rgb(42,161,152)", justify="center"
        ),
        Column("[white]DELEGATE/(24h)", style="rgb(42,161,152)", justify="center"),
        Column("[white]Desc", style="rgb(50,163,219)"),
        title="[underline dark_orange]Root Delegates\n",
        show_footer=True,
        width=None,
        pad_edge=False,
        box=None,
        expand=True,
    )

    for i, delegate in enumerate(delegates):
        owner_stake = next(
            (
                stake
                for owner, stake in delegate.nominators
                if owner == delegate.owner_ss58
            ),
            Balance.from_rao(0),  # default to 0 if no owner stake.
        )
        if delegate.hotkey_ss58 in registered_delegate_info:
            delegate_name = registered_delegate_info[delegate.hotkey_ss58].name
            delegate_url = registered_delegate_info[delegate.hotkey_ss58].url
            delegate_description = registered_delegate_info[
                delegate.hotkey_ss58
            ].description
        else:
            delegate_name = ""
            delegate_url = ""
            delegate_description = ""

        if delegate.hotkey_ss58 in prev_delegates_dict:
            prev_stake = prev_delegates_dict[delegate.hotkey_ss58].total_stake
            if prev_stake == 0:
                rate_change_in_stake_str = "[green]100%[/green]"
            else:
                rate_change_in_stake = (
                    100
                    * (float(delegate.total_stake) - float(prev_stake))
                    / float(prev_stake)
                )
                if rate_change_in_stake > 0:
                    rate_change_in_stake_str = "[green]{:.2f}%[/green]".format(
                        rate_change_in_stake
                    )
                elif rate_change_in_stake < 0:
                    rate_change_in_stake_str = "[red]{:.2f}%[/red]".format(
                        rate_change_in_stake
                    )
                else:
                    rate_change_in_stake_str = "[grey0]0%[/grey0]"
        else:
            rate_change_in_stake_str = "[grey0]NA[/grey0]"

        table.add_row(
            # INDEX
            str(i),
            # DELEGATE
            Text(delegate_name, style=f"link {delegate_url}"),
            # SS58
            f"{delegate.hotkey_ss58:8.8}...",
            # NOMINATORS
            str(len([nom for nom in delegate.nominators if nom[1].rao > 0])),
            # DELEGATE STAKE
            f"{owner_stake!s:13.13}",
            # TOTAL STAKE
            f"{delegate.total_stake!s:13.13}",
            # CHANGE/(4h)
            rate_change_in_stake_str,
            # VPERMIT
            str(delegate.registrations),
            # TAKE
            f"{delegate.take * 100:.1f}%",
            # NOMINATOR/(24h)/k
            f"{Balance.from_tao(delegate.total_daily_return.tao * (1000 / (0.001 + delegate.total_stake.tao)))!s:6.6}",
            # DELEGATE/(24h)
            f"{Balance.from_tao(delegate.total_daily_return.tao * 0.18) !s:6.6}",
            # Desc
            str(delegate_description),
            end_section=True,
        )
    console.print(table)


async def nominate(wallet: Wallet, subtensor: SubtensorInterface, prompt: bool):
    """Nominate wallet."""

    # Unlock the wallet.
    wallet.unlock_hotkey()
    wallet.unlock_coldkey()

    # Check if the hotkey is already a delegate.
    if await subtensor.is_hotkey_delegate(wallet.hotkey.ss58_address):
        err_console.print(
            f"Aborting: Hotkey {wallet.hotkey.ss58_address} is already a delegate."
        )
        return

    result: bool = await nominate_extrinsic(subtensor, wallet)
    if not result:
        err_console.print(
            f"Could not became a delegate on [white]{subtensor.network}[/white]"
        )
        return
    else:
        # Check if we are a delegate.
        is_delegate: bool = await subtensor.is_hotkey_delegate(
            wallet.hotkey.ss58_address
        )
        if not is_delegate:
            err_console.print(
                f"Could not became a delegate on [white]{subtensor.network}[/white]"
            )
            return
        console.print(
            f"Successfully became a delegate on [white]{subtensor.network}[/white]"
        )

        # Prompt use to set identity on chain.
        if prompt:
            do_set_identity = Confirm.ask(
                "Subnetwork registered successfully. Would you like to set your identity? [y/n]"
            )

            if do_set_identity:
                id_prompts = set_id_prompts()
                await set_id(wallet, subtensor, *id_prompts)
