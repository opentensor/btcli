import asyncio
from functools import partial

import typer
from typing import TYPE_CHECKING, Optional
from rich.table import Table
from rich.prompt import Confirm

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
    prompt_stake_amount,
)
from bittensor_wallet import Wallet
from bittensor_wallet.errors import KeyFileError

if TYPE_CHECKING:
    from bittensor_cli.src.bittensor.subtensor_interface import SubtensorInterface


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


def define_stake_stable(wallet: Wallet, subtensor: "SubtensorInterface") -> Table:
    """Creates and initializes a table for displaying stake information.

    Args:
        wallet: The wallet being used for staking
        subtensor: The subtensor interface

    Returns:
        Table: An initialized rich Table object with appropriate columns
    """
    table = Table(
        title=f"\n[{COLOR_PALETTE['GENERAL']['HEADER']}]Staking to:\n"
        f"Wallet: [{COLOR_PALETTE['GENERAL']['COLDKEY']}]{wallet.name}[/{COLOR_PALETTE['GENERAL']['COLDKEY']}], "
        f"Coldkey ss58: [{COLOR_PALETTE['GENERAL']['COLDKEY']}]{wallet.coldkeypub.ss58_address}[/{COLOR_PALETTE['GENERAL']['COLDKEY']}]\n"
        f"Network: {subtensor.network}[/{COLOR_PALETTE['GENERAL']['HEADER']}]\n",
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
        "Slippage", justify="center", style=COLOR_PALETTE["STAKE"]["SLIPPAGE_PERCENT"]
    )

    return table


def print_table_and_slippage(table: Table, max_slippage: float):
    """Prints the stake table, slippage warning, and table description.

    Args:
        table: The rich Table object to print
        max_slippage: The maximum slippage percentage across all operations
    """
    console.print(table)

    # Greater than 5%
    if max_slippage > 5:
        message = f"[{COLOR_PALETTE['STAKE']['SLIPPAGE_TEXT']}]-------------------------------------------------------------------------------------------------------------------\n"
        message += f"[bold]WARNING:[/bold]  The slippage on one of your operations is high: [{COLOR_PALETTE['STAKE']['SLIPPAGE_PERCENT']}]{max_slippage} %[/{COLOR_PALETTE['STAKE']['SLIPPAGE_PERCENT']}], this may result in a loss of funds.\n"
        message += "-------------------------------------------------------------------------------------------------------------------\n"
        console.print(message)

    # Table description
    console.print(
        """
[bold white]Description[/bold white]:
The table displays information about the stake operation you are about to perform.
The columns are as follows:
    - [bold white]Netuid[/bold white]: The netuid of the subnet you are staking to.
    - [bold white]Hotkey[/bold white]: The ss58 address of the hotkey you are staking to. 
    - [bold white]Amount[/bold white]: The TAO you are staking into this subnet onto this hotkey.
    - [bold white]Rate[/bold white]: The rate of exchange between your TAO and the subnet's stake.
    - [bold white]Received[/bold white]: The amount of stake you will receive on this subnet after slippage.
    - [bold white]Slippage[/bold white]: The slippage percentage of the stake operation. (0% if the subnet is not dynamic i.e. root).
"""
    )


def calculate_slippage(
    subnet_info, amount: Balance
) -> tuple[Balance, str, float]:
    """Calculate slippage when adding stake.

    Args:
        subnet_info: Subnet dynamic info
        amount: Amount being staked

    Returns:
        tuple containing:
        - received_amount: Amount received after slippage
        - slippage_str: Formatted slippage percentage string
        - slippage_float: Raw slippage percentage value
    """
    received_amount, _, slippage_pct_float = subnet_info.tao_to_alpha_with_slippage(
        amount
    )
    if subnet_info.is_dynamic:
        slippage_str = f"{slippage_pct_float:.4f} %"
        rate = str(1 / (float(subnet_info.price) or 1))
    else:
        slippage_pct_float = 0
        slippage_str = f"[{COLOR_PALETTE['STAKE']['SLIPPAGE_TEXT']}]N/A[/{COLOR_PALETTE['STAKE']['SLIPPAGE_TEXT']}]"
        rate = str(1)

    return received_amount, slippage_str, slippage_pct_float, rate


async def stake_add(
    wallet: Wallet,
    subtensor: "SubtensorInterface",
    netuid: Optional[int],
    stake_all: bool,
    amount: float,
    prompt: bool,
    all_hotkeys: bool,
    include_hotkeys: list[str],
    exclude_hotkeys: list[str],
):
    """

    Args:
        wallet: wallet object
        subtensor: SubtensorInterface object
        netuid: the netuid to stake to (None indicates all subnets)
        stake_all: whether to stake all available balance
        amount: specified amount of balance to stake
        delegate: whether to delegate stake, currently unused
        prompt: whether to prompt the user
        max_stake: maximum amount to stake (used in combination with stake_all), currently unused
        all_hotkeys: whether to stake all hotkeys
        include_hotkeys: list of hotkeys to include in staking process (if not specifying `--all`)
        exclude_hotkeys: list of hotkeys to exclude in staking (if specifying `--all`)

    Returns:
        bool: True if stake operation is successful, False otherwise
    """

    async def send_stake_extrinsic(
        netuid_i, amount_, current, staking_address_ss58, status=None
    ):
        err_out = partial(print_error, status=status)
        failure_prelude = (
            f":cross_mark: [red]Failed[/red] to stake {amount} on Netuid {netuid_i}"
        )
        next_nonce = await subtensor.substrate.get_account_next_index(
            wallet.coldkeypub.ss58_address
        )
        call = await subtensor.substrate.compose_call(
            call_module="SubtensorModule",
            call_function="add_stake",
            call_params={
                "hotkey": staking_address_ss58,
                "netuid": netuid_i,
                "amount_staked": amount_.rao,
            },
        )
        extrinsic = await subtensor.substrate.create_signed_extrinsic(
            call=call, keypair=wallet.coldkey, nonce=next_nonce
        )
        try:
            response = await subtensor.substrate.submit_extrinsic(
                extrinsic, wait_for_inclusion=True, wait_for_finalization=False
            )
        except SubstrateRequestException as e:
            err_out(
                f"\n{failure_prelude} with error: {format_error_message(e, subtensor.substrate)}"
            )
            return
        else:
            await response.process_events()
            if not await response.is_success:
                err_out(
                    f"\n{failure_prelude} with error: {format_error_message(await response.error_message, subtensor.substrate)}"
                )
            else:
                new_balance, stake_info_dict = await asyncio.gather(
                    subtensor.get_balance(wallet.coldkeypub.ss58_address),
                    subtensor.get_stake_for_coldkey(
                        coldkey_ss58=wallet.coldkeypub.ss58_address,
                    ),
                )
                new_stake = Balance.from_rao(0)
                for stake_info in stake_info_dict:
                    if (
                        stake_info.hotkey_ss58 == staking_address_ss58
                        and stake_info.netuid == netuid_i
                    ):
                        new_stake = stake_info.stake.set_unit(netuid_i)
                        break
                console.print(
                    f":white_heavy_check_mark: [dark_sea_green3]Finalized. Stake added to netuid: {netuid_i}[/dark_sea_green3]"
                )
                console.print(
                    f"Balance:\n  [blue]{current_wallet_balance}[/blue] :arrow_right: [{COLOR_PALETTE['STAKE']['STAKE_AMOUNT']}]{new_balance}"
                )
                console.print(
                    f"Subnet: [{COLOR_PALETTE['GENERAL']['SUBHEADING']}]{netuid_i}[/{COLOR_PALETTE['GENERAL']['SUBHEADING']}] "
                    f"Stake:\n"
                    f"  [blue]{current}[/blue] "
                    f":arrow_right: "
                    f"[{COLOR_PALETTE['STAKE']['STAKE_AMOUNT']}]{new_stake}\n"
                )

    netuids = (
        [int(netuid)]
        if netuid is not None
        else await subtensor.get_all_subnet_netuids()
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
        subtensor.all_subnets(),
        subtensor.get_stake_for_coldkey(
            coldkey_ss58=wallet.coldkeypub.ss58_address,
            block_hash=chain_head,
        ),
        subtensor.get_balance(wallet.coldkeypub.ss58_address),
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
    remaining_wallet_balance = current_wallet_balance
    max_slippage = 0.0

    for hotkey in hotkeys_to_stake_to:
        for netuid in netuids:
            # Check that the subnet exists.
            dynamic_info = all_subnets.get(netuid)
            if not dynamic_info:
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
                amount_to_stake, _ = prompt_stake_amount(
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

            # Calculate slippage
            received_amount, slippage_pct, slippage_pct_float, rate = (
                calculate_slippage(dynamic_info, amount_to_stake)
            )
            max_slippage = max(slippage_pct_float, max_slippage)

            # Add rows for the table
            rows.append(
                (
                    str(netuid),
                    f"{hotkey[1]}",
                    str(amount_to_stake),
                    rate + f" {Balance.get_unit(netuid)}/{Balance.get_unit(0)} ",
                    str(received_amount.set_unit(netuid)),
                    str(slippage_pct),
                )
            )

    # Define and print stake table + slippage warning
    table = define_stake_stable(wallet, subtensor)
    for row in rows:
        table.add_row(*row)
    print_table_and_slippage(table, max_slippage)

    if prompt:
        if not Confirm.ask("Would you like to continue?"):
            raise typer.Exit()

    # Perform staking operation.
    try:
        wallet.unlock_coldkey()
    except KeyFileError:
        err_console.print("Error decrypting coldkey (possibly incorrect password)")
        return False

    stake_coroutines = [
        send_stake_extrinsic(ni, am, curr, staking_address)
        for i, (ni, am, curr) in enumerate(
            zip(netuids, amounts_to_stake, current_stake_balances)
        )
        for _, staking_address in hotkeys_to_stake_to
    ]
    await asyncio.gather(*stake_coroutines)
