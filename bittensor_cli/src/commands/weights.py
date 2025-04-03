import asyncio
import json
import os
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from bittensor_wallet import Wallet
import numpy as np
from numpy.typing import NDArray
from rich.prompt import Confirm
from async_substrate_interface.errors import SubstrateRequestException

from bittensor_cli.src.bittensor.utils import (
    err_console,
    console,
    format_error_message,
    json_console,
)
from bittensor_cli.src.bittensor.extrinsics.root import (
    convert_weights_and_uids_for_emit,
    generate_weight_hash,
)

if TYPE_CHECKING:
    from bittensor_cli.src.bittensor.subtensor_interface import SubtensorInterface


# helpers and extrinsics


class SetWeightsExtrinsic:
    def __init__(
        self,
        subtensor: "SubtensorInterface",
        wallet: Wallet,
        netuid: int,
        uids: NDArray,
        weights: NDArray,
        salt: list[int],
        version_key: int,
        prompt: bool = False,
        wait_for_inclusion: bool = False,
        wait_for_finalization: bool = False,
    ):
        self.subtensor = subtensor
        self.wallet = wallet
        self.netuid = netuid
        self.uids = uids
        self.weights = weights
        self.salt = salt
        self.version_key = version_key
        self.prompt = prompt
        self.wait_for_inclusion = wait_for_inclusion
        self.wait_for_finalization = wait_for_finalization

    async def set_weights_extrinsic(self) -> tuple[bool, str]:
        """
        Sets the inter-neuronal weights for the specified neuron. This process involves specifying the
        influence or trust a neuron places on other neurons in the network, which is a fundamental aspect
        of Bittensor's decentralized learning architecture.

        This function is crucial in shaping the network's collective intelligence, where each neuron's
        learning and contribution are influenced by the weights it sets towards others.

        Returns:
            Tuple[bool, str]:
                `True` if the setting of weights is successful, False otherwise. And `msg`, a string
                value describing the success or potential error.
        """

        # Reformat and normalize.
        weight_uids, weight_vals = convert_weights_and_uids_for_emit(
            self.uids, self.weights
        )

        # Ask before moving on.
        formatted_weight_vals = [float(v / 65535) for v in weight_vals]
        if self.prompt and not Confirm.ask(
            f"Do you want to set weights:\n[bold white]"
            f"  weights: {formatted_weight_vals}\n  uids: {weight_uids}[/bold white ]?"
        ):
            return False, "Prompt refused."

        # Check if the commit-reveal mechanism is active for the given netuid.
        if bool(
            await self.subtensor.get_hyperparameter(
                param_name="get_commit_reveal_weights_enabled",
                netuid=self.netuid,
                reuse_block=False,
            )
        ):
            return await self._commit_reveal(
                weight_uids,
                weight_vals,
            )
        else:
            return await self._set_weights_without_commit_reveal(
                weight_uids,
                weight_vals,
            )

    async def commit_weights(
        self,
        uids: list[int],
        weights: list[int],
    ) -> tuple[bool, str]:
        """
        Commits a hash of the neuron's weights to the Bittensor blockchain using the provided wallet.
        This action serves as a commitment or snapshot of the neuron's current weight distribution.

        Args:
            uids (np.ndarray): NumPy array of neuron UIDs for which weights are being committed.
            weights (np.ndarray): NumPy array of weight values corresponding to each UID.

        Returns:
            Tuple[bool, str]: ``True`` if the weight commitment is successful, False otherwise. And `msg`, a string
            value describing the success or potential error.

        This function allows neurons to create a tamper-proof record of their weight distribution at a specific point in time,
        enhancing transparency and accountability within the Bittensor network.
        """

        # _logger.info(
        #     "Committing weights with params: netuid={}, uids={}, weights={}, version_key={}".format(
        #         netuid, uids, weights, version_key
        #     )
        # )

        # Generate the hash of the weights
        commit_hash = generate_weight_hash(
            address=self.wallet.hotkey.ss58_address,
            netuid=self.netuid,
            uids=uids,
            values=weights,
            salt=self.salt,
            version_key=self.version_key,
        )

        # _logger.info("Commit Hash: {}".format(commit_hash))
        try:
            success, message = await self.do_commit_weights(commit_hash=commit_hash)
        except SubstrateRequestException as e:
            err_console.print(f"Error committing weights: {format_error_message(e)}")
            # bittensor.logging.error(f"Error committing weights: {e}")
            success = False
            message = "No attempt made. Perhaps it is too soon to commit weights!"

        return success, message

    async def _commit_reveal(
        self, weight_uids: list[int], weight_vals: list[int]
    ) -> tuple[bool, str]:
        interval = int(
            await self.subtensor.get_hyperparameter(
                param_name="get_commit_reveal_period",
                netuid=self.netuid,
                reuse_block=False,
            )
        )

        if not self.salt:
            # Generate a random salt of specified length to be used in the commit-reveal process
            salt_length = 8
            self.salt = list(os.urandom(salt_length))

        # Attempt to commit the weights to the blockchain.
        commit_success, commit_msg = await self.commit_weights(
            uids=weight_uids,
            weights=weight_vals,
        )

        if commit_success:
            current_time = datetime.now().astimezone().replace(microsecond=0)
            reveal_time = (current_time + timedelta(seconds=interval)).isoformat()
            cli_retry_cmd = f"--netuid {self.netuid} --uids {weight_uids} --weights {self.weights} --reveal-using-salt {self.salt}"
            # Print params to screen and notify user this is a blocking operation
            console.print(
                ":white_heavy_check_mark: [green]Weights hash committed to chain[/green]"
            )
            console.print(
                f":alarm_clock: [dark_orange3]Weights hash will be revealed at {reveal_time}[/dark_orange3]"
            )
            console.print(
                ":alarm_clock: [red]WARNING: Turning off your computer will prevent this process from executing!!![/red]"
            )
            console.print(
                f"To manually retry after {reveal_time} run:\n{cli_retry_cmd}"
            )

            # bittensor.logging.info(msg=f"Weights hash committed and will be revealed at {reveal_time}")

            console.print(
                "Note: BTCLI will wait until the reveal time. To place BTCLI into background:"
            )
            console.print(
                "[red]CTRL+Z[/red] followed by the command [red]bg[/red] and [red]ENTER[/red]"
            )
            console.print(
                "To bring BTLCI into the foreground use the command [red]fg[/red] and [red]ENTER[/red]"
            )

            # Attempt executing reveal function after a delay of 'interval'
            await self.subtensor.substrate.close()
            await asyncio.sleep(interval)
            async with self.subtensor:
                return await self.reveal(weight_uids, weight_vals)
        else:
            console.print(f":cross_mark: [red]Failed[/red]: error:{commit_msg}")
            # bittensor.logging.error(msg=commit_msg, prefix="Set weights with hash commit",
            #                         suffix=f"<red>Failed: {commit_msg}</red>")
            return False, f"Failed to commit weights hash. {commit_msg}"

    async def reveal(self, weight_uids, weight_vals) -> tuple[bool, str]:
        # Attempt to reveal the weights using the salt.
        success, msg = await self.reveal_weights_extrinsic(weight_uids, weight_vals)

        if success:
            if not self.wait_for_finalization and not self.wait_for_inclusion:
                return True, "Not waiting for finalization or inclusion."

            console.print(
                ":white_heavy_check_mark: [green]Weights hash revealed on chain[/green]"
            )
            # bittensor.logging.success(prefix="Weights hash revealed", suffix=str(msg))

            return True, "Successfully revealed previously commited weights hash."
        else:
            # bittensor.logging.error(
            #     msg=msg,
            #     prefix=f"Failed to reveal previously commited weights hash for salt: {salt}",
            #     suffix="<red>Failed: </red>",
            # )
            return False, "Failed to reveal weights."

    async def _set_weights_without_commit_reveal(
        self,
        weight_uids,
        weight_vals,
    ) -> tuple[bool, str]:
        async def _do_set_weights():
            call = await self.subtensor.substrate.compose_call(
                call_module="SubtensorModule",
                call_function="set_weights",
                call_params={
                    "dests": weight_uids,
                    "weights": weight_vals,
                    "netuid": self.netuid,
                    "version_key": self.version_key,
                },
            )
            # Period dictates how long the extrinsic will stay as part of waiting pool
            extrinsic = await self.subtensor.substrate.create_signed_extrinsic(
                call=call,
                keypair=self.wallet.hotkey,
                era={"period": 5},
            )
            try:
                response = await self.subtensor.substrate.submit_extrinsic(
                    extrinsic,
                    wait_for_inclusion=self.wait_for_inclusion,
                    wait_for_finalization=self.wait_for_finalization,
                )
            except SubstrateRequestException as e:
                return False, format_error_message(e)
            # We only wait here if we expect finalization.
            if not self.wait_for_finalization and not self.wait_for_inclusion:
                return True, "Not waiting for finalization or inclusion."

            if await response.is_success:
                return True, "Successfully set weights."
            else:
                return False, format_error_message(await response.error_message)

        with console.status(
            f":satellite: Setting weights on [white]{self.subtensor.network}[/white] ..."
        ):
            success, error_message = await _do_set_weights()

            if not self.wait_for_finalization and not self.wait_for_inclusion:
                return True, "Not waiting for finalization or inclusion."

            if success:
                console.print(":white_heavy_check_mark: [green]Finalized[/green]")
                # bittensor.logging.success(prefix="Set weights", suffix="<green>Finalized: </green>" + str(success))
                return True, "Successfully set weights and finalized."
            else:
                # bittensor.logging.error(msg=error_message, prefix="Set weights", suffix="<red>Failed: </red>")
                return False, error_message

    async def reveal_weights_extrinsic(
        self, weight_uids, weight_vals
    ) -> tuple[bool, str]:
        if self.prompt and not Confirm.ask("Would you like to reveal weights?"):
            return False, "User cancelled the operation."

        call = await self.subtensor.substrate.compose_call(
            call_module="SubtensorModule",
            call_function="reveal_weights",
            call_params={
                "netuid": self.netuid,
                "uids": weight_uids,
                "values": weight_vals,
                "salt": self.salt,
                "version_key": self.version_key,
            },
        )
        extrinsic = await self.subtensor.substrate.create_signed_extrinsic(
            call=call,
            keypair=self.wallet.hotkey,
        )
        try:
            response = await self.subtensor.substrate.submit_extrinsic(
                extrinsic,
                wait_for_inclusion=self.wait_for_inclusion,
                wait_for_finalization=self.wait_for_finalization,
            )
        except SubstrateRequestException as e:
            return False, format_error_message(e)

        if not self.wait_for_finalization and not self.wait_for_inclusion:
            success, error_message = True, ""

        else:
            if await response.is_success:
                success, error_message = True, ""
            else:
                success, error_message = (
                    False,
                    format_error_message(await response.error_message),
                )

        if success:
            # bittensor.logging.info("Successfully revealed weights.")
            return True, "Successfully revealed weights."
        else:
            # bittensor.logging.error(f"Failed to reveal weights: {error_message}")
            return False, error_message

    async def do_commit_weights(self, commit_hash):
        call = await self.subtensor.substrate.compose_call(
            call_module="SubtensorModule",
            call_function="commit_weights",
            call_params={
                "netuid": self.netuid,
                "commit_hash": commit_hash,
            },
        )
        extrinsic = await self.subtensor.substrate.create_signed_extrinsic(
            call=call,
            keypair=self.wallet.hotkey,
        )
        response = await self.subtensor.substrate.submit_extrinsic(
            extrinsic,
            wait_for_inclusion=self.wait_for_inclusion,
            wait_for_finalization=self.wait_for_finalization,
        )

        if not self.wait_for_finalization and not self.wait_for_inclusion:
            return True, None

        if await response.is_success:
            return True, None
        else:
            return False, await response.error_message


# commands


async def reveal_weights(
    subtensor: "SubtensorInterface",
    wallet: Wallet,
    netuid: int,
    uids: list[int],
    weights: list[float],
    salt: list[int],
    version: int,
    json_output: bool = False,
    prompt: bool = True,
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
    # Call the reveal function in the module set_weights from extrinsics package
    extrinsic = SetWeightsExtrinsic(
        subtensor, wallet, netuid, uids_, weights_, list(salt_), version, prompt=prompt
    )
    success, message = await extrinsic.reveal(weight_uids, weight_vals)
    if json_output:
        json_console.print(json.dumps({"success": success, "message": message}))
    else:
        if success:
            console.print("Weights revealed successfully")
        else:
            err_console.print(f"Failed to reveal weights: {message}")


async def commit_weights(
    subtensor: "SubtensorInterface",
    wallet: Wallet,
    netuid: int,
    uids: list[int],
    weights: list[float],
    salt: list[int],
    version: int,
    json_output: bool = False,
    prompt: bool = True,
):
    """Commits weights and then reveals them for a specific subnet"""
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
    extrinsic = SetWeightsExtrinsic(
        subtensor, wallet, netuid, uids_, weights_, list(salt_), version, prompt=prompt
    )
    success, message = await extrinsic.set_weights_extrinsic()
    if json_output:
        json_console.print(json.dumps({"success": success, "message": message}))
    else:
        if success:
            console.print("Weights set successfully")
        else:
            err_console.print(f"Failed to commit weights: {message}")
