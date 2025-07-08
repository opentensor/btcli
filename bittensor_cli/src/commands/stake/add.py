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
async def stake_add(
    wallet: Wallet,
    subtensor: "SubtensorInterface",
    netuids: Optional[list[int]],
    stake_all: bool,
    amount: float,
    prompt: bool,
    all_hotkeys: bool,
    include_hotkeys: list[str],
    exclude_hotkeys: list[str],
    safe_staking: bool,
    rate_tolerance: float,
    allow_partial_stake: bool,
    json_output: bool,
    era: int,
):
    """
    Args:
        wallet: wallet object
        subtensor: SubtensorInterface object
        netuids: the netuids to stake to (None indicates all subnets)
        stake_all: whether to stake all available balance
        amount: specified amount of balance to stake
        prompt: whether to prompt the user
        all_hotkeys: whether to stake all hotkeys
        include_hotkeys: list of hotkeys to include in staking process (if not specifying `--all`)
        exclude_hotkeys: list of hotkeys to exclude in staking (if specifying `--all`)
        safe_staking: whether to use safe staking
        rate_tolerance: rate tolerance percentage for stake operations
        allow_partial_stake: whether to allow partial stake
        json_output: whether to output stake info in JSON format
        era: Blocks for which the transaction should be valid.

    Returns:
        bool: True if stake operation is successful, False otherwise
    """

    async def safe_stake_extrinsic(
        netuid_: int,
        amount_: Balance,
        current_stake: Balance,
        hotkey_ss58_: str,
        price_limit: Balance,
        status=None,
    ) -> tuple[bool, str]:
        err_out = partial(print_error, status=status)
        failure_prelude = (
            f":cross_mark: [red]Failed[/red] to stake {amount_} on Netuid {netuid_}"
        )
        current_balance, next_nonce, call = await asyncio.gather(
            subtensor.get_balance(wallet.coldkeypub.ss58_address),
            subtensor.substrate.get_account_next_index(wallet.coldkeypub.ss58_address),
            subtensor.substrate.compose_call(
                call_module="SubtensorModule",
                call_function="add_stake_limit",
                call_params={
                    "hotkey": hotkey_ss58_,
                    "netuid": netuid_,
                    "amount_staked": amount_.rao,
                    "limit_price": price_limit,
                    "allow_partial": allow_partial_stake,
                },
            ),
        )
        extrinsic = await subtensor.substrate.create_signed_extrinsic(
            call=call,
            keypair=wallet.coldkey,
            nonce=next_nonce,
            era={"period": era},
        )
        try:
            response = await subtensor.substrate.submit_extrinsic(
                extrinsic, wait_for_inclusion=True, wait_for_finalization=False
            )
        except SubstrateRequestException as e:
            if "Custom error: 8" in str(e):
                err_msg = (
                    f"{failure_prelude}: Price exceeded tolerance limit. "
                    f"Transaction rejected because partial staking is disabled. "
                    f"Either increase price tolerance or enable partial staking."
                )
                print_error("\n" + err_msg, status=status)
            else:
                err_msg = f"{failure_prelude} with error: {format_error_message(e)}"
                err_out("\n" + err_msg)
            return False, err_msg
        if not await response.is_success:
            err_msg = f"{failure_prelude} with error: {format_error_message(await response.error_message)}"
            err_out("\n" + err_msg)
            return False, err_msg
        else:
            if json_output:
                # the rest of this checking is not necessary if using json_output
                return True, ""
            block_hash = await subtensor.substrate.get_chain_head()
            new_balance, new_stake = await asyncio.gather(
                subtensor.get_balance(wallet.coldkeypub.ss58_address, block_hash),
                subtensor.get_stake(
                    hotkey_ss58=hotkey_ss58_,
                    coldkey_ss58=wallet.coldkeypub.ss58_address,
                    netuid=netuid_,
                    block_hash=block_hash,
                ),
            )
            console.print(
                f":white_heavy_check_mark: [dark_sea_green3]Finalized. "
                f"Stake added to netuid: {netuid_}[/dark_sea_green3]"
            )
            console.print(
                f"Balance:\n  [blue]{current_balance}[/blue] :arrow_right: "
                f"[{COLOR_PALETTE['STAKE']['STAKE_AMOUNT']}]{new_balance}"
            )

            amount_staked = current_balance - new_balance
            if allow_partial_stake and (amount_staked != amount_):
                console.print(
                    "Partial stake transaction. Staked:\n"
                    f"  [{COLOR_PALETTE['STAKE']['STAKE_AMOUNT']}]{amount_staked}"
                    f"[/{COLOR_PALETTE['STAKE']['STAKE_AMOUNT']}] "
                    f"instead of "
                    f"[blue]{amount_}[/blue]"
                )

            console.print(
                f"Subnet: [{COLOR_PALETTE['GENERAL']['SUBHEADING']}]"
                f"{netuid_}[/{COLOR_PALETTE['GENERAL']['SUBHEADING']}] "
                f"Stake:\n"
                f"  [blue]{current_stake}[/blue] "
                f":arrow_right: "
                f"[{COLOR_PALETTE['STAKE']['STAKE_AMOUNT']}]{new_stake}\n"
            )
            return True, ""

    async def stake_extrinsic(
        netuid_i, amount_, current, staking_address_ss58, status=None
    ) -> tuple[bool, str]:
        err_out = partial(print_error, status=status)
        current_balance, next_nonce, call = await asyncio.gather(
            subtensor.get_balance(wallet.coldkeypub.ss58_address),
            subtensor.substrate.get_account_next_index(wallet.coldkeypub.ss58_address),
            subtensor.substrate.compose_call(
                call_module="SubtensorModule",
                call_function="add_stake",
                call_params={
                    "hotkey": staking_address_ss58,
                    "netuid": netuid_i,
                    "amount_staked": amount_.rao,
                },
            ),
        )
        failure_prelude = (
            f":cross_mark: [red]Failed[/red] to stake {amount} on Netuid {netuid_i}"
        )
        extrinsic = await subtensor.substrate.create_signed_extrinsic(
            call=call, keypair=wallet.coldkey, nonce=next_nonce, era={"period": era}
        )
        try:
            response = await subtensor.substrate.submit_extrinsic(
                extrinsic, wait_for_inclusion=True, wait_for_finalization=False
            )
        except SubstrateRequestException as e:
            err_msg = f"{failure_prelude} with error: {format_error_message(e)}"
            err_out("\n" + err_msg)
            return False, err_msg
        else:
            if not await response.is_success:
                err_msg = f"{failure_prelude} with error: {format_error_message(await response.error_message)}"
                err_out("\n" + err_msg)
                return False, err_msg
            else:
                if json_output:
                    # the rest of this is not necessary if using json_output
                    return True, ""
                new_block_hash = await subtensor.substrate.get_chain_head()
                new_balance, new_stake = await asyncio.gather(
                    subtensor.get_balance(
                        wallet.coldkeypub.ss58_address, block_hash=new_block_hash
                    ),
                    subtensor.get_stake(
                        hotkey_ss58=staking_address_ss58,
                        coldkey_ss58=wallet.coldkeypub.ss58_address,
                        netuid=netuid_i,
                        block_hash=new_block_hash,
                    ),
                )
                console.print(
                    f":white_heavy_check_mark: "
                    f"[dark_sea_green3]Finalized. Stake added to netuid: {netuid_i}[/dark_sea_green3]"
                )
                console.print(
                    f"Balance:\n  [blue]{current_balance}[/blue] :arrow_right: "
                    f"[{COLOR_PALETTE['STAKE']['STAKE_AMOUNT']}]{new_balance}"
                )
                console.print(
                    f"Subnet: [{COLOR_PALETTE['GENERAL']['SUBHEADING']}]"
                    f"{netuid_i}[/{COLOR_PALETTE['GENERAL']['SUBHEADING']}] "
                    f"Stake:\n"
                    f"  [blue]{current}[/blue] "
                    f":arrow_right: "
                    f"[{COLOR_PALETTE['STAKE']['STAKE_AMOUNT']}]{new_stake}\n"
                )
                return True, ""

    netuids = (
        netuids if netuids is not None else await subtensor.get_all_subnet_netuids()
    )

    hotkeys_to_stake_to = _get_hotkeys_to_stake_to(
        wallet=wallet,
        all_hotkeys=all_hotkeys,
        include_hotkeys=include_hotkeys,
        exclude_hotkeys=exclude_hotkeys,
    )

    # Get subnet data and stake information for coldkey
    chain_head = await subtensor.substrate.get_chain_head()
    _all_subnets, _stake_info, current_wallet_balance = await asyncio.gather(
        subtensor.all_subnets(block_hash=chain_head),
        subtensor.get_stake_for_coldkey(
            coldkey_ss58=wallet.coldkeypub.ss58_address,
            block_hash=chain_head,
        ),
        subtensor.get_balance(wallet.coldkeypub.ss58_address, block_hash=chain_head),
    )
    all_subnets = {di.netuid: di for di in _all_subnets}

    # Map current stake balances for hotkeys
    hotkey_stake_map = {}
    for _, hotkey_ss58 in hotkeys_to_stake_to:
        hotkey_stake_map[hotkey_ss58] = {}
        for netuid in netuids:
            hotkey_stake_map[hotkey_ss58][netuid] = Balance.from_rao(0)

    for stake_info in _stake_info:
        if stake_info.hotkey_ss58 in hotkey_stake_map:
            hotkey_stake_map[stake_info.hotkey_ss58][stake_info.netuid] = (
                stake_info.stake
            )

    # Determine the amount we are staking.
    rows = []
    amounts_to_stake = []
    current_stake_balances = []
    prices_with_tolerance = []
    remaining_wallet_balance = current_wallet_balance
    max_slippage = 0.0

    for hotkey in hotkeys_to_stake_to:
        for netuid in netuids:
            # Check that the subnet exists.
            subnet_info = all_subnets.get(netuid)
            if not subnet_info:
                err_console.print(f"Subnet with netuid: {netuid} does not exist.")
                continue
            current_stake_balances.append(hotkey_stake_map[hotkey[1]][netuid])

            # Get the amount.
            amount_to_stake = Balance(0)
            if amount:
                amount_to_stake = Balance.from_tao(amount)
            elif stake_all:
                amount_to_stake = current_wallet_balance / len(netuids)
            elif not amount:
                amount_to_stake, _ = _prompt_stake_amount(
                    current_balance=remaining_wallet_balance,
                    netuid=netuid,
                    action_name="stake",
                )
            amounts_to_stake.append(amount_to_stake)

            # Check enough to stake.
            if amount_to_stake > remaining_wallet_balance:
                err_console.print(
                    f"[red]Not enough stake[/red]:[bold white]\n wallet balance:{remaining_wallet_balance} < "
                    f"staking amount: {amount_to_stake}[/bold white]"
                )
                return False
            remaining_wallet_balance -= amount_to_stake

            # TODO this should be asyncio gathered before the for loop
            stake_fee = await subtensor.get_stake_fee(
                origin_hotkey_ss58=None,
                origin_netuid=None,
                origin_coldkey_ss58=wallet.coldkeypub.ss58_address,
                destination_hotkey_ss58=hotkey[1],
                destination_netuid=netuid,
                destination_coldkey_ss58=wallet.coldkeypub.ss58_address,
                amount=amount_to_stake.rao,
            )

            # Calculate slippage
            # TODO: Update for V3, slippage calculation is significantly different in v3
            # try:
            #     received_amount, slippage_pct, slippage_pct_float, rate = (
            #         _calculate_slippage(subnet_info, amount_to_stake, stake_fee)
            #     )
            # except ValueError:
            #     return False
            #
            # max_slippage = max(slippage_pct_float, max_slippage)

            # Temporary workaround - calculations without slippage
            current_price_float = float(subnet_info.price.tao)
            rate = 1.0 / current_price_float
            received_amount = rate * amount_to_stake

            # Add rows for the table
            base_row = [
                str(netuid),  # netuid
                f"{hotkey[1]}",  # hotkey
                str(amount_to_stake),  # amount
                str(rate)
                + f" {Balance.get_unit(netuid)}/{Balance.get_unit(0)} ",  # rate
                str(received_amount.set_unit(netuid)),  # received
                str(stake_fee),  # fee
                # str(slippage_pct),  # slippage
            ]

            # If we are staking safe, add price tolerance
            if safe_staking:
                if subnet_info.is_dynamic:
                    price_with_tolerance = current_price_float * (1 + rate_tolerance)
                    _rate_with_tolerance = (
                        1.0 / price_with_tolerance
                    )  # Rate only for display
                    rate_with_tolerance = f"{_rate_with_tolerance:.4f}"
                    price_with_tolerance = Balance.from_tao(
                        price_with_tolerance
                    ).rao  # Actual price to pass to extrinsic
                else:
                    rate_with_tolerance = "1"
                    price_with_tolerance = Balance.from_rao(1)
                prices_with_tolerance.append(price_with_tolerance)

                base_row.extend(
                    [
                        f"{rate_with_tolerance} {Balance.get_unit(netuid)}/{Balance.get_unit(0)} ",
                        f"[{'dark_sea_green3' if allow_partial_stake else 'red'}]"
                        # safe staking
                        f"{allow_partial_stake}[/{'dark_sea_green3' if allow_partial_stake else 'red'}]",
                    ]
                )

            rows.append(tuple(base_row))

    # Define and print stake table + slippage warning
    table = _define_stake_table(wallet, subtensor, safe_staking, rate_tolerance)
    for row in rows:
        table.add_row(*row)
    _print_table_and_slippage(table, max_slippage, safe_staking)

    if prompt:
        if not Confirm.ask("Would you like to continue?"):
            return False
    if not unlock_key(wallet).success:
        return False

    if safe_staking:
        stake_coroutines = {}
        for i, (ni, am, curr, price_with_tolerance) in enumerate(
            zip(
                netuids, amounts_to_stake, current_stake_balances, prices_with_tolerance
            )
        ):
            for _, staking_address in hotkeys_to_stake_to:
                # Regular extrinsic for root subnet
                if ni == 0:
                    stake_coroutines[(ni, staking_address)] = stake_extrinsic(
                        netuid_i=ni,
                        amount_=am,
                        current=curr,
                        staking_address_ss58=staking_address,
                    )
                else:
                    stake_coroutines[(ni, staking_address)] = safe_stake_extrinsic(
                        netuid_=ni,
                        amount_=am,
                        current_stake=curr,
                        hotkey_ss58_=staking_address,
                        price_limit=price_with_tolerance,
                    )
    else:
        stake_coroutines = {
            (ni, staking_address): stake_extrinsic(
                netuid_i=ni,
                amount_=am,
                current=curr,
                staking_address_ss58=staking_address,
            )
            for i, (ni, am, curr) in enumerate(
                zip(netuids, amounts_to_stake, current_stake_balances)
            )
            for _, staking_address in hotkeys_to_stake_to
        }
    successes = defaultdict(dict)
    error_messages = defaultdict(dict)
    with console.status(f"\n:satellite: Staking on netuid(s): {netuids} ..."):
        # We can gather them all at once but balance reporting will be in race-condition.
        for (ni, staking_address), coroutine in stake_coroutines.items():
            success, er_msg = await coroutine
            successes[ni][staking_address] = success
            error_messages[ni][staking_address] = er_msg
    if json_output:
        json_console.print(
            json.dumps({"staking_success": successes, "error_messages": error_messages})
        )


# Helper functions
def _prompt_stake_amount(
    current_balance: Balance, netuid: int, action_name: str
) -> tuple[Balance, bool]:
    """Prompts user to input a stake amount with validation.

    Args:
        current_balance (Balance): The maximum available balance
        netuid (int): The subnet id to get the correct unit
        action_name (str): The name of the action (e.g. "transfer", "move", "unstake")

    Returns:
        tuple[Balance, bool]: (The amount to use as Balance object, whether all balance was selected)
    """
    while True:
        amount_input = Prompt.ask(
            f"\nEnter the amount to {action_name}"
            f"[{COLOR_PALETTE.S.STAKE_AMOUNT}]{Balance.get_unit(netuid)}[/{COLOR_PALETTE.S.STAKE_AMOUNT}] "
            f"[{COLOR_PALETTE.S.STAKE_AMOUNT}](max: {current_balance})[/{COLOR_PALETTE.S.STAKE_AMOUNT}] "
            f"or "
            f"[{COLOR_PALETTE.S.STAKE_AMOUNT}]'all'[/{COLOR_PALETTE.S.STAKE_AMOUNT}] "
            f"for entire balance"
        )

        if amount_input.lower() == "all":
            return current_balance, True

        try:
            amount = float(amount_input)
            if amount <= 0:
                console.print("[red]Amount must be greater than 0[/red]")
                continue
            if amount > current_balance.tao:
                console.print(
                    f"[red]Amount exceeds available balance of "
                    f"[{COLOR_PALETTE.S.STAKE_AMOUNT}]{current_balance}[/{COLOR_PALETTE.S.STAKE_AMOUNT}]"
                    f"[/red]"
                )
                continue
            return Balance.from_tao(amount), False
        except ValueError:
            console.print("[red]Please enter a valid number or 'all'[/red]")


def _get_hotkeys_to_stake_to(
    wallet: Wallet,
    all_hotkeys: bool = False,
    include_hotkeys: list[str] = None,
    exclude_hotkeys: list[str] = None,
) -> list[tuple[Optional[str], str]]:
    """Get list of hotkeys to stake to based on input parameters.

    Args:
        wallet: The wallet containing hotkeys
        all_hotkeys: If True, get all hotkeys from wallet except excluded ones
        include_hotkeys: List of specific hotkeys to include (by name or ss58 address)
        exclude_hotkeys: List of hotkeys to exclude when all_hotkeys is True

    Returns:
        List of tuples containing (hotkey_name, hotkey_ss58_address)
        hotkey_name may be None if ss58 address was provided directly
    """
    if all_hotkeys:
        # Stake to all hotkeys except excluded ones
        all_hotkeys_: list[Wallet] = get_hotkey_wallets_for_wallet(wallet=wallet)
        return [
            (wallet.hotkey_str, wallet.hotkey.ss58_address)
            for wallet in all_hotkeys_
            if wallet.hotkey_str not in (exclude_hotkeys or [])
        ]

    if include_hotkeys:
        print_verbose("Staking to only included hotkeys")
        # Stake to specific hotkeys
        hotkeys = []
        for hotkey_ss58_or_hotkey_name in include_hotkeys:
            if is_valid_ss58_address(hotkey_ss58_or_hotkey_name):
                # If valid ss58 address, add directly
                hotkeys.append((None, hotkey_ss58_or_hotkey_name))
            else:
                # If hotkey name, get ss58 from wallet
                wallet_ = Wallet(
                    path=wallet.path,
                    name=wallet.name,
                    hotkey=hotkey_ss58_or_hotkey_name,
                )
                hotkeys.append((wallet_.hotkey_str, wallet_.hotkey.ss58_address))

        return hotkeys

    # Default: stake to single hotkey from wallet
    print_verbose(
        f"Staking to hotkey: ({wallet.hotkey_str}) in wallet: ({wallet.name})"
    )
    assert wallet.hotkey is not None
    return [(None, wallet.hotkey.ss58_address)]


def _define_stake_table(
    wallet: Wallet,
    subtensor: "SubtensorInterface",
    safe_staking: bool,
    rate_tolerance: float,
) -> Table:
    """Creates and initializes a table for displaying stake information.

    Args:
        wallet: The wallet being used for staking
        subtensor: The subtensor interface

    Returns:
        Table: An initialized rich Table object with appropriate columns
    """
    table = Table(
        title=f"\n[{COLOR_PALETTE.G.HEADER}]Staking to:\n"
        f"Wallet: [{COLOR_PALETTE.G.CK}]{wallet.name}[/{COLOR_PALETTE.G.CK}], "
        f"Coldkey ss58: [{COLOR_PALETTE.G.CK}]{wallet.coldkeypub.ss58_address}[/{COLOR_PALETTE.G.CK}]\n"
        f"Network: {subtensor.network}[/{COLOR_PALETTE.G.HEADER}]\n",
        show_footer=True,
        show_edge=False,
        header_style="bold white",
        border_style="bright_black",
        style="bold",
        title_justify="center",
        show_lines=False,
        pad_edge=True,
    )

    table.add_column("Netuid", justify="center", style="grey89")
    table.add_column(
        "Hotkey", justify="center", style=COLOR_PALETTE["GENERAL"]["HOTKEY"]
    )
    table.add_column(
        f"Amount ({Balance.get_unit(0)})",
        justify="center",
        style=COLOR_PALETTE["POOLS"]["TAO"],
    )
    table.add_column(
        f"Rate (per {Balance.get_unit(0)})",
        justify="center",
        style=COLOR_PALETTE["POOLS"]["RATE"],
    )
    table.add_column(
        "Received",
        justify="center",
        style=COLOR_PALETTE["POOLS"]["TAO_EQUIV"],
    )
    table.add_column(
        "Fee (τ)",
        justify="center",
        style=COLOR_PALETTE["STAKE"]["STAKE_AMOUNT"],
    )
    # TODO: Uncomment when slippage is reimplemented for v3
    # table.add_column(
    #     "Slippage", justify="center", style=COLOR_PALETTE["STAKE"]["SLIPPAGE_PERCENT"]
    # )

    if safe_staking:
        table.add_column(
            f"Rate with tolerance: [blue]({rate_tolerance * 100}%)[/blue]",
            justify="center",
            style=COLOR_PALETTE["POOLS"]["RATE"],
        )
        table.add_column(
            "Partial stake enabled",
            justify="center",
            style=COLOR_PALETTE["STAKE"]["SLIPPAGE_PERCENT"],
        )
    return table


def _print_table_and_slippage(table: Table, max_slippage: float, safe_staking: bool):
    """Prints the stake table, slippage warning, and table description.

    Args:
        table: The rich Table object to print
        max_slippage: The maximum slippage percentage across all operations
    """
    console.print(table)

    # Greater than 5%
    if max_slippage > 5:
        message = (
            f"[{COLOR_PALETTE.S.SLIPPAGE_TEXT}]" + ("-" * 115) + "\n"
            f"[bold]WARNING:[/bold]  The slippage on one of your operations is high: "
            f"[{COLOR_PALETTE.S.SLIPPAGE_PERCENT}]{max_slippage} %[/{COLOR_PALETTE.S.SLIPPAGE_PERCENT}], "
            f"this may result in a loss of funds.\n" + ("-" * 115) + "\n"
        )

        console.print(message)

    # Table description
    base_description = """
[bold white]Description[/bold white]:
The table displays information about the stake operation you are about to perform.
The columns are as follows:
    - [bold white]Netuid[/bold white]: The netuid of the subnet you are staking to.
    - [bold white]Hotkey[/bold white]: The ss58 address of the hotkey you are staking to. 
    - [bold white]Amount[/bold white]: The TAO you are staking into this subnet onto this hotkey.
    - [bold white]Rate[/bold white]: The rate of exchange between your TAO and the subnet's stake.
    - [bold white]Received[/bold white]: The amount of stake you will receive on this subnet after slippage."""
    # - [bold white]Slippage[/bold white]: The slippage percentage of the stake operation. (0% if the subnet is not dynamic i.e. root)."""

    safe_staking_description = """
    - [bold white]Rate Tolerance[/bold white]: Maximum acceptable alpha rate. If the rate exceeds this tolerance, the transaction will be limited or rejected.
    - [bold white]Partial staking[/bold white]: If True, allows staking up to the rate tolerance limit. If False, the entire transaction will fail if rate tolerance is exceeded.\n"""

    console.print(base_description + (safe_staking_description if safe_staking else ""))


def _calculate_slippage(
    subnet_info, amount: Balance, stake_fee: Balance
) -> tuple[Balance, str, float, str]:
    """Calculate slippage when adding stake.

    Args:
        subnet_info: Subnet dynamic info
        amount: Amount being staked
        stake_fee: Transaction fee for the stake operation

    Returns:
        tuple containing:
        - received_amount: Amount received after slippage and fees
        - slippage_str: Formatted slippage percentage string
        - slippage_float: Raw slippage percentage value
        - rate: Exchange rate string

    TODO: Update to v3. This method only works for protocol-liquidity-only
          mode (user liquidity disabled)
    """
    amount_after_fee = amount - stake_fee

    if amount_after_fee < 0:
        print_error("You don't have enough balance to cover the stake fee.")
        raise ValueError()

    received_amount, _, _ = subnet_info.tao_to_alpha_with_slippage(amount_after_fee)

    if subnet_info.is_dynamic:
        ideal_amount = subnet_info.tao_to_alpha(amount)
        total_slippage = ideal_amount - received_amount
        slippage_pct_float = 100 * (total_slippage.tao / ideal_amount.tao)
        slippage_str = f"{slippage_pct_float:.4f} %"
        rate = f"{(1 / subnet_info.price.tao or 1):.4f}"
    else:
        # TODO: Fix this. Slippage is always zero for static networks.
        slippage_pct_float = (
            100 * float(stake_fee.tao) / float(amount.tao) if amount.tao != 0 else 0
        )
        slippage_str = f"{slippage_pct_float:.4f} %"
        rate = "1"

    return received_amount, slippage_str, slippage_pct_float, rate
