import asyncio
from typing import TYPE_CHECKING, Union

from bittensor_wallet import Wallet
from bittensor_wallet.errors import KeyFileError
from rich import box
from rich.table import Column, Table

from bittensor_cli.src import HYPERPARAMS
from bittensor_cli.src.bittensor.chain_data import decode_account_id
from bittensor_cli.src.bittensor.utils import (
    console,
    err_console,
    print_error,
    print_verbose,
    normalize_hyperparameters,
)

if TYPE_CHECKING:
    from bittensor_cli.src.bittensor.subtensor_interface import SubtensorInterface


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
