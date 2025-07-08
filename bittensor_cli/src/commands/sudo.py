import asyncio
import json
from typing import TYPE_CHECKING, Union, Optional

from bittensor_wallet import Wallet
from rich import box
from rich.table import Column, Table
from rich.prompt import Confirm
from scalecodec import GenericCall

from bittensor_cli.src import (
    HYPERPARAMS,
    HYPERPARAMS_MODULE,
    DelegatesDetails,
    COLOR_PALETTE,
)
from bittensor_cli.src.bittensor.chain_data import decode_account_id
from bittensor_cli.src.bittensor.utils import (
    console,
    err_console,
    print_error,
    print_verbose,
    normalize_hyperparameters,
    unlock_key,
    blocks_to_duration,
    json_console,
    string_to_u16,
    string_to_u64,
)

if TYPE_CHECKING:
    from bittensor_cli.src.bittensor.subtensor_interface import (
        SubtensorInterface,
        ProposalVoteData,
    )


# helpers and extrinsics
DEFAULT_PALLET = "AdminUtils"


def allowed_value(
    param: str, value: Union[str, bool]
) -> tuple[bool, Union[str, list[float], float, bool]]:
    """
    Check the allowed values on hyperparameters. Return False if value is out of bounds.

    Reminder error message ends like:  Value is {value} but must be {error_message}. (the second part of return
    statement)

    Check if value is a boolean, only allow boolean and floats
    """
    try:
        if not isinstance(value, bool):
            if param == "alpha_values":
                # Split the string into individual values
                alpha_low_str, alpha_high_str = value.split(",")
                alpha_high = float(alpha_high_str)
                alpha_low = float(alpha_low_str)

                # Check alpha_high value
                if alpha_high <= 52428 or alpha_high >= 65535:
                    return (
                        False,
                        f"between 52428 and 65535 for alpha_high (but is {alpha_high})",
                    )

                # Check alpha_low value
                if alpha_low < 0 or alpha_low > 52428:
                    return (
                        False,
                        f"between 0 and 52428 for alpha_low (but is {alpha_low})",
                    )

                return True, [alpha_low, alpha_high]
    except ValueError:
        return False, "a number or a boolean"

    return True, value


def string_to_bool(val) -> bool:
    try:
        return {"true": True, "1": True, "0": False, "false": False}[val.lower()]
    except KeyError:
        return ValueError


def search_metadata(
    param_name: str,
    value: Union[str, bool, float, list[float]],
    netuid: int,
    metadata,
    pallet: str = DEFAULT_PALLET,
) -> tuple[bool, Optional[dict]]:
    """
    Searches the substrate metadata AdminUtils pallet for a given parameter name. Crafts a response dict to be used
        as call parameters for setting this hyperparameter.

    Args:
        param_name: the name of the hyperparameter
        value: the value to set the hyperparameter
        netuid: the specified netuid
        metadata: the subtensor.substrate.metadata
        pallet: the name of the module to use for the query. If not set, the default value is DEFAULT_PALLET

    Returns:
        (success, dict of call params)

    """

    def type_converter_with_retry(type_, val, arg_name):
        try:
            if val is None:
                val = input(
                    f"Enter a value for field '{arg_name}' with type '{arg_type_output[type_]}': "
                )
            return arg_types[type_](val)
        except ValueError:
            return type_converter_with_retry(type_, None, arg_name)

    arg_types = {"bool": string_to_bool, "u16": string_to_u16, "u64": string_to_u64}
    arg_type_output = {"bool": "bool", "u16": "float", "u64": "float"}

    call_crafter = {"netuid": netuid}

    pallet = metadata.get_metadata_pallet(pallet)
    for call in pallet.calls:
        if call.name == param_name:
            if "netuid" not in [x.name for x in call.args]:
                return False, None
            call_args = [arg for arg in call.args if arg.value["name"] != "netuid"]
            if len(call_args) == 1:
                arg = call_args[0].value
                call_crafter[arg["name"]] = type_converter_with_retry(
                    arg["typeName"], value, arg["name"]
                )
            else:
                for arg_ in call_args:
                    arg = arg_.value
                    call_crafter[arg["name"]] = type_converter_with_retry(
                        arg["typeName"], None, arg["name"]
                    )
            return True, call_crafter
    else:
        return False, None


def requires_bool(metadata, param_name, pallet: str = DEFAULT_PALLET) -> bool:
    """
    Determines whether a given hyperparam takes a single arg (besides netuid) that is of bool type.
    """
    pallet = metadata.get_metadata_pallet(pallet)
    for call in pallet.calls:
        if call.name == param_name:
            if "netuid" not in [x.name for x in call.args]:
                return False, None
            call_args = [arg for arg in call.args if arg.value["name"] != "netuid"]
            if len(call_args) != 1:
                return False
            else:
                arg = call_args[0].value
                if arg["typeName"] == "bool":
                    return True
                else:
                    return False
    raise ValueError(f"{param_name} not found in pallet.")


async def set_hyperparameter_extrinsic(
    subtensor: "SubtensorInterface",
    wallet: "Wallet",
    netuid: int,
    parameter: str,
    value: Optional[Union[str, float, list[float]]],
    wait_for_inclusion: bool = False,
    wait_for_finalization: bool = True,
    prompt: bool = True,
) -> bool:
    """Sets a hyperparameter for a specific subnetwork.

    :param subtensor: initialized SubtensorInterface object
    :param wallet: bittensor wallet object.
    :param netuid: Subnetwork `uid`.
    :param parameter: Hyperparameter name.
    :param value: New hyperparameter value.
    :param wait_for_inclusion: If set, waits for the extrinsic to enter a block before returning `True`, or returns
                               `False` if the extrinsic fails to enter the block within the timeout.
    :param wait_for_finalization: If set, waits for the extrinsic to be finalized on the chain before returning `True`,
                                  or returns `False` if the extrinsic fails to be finalized within the timeout.

    :return: success: `True` if extrinsic was finalized or included in the block. If we did not wait for
                      finalization/inclusion, the response is `True`.
    """
    print_verbose("Confirming subnet owner")
    subnet_owner = await subtensor.query(
        module="SubtensorModule",
        storage_function="SubnetOwner",
        params=[netuid],
    )
    if subnet_owner != wallet.coldkeypub.ss58_address:
        err_console.print(
            ":cross_mark: [red]This wallet doesn't own the specified subnet.[/red]"
        )
        return False

    if not unlock_key(wallet).success:
        return False

    arbitrary_extrinsic = False

    extrinsic, sudo_ = HYPERPARAMS.get(parameter, ("", False))
    call_params = {"netuid": netuid}
    if not extrinsic:
        arbitrary_extrinsic, call_params = search_metadata(
            parameter, value, netuid, subtensor.substrate.metadata
        )
        extrinsic = parameter
        if not arbitrary_extrinsic:
            err_console.print(
                ":cross_mark: [red]Invalid hyperparameter specified.[/red]"
            )
            return False
    if sudo_ and prompt:
        if not Confirm.ask(
            "This hyperparam is only settable by root sudo users. If you are not, this will fail. Please confirm"
        ):
            return False

    substrate = subtensor.substrate
    msg_value = value if not arbitrary_extrinsic else call_params
    pallet = HYPERPARAMS_MODULE.get(parameter) or DEFAULT_PALLET

    with console.status(
        f":satellite: Setting hyperparameter [{COLOR_PALETTE['GENERAL']['SUBHEADING']}]{parameter}"
        f"[/{COLOR_PALETTE['GENERAL']['SUBHEADING']}] to [{COLOR_PALETTE['GENERAL']['SUBHEADING']}]{msg_value}"
        f"[/{COLOR_PALETTE['GENERAL']['SUBHEADING']}] on subnet: [{COLOR_PALETTE['GENERAL']['SUBHEADING']}]"
        f"{netuid}[/{COLOR_PALETTE['GENERAL']['SUBHEADING']}] ...",
        spinner="earth",
    ):
        if not arbitrary_extrinsic:
            extrinsic_params = await substrate.get_metadata_call_function(
                module_name=pallet, call_function_name=extrinsic
            )

            # if input value is a list, iterate through the list and assign values
            if isinstance(value, list):
                # Ensure that there are enough values for all non-netuid parameters
                non_netuid_fields = [
                    pn_str
                    for param in extrinsic_params["fields"]
                    if "netuid" not in (pn_str := str(param["name"]))
                ]

                if len(value) < len(non_netuid_fields):
                    err_console.print(
                        "Not enough values provided in the list for all parameters"
                    )
                    return False

                call_params.update(
                    {name: val for name, val in zip(non_netuid_fields, value)}
                )

            else:
                if requires_bool(
                    substrate.metadata, param_name=extrinsic, pallet=pallet
                ) and isinstance(value, str):
                    value = string_to_bool(value)
                value_argument = extrinsic_params["fields"][
                    len(extrinsic_params["fields"]) - 1
                ]
                call_params[str(value_argument["name"])] = value

        # create extrinsic call
        call_ = await substrate.compose_call(
            call_module=pallet,
            call_function=extrinsic,
            call_params=call_params,
        )
        if sudo_:
            call = await substrate.compose_call(
                call_module="Sudo", call_function="sudo", call_params={"call": call_}
            )
        else:
            call = call_
        success, err_msg = await subtensor.sign_and_send_extrinsic(
            call, wallet, wait_for_inclusion, wait_for_finalization
        )
        if not success:
            err_console.print(f":cross_mark: [red]Failed[/red]: {err_msg}")
            return False
        elif arbitrary_extrinsic:
            console.print(
                f":white_heavy_check_mark: "
                f"[dark_sea_green3]Hyperparameter {parameter} values changed to {call_params}[/dark_sea_green3]"
            )
            return True
        # Successful registration, final check for membership
        else:
            console.print(
                f":white_heavy_check_mark: "
                f"[dark_sea_green3]Hyperparameter {parameter} changed to {value}[/dark_sea_green3]"
            )
            return True


async def _get_senate_members(
    subtensor: "SubtensorInterface", block_hash: Optional[str] = None
) -> list[str]:
    """
    Gets all members of the senate on the given subtensor's network

    :param subtensor: SubtensorInterface object to use for the query

    :return: list of the senate members' ss58 addresses
    """
    senate_members = await subtensor.query(
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
    subtensor: "SubtensorInterface", block_hash: str
) -> dict[str, tuple[dict, "ProposalVoteData"]]:
    async def get_proposal_call_data(p_hash: str) -> Optional[GenericCall]:
        proposal_data = await subtensor.query(
            module="Triumvirate",
            storage_function="ProposalOf",
            block_hash=block_hash,
            params=[p_hash],
        )
        return proposal_data

    ph = await subtensor.query(
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


def serialize_vote_data(
    vote_data: "ProposalVoteData", delegate_info: dict[str, DelegatesDetails]
) -> list[dict[str, bool]]:
    vote_list = {}
    for address in vote_data.ayes:
        f_add = delegate_info[address].display if address in delegate_info else address
        vote_list[f_add] = True
    for address in vote_data.nays:
        f_add = delegate_info[address].display if address in delegate_info else address
        vote_list[f_add] = False
    return vote_list


def format_call_data(call_data: dict) -> str:
    # Extract the module and call details
    module, call_details = next(iter(call_data.items()))

    # Extract the call function name and arguments
    call_info = call_details[0]
    call_function, call_args = next(iter(call_info.items()))

    # Format arguments, handle nested/large payloads
    formatted_args = []
    for arg_name, arg_value in call_args.items():
        if isinstance(arg_value, (tuple, list, dict)):
            # For large nested, show abbreviated version
            content_str = str(arg_value)
            if len(content_str) > 20:
                formatted_args.append(f"{arg_name}: ... [{len(content_str)}] ...")
            else:
                formatted_args.append(f"{arg_name}: {arg_value}")
        else:
            formatted_args.append(f"{arg_name}: {arg_value}")

    # Format the final output string
    args_str = ", ".join(formatted_args)
    return f"{module}.{call_function}({args_str})"


def _validate_proposal_hash(proposal_hash: str) -> bool:
    if proposal_hash[0:2] != "0x" or len(proposal_hash) != 66:
        return False
    else:
        return True


async def _is_senate_member(subtensor: "SubtensorInterface", hotkey_ss58: str) -> bool:
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
    subtensor: "SubtensorInterface",
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


async def set_take_extrinsic(
    subtensor: "SubtensorInterface",
    wallet: Wallet,
    delegate_ss58: str,
    take: float = 0.0,
) -> bool:
    """
    Set delegate hotkey take

    :param subtensor: SubtensorInterface (initialized)
    :param wallet: The wallet containing the hotkey to be nominated.
    :param delegate_ss58:  Hotkey
    :param take: Delegate take on subnet ID

    :return: `True` if the process is successful, `False` otherwise.

    This function is a key part of the decentralized governance mechanism of Bittensor, allowing for the
    dynamic selection and participation of validators in the network's consensus process.
    """

    # Calculate u16 representation of the take
    take_u16 = int(take * 0xFFFF)

    print_verbose("Checking current take")
    # Check if the new take is greater or lower than existing take or if existing is set
    current_take = await get_current_take(subtensor, wallet)
    current_take_u16 = int(float(current_take) * 0xFFFF)

    if take_u16 == current_take_u16:
        console.print("Nothing to do, take hasn't changed")
        return True

    if current_take_u16 < take_u16:
        console.print(
            f"Current take is [{COLOR_PALETTE.P.RATE}]{current_take * 100.0:.2f}%[/{COLOR_PALETTE.P.RATE}]. "
            f"Increasing to [{COLOR_PALETTE.P.RATE}]{take * 100:.2f}%."
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
            f"Current take is [{COLOR_PALETTE.P.RATE}]{current_take * 100.0:.2f}%[/{COLOR_PALETTE.P.RATE}]. "
            f"Decreasing to [{COLOR_PALETTE.P.RATE}]{take * 100:.2f}%."
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
        console.print(
            ":white_heavy_check_mark: [dark_sea_green_3]Finalized[/dark_sea_green_3]"
        )
    return success


# commands


async def sudo_set_hyperparameter(
    wallet: Wallet,
    subtensor: "SubtensorInterface",
    netuid: int,
    param_name: str,
    param_value: Optional[str],
    prompt: bool,
    json_output: bool,
):
    """Set subnet hyperparameters."""
    is_allowed_value, value = allowed_value(param_name, param_value)
    if not is_allowed_value:
        err_console.print(
            f"Hyperparameter [dark_orange]{param_name}[/dark_orange] value is not within bounds. "
            f"Value is {param_value} but must be {value}"
        )
        return False
    success = await set_hyperparameter_extrinsic(
        subtensor, wallet, netuid, param_name, value, prompt=prompt
    )
    if json_output:
        return success
    if success:
        console.print("\n")
        print_verbose("Fetching hyperparameters")
        await get_hyperparameters(subtensor, netuid=netuid)
    return success


async def get_hyperparameters(
    subtensor: "SubtensorInterface", netuid: int, json_output: bool = False
) -> bool:
    """View hyperparameters of a subnetwork."""
    print_verbose("Fetching hyperparameters")
    if not await subtensor.subnet_exists(netuid):
        print_error(f"Subnet with netuid {netuid} does not exist.")
        return False
    subnet, subnet_info = await asyncio.gather(
        subtensor.get_subnet_hyperparameters(netuid), subtensor.subnet(netuid)
    )
    if subnet_info is None:
        print_error(f"Subnet with netuid {netuid} does not exist.")
        return False

    table = Table(
        Column("[white]HYPERPARAMETER", style=COLOR_PALETTE.SU.HYPERPARAMETER),
        Column("[white]VALUE", style=COLOR_PALETTE.SU.VALUE),
        Column("[white]NORMALIZED", style=COLOR_PALETTE.SU.NORMAL),
        title=f"[{COLOR_PALETTE.G.HEADER}]\nSubnet Hyperparameters\n NETUID: "
        f"[{COLOR_PALETTE.G.SUBHEAD}]{netuid}"
        f"{f' ({subnet_info.subnet_name})' if subnet_info.subnet_name is not None else ''}"
        f"[/{COLOR_PALETTE.G.SUBHEAD}]"
        f" - Network: [{COLOR_PALETTE.G.SUBHEAD}]{subtensor.network}[/{COLOR_PALETTE.G.SUBHEAD}]\n",
        show_footer=True,
        width=None,
        pad_edge=False,
        box=box.SIMPLE,
        show_edge=True,
    )
    dict_out = []

    normalized_values = normalize_hyperparameters(subnet, json_output=json_output)
    for param, value, norm_value in normalized_values:
        if not json_output:
            table.add_row("  " + param, value, norm_value)
        else:
            dict_out.append(
                {
                    "hyperparameter": param,
                    "value": value,
                    "normalized_value": norm_value,
                }
            )
    if json_output:
        json_console.print(json.dumps(dict_out))
    else:
        console.print(table)
    return True


async def get_senate(
    subtensor: "SubtensorInterface", json_output: bool = False
) -> None:
    """View Bittensor's senate members"""
    with console.status(
        f":satellite: Syncing with chain: [white]{subtensor}[/white] ...",
        spinner="aesthetic",
    ) as status:
        print_verbose("Fetching senate members", status)
        senate_members = await _get_senate_members(subtensor)

    print_verbose("Fetching member details from Github and on-chain identities")
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
    dict_output = []

    for ss58_address in senate_members:
        member_name = (
            delegate_info[ss58_address].display
            if ss58_address in delegate_info
            else "~"
        )
        table.add_row(
            member_name,
            ss58_address,
        )
        dict_output.append({"name": member_name, "ss58_address": ss58_address})
    if json_output:
        json_console.print(json.dumps(dict_output))
    return console.print(table)


async def proposals(
    subtensor: "SubtensorInterface", verbose: bool, json_output: bool = False
) -> None:
    console.print(
        ":satellite: Syncing with chain: [white]{}[/white] ...".format(
            subtensor.network
        )
    )
    block_hash = await subtensor.substrate.get_chain_head()
    senate_members, all_proposals, current_block = await asyncio.gather(
        _get_senate_members(subtensor, block_hash),
        _get_proposals(subtensor, block_hash),
        subtensor.substrate.get_block_number(block_hash),
    )

    registered_delegate_info: dict[
        str, DelegatesDetails
    ] = await subtensor.get_delegate_identities()

    title = (
        f"[bold #4196D6]Bittensor Governance Proposals[/bold #4196D6]\n"
        f"[steel_blue3]Current Block:[/steel_blue3] {current_block}\t"
        f"[steel_blue3]Network:[/steel_blue3] {subtensor.network}\n\n"
        f"[steel_blue3]Active Proposals:[/steel_blue3] {len(all_proposals)}\t"
        f"[steel_blue3]Senate Size:[/steel_blue3] {len(senate_members)}\n"
    )
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
        Column("[white]CALLDATA", style="dark_sea_green", width=30),
        title=title,
        show_footer=True,
        box=box.SIMPLE_HEAVY,
        pad_edge=False,
        width=None,
        border_style="bright_black",
    )
    dict_output = []
    for hash_, (call_data, vote_data) in all_proposals.items():
        blocks_remaining = vote_data.end - current_block
        if blocks_remaining > 0:
            duration_str = blocks_to_duration(blocks_remaining)
            vote_end_cell = f"{vote_data.end} [dim](in {duration_str})[/dim]"
        else:
            vote_end_cell = f"{vote_data.end} [red](expired)[/red]"

        ayes_threshold = (
            (len(vote_data.ayes) / vote_data.threshold * 100)
            if vote_data.threshold > 0
            else 0
        )
        nays_threshold = (
            (len(vote_data.nays) / vote_data.threshold * 100)
            if vote_data.threshold > 0
            else 0
        )
        f_call_data = format_call_data(call_data)
        table.add_row(
            hash_ if verbose else f"{hash_[:4]}...{hash_[-4:]}",
            str(vote_data.threshold),
            f"{len(vote_data.ayes)} ({ayes_threshold:.2f}%)",
            f"{len(vote_data.nays)} ({nays_threshold:.2f}%)",
            display_votes(vote_data, registered_delegate_info),
            vote_end_cell,
            f_call_data,
        )
        dict_output.append(
            {
                "hash": hash_,
                "threshold": vote_data.threshold,
                "ayes": len(vote_data.ayes),
                "nays": len(vote_data.nays),
                "votes": serialize_vote_data(vote_data, registered_delegate_info),
                "end": vote_data.end,
                "call_data": f_call_data,
            }
        )
    if json_output:
        json_console.print(json.dumps(dict_output))
    console.print(table)
    console.print(
        "\n[dim]* Both Ayes and Nays percentages are calculated relative to the proposal's threshold.[/dim]"
    )


async def senate_vote(
    wallet: Wallet,
    subtensor: "SubtensorInterface",
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
    if not unlock_key(wallet, "hot").success and unlock_key(wallet, "cold").success:
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


async def get_current_take(subtensor: "SubtensorInterface", wallet: Wallet):
    current_take = await subtensor.current_take(wallet.hotkey.ss58_address)
    return current_take


async def display_current_take(subtensor: "SubtensorInterface", wallet: Wallet) -> None:
    current_take = await get_current_take(subtensor, wallet)
    console.print(
        f"Current take is [{COLOR_PALETTE.P.RATE}]{current_take * 100.0:.2f}%"
    )


async def set_take(
    wallet: Wallet, subtensor: "SubtensorInterface", take: float
) -> bool:
    """Set delegate take."""

    async def _do_set_take() -> bool:
        if take > 0.18 or take < 0:
            err_console.print("ERROR: Take value should not exceed 18% or be below 0%")
            return False

        block_hash = await subtensor.substrate.get_chain_head()
        netuids_registered = await subtensor.get_netuids_for_hotkey(
            wallet.hotkey.ss58_address, block_hash=block_hash
        )
        if not len(netuids_registered) > 0:
            err_console.print(
                f"Hotkey [{COLOR_PALETTE.G.HK}]{wallet.hotkey.ss58_address}[/{COLOR_PALETTE.G.HK}] is not registered to"
                f" any subnet. Please register using [{COLOR_PALETTE.G.SUBHEAD}]`btcli subnets register`"
                f"[{COLOR_PALETTE.G.SUBHEAD}] and try again."
            )
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
            new_take = await get_current_take(subtensor, wallet)
            console.print(
                f"New take is [{COLOR_PALETTE.P.RATE}]{new_take * 100.0:.2f}%"
            )
            return True

    console.print(
        f"Setting take on [{COLOR_PALETTE.G.LINKS}]network: {subtensor.network}"
    )

    if not unlock_key(wallet, "hot").success and unlock_key(wallet, "cold").success:
        return False

    result_ = await _do_set_take()

    return result_
