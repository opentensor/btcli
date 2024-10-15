import asyncio
import json
from typing import Optional, TYPE_CHECKING

from bittensor_wallet import Wallet
from bittensor_wallet.errors import KeyFileError
import numpy as np
from numpy.typing import NDArray
from rich import box
from rich.prompt import Confirm
from rich.table import Column, Table
from rich.text import Text
from scalecodec import GenericCall, ScaleType
from substrateinterface.exceptions import SubstrateRequestException
import typer

from bittensor_cli.src import DelegatesDetails
from bittensor_cli.src.bittensor.balances import Balance
from bittensor_cli.src.bittensor.chain_data import (
    DelegateInfo,
    NeuronInfoLite,
    decode_account_id,
)
from bittensor_cli.src.bittensor.extrinsics.root import (
    root_register_extrinsic,
    set_root_weights_extrinsic,
)
from bittensor_cli.src.commands.wallets import (
    get_coldkey_wallets_for_path,
    set_id,
    set_id_prompts,
)
from bittensor_cli.src.bittensor.subtensor_interface import SubtensorInterface
from bittensor_cli.src.bittensor.utils import (
    console,
    convert_weight_uids_and_vals_to_tensor,
    create_table,
    err_console,
    print_verbose,
    get_metadata_table,
    render_table,
    ss58_to_vec_u8,
    update_metadata_table,
    group_subnets,
)

if TYPE_CHECKING:
    from bittensor_cli.src.bittensor.subtensor_interface import ProposalVoteData

# helpers


def display_votes(
    vote_data: "ProposalVoteData", delegate_info: dict[str, DelegatesDetails]
) -> str:
    vote_list = list()

    for address in vote_data.ayes:
        vote_list.append(
            "{}: {}".format(
                delegate_info[address].display if address in delegate_info else address,
                "[bold green]Aye[/bold green]",
            )
        )

    for address in vote_data.nays:
        vote_list.append(
            "{}: {}".format(
                delegate_info[address].display if address in delegate_info else address,
                "[bold red]Nay[/bold red]",
            )
        )

    return "\n".join(vote_list)


def format_call_data(call_data: dict) -> str:
    # Extract the module and call details
    module, call_details = next(iter(call_data.items()))

    # Extract the call function name and arguments
    call_info = call_details[0]
    call_function, call_args = next(iter(call_info.items()))

    # Extract the argument, handling tuple values
    formatted_args = ", ".join(
        str(arg[0]) if isinstance(arg, tuple) else str(arg)
        for arg in call_args.values()
    )

    # Format the final output string
    return f"{call_function}({formatted_args})"


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
    try:
        return [
            decode_account_id(i[x][0]) for i in senate_members for x in range(len(i))
        ]
    except (IndexError, TypeError):
        err_console.print("Unable to retrieve senate members.")
        return []


async def _get_proposals(
    subtensor: SubtensorInterface, block_hash: str
) -> dict[str, tuple[dict, "ProposalVoteData"]]:
    async def get_proposal_call_data(p_hash: str) -> Optional[GenericCall]:
        proposal_data = await subtensor.substrate.query(
            module="Triumvirate",
            storage_function="ProposalOf",
            block_hash=block_hash,
            params=[p_hash],
        )
        return proposal_data

    ph = await subtensor.substrate.query(
        module="Triumvirate",
        storage_function="Proposals",
        params=None,
        block_hash=block_hash,
    )

    try:
        proposal_hashes: list[str] = [
            f"0x{bytes(ph[0][x][0]).hex()}" for x in range(len(ph[0]))
        ]
    except (IndexError, TypeError):
        err_console.print("Unable to retrieve proposal vote data")
        return {}

    call_data_, vote_data_ = await asyncio.gather(
        asyncio.gather(*[get_proposal_call_data(h) for h in proposal_hashes]),
        asyncio.gather(*[subtensor.get_vote_data(h) for h in proposal_hashes]),
    )
    return {
        proposal_hash: (cd, vd)
        for cd, vd, proposal_hash in zip(call_data_, vote_data_, proposal_hashes)
    }


def _validate_proposal_hash(proposal_hash: str) -> bool:
    if proposal_hash[0:2] != "0x" or len(proposal_hash) != 66:
        return False
    else:
        return True


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

    with console.status(":satellite: Casting vote..", spinner="aesthetic"):
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
            if vote_data := await subtensor.get_vote_data(proposal_hash):
                if (
                    vote_data.ayes.count(wallet.hotkey.ss58_address) > 0
                    or vote_data.nays.count(wallet.hotkey.ss58_address) > 0
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
    wait_for_inclusion: bool = True,
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

    try:
        wallet.unlock_coldkey()
    except KeyFileError:
        err_console.print("Error decrypting coldkey (possibly incorrect password)")
        return False

    with console.status(
        f":satellite: Checking Account on [bold]subnet:{netuid}[/bold]...",
        spinner="aesthetic",
    ) as status:
        my_uid = await subtensor.substrate.query(
            "SubtensorModule", "Uids", [netuid, wallet.hotkey.ss58_address]
        )

        print_verbose("Checking if already registered", status)
        neuron = await subtensor.neuron_for_uid(
            uid=my_uid,
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

    with console.status(
        ":satellite: Recycling TAO for Registration...", spinner="aesthetic"
    ):
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
        with console.status(":satellite: Checking Balance...", spinner="aesthetic"):
            block_hash = await subtensor.substrate.get_chain_head()
            new_balance, netuids_for_hotkey, my_uid = await asyncio.gather(
                subtensor.get_balance(
                    wallet.coldkeypub.ss58_address,
                    block_hash=block_hash,
                    reuse_block=False,
                ),
                subtensor.get_netuids_for_hotkey(
                    wallet.hotkey.ss58_address, block_hash=block_hash
                ),
                subtensor.substrate.query(
                    "SubtensorModule", "Uids", [netuid, wallet.hotkey.ss58_address]
                ),
            )

        console.print(
            "Balance:\n"
            f"  [blue]{old_balance}[/blue] :arrow_right: [green]{new_balance[wallet.coldkey.ss58_address]}[/green]"
        )

        if len(netuids_for_hotkey) > 0:
            console.print(
                f":white_heavy_check_mark: [green]Registered on netuid {netuid} with UID {my_uid}[/green]"
            )
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
            return DelegateInfo.from_vec_u8(bytes(result))

    # Calculate u16 representation of the take
    take_u16 = int(take * 0xFFFF)

    print_verbose("Checking current take")
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
            f"Current take is {float(delegate.take):.4f}. Increasing to {take:.4f}."
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
        console.print(
            f"Current take is {float(delegate.take):.4f}. Decreasing to {take:.4f}."
        )
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
    amount: Optional[float],
    wait_for_inclusion: bool = True,
    wait_for_finalization: bool = False,
    prompt: bool = False,
    delegate: bool = True,
) -> bool:
    """Delegates the specified amount of stake to the passed delegate.

    :param subtensor: The SubtensorInterface used to perform the delegation, initialized.
    :param wallet: Bittensor wallet object.
    :param delegate_ss58: The `ss58` address of the delegate.
    :param amount: Amount to stake as bittensor balance, None to stake all available TAO.
    :param wait_for_inclusion: If set, waits for the extrinsic to enter a block before returning `True`, or returns
                              `False` if the extrinsic fails to enter the block within the timeout.
    :param wait_for_finalization: If set, waits for the extrinsic to be finalized on the chain before returning `True`,
                                  or returns `False` if the extrinsic fails to be finalized within the timeout.
    :param prompt: If `True`, the call waits for confirmation from the user before proceeding.
    :param delegate: whether to delegate (`True`) or undelegate (`False`)

    :return: `True` if extrinsic was finalized or included in the block. If we did not wait for finalization/inclusion,
             the response is `True`.
    """

    async def _do_delegation(staking_balance_: Balance) -> tuple[bool, str]:
        """Performs the delegation extrinsic call to the chain."""
        if delegate:
            call = await subtensor.substrate.compose_call(
                call_module="SubtensorModule",
                call_function="add_stake",
                call_params={
                    "hotkey": delegate_ss58,
                    "amount_staked": staking_balance_.rao,
                },
            )
        else:
            call = await subtensor.substrate.compose_call(
                call_module="SubtensorModule",
                call_function="remove_stake",
                call_params={
                    "hotkey": delegate_ss58,
                    "amount_unstaked": staking_balance_.rao,
                },
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
        return decode_account_id(_result[0])

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
        return Balance.from_rao(_result or 0)

    delegate_string = "delegate" if delegate else "undelegate"

    # Decrypt key
    try:
        wallet.unlock_coldkey()
    except KeyFileError:
        err_console.print("Error decrypting coldkey (possibly incorrect password)")
        return False

    print_verbose("Checking if hotkey is a delegate")
    if not await subtensor.is_hotkey_delegate(delegate_ss58):
        err_console.print(f"Hotkey: {delegate_ss58} is not a delegate.")
        return False

    # Get state.
    with console.status(
        f":satellite: Syncing with [bold white]{subtensor}[/bold white] ...",
        spinner="aesthetic",
    ) as status:
        print_verbose("Fetching balance, stake, and ownership", status)
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
        if delegate_string == "delegate":
            staking_balance = Balance.from_tao(my_prev_coldkey_balance.tao)
        else:
            # Unstake all
            staking_balance = Balance.from_tao(my_prev_delegated_stake.tao)
    else:
        staking_balance = Balance.from_tao(amount)

    # Check enough balance to stake.
    if delegate_string == "delegate" and staking_balance > my_prev_coldkey_balance:
        err_console.print(
            ":cross_mark: [red]Not enough balance to stake[/red]:\n"
            f"  [bold blue]current balance[/bold blue]:{my_prev_coldkey_balance}\n"
            f"  [bold red]amount staking[/bold red]: {staking_balance}\n"
            f"  [bold white]coldkey: {wallet.name}[/bold white]"
        )
        return False

    if delegate_string == "undelegate" and (
        my_prev_delegated_stake is None or staking_balance > my_prev_delegated_stake
    ):
        err_console.print(
            "\n:cross_mark: [red]Not enough balance to unstake[/red]:\n"
            f"  [bold blue]current stake[/bold blue]: {my_prev_delegated_stake}\n"
            f"  [bold red]amount unstaking[/bold red]: {staking_balance}\n"
            f"  [bold white]coldkey: {wallet.name}[bold white]\n\n"
        )
        return False

    if delegate:
        # Grab the existential deposit.
        existential_deposit = await subtensor.get_existential_deposit()

        # Remove existential balance to keep key alive.
        if staking_balance > my_prev_coldkey_balance - existential_deposit:
            staking_balance = my_prev_coldkey_balance - existential_deposit
        else:
            staking_balance = staking_balance

    # Ask before moving on.
    if prompt:
        if not Confirm.ask(
            f"\n[bold blue]Current stake[/bold blue]: [blue]{my_prev_delegated_stake}[/blue]\n"
            f"[bold white]Do you want to {delegate_string}:[/bold white]\n"
            f"  [bold red]amount[/bold red]: [red]{staking_balance}\n[/red]"
            f"  [bold yellow]{'to' if delegate_string == 'delegate' else 'from'} hotkey[/bold yellow]: [yellow]{delegate_ss58}\n[/yellow]"
            f"  [bold green]hotkey owner[/bold green]: [green]{delegate_owner}[/green]"
        ):
            return False

    with console.status(
        f":satellite: Staking to: [bold white]{subtensor}[/bold white] ...",
        spinner="aesthetic",
    ) as status:
        print_verbose("Transmitting delegate operation call")
        staking_response, err_msg = await _do_delegation(staking_balance)

    if staking_response is True:  # If we successfully staked.
        # We only wait here if we expect finalization.
        if not wait_for_finalization and not wait_for_inclusion:
            return True

        console.print(":white_heavy_check_mark: [green]Finalized[/green]\n")
        with console.status(
            f":satellite: Checking Balance on: [white]{subtensor}[/white] ...",
            spinner="aesthetic",
        ) as status:
            print_verbose("Fetching balance and stakes", status)
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
        sm = [decode_account_id(i[x][0]) for i in senate_query for x in range(len(i))]

        rn: list[NeuronInfoLite] = await subtensor.neurons_lite(netuid=0)
        if not rn:
            return [], [], {}, {}

        di: dict[str, DelegatesDetails] = await subtensor.get_delegate_identities()
        ts: dict[str, ScaleType] = await subtensor.substrate.query_multiple(
            [n.hotkey for n in rn],
            module="SubtensorModule",
            storage_function="TotalHotkeyStake",
            reuse_block_hash=True,
        )
        return sm, rn, di, ts

    with console.status(
        f":satellite: Syncing with chain: [white]{subtensor}[/white] ...",
        spinner="aesthetic",
    ):
        senate_members, root_neurons, delegate_info, total_stakes = await _get_list()
        total_tao = sum(
            float(Balance.from_rao(total_stakes[neuron.hotkey]))
            for neuron in root_neurons
        )

        table = Table(
            Column(
                "[bold white]UID",
                style="dark_orange",
                no_wrap=True,
                footer=f"[bold]{len(root_neurons)}[/bold]",
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
                footer=f"{total_tao:.2f} (\u03c4) ",
            ),
            Column(
                "[bold white]SENATOR",
                style="dark_sea_green",
                no_wrap=True,
            ),
            title=f"[underline dark_orange]Root Network[/underline dark_orange]\n[dark_orange]Network {subtensor.network}",
            show_footer=True,
            show_edge=False,
            expand=False,
            border_style="bright_black",
            leading=True,
        )

        if not root_neurons:
            err_console.print(
                f"[red]Error: No neurons detected on the network:[/red] [white]{subtensor}"
            )
            raise typer.Exit()

        sorted_root_neurons = sorted(
            root_neurons,
            key=lambda neuron: float(Balance.from_rao(total_stakes[neuron.hotkey])),
            reverse=True,
        )

    for neuron_data in sorted_root_neurons:
        table.add_row(
            str(neuron_data.uid),
            (
                delegate_info[neuron_data.hotkey].display
                if neuron_data.hotkey in delegate_info
                else "~"
            ),
            neuron_data.hotkey,
            "{:.5f}".format(float(Balance.from_rao(total_stakes[neuron_data.hotkey]))),
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
    console.print(f"Setting weights in [dark_orange]network: {subtensor.network}")

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
        with console.status(
            ":satellite: Fetching weights from chain...", spinner="aesthetic"
        ):
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
        netuids = list(netuids)
        for netuid in netuids[_min_lim:_max_lim]:
            table.add_column(
                f"[white]{netuid}",
                header_style="overline white",
                footer_style="overline white",
                justify="right",
                style="green",
                no_wrap=True,
            )

        if not rows:
            err_console.print("No weights exist on the root network.")
            return

        # Adding rows
        for row in rows:
            new_row = [row[0]] + row[_min_lim + 1 : _max_lim + 1]
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
    # If setting weights for the first time, pass 0 root weights
    my_weights: list[tuple[int, int]] = (
        my_weights_ if my_weights_ is not None else [(0, 0)]
    )
    total_subnets: int = total_subnets_

    print_verbose("Fetching current weights")
    for _, w in enumerate(my_weights):
        if w:
            print_verbose(f"{w}")

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
    console.print(f"Boosting weights in [dark_orange]network: {subtensor.network}")
    print_verbose(f"Fetching uid of hotkey on root: {wallet.hotkey_str}")
    my_uid = await subtensor.substrate.query(
        "SubtensorModule", "Uids", [0, wallet.hotkey.ss58_address]
    )

    if my_uid is None:
        err_console.print("Your hotkey is not registered to the root network")
        return False

    print_verbose("Fetching current weights")
    my_weights = await _get_my_weights(subtensor, wallet.hotkey.ss58_address, my_uid)
    prev_weights = my_weights.copy()
    my_weights[netuid] += amount
    all_netuids = np.arange(len(my_weights))

    console.print(
        f"Boosting weight for netuid {netuid}\n\tfrom {prev_weights[netuid]} to {my_weights[netuid]}\n"
    )
    console.print(
        f"Previous weights -> Raw weights: \n\t{prev_weights} -> \n\t{my_weights}"
    )

    print_verbose(f"All netuids: {all_netuids}")
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
    """Slashes weight"""
    console.print(f"Slashing weights in [dark_orange]network: {subtensor.network}")
    print_verbose(f"Fetching uid of hotkey on root: {wallet.hotkey_str}")
    my_uid = await subtensor.substrate.query(
        "SubtensorModule", "Uids", [0, wallet.hotkey.ss58_address]
    )
    if my_uid is None:
        err_console.print("Your hotkey is not registered to the root network")
        return False

    print_verbose("Fetching current weights")
    my_weights = await _get_my_weights(subtensor, wallet.hotkey.ss58_address, my_uid)
    prev_weights = my_weights.copy()
    my_weights[netuid] -= amount
    my_weights[my_weights < 0] = 0  # Ensure weights don't go negative
    all_netuids = np.arange(len(my_weights))

    console.print(
        f"Slashing weight for netuid {netuid}\n\tfrom {prev_weights[netuid]} to {my_weights[netuid]}\n"
    )
    console.print(
        f"Previous weights -> Raw weights: \n\t{prev_weights} -> \n\t{my_weights}"
    )

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
    vote: bool,
    prompt: bool,
) -> bool:
    """Vote in Bittensor's governance protocol proposals"""

    if not proposal_hash:
        err_console.print(
            "Aborting: Proposal hash not specified. View all proposals with the `proposals` command."
        )
        return False
    elif not _validate_proposal_hash(proposal_hash):
        err_console.print(
            "Aborting. Proposal hash is invalid. Proposal hashes should start with '0x' and be 32 bytes long"
        )
        return False

    print_verbose(f"Fetching senate status of {wallet.hotkey_str}")
    if not await _is_senate_member(subtensor, hotkey_ss58=wallet.hotkey.ss58_address):
        err_console.print(
            f"Aborting: Hotkey {wallet.hotkey.ss58_address} isn't a senate member."
        )
        return False

    # Unlock the wallet.
    try:
        wallet.unlock_hotkey()
        wallet.unlock_coldkey()
    except KeyFileError:
        err_console.print("Error decrypting coldkey (possibly incorrect password)")
        return False

    console.print(f"Fetching proposals in [dark_orange]network: {subtensor.network}")
    vote_data = await subtensor.get_vote_data(proposal_hash, reuse_block=True)
    if not vote_data:
        err_console.print(":cross_mark: [red]Failed[/red]: Proposal not found.")
        return False

    success = await vote_senate_extrinsic(
        subtensor=subtensor,
        wallet=wallet,
        proposal_hash=proposal_hash,
        proposal_idx=vote_data.index,
        vote=vote,
        wait_for_inclusion=True,
        wait_for_finalization=False,
        prompt=prompt,
    )

    return success


async def get_senate(subtensor: SubtensorInterface):
    """View Bittensor's governance protocol proposals"""
    with console.status(
        f":satellite: Syncing with chain: [white]{subtensor}[/white] ...",
        spinner="aesthetic",
    ) as status:
        print_verbose("Fetching senate members", status)
        senate_members = await _get_senate_members(subtensor)

    print_verbose("Fetching member details from Github")
    delegate_info: dict[
        str, DelegatesDetails
    ] = await subtensor.get_delegate_identities()

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
        title=f"[underline dark_orange]Senate[/underline dark_orange]\n[dark_orange]Network: {subtensor.network}\n",
        show_footer=True,
        show_edge=False,
        expand=False,
        border_style="bright_black",
        leading=True,
    )

    for ss58_address in senate_members:
        table.add_row(
            (
                delegate_info[ss58_address].display
                if ss58_address in delegate_info
                else "~"
            ),
            ss58_address,
        )

    return console.print(table)


async def register(wallet: Wallet, subtensor: SubtensorInterface, prompt: bool):
    """Register neuron by recycling some TAO."""

    console.print(
        f"Registering on [dark_orange]netuid 0[/dark_orange] on network: [dark_orange]{subtensor.network}"
    )

    # Check current recycle amount
    print_verbose("Fetching recycle amount & balance")
    recycle_call, balance_ = await asyncio.gather(
        subtensor.get_hyperparameter(param_name="Burn", netuid=0, reuse_block=True),
        subtensor.get_balance(wallet.coldkeypub.ss58_address, reuse_block=True),
    )
    current_recycle = Balance.from_rao(int(recycle_call))
    try:
        balance: Balance = balance_[wallet.coldkeypub.ss58_address]
    except TypeError as e:
        err_console.print(f"Unable to retrieve current recycle. {e}")
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
    print_verbose("Fetching senate members & proposals")
    block_hash = await subtensor.substrate.get_chain_head()
    senate_members, all_proposals = await asyncio.gather(
        _get_senate_members(subtensor, block_hash),
        _get_proposals(subtensor, block_hash),
    )

    print_verbose("Fetching member information from Chain")
    registered_delegate_info: dict[
        str, DelegatesDetails
    ] = await subtensor.get_delegate_identities()

    table = Table(
        Column(
            "[white]HASH",
            style="light_goldenrod2",
            no_wrap=True,
        ),
        Column("[white]THRESHOLD", style="rgb(42,161,152)"),
        Column("[white]AYES", style="green"),
        Column("[white]NAYS", style="red"),
        Column(
            "[white]VOTES",
            style="rgb(50,163,219)",
        ),
        Column("[white]END", style="bright_cyan"),
        Column("[white]CALLDATA", style="dark_sea_green"),
        title=f"\n[dark_orange]Proposals\t\t\nActive Proposals: {len(all_proposals)}\t\tSenate Size: {len(senate_members)}\nNetwork: {subtensor.network}",
        show_footer=True,
        box=box.SIMPLE_HEAVY,
        pad_edge=False,
        width=None,
        border_style="bright_black",
    )
    for hash_, (call_data, vote_data) in all_proposals.items():
        table.add_row(
            hash_,
            str(vote_data.threshold),
            str(len(vote_data.ayes)),
            str(len(vote_data.nays)),
            display_votes(vote_data, registered_delegate_info),
            str(vote_data.end),
            format_call_data(call_data),
        )
    return console.print(table)


async def set_take(wallet: Wallet, subtensor: SubtensorInterface, take: float) -> bool:
    """Set delegate take."""

    async def _do_set_take() -> bool:
        """
        Just more easily allows an early return and to close the substrate interface after the logic
        """
        print_verbose("Checking if hotkey is a delegate")
        # Check if the hotkey is not a delegate.
        if not await subtensor.is_hotkey_delegate(wallet.hotkey.ss58_address):
            err_console.print(
                f"Aborting: Hotkey {wallet.hotkey.ss58_address} is NOT a delegate."
            )
            return False

        if take > 0.18 or take < 0:
            err_console.print("ERROR: Take value should not exceed 18% or be below 0%")
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

    console.print(f"Setting take on [dark_orange]network: {subtensor.network}")
    # Unlock the wallet.
    try:
        wallet.unlock_hotkey()
        wallet.unlock_coldkey()
    except KeyFileError:
        err_console.print("Error decrypting coldkey (possibly incorrect password)")
        return False

    result_ = await _do_set_take()

    return result_


async def delegate_stake(
    wallet: Wallet,
    subtensor: SubtensorInterface,
    amount: Optional[float],
    delegate_ss58key: str,
    prompt: bool,
):
    """Delegates stake to a chain delegate."""
    console.print(f"Delegating stake on [dark_orange]network: {subtensor.network}")
    await delegate_extrinsic(
        subtensor,
        wallet,
        delegate_ss58key,
        amount,
        wait_for_inclusion=True,
        prompt=prompt,
        delegate=True,
    )


async def delegate_unstake(
    wallet: Wallet,
    subtensor: SubtensorInterface,
    amount: Optional[float],
    delegate_ss58key: str,
    prompt: bool,
):
    """Undelegates stake from a chain delegate."""
    console.print(f"Undelegating stake on [dark_orange]network: {subtensor.network}")
    await delegate_extrinsic(
        subtensor,
        wallet,
        delegate_ss58key,
        amount,
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
        Column("[white]Wallet", style="bright_cyan"),
        Column(
            "[white]OWNER",
            style="bold bright_cyan",
            overflow="fold",
            justify="left",
            ratio=1,
        ),
        Column(
            "[white]SS58",
            style="bright_magenta",
            justify="left",
            overflow="fold",
            ratio=3,
        ),
        Column("[white]Delegation", style="dark_orange", no_wrap=True, ratio=1),
        Column("[white]\u03c4/24h", style="bold green", ratio=1),
        Column(
            "[white]NOMS",
            justify="center",
            style="rgb(42,161,152)",
            no_wrap=True,
            ratio=1,
        ),
        Column(
            "[white]OWNER STAKE(\u03c4)",
            justify="right",
            style="light_goldenrod2",
            no_wrap=True,
            ratio=1,
        ),
        Column(
            "[white]TOTAL STAKE(\u03c4)",
            justify="right",
            style="light_goldenrod2",
            no_wrap=True,
            ratio=1,
        ),
        Column("[white]SUBNETS", justify="right", style="white", ratio=1),
        Column("[white]VPERMIT", justify="right"),
        Column(
            "[white]24h/k\u03c4", style="rgb(42,161,152)", justify="center", ratio=1
        ),
        Column("[white]Desc", style="rgb(50,163,219)", ratio=3),
        title=f"[underline dark_orange]My Delegates[/underline dark_orange]\n[dark_orange]Network: {subtensor.network}\n",
        show_footer=True,
        show_edge=False,
        expand=False,
        box=box.SIMPLE_HEAVY,
        border_style="bright_black",
        leading=True,
    )

    total_delegated = 0

    # TODO: this doesnt work when passed to wallets_with_delegates
    # block_hash = await subtensor.substrate.get_chain_head()

    registered_delegate_info: dict[str, DelegatesDetails]
    wallets_with_delegates: tuple[
        tuple[Optional[Wallet], Optional[list[tuple[DelegateInfo, Balance]]]]
    ]

    print_verbose("Fetching delegate information")
    wallets_with_delegates, registered_delegate_info = await asyncio.gather(
        asyncio.gather(*[wallet_to_delegates(wallet_, None) for wallet_ in wallets]),
        subtensor.get_delegate_identities(),
    )
    if not registered_delegate_info:
        console.print(
            ":warning:[yellow]Could not get delegate info from chain.[/yellow]"
        )

    print_verbose("Processing delegate information")
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
                delegate_name = registered_delegate_info[
                    delegate[0].hotkey_ss58
                ].display
                delegate_url = registered_delegate_info[delegate[0].hotkey_ss58].web
                delegate_description = registered_delegate_info[
                    delegate[0].hotkey_ss58
                ].additional
            else:
                delegate_name = "~"
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
                    group_subnets(delegate[0].registrations),
                    group_subnets(delegate[0].validator_permits),
                    f"{delegate[0].total_daily_return.tao * (1000 / (0.001 + delegate[0].total_stake.tao))!s:6.6}",
                    str(delegate_description),
                )
    if console.width < 150:
        console.print(
            "[yellow]Warning: Your terminal width might be too small to view all the information clearly"
        )
    console.print(table)
    console.print(f"Total delegated TAO: {total_delegated}")


async def list_delegates(subtensor: SubtensorInterface):
    """List all delegates on the network."""

    with console.status(
        ":satellite: Loading delegates...", spinner="aesthetic"
    ) as status:
        print_verbose("Fetching delegate details from chain", status)
        block_hash = await subtensor.substrate.get_chain_head()
        registered_delegate_info, block_number, delegates = await asyncio.gather(
            subtensor.get_delegate_identities(block_hash=block_hash),
            subtensor.substrate.get_block_number(block_hash),
            subtensor.get_delegates(block_hash=block_hash),
        )

        print_verbose("Fetching previous delegates info from chain", status)

        async def get_prev_delegates(fallback_offsets=(1200, 200)):
            for offset in fallback_offsets:
                try:
                    prev_block_hash = await subtensor.substrate.get_block_hash(
                        max(0, block_number - offset)
                    )
                    return await subtensor.get_delegates(block_hash=prev_block_hash)
                except SubstrateRequestException:
                    continue
            return None

        prev_delegates = await get_prev_delegates()

    if prev_delegates is None:
        err_console.print(
            ":warning: [yellow]Could not fetch delegates history. [/yellow]"
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
            "[white]INDEX\n\n",
            str(len(delegates)),
            style="bold white",
        ),
        Column(
            "[white]DELEGATE\n\n",
            style="bold bright_cyan",
            justify="left",
            overflow="fold",
            ratio=1,
        ),
        Column(
            "[white]SS58\n\n",
            style="bright_magenta",
            no_wrap=False,
            overflow="fold",
            ratio=2,
        ),
        Column(
            "[white]NOMINATORS\n\n",
            justify="center",
            style="gold1",
            no_wrap=True,
            ratio=1,
        ),
        Column(
            "[white]OWN STAKE\n(\u03c4)\n",
            justify="right",
            style="orange1",
            no_wrap=True,
            ratio=1,
        ),
        Column(
            "[white]TOTAL STAKE\n(\u03c4)\n",
            justify="right",
            style="light_goldenrod2",
            no_wrap=True,
            ratio=1,
        ),
        Column("[white]CHANGE\n/(4h)\n", style="grey0", justify="center", ratio=1),
        Column("[white]TAKE\n\n", style="white", no_wrap=True, ratio=1),
        Column(
            "[white]NOMINATOR\n/(24h)/k\u03c4\n",
            style="dark_olive_green3",
            justify="center",
            ratio=1,
        ),
        Column(
            "[white]DELEGATE\n/(24h)\n",
            style="dark_olive_green3",
            justify="center",
            ratio=1,
        ),
        Column(
            "[white]VPERMIT\n\n",
            justify="center",
            no_wrap=False,
            max_width=20,
            style="dark_sea_green",
            ratio=2,
        ),
        Column("[white]Desc\n\n", style="rgb(50,163,219)", max_width=30, ratio=2),
        title=f"[underline dark_orange]Root Delegates[/underline dark_orange]\n[dark_orange]Network: {subtensor.network}\n",
        show_footer=True,
        pad_edge=False,
        box=None,
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
            delegate_name = registered_delegate_info[delegate.hotkey_ss58].display
            delegate_url = registered_delegate_info[delegate.hotkey_ss58].web
            delegate_description = registered_delegate_info[
                delegate.hotkey_ss58
            ].additional
        else:
            delegate_name = "~"
            delegate_url = ""
            delegate_description = ""

        if delegate.hotkey_ss58 in prev_delegates_dict:
            prev_stake = prev_delegates_dict[delegate.hotkey_ss58].total_stake
            if prev_stake == 0:
                if delegate.total_stake > 0:
                    rate_change_in_stake_str = "[green]100%[/green]"
                else:
                    rate_change_in_stake_str = "[grey0]0%[/grey0]"
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
            f"{delegate.hotkey_ss58}",
            # NOMINATORS
            str(len([nom for nom in delegate.nominators if nom[1].rao > 0])),
            # DELEGATE STAKE
            f"{owner_stake!s:13.13}",
            # TOTAL STAKE
            f"{delegate.total_stake!s:13.13}",
            # CHANGE/(4h)
            rate_change_in_stake_str,
            # TAKE
            f"{delegate.take * 100:.1f}%",
            # NOMINATOR/(24h)/k
            f"{Balance.from_tao(delegate.total_daily_return.tao * (1000 / (0.001 + delegate.total_stake.tao)))!s:6.6}",
            # DELEGATE/(24h)
            f"{Balance.from_tao(delegate.total_daily_return.tao * 0.18) !s:6.6}",
            # VPERMIT
            str(group_subnets(delegate.registrations)),
            # Desc
            str(delegate_description),
            end_section=True,
        )
    console.print(table)


async def nominate(wallet: Wallet, subtensor: SubtensorInterface, prompt: bool):
    """Nominate wallet."""

    console.print(f"Nominating on [dark_orange]network: {subtensor.network}")
    # Unlock the wallet.
    try:
        wallet.unlock_hotkey()
        wallet.unlock_coldkey()
    except KeyFileError:
        err_console.print("Error decrypting coldkey (possibly incorrect password)")
        return False

    print_verbose(f"Checking hotkey ({wallet.hotkey_str}) is a delegate")
    # Check if the hotkey is already a delegate.
    if await subtensor.is_hotkey_delegate(wallet.hotkey.ss58_address):
        err_console.print(
            f"Aborting: Hotkey {wallet.hotkey.ss58_address} is already a delegate."
        )
        return

    print_verbose("Nominating hotkey as a delegate")
    result: bool = await nominate_extrinsic(subtensor, wallet)
    if not result:
        err_console.print(
            f"Could not became a delegate on [white]{subtensor.network}[/white]"
        )
        return
    else:
        # Check if we are a delegate.
        print_verbose("Confirming delegate status")
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
            do_set_identity = Confirm.ask("Would you like to set your identity? [y/n]")

            if do_set_identity:
                id_prompts = set_id_prompts(validator=True)
                await set_id(wallet, subtensor, *id_prompts, prompt=prompt)
