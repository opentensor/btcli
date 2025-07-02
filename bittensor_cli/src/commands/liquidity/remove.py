import asyncio
import json
from functools import partial

from typing import TYPE_CHECKING, Optional

from bittensor_wallet import Wallet
from rich.prompt import Confirm, Prompt
from rich.table import Table

from async_substrate_interface.errors import SubstrateRequestException
from bittensor_cli.src import COLOR_PALETTE
from bittensor_cli.src.bittensor.balances import Balance
from bittensor_cli.src.bittensor.utils import (
    console,
    err_console,
    print_verbose,
    print_error,
    get_hotkey_wallets_for_wallet,
    is_valid_ss58_address,
    format_error_message,
    group_subnets,
    unlock_key,
    json_console,
)

if TYPE_CHECKING:
    from bittensor_cli.src.bittensor.subtensor_interface import SubtensorInterface


#  Command
async def run(
    wallet: Wallet,
    subtensor: "SubtensorInterface",
    netuid: Optional[int],
    hotkey: str,
    prompt: bool,
    json_output: bool,
):
    """
    Args:
        wallet: wallet object
        subtensor: SubtensorInterface object
        netuid: the netuid to stake to (None indicates all subnets)
        hotkey: the hotkey that will taken the stake from
        amount: specified amount of balance to stake
        prompt: whether to prompt the user
        json_output: whether to output stake info in JSON format
        era: Blocks for which the transaction should be valid.

    Returns:
        bool: True if remove_liquidity operation is successful, False otherwise
    """
    err_out = partial(print_error)

    async def remove_liquidity_extrinsic(
        netuid_: int,
        hotkey: str,
        position_id: int,
    ) -> bool:
        failure_prelude = (
            f":cross_mark: [red]Failed[/red] to remove liquidity position {position_id} on Netuid {netuid_}"
        )

        next_nonce, call = await asyncio.gather(
            subtensor.substrate.get_account_next_index(wallet.coldkeypub.ss58_address),
            subtensor.substrate.compose_call(
                call_module="Swap",
                # call_module="SubtensorModule",
                call_function="remove_liquidity",
                call_params={
                    "hotkey": hotkey,
                    "netuid": netuid_,
                    "position_id": position_id,
                },
            ),
        )
        extrinsic = await subtensor.substrate.create_signed_extrinsic(
            call=call,
            keypair=wallet.coldkey,
            nonce=next_nonce,
        )
        try:
            response = await subtensor.substrate.submit_extrinsic(
                extrinsic, wait_for_inclusion=True, wait_for_finalization=False
            )
        except SubstrateRequestException as e:
            # if "Custom error: 8" in str(e):
            err_out(f"\n{failure_prelude} with error: {format_error_message(e)}")
            return False
        if not await response.is_success:
            err_out(
                f"\n{failure_prelude} with error: {format_error_message(await response.error_message)}"
            )
            return False
        else:
            if json_output:
                # the rest of this checking is not necessary if using json_output
                return True

            return True

    # Get subnet data and stake information for coldkey
    _all_subnets = await subtensor.all_subnets()
    all_subnets = {int(di.netuid): di for di in _all_subnets}

    # Check that the subnet exists.
    subnet_info = all_subnets.get(int(netuid))
    if not subnet_info:
        err_console.print(f"Subnet with netuid: {netuid} does not exist.")
        return False
    
    # Get the position ID
    position_id = _prompt_position_id()

    if prompt:
        if not Confirm.ask("Would you like to continue?"):
            return False
    if not unlock_key(wallet).success:
        return False

    success = await remove_liquidity_extrinsic(
        netuid_=netuid,
        hotkey=hotkey,
        position_id=position_id,
    )

# Helper functions
def _prompt_position_id() -> int:
    """
    TODO
    """
    while True:
        position_id = Prompt.ask(
            f"\nEnter the ID of the liquidity position to remove"
        )

        try:
            position_id = int(position_id)
            if position_id <= 1:
                console.print("[red]Position ID must be greater than 1[/red]")
                continue
            return position_id
        except ValueError:
            console.print("[red]Please enter a valid number[/red]")
