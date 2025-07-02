import asyncio
from functools import partial

from typing import TYPE_CHECKING, Optional

from bittensor_cli.src.bittensor.balances import Balance, fixed_to_float
from bittensor_cli.src.bittensor.swap_math import price_to_tick, tick_to_price
from bittensor_cli.src.bittensor.utils import (
    console,
    err_console,
    print_error,
    json_console,
)
from bittensor_wallet import Wallet

if TYPE_CHECKING:
    from bittensor_cli.src.bittensor.subtensor_interface import SubtensorInterface

def get_fees_above(
    current_tick,
    tick,
    tick_index,
    quote,
    global_fees_tao,
    global_fees_alpha,
) -> float:
    if tick_index <= current_tick:
        if quote:
            return global_fees_tao - fixed_to_float(tick.get('fees_out_tao'))
        else:
            return global_fees_alpha - fixed_to_float(tick.get('fees_out_alpha'))
    elif quote:
        return fixed_to_float(tick.get('fees_out_tao'))
    else:
        return fixed_to_float(tick.get('fees_out_alpha'))

def get_fees_below(
    current_tick,
    tick,
    tick_index,
    quote,
    global_fees_tao,
    global_fees_alpha,
) -> float:
    if tick_index <= current_tick:
        if quote:
            return fixed_to_float(tick.get('fees_out_tao'))
        else:
            return fixed_to_float(tick.get('fees_out_alpha'))
    elif quote:
        return global_fees_tao - fixed_to_float(tick.get('fees_out_tao'))
    else:
        return global_fees_alpha - fixed_to_float(tick.get('fees_out_alpha'))

def get_fees_in_range(
    quote,
    global_fees_tao,
    global_fees_alpha,
    fees_below_low,
    fees_above_high,
) -> float:
    global_fees = 0
    if quote:
        global_fees = global_fees_tao
    else:
        global_fees = global_fees_alpha

    return global_fees - fees_below_low - fees_above_high

# Calculate fees for a position
def calculate_fees(
    position,
    global_fees_tao,
    global_fees_alpha,
    tao_fees_below_low,
    tao_fees_above_high,
    alpha_fees_below_low,
    alpha_fees_above_high,
) -> list[Balance]:
    fee_tao_agg = get_fees_in_range(
        True, global_fees_tao, global_fees_alpha,
        tao_fees_below_low, tao_fees_above_high
    )
    fee_alpha_agg = get_fees_in_range(
        False, global_fees_tao, global_fees_alpha,
        alpha_fees_below_low, alpha_fees_above_high
    )

    fee_tao = fee_tao_agg - fixed_to_float(position["fees_tao"])
    fee_alpha = fee_alpha_agg - fixed_to_float(position["fees_alpha"])

    liquidity_frac = position["liquidity"]

    fee_tao = liquidity_frac * fee_tao
    fee_alpha = liquidity_frac * fee_alpha

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

    print(f"============ debug")

    (
        positions_response,
        fee_global_tao,
        fee_global_alpha,
        current_sqrt_price,
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
        subtensor.substrate.query(
            module="Swap",
            storage_function="AlphaSqrtPrice",
            params=[netuid],
        ),
    )

    current_sqrt_price = fixed_to_float(current_sqrt_price)
    fee_global_tao = fixed_to_float(fee_global_tao)
    fee_global_alpha = fixed_to_float(fee_global_alpha)

    current_price = current_sqrt_price * current_sqrt_price
    current_tick = price_to_tick(current_price)

    print(f"current price = {current_price}")
    print(f"global fees TAO = {fee_global_tao}")
    print(f"global fees Alpha = {fee_global_alpha}")

    positions = []
    async for _id, p in positions_response:
        tick_index_low = p.value.get('tick_low')[0]
        tick_index_high = p.value.get('tick_high')[0]

        # Get ticks for the position (for below/above fees)
        (
            tick_low,
            tick_high,
        ) = await asyncio.gather(
            subtensor.substrate.query(
                module="Swap",
                storage_function="Ticks",
                params=[netuid, tick_index_low],
            ),
            subtensor.substrate.query(
                module="Swap",
                storage_function="Ticks",
                params=[netuid, tick_index_high],
            ),
        )

        print(f"p = {p}")
        print(f"tick_low = {tick_low}")
        print(f"tick_high = {tick_high}")

        tao_fees_below_low = get_fees_below(current_tick, tick_low, tick_index_low, True, fee_global_tao, fee_global_alpha)
        tao_fees_above_high = get_fees_above(current_tick, tick_high, tick_index_high, True, fee_global_tao, fee_global_alpha)
        alpha_fees_below_low = get_fees_below(current_tick, tick_low, tick_index_low, False, fee_global_tao, fee_global_alpha)
        alpha_fees_above_high = get_fees_above(current_tick, tick_high, tick_index_high, False, fee_global_tao, fee_global_alpha)

        # Get position accrued fees

        # print(f"fees_in_range_tao = {fees_in_range_tao}")

        [fees_tao, fees_alpha] = calculate_fees(
            p, fee_global_tao, fee_global_alpha, 
            tao_fees_below_low, tao_fees_above_high,
            alpha_fees_below_low, alpha_fees_above_high,
        )

        print(f"fees_tao = {fees_tao}")
        print(f"fees_alpha = {fees_alpha}")

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
        print(f"Position liquidity: {p['liquidity'].tao}")
        print(f"Price range:")
        print(f"   low:  {p['price_low']}")
        print(f"   high: {p['price_high']}")
        print(f"Fees accrued:")
        print(f"   tao:   {p['fees_tao']}")
        print(f"   alpha: {p['fees_alpha'].tao}")
