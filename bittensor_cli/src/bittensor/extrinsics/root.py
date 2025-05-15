# The MIT License (MIT)
# Copyright © 2021 Yuma Rao
# Copyright © 2023 Opentensor Foundation
# Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
# documentation files (the “Software”), to deal in the Software without restriction, including without limitation
# the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software,
# and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all copies or substantial portions of
# the Software.

# THE SOFTWARE IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO
# THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
# THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
# OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
# DEALINGS IN THE SOFTWARE.

import asyncio
import hashlib
import time
from typing import Union, List, TYPE_CHECKING

from bittensor_wallet import Wallet, Keypair
import numpy as np
from numpy.typing import NDArray
from rich.prompt import Confirm
from rich.table import Table, Column
from scalecodec import ScaleBytes, U16, Vec
from async_substrate_interface.errors import SubstrateRequestException

from bittensor_cli.src.bittensor.subtensor_interface import SubtensorInterface
from bittensor_cli.src.bittensor.extrinsics.registration import is_hotkey_registered
from bittensor_cli.src.bittensor.utils import (
    console,
    err_console,
    u16_normalized_float,
    print_verbose,
    format_error_message,
    unlock_key,
)

if TYPE_CHECKING:
    from bittensor_cli.src.bittensor.minigraph import MiniGraph

U32_MAX = 4294967295
U16_MAX = 65535


async def get_limits(subtensor: SubtensorInterface) -> tuple[int, float]:
    # Get weight restrictions.
    maw, mwl = await asyncio.gather(
        subtensor.get_hyperparameter("MinAllowedWeights", netuid=0),
        subtensor.get_hyperparameter("MaxWeightsLimit", netuid=0),
    )
    min_allowed_weights = int(maw)
    max_weight_limit = u16_normalized_float(int(mwl))
    return min_allowed_weights, max_weight_limit


def normalize_max_weight(
    x: NDArray[np.float32], limit: float = 0.1
) -> NDArray[np.float32]:
    """
    Normalizes the tensor x so that sum(x) = 1 and the max value is not greater than the limit.

    :param x: Tensor to be max_value normalized.
    :param limit: Max value after normalization.

    :return: Normalized x tensor.
    """
    epsilon = 1e-7  # For numerical stability after normalization

    weights = x.copy()
    values = np.sort(weights)

    if x.sum() == 0 or x.shape[0] * limit <= 1:
        return np.ones_like(x) / x.shape[0]
    else:
        estimation = values / values.sum()

        if estimation.max() <= limit:
            return weights / weights.sum()

        # Find the cumulative sum and sorted tensor
        cumsum = np.cumsum(estimation, 0)

        # Determine the index of cutoff
        estimation_sum = np.array(
            [(len(values) - i - 1) * estimation[i] for i in range(len(values))]
        )
        n_values = (estimation / (estimation_sum + cumsum + epsilon) < limit).sum()

        # Determine the cutoff based on the index
        cutoff_scale = (limit * cumsum[n_values - 1] - epsilon) / (
            1 - (limit * (len(estimation) - n_values))
        )
        cutoff = cutoff_scale * values.sum()

        # Applying the cutoff
        weights[weights > cutoff] = cutoff

        y = weights / weights.sum()

        return y


def convert_weights_and_uids_for_emit(
    uids: NDArray[np.int64],
    weights: NDArray[np.float32],
) -> tuple[List[int], List[int]]:
    """Converts weights into integer u32 representation that sum to MAX_INT_WEIGHT.

    :param uids: Tensor of uids as destinations for passed weights.
    :param weights: Tensor of weights.

    :return: (weight_uids, weight_vals)
    """
    # Checks.
    weights = weights.tolist()
    uids = uids.tolist()
    if min(weights) < 0:
        raise ValueError(
            "Passed weight is negative cannot exist on chain {}".format(weights)
        )
    if min(uids) < 0:
        raise ValueError("Passed uid is negative cannot exist on chain {}".format(uids))
    if len(uids) != len(weights):
        raise ValueError(
            "Passed weights and uids must have the same length, got {} and {}".format(
                len(uids), len(weights)
            )
        )
    if sum(weights) == 0:
        return [], []  # Nothing to set on chain.
    else:
        max_weight = float(max(weights))
        weights = [
            float(value) / max_weight for value in weights
        ]  # max-upscale values (max_weight = 1).

    weight_vals = []
    weight_uids = []
    for i, (weight_i, uid_i) in enumerate(list(zip(weights, uids))):
        uint16_val = round(
            float(weight_i) * int(U16_MAX)
        )  # convert to int representation.

        # Filter zeros
        if uint16_val != 0:  # Filter zeros
            weight_vals.append(uint16_val)
            weight_uids.append(uid_i)

    return weight_uids, weight_vals


async def process_weights_for_netuid(
    uids: NDArray[np.int64],
    weights: NDArray[np.float32],
    netuid: int,
    subtensor: SubtensorInterface,
    metagraph: "MiniGraph" = None,
    exclude_quantile: int = 0,
) -> tuple[NDArray[np.int64], NDArray[np.float32]]:
    # bittensor.logging.debug("process_weights_for_netuid()")
    # bittensor.logging.debug("weights", weights)
    # bittensor.logging.debug("netuid", netuid)
    # bittensor.logging.debug("subtensor", subtensor)
    # bittensor.logging.debug("metagraph", metagraph)

    # Get latest metagraph from chain if metagraph is None.
    if metagraph is None:
        metagraph = subtensor.metagraph(netuid)

    if not isinstance(weights, np.float32):
        weights = weights.astype(np.float32)

    # Network configuration parameters from a subtensor.
    # These parameters determine the range of acceptable weights for each neuron.
    quantile = exclude_quantile / U16_MAX
    min_allowed_weights, max_weight_limit = await get_limits(subtensor)
    # bittensor.logging.debug("quantile", quantile)
    # bittensor.logging.debug("min_allowed_weights", min_allowed_weights)
    # bittensor.logging.debug("max_weight_limit", max_weight_limit)

    # Find all non zero weights.
    non_zero_weight_idx = np.argwhere(weights > 0).squeeze(axis=1)
    non_zero_weight_uids = uids[non_zero_weight_idx]
    non_zero_weights = weights[non_zero_weight_idx]
    nzw_size = non_zero_weights.size
    if nzw_size == 0 or metagraph.n < min_allowed_weights:
        # bittensor.logging.warning("No non-zero weights returning all ones.")
        final_weights = np.ones(metagraph.n, dtype=np.int64) / metagraph.n
        # bittensor.logging.debug("final_weights", final_weights)
        final_weights_count = np.arange(len(final_weights))
        return final_weights_count, final_weights

    elif nzw_size < min_allowed_weights:
        # bittensor.logging.warning(
        #     "No non-zero weights less than min allowed weight, returning all ones."
        # )
        weights = (
            np.ones(metagraph.n, dtype=np.int64) * 1e-5
        )  # creating minimum even non-zero weights
        weights[non_zero_weight_idx] += non_zero_weights
        # bittensor.logging.debug("final_weights", weights)
        normalized_weights = normalize_max_weight(x=weights, limit=max_weight_limit)
        nw_arange = np.arange(len(normalized_weights))
        return nw_arange, normalized_weights

    # bittensor.logging.debug("non_zero_weights", non_zero_weights)

    # Compute the exclude quantile and find the weights in the lowest quantile
    max_exclude = max(0, len(non_zero_weights) - min_allowed_weights) / len(
        non_zero_weights
    )
    exclude_quantile = min([quantile, max_exclude])
    lowest_quantile = np.quantile(non_zero_weights, exclude_quantile)
    # bittensor.logging.debug("max_exclude", max_exclude)
    # bittensor.logging.debug("exclude_quantile", exclude_quantile)
    # bittensor.logging.debug("lowest_quantile", lowest_quantile)

    # Exclude all weights below the allowed quantile.
    non_zero_weight_uids = non_zero_weight_uids[lowest_quantile <= non_zero_weights]
    non_zero_weights = non_zero_weights[lowest_quantile <= non_zero_weights]
    # bittensor.logging.debug("non_zero_weight_uids", non_zero_weight_uids)
    # bittensor.logging.debug("non_zero_weights", non_zero_weights)

    # Normalize weights and return.
    normalized_weights = normalize_max_weight(
        x=non_zero_weights, limit=max_weight_limit
    )
    # bittensor.logging.debug("final_weights", normalized_weights)

    return non_zero_weight_uids, normalized_weights


def generate_weight_hash(
    address: str,
    netuid: int,
    uids: List[int],
    values: List[int],
    version_key: int,
    salt: List[int],
) -> str:
    """
    Generate a valid commit hash from the provided weights.

    :param address: The account identifier. Wallet ss58_address.
    :param netuid: The network unique identifier.
    :param uids: The list of UIDs.
    :param salt: The salt to add to hash.
    :param values: The list of weight values.
    :param version_key: The version key.

    :return The generated commit hash.
    """
    # Encode data using SCALE codec
    wallet_address = ScaleBytes(Keypair(ss58_address=address).public_key)
    netuid = ScaleBytes(netuid.to_bytes(2, "little"))

    vec_uids = Vec(data=None, sub_type="U16")
    vec_uids.value = [U16(ScaleBytes(uid.to_bytes(2, "little"))) for uid in uids]
    uids = ScaleBytes(vec_uids.encode().data)

    vec_values = Vec(data=None, sub_type="U16")
    vec_values.value = [
        U16(ScaleBytes(value.to_bytes(2, "little"))) for value in values
    ]
    values = ScaleBytes(vec_values.encode().data)

    version_key = ScaleBytes(version_key.to_bytes(8, "little"))

    vec_salt = Vec(data=None, sub_type="U16")
    vec_salt.value = [U16(ScaleBytes(salts.to_bytes(2, "little"))) for salts in salt]
    salt = ScaleBytes(vec_salt.encode().data)

    data = wallet_address + netuid + uids + values + salt + version_key

    # Generate Blake2b hash of the data tuple
    blake2b_hash = hashlib.blake2b(data.data, digest_size=32)

    # Convert the hash to hex string and add "0x" prefix
    commit_hash = "0x" + blake2b_hash.hexdigest()

    return commit_hash


async def root_register_extrinsic(
    subtensor: SubtensorInterface,
    wallet: Wallet,
    wait_for_inclusion: bool = True,
    wait_for_finalization: bool = True,
) -> tuple[bool, str]:
    r"""Registers the wallet to root network.

    :param subtensor: The SubtensorInterface object
    :param wallet: Bittensor wallet object.
    :param wait_for_inclusion: If set, waits for the extrinsic to enter a block before returning `True`, or returns
                               `False` if the extrinsic fails to enter the block within the timeout.
    :param wait_for_finalization: If set, waits for the extrinsic to be finalized on the chain before returning `True`,
                                  or returns `False` if the extrinsic fails to be finalized within the timeout.
    :param prompt: If `True`, the call waits for confirmation from the user before proceeding.

    :return: (success, msg), with success being `True` if extrinsic was finalized or included in the block. If we did
        not wait for finalization/inclusion, the response is `True`.
    """

    if not (unlock := unlock_key(wallet)).success:
        return False, unlock.message

    print_verbose(f"Checking if hotkey ({wallet.hotkey_str}) is registered on root")
    is_registered = await is_hotkey_registered(
        subtensor, netuid=0, hotkey_ss58=wallet.hotkey.ss58_address
    )
    if is_registered:
        console.print(
            ":white_heavy_check_mark: [green]Already registered on root network.[/green]"
        )
        return True, "Already registered on root network"

    with console.status(":satellite: Registering to root network...", spinner="earth"):
        call = await subtensor.substrate.compose_call(
            call_module="SubtensorModule",
            call_function="root_register",
            call_params={"hotkey": wallet.hotkey.ss58_address},
        )
        success, err_msg = await subtensor.sign_and_send_extrinsic(
            call,
            wallet=wallet,
            wait_for_inclusion=wait_for_inclusion,
            wait_for_finalization=wait_for_finalization,
        )

        if not success:
            err_console.print(f":cross_mark: [red]Failed[/red]: {err_msg}")
            await asyncio.sleep(0.5)
            return False, err_msg

        # Successful registration, final check for neuron and pubkey
        else:
            uid = await subtensor.query(
                module="SubtensorModule",
                storage_function="Uids",
                params=[0, wallet.hotkey.ss58_address],
            )
            if uid is not None:
                console.print(
                    f":white_heavy_check_mark: [green]Registered with UID {uid}[/green]"
                )
                return True, f"Registered with UID {uid}"
            else:
                # neuron not found, try again
                err_console.print(
                    ":cross_mark: [red]Unknown error. Neuron not found.[/red]"
                )
                return False, "Unknown error. Neuron not found."


async def set_root_weights_extrinsic(
    subtensor: SubtensorInterface,
    wallet: Wallet,
    netuids: Union[NDArray[np.int64], list[int]],
    weights: Union[NDArray[np.float32], list[float]],
    version_key: int = 0,
    wait_for_inclusion: bool = False,
    wait_for_finalization: bool = False,
    prompt: bool = False,
) -> bool:
    """Sets the given weights and values on chain for wallet hotkey account.

    :param subtensor: The SubtensorInterface object
    :param wallet: Bittensor wallet object.
    :param netuids: The `netuid` of the subnet to set weights for.
    :param weights: Weights to set. These must be `float` s and must correspond to the passed `netuid` s.
    :param version_key: The version key of the validator.
    :param wait_for_inclusion: If set, waits for the extrinsic to enter a block before returning `True`, or returns
                              `False` if the extrinsic fails to enter the block within the timeout.
    :param wait_for_finalization: If set, waits for the extrinsic to be finalized on the chain before returning `True`,
                                  or returns `False` if the extrinsic fails to be finalized within the timeout.
    :param prompt: If `True`, the call waits for confirmation from the user before proceeding.
    :return: `True` if extrinsic was finalized or included in the block. If we did not wait for finalization/inclusion,
             the response is `True`.
    """

    async def _do_set_weights():
        call = await subtensor.substrate.compose_call(
            call_module="SubtensorModule",
            call_function="set_root_weights",
            call_params={
                "dests": weight_uids,
                "weights": weight_vals,
                "netuid": 0,
                "version_key": version_key,
                "hotkey": wallet.hotkey.ss58_address,
            },
        )
        # Period dictates how long the extrinsic will stay as part of waiting pool
        extrinsic = await subtensor.substrate.create_signed_extrinsic(
            call=call,
            keypair=wallet.coldkey,
            era={"period": 5},
        )
        response = await subtensor.substrate.submit_extrinsic(
            extrinsic,
            wait_for_inclusion=wait_for_inclusion,
            wait_for_finalization=wait_for_finalization,
        )
        # We only wait here if we expect finalization.
        if not wait_for_finalization and not wait_for_inclusion:
            return True, "Not waiting for finalization or inclusion."

        if await response.is_success:
            return True, "Successfully set weights."
        else:
            return False, await response.error_message

    my_uid = await subtensor.query(
        "SubtensorModule", "Uids", [0, wallet.hotkey.ss58_address]
    )

    if my_uid is None:
        err_console.print("Your hotkey is not registered to the root network")
        return False

    if not unlock_key(wallet).success:
        return False

    # First convert types.
    if isinstance(netuids, list):
        netuids = np.array(netuids, dtype=np.int64)
    if isinstance(weights, list):
        weights = np.array(weights, dtype=np.float32)

    print_verbose("Fetching weight limits")
    min_allowed_weights, max_weight_limit = await get_limits(subtensor)

    # Get non zero values.
    non_zero_weight_idx = np.argwhere(weights > 0).squeeze(axis=1)
    non_zero_weights = weights[non_zero_weight_idx]
    if non_zero_weights.size < min_allowed_weights:
        raise ValueError(
            "The minimum number of weights required to set weights is {}, got {}".format(
                min_allowed_weights, non_zero_weights.size
            )
        )

    # Normalize the weights to max value.
    print_verbose("Normalizing weights")
    formatted_weights = normalize_max_weight(x=weights, limit=max_weight_limit)
    console.print(
        f"\nRaw weights -> Normalized weights: \n\t{weights} -> \n\t{formatted_weights}\n"
    )

    # Ask before moving on.
    if prompt:
        table = Table(
            Column("[dark_orange]Netuid", justify="center", style="bold green"),
            Column(
                "[dark_orange]Weight", justify="center", style="bold light_goldenrod2"
            ),
            expand=False,
            show_edge=False,
        )

        for netuid, weight in zip(netuids, formatted_weights):
            table.add_row(str(netuid), f"{weight:.8f}")

        console.print(table)
        if not Confirm.ask("\nDo you want to set these root weights?"):
            return False

    try:
        with console.status("Setting root weights...", spinner="earth"):
            weight_uids, weight_vals = convert_weights_and_uids_for_emit(
                netuids, weights
            )

            success, error_message = await _do_set_weights()

            if not wait_for_finalization and not wait_for_inclusion:
                return True

            if success is True:
                console.print(":white_heavy_check_mark: [green]Finalized[/green]")
                return True
            else:
                fmt_err = format_error_message(error_message)
                err_console.print(f":cross_mark: [red]Failed[/red]: {fmt_err}")
                return False

    except SubstrateRequestException as e:
        fmt_err = format_error_message(e)
        err_console.print(":cross_mark: [red]Failed[/red]: error:{}".format(fmt_err))
        return False
