import asyncio
import json
import math
from typing import TYPE_CHECKING, Optional

from rich.prompt import Confirm, FloatPrompt, Prompt
from rich.table import Column, Table

from bittensor_cli.src import COLORS
from bittensor_cli.src.bittensor.utils import (
    unlock_key,
    console,
    err_console,
    json_console,
    print_extrinsic_id,
    get_hotkey_pub_ss58,
)
from bittensor_cli.src.bittensor.balances import Balance, fixed_to_float
from bittensor_cli.src.bittensor.extrinsics.liquidity import (
    add_liquidity_extrinsic,
    modify_liquidity_extrinsic,
    remove_liquidity_extrinsic,
)
from bittensor_cli.src.commands.liquidity.utils import (
    LiquidityPosition,
    calculate_fees,
    get_fees,
    price_to_tick,
    tick_to_price,
    calculate_max_liquidity_from_balances,
    calculate_alpha_from_tao,
    calculate_tao_from_alpha,
)
from bittensor_wallet import Wallet

if TYPE_CHECKING:
    from bittensor_wallet import Wallet
    from bittensor_cli.src.bittensor.subtensor_interface import SubtensorInterface


async def add_liquidity_interactive(
    subtensor: "SubtensorInterface",
    wallet: "Wallet",
    netuid: int,
    price_low: Optional[float],
    price_high: Optional[float],
    tao_amount: Optional[float],
    alpha_amount: Optional[float],
    prompt: bool,
    json_output: bool,
) -> tuple[bool, str]:
    """Interactive flow for adding liquidity based on the improved logic.

    Steps:
    1. Check if subnet exists
    2. Ask user to enter low and high position prices
    3. Fetch current SN price
    4. Based on price position:
       - If low >= current: only ask for Alpha amount
       - If high <= current: only ask for TAO amount
       - Otherwise: calculate max liquidity and ask for TAO or Alpha amount
    5. Execute the extrinsic
    """
    # Step 2: Check if the subnet exists
    if not await subtensor.subnet_exists(netuid=netuid):
        return False, f"Subnet with netuid: {netuid} does not exist in {subtensor}."

    # Check if user liquidity is enabled for this subnet
    with console.status(
        ":satellite: Checking user liquidity status...", spinner="aesthetic"
    ):
        hyperparams = await subtensor.get_subnet_hyperparameters(netuid=netuid)

    if not hyperparams:
        return False, f"Failed to get hyperparameters for subnet {netuid}."

    if not hyperparams.user_liquidity_enabled:
        err_console.print(
            f"[red]User liquidity is disabled for subnet {netuid}.[/red]\n"
        )
        return False, f"User liquidity is disabled for subnet {netuid}."

    console.print(f"[green]✓ User liquidity is enabled for subnet {netuid}[/green]\n")

    # Step 3: Ask user to enter low and high position prices
    if price_low is None:
        while True:
            price_low_input = FloatPrompt.ask(
                f"[{COLORS.G.SUBHEAD_MAIN}]Enter the low price for the liquidity position[/{COLORS.G.SUBHEAD_MAIN}]"
            )
            if price_low_input > 0:
                price_low = price_low_input
                break
            console.print("[red]Price must be greater than 0[/red]")

    if price_high is None:
        while True:
            price_high_input = FloatPrompt.ask(
                f"[{COLORS.G.SUBHEAD_MAIN}]Enter the high price for the liquidity position[/{COLORS.G.SUBHEAD_MAIN}]"
            )
            if price_high_input > price_low:
                price_high = price_high_input
                break
            console.print(
                f"[red]High price must be greater than low price ({price_low})[/red]"
            )

    price_low_balance = Balance.from_tao(price_low)
    price_high_balance = Balance.from_tao(price_high)

    # Step 4: Fetch current SN price
    with console.status(
        ":satellite: Fetching current subnet price...", spinner="aesthetic"
    ):
        current_price = await subtensor.get_subnet_price(netuid=netuid)

    console.print(f"Current subnet price: [cyan]{current_price.tao:.6f} τ[/cyan]")

    # Determine hotkey to use - default to wallet's hotkey
    hotkey_ss58 = get_hotkey_pub_ss58(wallet)

    # Step 5: Determine which case we're in based on price position
    liquidity_to_add = None
    tao_to_provide = Balance.from_tao(0)
    alpha_to_provide = Balance.from_tao(0)

    # Case 1: Low price >= current price (only Alpha needed)
    if price_low >= current_price.tao:
        console.print(
            f"\n[yellow]The low price ({price_low:.6f}) is higher than or equal to the current price ({current_price.tao:.6f}).[/yellow]"
        )
        console.print(
            "[yellow]Only Alpha tokens are needed for this position.[/yellow]\n"
        )

        # Fetch Alpha balance
        with console.status(
            ":satellite: Fetching Alpha balance...", spinner="aesthetic"
        ):
            alpha_balance_available = await subtensor.get_stake_for_coldkey_and_hotkey(
                hotkey_ss58=hotkey_ss58,
                coldkey_ss58=wallet.coldkeypub.ss58_address,
                netuid=netuid,
            )

        console.print(
            f"Available Alpha: {alpha_balance_available.tao:.6f} α (for subnet {netuid})\n"
        )

        # Ask for Alpha amount
        if alpha_amount is None:
            alpha_amount = FloatPrompt.ask(
                f"[{COLORS.G.SUBHEAD_MAIN}]Enter the amount of Alpha to provide[/{COLORS.G.SUBHEAD_MAIN}]"
            )

        alpha_to_provide = Balance.from_tao(alpha_amount)

        # Check if user has enough Alpha
        if alpha_to_provide > alpha_balance_available:
            err_console.print(
                f"[red]Insufficient Alpha balance.[/red]\n"
                f"Required: {alpha_to_provide.tao:.6f} α (for subnet {netuid})\n"
                f"Available: {alpha_balance_available.tao:.6f} α (for subnet {netuid})"
            )
            return False, "Insufficient Alpha balance."

        # Calculate liquidity from Alpha
        # L = alpha / (1/sqrt_price_low - 1/sqrt_price_high)
        sqrt_price_low = math.sqrt(price_low)
        sqrt_price_high = math.sqrt(price_high)
        liquidity_to_add = Balance.from_rao(
            int(alpha_to_provide.rao / (1 / sqrt_price_low - 1 / sqrt_price_high))
        )

    # Case 2: High price <= current price (only TAO needed)
    elif price_high <= current_price.tao:
        console.print(
            f"\n[yellow]The high price ({price_high:.6f}) is lower than or equal to the current price ({current_price.tao:.6f}).[/yellow]"
        )
        console.print(
            "[yellow]Only TAO tokens are needed for this position.[/yellow]\n"
        )

        # Fetch TAO balance
        with console.status(":satellite: Fetching TAO balance...", spinner="aesthetic"):
            tao_balance_available = await subtensor.get_balance(
                wallet.coldkeypub.ss58_address
            )

        console.print(f"Available TAO: {tao_balance_available.tao:.6f} τ\n")

        # Ask for TAO amount
        if tao_amount is None:
            tao_amount = FloatPrompt.ask(
                f"[{COLORS.G.SUBHEAD_MAIN}]Enter the amount of TAO to provide[/{COLORS.G.SUBHEAD_MAIN}]"
            )

        tao_to_provide = Balance.from_tao(tao_amount)

        # Check if user has enough TAO
        if tao_to_provide > tao_balance_available:
            err_console.print(
                f"[red]Insufficient TAO balance.[/red]\n"
                f"Required: {tao_to_provide.tao:.6f} τ\n"
                f"Available: {tao_balance_available.tao:.6f} τ"
            )
            return False, "Insufficient TAO balance."

        # Calculate liquidity from TAO
        # L = tao / (sqrt_price_high - sqrt_price_low)
        sqrt_price_low = math.sqrt(price_low)
        sqrt_price_high = math.sqrt(price_high)
        liquidity_to_add = Balance.from_rao(
            int(tao_to_provide.rao / (sqrt_price_high - sqrt_price_low))
        )

    # Case 3: Current price is within range (both TAO and Alpha needed)
    else:
        console.print(
            f"\n[green]The current price ({current_price.tao:.6f}) is within the range ({price_low:.6f} - {price_high:.6f}).[/green]"
        )
        console.print(
            "[green]Both TAO and Alpha tokens are needed for this position.[/green]\n"
        )

        # Fetch TAO and Alpha balances
        with console.status(":satellite: Fetching balances...", spinner="aesthetic"):
            tao_balance_available, alpha_balance_available = await asyncio.gather(
                subtensor.get_balance(wallet.coldkeypub.ss58_address),
                subtensor.get_stake_for_coldkey_and_hotkey(
                    hotkey_ss58=hotkey_ss58,
                    coldkey_ss58=wallet.coldkeypub.ss58_address,
                    netuid=netuid,
                ),
            )

        # Calculate maximum liquidity
        max_liquidity, max_tao_needed, max_alpha_needed = (
            calculate_max_liquidity_from_balances(
                tao_balance=tao_balance_available,
                alpha_balance=alpha_balance_available,
                current_price=current_price,
                price_low=price_low_balance,
                price_high=price_high_balance,
            )
        )

        console.print(
            f"\n[cyan]Maximum liquidity that can be provided:[/cyan]\n"
            f"  TAO:   {max_tao_needed.tao:.6f} τ\n"
            f"  Alpha: {max_alpha_needed.tao:.6f} α (for subnet {netuid})\n"
        )

        # Determine which amount to use based on what was provided
        if tao_amount is not None and alpha_amount is not None:
            # Both provided - use TAO amount and calculate Alpha
            choice = "tao"
        elif tao_amount is not None:
            # Only TAO provided
            choice = "tao"
        elif alpha_amount is not None:
            # Only Alpha provided
            choice = "alpha"
        else:
            # Neither provided - ask user
            choice = Prompt.ask(
                f"[{COLORS.G.SUBHEAD_MAIN}]Enter 'tao' to specify TAO amount or 'alpha' to specify Alpha amount[/{COLORS.G.SUBHEAD_MAIN}]",
                choices=["tao", "alpha"],
                default="tao",
            )

        if choice == "tao":
            if tao_amount is None:
                tao_amount = FloatPrompt.ask(
                    f"[{COLORS.G.SUBHEAD_MAIN}]Enter the amount of TAO to provide (max: {max_tao_needed.tao:.6f})[/{COLORS.G.SUBHEAD_MAIN}]"
                )
            tao_to_provide = Balance.from_tao(tao_amount)

            # Calculate corresponding Alpha
            alpha_to_provide = calculate_alpha_from_tao(
                tao_amount=tao_to_provide,
                current_price=current_price,
                price_low=price_low_balance,
                price_high=price_high_balance,
            )

            console.print(
                f"[cyan]This will require {alpha_to_provide.tao:.6f} Alpha tokens[/cyan]"
            )

            # Check if user has enough balance
            if tao_to_provide > tao_balance_available:
                err_console.print(
                    f"[red]Insufficient TAO balance.[/red]\n"
                    f"Required: {tao_to_provide.tao:.6f} τ\n"
                    f"Available: {tao_balance_available.tao:.6f} τ"
                )
                return False, "Insufficient TAO balance."

            if alpha_to_provide > alpha_balance_available:
                err_console.print(
                    f"[red]Insufficient Alpha balance.[/red]\n"
                    f"Required: {alpha_to_provide.tao:.6f} α (for subnet {netuid})\n"
                    f"Available: {alpha_balance_available.tao:.6f} α (for subnet {netuid})"
                )
                return False, "Insufficient Alpha balance."

            # Calculate liquidity
            sqrt_current_price = math.sqrt(current_price.tao)
            sqrt_price_low = math.sqrt(price_low)
            liquidity_to_add = Balance.from_rao(
                int(tao_to_provide.rao / (sqrt_current_price - sqrt_price_low))
            )
        else:
            if alpha_amount is None:
                alpha_amount = FloatPrompt.ask(
                    f"[{COLORS.G.SUBHEAD_MAIN}]Enter the amount of Alpha to provide (max: {max_alpha_needed.tao:.6f})[/{COLORS.G.SUBHEAD_MAIN}]"
                )
            alpha_to_provide = Balance.from_tao(alpha_amount)

            # Calculate corresponding TAO
            tao_to_provide = calculate_tao_from_alpha(
                alpha_amount=alpha_to_provide,
                current_price=current_price,
                price_low=price_low_balance,
                price_high=price_high_balance,
            )

            console.print(
                f"[cyan]This will require {tao_to_provide.tao:.6f} TAO tokens[/cyan]"
            )

            # Check if user has enough balance
            if tao_to_provide > tao_balance_available:
                err_console.print(
                    f"[red]Insufficient TAO balance.[/red]\n"
                    f"Required: {tao_to_provide.tao:.6f} τ\n"
                    f"Available: {tao_balance_available.tao:.6f} τ"
                )
                return False, "Insufficient TAO balance."

            if alpha_to_provide > alpha_balance_available:
                err_console.print(
                    f"[red]Insufficient Alpha balance.[/red]\n"
                    f"Required: {alpha_to_provide.tao:.6f} α (for subnet {netuid})\n"
                    f"Available: {alpha_balance_available.tao:.6f} α (for subnet {netuid})"
                )
                return False, "Insufficient Alpha balance."

            # Calculate liquidity
            sqrt_current_price = math.sqrt(current_price.tao)
            sqrt_price_high = math.sqrt(price_high)
            liquidity_to_add = Balance.from_rao(
                int(
                    alpha_to_provide.rao
                    / (1 / sqrt_current_price - 1 / sqrt_price_high)
                )
            )

    # Step 6: Confirm and execute the extrinsic
    if prompt:
        console.print(
            "You are about to add a LiquidityPosition with:\n"
            f"\tTAO amount: {tao_to_provide.tao:.6f} τ\n"
            f"\tAlpha amount: {alpha_to_provide.tao:.6f} α (for subnet {netuid})\n"
            f"\tprice low: {price_low_balance}\n"
            f"\tprice high: {price_high_balance}\n"
            f"\tto SN: {netuid}\n"
            f"\tusing wallet with name: {wallet.name}"
        )

        if not Confirm.ask("Would you like to continue?"):
            return False, "User cancelled operation."

    # Unlock wallet before executing extrinsic
    if not (ulw := unlock_key(wallet)).success:
        return False, ulw.message

    success, message, ext_receipt = await add_liquidity_extrinsic(
        subtensor=subtensor,
        wallet=wallet,
        hotkey_ss58=hotkey_ss58,
        netuid=netuid,
        liquidity=liquidity_to_add,
        price_low=price_low_balance,
        price_high=price_high_balance,
    )

    ext_id = None
    if ext_receipt:
        await print_extrinsic_id(ext_receipt)
        ext_id = await ext_receipt.get_extrinsic_identifier()

    if json_output:
        json_console.print(
            json.dumps(
                {"success": success, "message": message, "extrinsic_identifier": ext_id}
            )
        )
    else:
        if success:
            console.print(
                "[green]LiquidityPosition has been successfully added.[/green]"
            )
        else:
            err_console.print(f"[red]Error: {message}[/red]")

    return success, message


async def get_liquidity_list(
    subtensor: "SubtensorInterface",
    wallet: "Wallet",
    netuid: Optional[int],
) -> tuple[bool, str, list]:
    """
    Args:
        wallet: wallet object
        subtensor: SubtensorInterface object
        netuid: the netuid to stake to (None indicates all subnets)

    Returns:
        Tuple of (success, error message, liquidity list)
    """

    if not await subtensor.subnet_exists(netuid=netuid):
        return False, f"Subnet with netuid: {netuid} does not exist in {subtensor}.", []

    if not await subtensor.is_subnet_active(netuid=netuid):
        return False, f"Subnet with netuid: {netuid} is not active in {subtensor}.", []

    block_hash = await subtensor.substrate.get_chain_head()
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
            block_hash=block_hash,
        ),
        subtensor.query(
            module="Swap",
            storage_function="FeeGlobalTao",
            params=[netuid],
            block_hash=block_hash,
        ),
        subtensor.query(
            module="Swap",
            storage_function="FeeGlobalAlpha",
            params=[netuid],
            block_hash=block_hash,
        ),
        subtensor.query(
            module="Swap",
            storage_function="AlphaSqrtPrice",
            params=[netuid],
            block_hash=block_hash,
        ),
    )
    if len(positions_response.records) == 0:
        return False, "No liquidity positions found.", []

    current_sqrt_price = fixed_to_float(current_sqrt_price)
    fee_global_tao = fixed_to_float(fee_global_tao)
    fee_global_alpha = fixed_to_float(fee_global_alpha)

    current_price = current_sqrt_price * current_sqrt_price
    current_tick = price_to_tick(current_price)

    preprocessed_positions = []
    positions_futures = []

    async for _, p in positions_response:
        position = p.value
        tick_index_low = position.get("tick_low")[0]
        tick_index_high = position.get("tick_high")[0]
        preprocessed_positions.append((position, tick_index_low, tick_index_high))

        # Get ticks for the position (for below/above fees)
        positions_futures.append(
            asyncio.gather(
                subtensor.query(
                    module="Swap",
                    storage_function="Ticks",
                    params=[netuid, tick_index_low],
                    block_hash=block_hash,
                ),
                subtensor.query(
                    module="Swap",
                    storage_function="Ticks",
                    params=[netuid, tick_index_high],
                    block_hash=block_hash,
                ),
            )
        )

    awaited_futures = await asyncio.gather(*positions_futures)

    positions = []

    for (position, tick_index_low, tick_index_high), (tick_low, tick_high) in zip(
        preprocessed_positions, awaited_futures
    ):
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

    return True, "", positions


async def show_liquidity_list(
    subtensor: "SubtensorInterface",
    wallet: "Wallet",
    netuid: int,
    json_output: bool = False,
) -> None:
    current_price_, liquidity_list_ = await asyncio.gather(
        subtensor.subnet(netuid=netuid),
        get_liquidity_list(subtensor, wallet, netuid),
        return_exceptions=True,
    )
    if isinstance(current_price_, Exception):
        success = False
        err_msg = str(current_price_)
        positions = []
    elif isinstance(liquidity_list_, Exception):
        success = False
        err_msg = str(liquidity_list_)
        positions = []
    else:
        (success, err_msg, positions) = liquidity_list_
    if not success:
        if json_output:
            json_console.print(
                json.dumps({"success": success, "err_msg": err_msg, "positions": []})
            )
            return
        else:
            err_console.print(f"Error: {err_msg}")
            return
    liquidity_table = Table(
        Column("ID", justify="center"),
        Column("Liquidity", justify="center"),
        Column("Alpha", justify="center"),
        Column("Tao", justify="center"),
        Column("Price low", justify="center"),
        Column("Price high", justify="center"),
        Column("Fee TAO", justify="center"),
        Column("Fee Alpha", justify="center"),
        title=f"\n[{COLORS.G.HEADER}]{'Liquidity Positions of '}{wallet.name} wallet in SN #{netuid}\n"
        "Alpha and Tao columns are respective portions of liquidity.",
        show_footer=False,
        show_edge=True,
        header_style="bold white",
        border_style="bright_black",
        style="bold",
        title_justify="center",
        show_lines=False,
        pad_edge=True,
    )
    json_table = []
    current_price = current_price_.price
    lp: LiquidityPosition
    for lp in positions:
        alpha, tao = lp.to_token_amounts(current_price)
        liquidity_table.add_row(
            str(lp.id),
            str(lp.liquidity.tao),
            str(alpha),
            str(tao),
            str(lp.price_low),
            str(lp.price_high),
            str(lp.fees_tao),
            str(lp.fees_alpha),
        )
        json_table.append(
            {
                "id": lp.id,
                "liquidity": lp.liquidity.tao,
                "token_amounts": {"alpha": alpha.tao, "tao": tao.tao},
                "price_low": lp.price_low.tao,
                "price_high": lp.price_high.tao,
                "fees_tao": lp.fees_tao.tao,
                "fees_alpha": lp.fees_alpha.tao,
                "netuid": lp.netuid,
            }
        )
    if not json_output:
        console.print(liquidity_table)
    else:
        json_console.print(
            json.dumps({"success": True, "err_msg": "", "positions": json_table})
        )


async def remove_liquidity(
    subtensor: "SubtensorInterface",
    wallet: "Wallet",
    hotkey_ss58: str,
    netuid: int,
    position_id: Optional[int] = None,
    prompt: Optional[bool] = None,
    all_liquidity_ids: Optional[bool] = None,
    json_output: bool = False,
) -> None:
    """Remove liquidity position from provided subnet."""
    if not await subtensor.subnet_exists(netuid=netuid):
        return None

    if all_liquidity_ids:
        success, msg, positions = await get_liquidity_list(subtensor, wallet, netuid)
        if not success:
            if json_output:
                json_console.print_json(
                    data={"success": False, "err_msg": msg, "positions": positions}
                )
            else:
                return err_console.print(f"Error: {msg}")
            return None
        else:
            position_ids = [p.id for p in positions]
    else:
        position_ids = [position_id]

    if prompt:
        console.print("You are about to remove LiquidityPositions with:")
        console.print(f"\tSubnet: {netuid}")
        console.print(f"\tWallet name: {wallet.name}")
        for pos in position_ids:
            console.print(f"\tPosition id: {pos}")

        if not Confirm.ask("Would you like to continue?"):
            return None

    results = await asyncio.gather(
        *[
            remove_liquidity_extrinsic(
                subtensor=subtensor,
                wallet=wallet,
                hotkey_ss58=hotkey_ss58,
                netuid=netuid,
                position_id=pos_id,
            )
            for pos_id in position_ids
        ]
    )
    if not json_output:
        for (success, msg, ext_receipt), posid in zip(results, position_ids):
            if success:
                await print_extrinsic_id(ext_receipt)
                console.print(f"[green] Position {posid} has been removed.")
            else:
                err_console.print(f"[red] Error removing {posid}: {msg}")
    else:
        json_table = {}
        for (success, msg, ext_receipt), posid in zip(results, position_ids):
            json_table[posid] = {
                "success": success,
                "err_msg": msg,
                "extrinsic_identifier": await ext_receipt.get_extrinsic_identifier(),
            }
        json_console.print_json(data=json_table)
    return None


async def modify_liquidity(
    subtensor: "SubtensorInterface",
    wallet: "Wallet",
    hotkey_ss58: str,
    netuid: int,
    position_id: int,
    liquidity_delta: Balance,
    prompt: Optional[bool] = None,
    json_output: bool = False,
) -> bool:
    """Modify liquidity position in provided subnet."""
    if not await subtensor.subnet_exists(netuid=netuid):
        err_msg = f"Subnet with netuid: {netuid} does not exist in {subtensor}."
        if json_output:
            json_console.print(json.dumps({"success": False, "err_msg": err_msg}))
        else:
            err_console.print(err_msg)
        return False

    if prompt:
        console.print(
            "You are about to modify a LiquidityPosition with:"
            f"\tSubnet: {netuid}\n"
            f"\tPosition id: {position_id}\n"
            f"\tWallet name: {wallet.name}\n"
            f"\tLiquidity delta: {liquidity_delta}"
        )

        if not Confirm.ask("Would you like to continue?"):
            return False

    success, msg, ext_receipt = await modify_liquidity_extrinsic(
        subtensor=subtensor,
        wallet=wallet,
        hotkey_ss58=hotkey_ss58,
        netuid=netuid,
        position_id=position_id,
        liquidity_delta=liquidity_delta,
    )
    if json_output:
        ext_id = await ext_receipt.get_extrinsic_identifier() if success else None
        json_console.print_json(
            data={"success": success, "err_msg": msg, "extrinsic_identifier": ext_id}
        )
    else:
        if success:
            await print_extrinsic_id(ext_receipt)
            console.print(f"[green] Position {position_id} has been modified.")
        else:
            err_console.print(f"[red] Error modifying {position_id}: {msg}")
    return success
