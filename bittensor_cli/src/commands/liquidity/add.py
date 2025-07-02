import asyncio
import json
from collections import defaultdict
from functools import partial

from typing import TYPE_CHECKING, Optional
from rich.table import Table
from rich.prompt import Confirm, Prompt

from async_substrate_interface.errors import SubstrateRequestException
from bittensor_cli.src import COLOR_PALETTE
from bittensor_cli.src.bittensor.balances import Balance
from bittensor_cli.src.bittensor.swap_math import price_to_tick
from bittensor_cli.src.bittensor.utils import (
    console,
    err_console,
    format_error_message,
    get_hotkey_wallets_for_wallet,
    is_valid_ss58_address,
    print_error,
    print_verbose,
    unlock_key,
    json_console,
)
from bittensor_wallet import Wallet

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
        bool: True if add_liquidity operation is successful, False otherwise
    """
    err_out = partial(print_error)

    async def add_liquidity_extrinsic(
        netuid_: int,
        amount_: Balance,
        hotkey: str,
        price_low: float,
        price_high: float,
    ) -> bool:
        failure_prelude = (
            f":cross_mark: [red]Failed[/red] to add liquidity {amount_} on Netuid {netuid_}"
        )
        tick_low = price_to_tick(price_low)
        tick_high = price_to_tick(price_high)

        next_nonce, call = await asyncio.gather(
            subtensor.substrate.get_account_next_index(wallet.coldkeypub.ss58_address),
            subtensor.substrate.compose_call(
                call_module="Swap",
                # call_module="SubtensorModule",
                call_function="add_liquidity",
                call_params={
                    "hotkey": hotkey,
                    "netuid": netuid_,
                    "tick_low": tick_low,
                    "tick_high": tick_high,
                    "liquidity": amount_.rao,
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

    # Determine the liquidity amount.
    liquidity_amount = _prompt_liquidity_amount()

    # Determine price range
    price_low = _prompt_price("liquidity position low price")
    price_high = _prompt_price("liquidity position high price")
    if price_low >= price_high:
        err_console.print(f"The low price must be lower than the high price.")
        return False

    if prompt:
        if not Confirm.ask("Would you like to continue?"):
            return False
    if not unlock_key(wallet).success:
        return False

    success = await add_liquidity_extrinsic(
        netuid_=netuid,
        amount_=liquidity_amount,
        hotkey=hotkey,
        price_low=price_low,
        price_high=price_high,
    )

# Helper functions
def _prompt_liquidity_amount() -> Balance:
    """
    TODO
    """
    while True:
        amount_input = Prompt.ask(
            f"\nEnter the amount of liquidity"
        )

        try:
            amount = float(amount_input)
            if amount <= 0:
                console.print("[red]Amount must be greater than 0[/red]")
                continue
            return Balance.from_tao(amount)
        except ValueError:
            console.print("[red]Please enter a valid number[/red]")

def _prompt_price(prompt: str) -> float:
    """
    TODO
    """
    while True:
        input = Prompt.ask(
            f"\nEnter the {prompt}"
        )

        try:
            price = float(input)
            if price <= 0:
                console.print("[red]Price must be greater than 0[/red]")
                continue
            return price
        except ValueError:
            console.print("[red]Please enter a valid number[/red]")

