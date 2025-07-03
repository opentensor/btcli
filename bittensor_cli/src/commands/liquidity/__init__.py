import asyncio
from typing import TYPE_CHECKING, Optional

from rich.prompt import Confirm

from bittensor_cli.src.bittensor.balances import Balance, fixed_to_float
from bittensor_cli.src.bittensor.utils import (
    console,
    err_console,
    unlock_key,
)
from bittensor_cli.src.commands.liquidity.liquidity import (
    add_liquidity_extrinsic,
    modify_liquidity_extrinsic,
    remove_liquidity_extrinsic,
    toggle_user_liquidity_extrinsic,
)
from .utils import (
    LiquidityPosition,
    calculate_fees,
    get_fees,
    price_to_tick,
    prompt_position_id,
    prompt_liquidity,
    tick_to_price,
)

if TYPE_CHECKING:
    from bittensor_wallet import Wallet
    from bittensor_cli.src.bittensor.subtensor_interface import SubtensorInterface


__all__ = [
    "add_liquidity",
    "get_liquidity_list",
    "modify_liquidity",
    "remove_liquidity",
]


#  Command
async def add_liquidity(
    subtensor: "SubtensorInterface",
    wallet: "Wallet",
    netuid: Optional[int],
    liquidity: Optional[float],
    price_low: Optional[float],
    price_high: Optional[float],
    prompt: bool,
    json_output: bool,
):
    """Add liquidity position to provided subnet."""
    # Check wallet access
    if not unlock_key(wallet).success:
        return False

    # Check that the subnet exists.
    if not await subtensor.subnet_exists(netuid=netuid):
        return False, f"Subnet with netuid: {netuid} does not exist in {subtensor}."

    # Determine the liquidity amount.
    if liquidity:
        liquidity = Balance.from_tao(liquidity)
    else:
        liquidity = prompt_liquidity("Enter the amount of liquidity")

    # Determine price range
    if price_low:
        price_low = Balance.from_tao(price_low)
    else:
        price_low = prompt_liquidity("Enter liquidity position low price")

    if price_high:
        price_high = Balance.from_tao(price_high)
    else:
        price_high = prompt_liquidity(
            "Enter liquidity position high price (must be greater than low price)"
        )

    if price_low >= price_high:
        err_console.print(f"The low price must be lower than the high price.")
        return False

    if prompt:
        console.print("You are about to add a LiquidityPosition with:")
        console.print(f"\tliquidity: {liquidity}")
        console.print(f"\tprice low: {price_low}")
        console.print(f"\tprice high: {price_high}")
        console.print(f"\tto SN: {netuid}")
        console.print(f"\tusing wallet with name: {wallet.name}")

        if not Confirm.ask("Would you like to continue?"):
            return False, "User cancelled operation."

    return await add_liquidity_extrinsic(
        subtensor=subtensor,
        wallet=wallet,
        netuid=netuid,
        liquidity=liquidity,
        price_low=price_low,
        price_high=price_high,
    )


async def get_liquidity_list(
    subtensor: "SubtensorInterface",
    wallet: "Wallet",
    netuid: Optional[int],
    json_output: bool,
):
    """
    Args:
        wallet: wallet object
        subtensor: SubtensorInterface object
        netuid: the netuid to stake to (None indicates all subnets)
        json_output: whether to output stake info in JSON format

    Returns:
        bool: True if add_liquidity operation is successful, False otherwise
    """

    if not await subtensor.subnet_exists(netuid=netuid):
        return False, f"Subnet with netuid: {netuid} does not exist in {subtensor}."

    if not await subtensor.is_subnet_active(netuid=netuid):
        return False, f"Subnet with netuid: {netuid} is not active in {subtensor}."

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

    positions = []

    async for _, p in positions_response:
        position = p.value
        tick_index_low = position.get("tick_low")[0]
        tick_index_high = position.get("tick_high")[0]

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

        tao_fees_below_low = get_fees(
            current_tick=current_tick,
            tick=tick_low,
            tick_index=tick_index_low,
            quote=True,
            global_fees_tao=fee_global_tao,
            global_fees_alpha=fee_global_alpha,
            above=False,
        )
        tao_fees_above_high = get_fees(
            current_tick=current_tick,
            tick=tick_high,
            tick_index=tick_index_high,
            quote=True,
            global_fees_tao=fee_global_tao,
            global_fees_alpha=fee_global_alpha,
            above=True,
        )
        alpha_fees_below_low = get_fees(
            current_tick=current_tick,
            tick=tick_low,
            tick_index=tick_index_low,
            quote=False,
            global_fees_tao=fee_global_tao,
            global_fees_alpha=fee_global_alpha,
            above=False,
        )
        alpha_fees_above_high = get_fees(
            current_tick=current_tick,
            tick=tick_high,
            tick_index=tick_index_high,
            quote=False,
            global_fees_tao=fee_global_tao,
            global_fees_alpha=fee_global_alpha,
            above=True,
        )

        # Get position accrued fees
        fees_tao, fees_alpha = calculate_fees(
            position=position,
            global_fees_tao=fee_global_tao,
            global_fees_alpha=fee_global_alpha,
            tao_fees_below_low=tao_fees_below_low,
            tao_fees_above_high=tao_fees_above_high,
            alpha_fees_below_low=alpha_fees_below_low,
            alpha_fees_above_high=alpha_fees_above_high,
            netuid=netuid,
        )

        lp = LiquidityPosition(
            **{
                "id": position.get("id")[0],
                "price_low": Balance.from_tao(
                    tick_to_price(position.get("tick_low")[0])
                ),
                "price_high": Balance.from_tao(
                    tick_to_price(position.get("tick_high")[0])
                ),
                "liquidity": Balance.from_rao(position.get("liquidity")),
                "fees_tao": fees_tao,
                "fees_alpha": fees_alpha,
                "netuid": position.get("netuid"),
            }
        )
        positions.append(lp)

    return positions


async def remove_liquidity(
    subtensor: "SubtensorInterface",
    wallet: "Wallet",
    netuid: int,
    position_id: Optional[int] = None,
    prompt: Optional[bool] = None,
    all_liquidity_ids: Optional[bool] = None,
    json_output: bool = False,
) -> tuple[bool, str]:
    """Remove liquidity position from provided subnet."""
    if not await subtensor.subnet_exists(netuid=netuid):
        return False, f"Subnet with netuid: {netuid} does not exist in {subtensor}."

    if not position_id:
        position_id = prompt_position_id()

    if prompt and not all_liquidity_ids:
        console.print("You are about to remove a LiquidityPosition with:")
        console.print(f"\tSubnet: {netuid}")
        console.print(f"\tPosition id: {position_id}")
        console.print(f"\tWallet name: {wallet.name}")

        if not Confirm.ask("Would you like to continue?"):
            return False, "User cancelled operation."

    return await remove_liquidity_extrinsic(
        subtensor=subtensor,
        wallet=wallet,
        netuid=netuid,
        position_id=position_id,
    )


async def modify_liquidity(
    subtensor: "SubtensorInterface",
    wallet: "Wallet",
    netuid: int,
    position_id: int,
    liquidity_delta: Optional[float],
    prompt: Optional[bool] = None,
    json_output: bool = False,
):
    """Modify liquidity position in provided subnet."""
    if not await subtensor.subnet_exists(netuid=netuid):
        return False, f"Subnet with netuid: {netuid} does not exist in {subtensor}."

    if not position_id:
        position_id = prompt_position_id()

    if liquidity_delta:
        liquidity_delta = Balance.from_tao(liquidity_delta)
    else:
        liquidity_delta = prompt_liquidity(
            f"Enter the [blue]liquidity_delta[/blue] for modify position with id "
            f"[blue]{position_id}[/blue] (could be positive or negative)",
            negative_allowed=True,
        )

    if prompt:
        console.print("You are about to modify a LiquidityPosition with:")
        console.print(f"\tSubnet: {netuid}")
        console.print(f"\tPosition id: {position_id}")
        console.print(f"\tWallet name: {wallet.name}")
        console.print(f"\tLiquidity delta: {liquidity_delta}")

        if not Confirm.ask("Would you like to continue?"):
            return False, "User cancelled operation."

    return await modify_liquidity_extrinsic(
        subtensor=subtensor,
        wallet=wallet,
        netuid=netuid,
        position_id=position_id,
        liquidity_delta=liquidity_delta,
    )
