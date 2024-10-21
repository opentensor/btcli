import asyncio
from typing import TYPE_CHECKING, Union, Optional

from bittensor_wallet import Wallet
from bittensor_wallet.errors import KeyFileError
from rich import box
from rich.table import Column, Table
from scalecodec import GenericCall

from bittensor_cli.src import HYPERPARAMS, DelegatesDetails
from bittensor_cli.src.bittensor.chain_data import decode_account_id
from bittensor_cli.src.bittensor.utils import (
    console,
    err_console,
    print_error,
    print_verbose,
    normalize_hyperparameters,
)

if TYPE_CHECKING:
    from bittensor_cli.src.bittensor.subtensor_interface import (
        SubtensorInterface,
        ProposalVoteData,
    )


# helpers and extrinsics


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


async def set_hyperparameter_extrinsic(
    subtensor: "SubtensorInterface",
    wallet: "Wallet",
    netuid: int,
    parameter: str,
    value: Union[str, bool, float, list[float]],
    wait_for_inclusion: bool = False,
    wait_for_finalization: bool = True,
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
    :param prompt: If `True`, the call waits for confirmation from the user before proceeding.

    :return: success: `True` if extrinsic was finalized or included in the block. If we did not wait for
                      finalization/inclusion, the response is `True`.
    """
    print_verbose("Confirming subnet owner")
    subnet_owner_ = await subtensor.substrate.query(
        module="SubtensorModule",
        storage_function="SubnetOwner",
        params=[netuid],
    )
    subnet_owner = decode_account_id(subnet_owner_[0])
    if subnet_owner != wallet.coldkeypub.ss58_address:
        err_console.print(
            ":cross_mark: [red]This wallet doesn't own the specified subnet.[/red]"
        )
        return False

    try:
        wallet.unlock_coldkey()
    except KeyFileError:
        err_console.print("Error decrypting coldkey (possibly incorrect password)")
        return False

    extrinsic = HYPERPARAMS.get(parameter)
    if extrinsic is None:
        err_console.print(":cross_mark: [red]Invalid hyperparameter specified.[/red]")
        return False

    with console.status(
        f":satellite: Setting hyperparameter {parameter} to {value} on subnet: {netuid} ...",
        spinner="earth",
    ):
        substrate = subtensor.substrate
        extrinsic_params = await substrate.get_metadata_call_function(
            "AdminUtils", extrinsic
        )
        call_params: dict[str, Union[str, bool, float]] = {"netuid": netuid}

        # if input value is a list, iterate through the list and assign values
        if isinstance(value, list):
            # Ensure that there are enough values for all non-netuid parameters
            non_netuid_fields = [
                param["name"]
                for param in extrinsic_params["fields"]
                if "netuid" not in param["name"]
            ]

            if len(value) < len(non_netuid_fields):
                raise ValueError(
                    "Not enough values provided in the list for all parameters"
                )

            call_params.update(
                {str(name): val for name, val in zip(non_netuid_fields, value)}
            )

        else:
            value_argument = extrinsic_params["fields"][
                len(extrinsic_params["fields"]) - 1
            ]
            call_params[str(value_argument["name"])] = value

        # create extrinsic call
        call = await substrate.compose_call(
            call_module="AdminUtils",
            call_function=extrinsic,
            call_params=call_params,
        )
        success, err_msg = await subtensor.sign_and_send_extrinsic(
            call, wallet, wait_for_inclusion, wait_for_finalization
        )
        if not success:
            err_console.print(f":cross_mark: [red]Failed[/red]: {err_msg}")
            await asyncio.sleep(0.5)

        # Successful registration, final check for membership
        else:
            console.print(
                f":white_heavy_check_mark: [green]Hyperparameter {parameter} changed to {value}[/green]"
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
    subtensor: "SubtensorInterface", block_hash: str
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


# commands


async def sudo_set_hyperparameter(
    wallet: Wallet,
    subtensor: "SubtensorInterface",
    netuid: int,
    param_name: str,
    param_value: str,
):
    """Set subnet hyperparameters."""

    normalized_value: Union[str, bool]
    if param_name in [
        "network_registration_allowed",
        "network_pow_registration_allowed",
        "commit_reveal_weights_enabled",
        "liquid_alpha_enabled",
    ]:
        normalized_value = param_value.lower() in ["true", "1"]
    else:
        normalized_value = param_value

    is_allowed_value, value = allowed_value(param_name, normalized_value)
    if not is_allowed_value:
        err_console.print(
            f"Hyperparameter {param_name} value is not within bounds. Value is {normalized_value} but must be {value}"
        )
        return

    success = await set_hyperparameter_extrinsic(
        subtensor, wallet, netuid, param_name, value
    )
    if success:
        console.print("\n")
        print_verbose("Fetching hyperparameters")
        await get_hyperparameters(subtensor, netuid=netuid)


async def get_hyperparameters(subtensor: "SubtensorInterface", netuid: int):
    """View hyperparameters of a subnetwork."""
    print_verbose("Fetching hyperparameters")
    if not await subtensor.subnet_exists(netuid):
        print_error(f"Subnet with netuid {netuid} does not exist.")
        return False
    subnet = await subtensor.get_subnet_hyperparameters(netuid)

    table = Table(
        Column("[white]HYPERPARAMETER", style="bright_magenta"),
        Column("[white]VALUE", style="light_goldenrod2"),
        Column("[white]NORMALIZED", style="light_goldenrod3"),
        title=f"[underline dark_orange]\nSubnet Hyperparameters[/underline dark_orange]\n NETUID: [dark_orange]"
        f"{netuid}[/dark_orange] - Network: [dark_orange]{subtensor.network}[/dark_orange]\n",
        show_footer=True,
        width=None,
        pad_edge=False,
        box=box.SIMPLE,
        show_edge=True,
    )

    normalized_values = normalize_hyperparameters(subnet)

    for param, value, norm_value in normalized_values:
        table.add_row("  " + param, value, norm_value)

    console.print(table)
    return True


async def get_senate(subtensor: "SubtensorInterface"):
    """View Bittensor's senate memebers"""
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


async def proposals(subtensor: "SubtensorInterface"):
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
