from typing import TYPE_CHECKING

from bittensor_wallet import Wallet
import numpy as np
from rich.prompt import Confirm

from src.utils import err_console, console, format_error_message
from src.bittensor.extrinsics.root import convert_weights_and_uids_for_emit

if TYPE_CHECKING:
    from src.subtensor_interface import SubtensorInterface


# helpers and extrinsics


async def reveal_weights_extrinsic(
    subtensor: "SubtensorInterface",
    wallet: Wallet,
    netuid: int,
    uids: list[int],
    weights: list[int],
    salt: list[int],
    version_key: int,
    wait_for_inclusion: bool = False,
    wait_for_finalization: bool = False,
    prompt: bool = False,
) -> tuple[bool, str]:
    """
    Reveals the weights for a specific subnet on the Bittensor blockchain using the provided wallet.
    This function is a wrapper around the `_do_reveal_weights` method, handling user prompts and error messages.

    :param subtensor: The subtensor instance used for blockchain interaction.
    :param wallet: The wallet associated with the neuron revealing the weights.
    :param netuid: identifier of the subnet.
    :param uids: List of neuron UIDs for which weights are being revealed.
    :param weights: List of weight values corresponding to each UID.
    :param salt: List of salt values corresponding to the hash function.
    :param version_key: for compatibility with the network.
    :param wait_for_inclusion: Waits for the transaction to be included in a block.
    :param wait_for_finalization: Waits for the transaction to be finalized on the blockchain.
    :param prompt: If `True`, prompts for user confirmation before proceeding.

    :return: `True` if the weight revelation is successful, `False` otherwise. And `msg`, a string value describing the
             success or potential error.

    This function provides a user-friendly interface for revealing weights on the Bittensor blockchain, ensuring proper
    error handling and user interaction when required.
    """
    if prompt and not Confirm.ask("Would you like to reveal weights?"):
        return False, "User cancelled the operation."

    call = await subtensor.substrate.compose_call(
        call_module="SubtensorModule",
        call_function="reveal_weights",
        call_params={
            "netuid": netuid,
            "uids": uids,
            "values": weights,
            "salt": salt,
            "version_key": version_key,
        },
    )
    extrinsic = await subtensor.substrate.create_signed_extrinsic(
        call=call,
        keypair=wallet.hotkey,
    )
    response = await subtensor.substrate.submit_extrinsic(
        extrinsic,
        wait_for_inclusion=wait_for_inclusion,
        wait_for_finalization=wait_for_finalization,
    )

    if not wait_for_finalization and not wait_for_inclusion:
        success, error_message = True, ""

    else:
        response.process_events()
        if response.is_success:
            success, error_message = True, ""
        else:
            success, error_message = False, format_error_message(response.error_message)

    if success:
        # bittensor.logging.info("Successfully revealed weights.")
        return True, "Successfully revealed weights."
    else:
        # bittensor.logging.error(f"Failed to reveal weights: {error_message}")
        return False, error_message


# commands


async def reveal_weights(
    subtensor: "SubtensorInterface",
    wallet: Wallet,
    netuid: int,
    uids: list[int],
    weights: list[float],
    salt: list[int],
    version: int,
) -> None:
    """Reveal weights for a specific subnet."""

    uids_ = np.array(
        uids,
        dtype=np.int64,
    )
    weights_ = np.array(
        weights,
        dtype=np.float32,
    )
    salt_ = np.array(
        salt,
        dtype=np.int64,
    )
    weight_uids, weight_vals = convert_weights_and_uids_for_emit(
        uids=uids_, weights=weights_
    )

    # Run the reveal weights operation.
    success, message = await reveal_weights_extrinsic(
        subtensor,
        wallet=wallet,
        netuid=netuid,
        uids=weight_uids,
        weights=weight_vals,
        salt=list(salt_),
        version_key=version,
        prompt=True,  # TODO no-prompt
    )

    if success:
        console.print("Weights revealed successfully")
    else:
        err_console.print(f"Failed to reveal weights: {message}")
