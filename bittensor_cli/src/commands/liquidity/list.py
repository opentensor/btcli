import asyncio
from functools import partial

from typing import TYPE_CHECKING, Optional

from bittensor_cli.src.bittensor.balances import Balance, fixed_to_float
from bittensor_cli.src.bittensor.swap_math import tick_to_price
from bittensor_cli.src.bittensor.utils import (
    console,
    err_console,
    print_error,
    json_console,
)
from bittensor_wallet import Wallet

if TYPE_CHECKING:
    from bittensor_cli.src.bittensor.subtensor_interface import SubtensorInterface


def fees_in_range(fee_global, fees_below, fees_above) -> int:
    return fee_global - fees_below - fees_above

# Calculate fees for a position
def calculate_fees(position, fees_in_range_tao, fees_in_range_alpha) -> list[Balance]:
    fee_tao = fees_in_range_tao
    fee_alpha = fees_in_range_alpha

    fee_tao -= fixed_to_float(position["fees_tao"])
    fee_alpha -= fixed_to_float(position["fees_alpha"])

    fee_tao *= position["liquidity"]
    fee_alpha *= position["liquidity"]

    return [Balance.from_rao(fee_tao), Balance.from_rao(fee_alpha)]

#  Command
async def run(
    wallet: Wallet,
    subtensor: "SubtensorInterface",
    netuid: Optional[int],
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

    (
        positions_response,
        fee_global_tao,
        fee_global_alpha,
    ) = await asyncio.gather(
        subtensor.substrate.query_map(
            module="Swap",
            storage_function="Positions",
            params=[netuid, wallet.coldkeypub.ss58_address],
        ),
        subtensor.substrate.query(
            module="Swap",
            storage_function="FeeGlobalTao",
            params=[netuid],
        ),
        subtensor.substrate.query(
            module="Swap",
            storage_function="FeeGlobalAlpha",
            params=[netuid],
        ),
    )

    positions = []
    async for _id, p in positions_response:
        # Get ticks for the position (for below/above fees)
        (
            tick_low,
            tick_high,
        ) = await asyncio.gather(
            subtensor.substrate.query(
                module="Swap",
                storage_function="Ticks",
                params=[netuid, p.value.get('tick_low')[0]],
            ),
            subtensor.substrate.query(
                module="Swap",
                storage_function="Ticks",
                params=[netuid, p.value.get('tick_high')[0]],
            ),
        )

        print(f"p = {p}")
        print(f"tick_low = {tick_low}")
        print(f"tick_high = {tick_high}")

        fees_below_low = fixed_to_float(tick_low.get('fees_out_tao'))
        fees_above_high = fixed_to_float(tick_high.get('fees_out_alpha'))
        fee_global_tao = fixed_to_float(fee_global_tao)
        fee_global_alpha = fixed_to_float(fee_global_alpha)

        # Get position accrued fees
        fees_in_range_tao = fees_in_range(fee_global_tao, fees_below_low, fees_above_high)
        fees_in_range_alpha = fees_in_range(fee_global_alpha, fees_below_low, fees_above_high)

        print(f"fees_in_range_tao = {fees_in_range_tao}")

        [fees_tao, fees_alpha] = calculate_fees(p, fees_in_range_tao, fees_in_range_alpha)

        print(f"fees_tao = {fees_tao}")


        positions.append(
            {
                'id': p.value.get('id')[0],
                'price_low': tick_to_price(p.value.get('tick_low')[0]),
                'price_high': tick_to_price(p.value.get('tick_high')[0]),
                'liquidity': Balance.from_rao(p.value.get('liquidity')),
                'fees_tao': fees_tao,
                'fees_alpha': fees_alpha,
            }
        )

    for p in positions:
        print(f"Position ID: {p['id']}")
        print(f"Position liquidity: {p['liquidity']}")
        print(f"Price range:")
        print(f"   low:  {p['price_low']}")
        print(f"   high: {p['price_high']}")
        print(f"Fees accrued:")
        print(f"   tao:   {p['fees_tao']}")
        print(f"   alpha: {p['fees_alpha']}")
