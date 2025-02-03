import asyncio
from functools import partial

from typing import TYPE_CHECKING, Optional
import typer

from bittensor_wallet import Wallet
from bittensor_wallet.errors import KeyFileError
from rich.prompt import Confirm, FloatPrompt, Prompt
from rich.table import Table
from rich import box
from rich.progress import Progress, BarColumn, TextColumn
from rich.console import Group
from rich.live import Live
from substrateinterface.exceptions import SubstrateRequestException

from bittensor_cli.src import COLOR_PALETTE
from bittensor_cli.src.bittensor.balances import Balance
from bittensor_cli.src.bittensor.chain_data import StakeInfo
from bittensor_cli.src.bittensor.utils import (
    # TODO add back in caching
    console,
    err_console,
    print_verbose,
    print_error,
    get_hotkey_wallets_for_wallet,
    is_valid_ss58_address,
    format_error_message,
    group_subnets,
    millify_tao,
    get_subnet_name,
)

if TYPE_CHECKING:
    from bittensor_cli.src.bittensor.subtensor_interface import SubtensorInterface


async def stake_add(
    wallet: Wallet,
    subtensor: "SubtensorInterface",
    netuid: Optional[int],
    stake_all: bool,
    amount: float,
    delegate: bool,
    prompt: bool,
    max_stake: float,
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

    """
    netuids = (
        [int(netuid)]
        if netuid is not None
        else await subtensor.get_all_subnet_netuids()
    )
    # Init the table.
    table = Table(
        title=f"\n[{COLOR_PALETTE['GENERAL']['HEADER']}]Staking to: \nWallet: [{COLOR_PALETTE['GENERAL']['COLDKEY']}]{wallet.name}[/{COLOR_PALETTE['GENERAL']['COLDKEY']}], Coldkey ss58: [{COLOR_PALETTE['GENERAL']['COLDKEY']}]{wallet.coldkeypub.ss58_address}[/{COLOR_PALETTE['GENERAL']['COLDKEY']}]\nNetwork: {subtensor.network}[/{COLOR_PALETTE['GENERAL']['HEADER']}]\n",
        show_footer=True,
        show_edge=False,
        header_style="bold white",
        border_style="bright_black",
        style="bold",
        title_justify="center",
        show_lines=False,
        pad_edge=True,
    )

    # Determine the amount we are staking.
    rows = []
    stake_amount_balance = []
    current_stake_balances = []
    current_wallet_balance_ = await subtensor.get_balance(
        wallet.coldkeypub.ss58_address
    )
    current_wallet_balance = current_wallet_balance_[
        wallet.coldkeypub.ss58_address
    ].set_unit(0)
    remaining_wallet_balance = current_wallet_balance
    max_slippage = 0.0

    hotkeys_to_stake_to: list[tuple[Optional[str], str]] = []
    if all_hotkeys:
        # Stake to all hotkeys.
        all_hotkeys_: list[Wallet] = get_hotkey_wallets_for_wallet(wallet=wallet)
        # Get the hotkeys to exclude. (d)efault to no exclusions.
        # Exclude hotkeys that are specified.
        hotkeys_to_stake_to = [
            (wallet.hotkey_str, wallet.hotkey.ss58_address)
            for wallet in all_hotkeys_
            if wallet.hotkey_str not in exclude_hotkeys
        ]  # definitely wallets

    elif include_hotkeys:
        print_verbose("Staking to only included hotkeys")
        # Stake to specific hotkeys.
        for hotkey_ss58_or_hotkey_name in include_hotkeys:
            if is_valid_ss58_address(hotkey_ss58_or_hotkey_name):
                # If the hotkey is a valid ss58 address, we add it to the list.
                hotkeys_to_stake_to.append((None, hotkey_ss58_or_hotkey_name))
            else:
                # If the hotkey is not a valid ss58 address, we assume it is a hotkey name.
                #  We then get the hotkey from the wallet and add it to the list.
                wallet_ = Wallet(
                    path=wallet.path,
                    name=wallet.name,
                    hotkey=hotkey_ss58_or_hotkey_name,
                )
                hotkeys_to_stake_to.append(
                    (wallet_.hotkey_str, wallet_.hotkey.ss58_address)
                )
    else:
        # Only config.wallet.hotkey is specified.
        #  so we stake to that single hotkey.
        print_verbose(
            f"Staking to hotkey: ({wallet.hotkey_str}) in wallet: ({wallet.name})"
        )
        assert wallet.hotkey is not None
        hotkey_ss58_or_name = wallet.hotkey.ss58_address
        hotkeys_to_stake_to = [(None, hotkey_ss58_or_name)]

    starting_chain_head = await subtensor.substrate.get_chain_head()
    _all_dynamic_info, stake_info_dict = await asyncio.gather(
        subtensor.all_subnets(),
        subtensor.get_stake_for_coldkeys(
            coldkey_ss58_list=[wallet.coldkeypub.ss58_address],
            block_hash=starting_chain_head,
        ),
    )
    all_dynamic_info = {di.netuid: di for di in _all_dynamic_info}
    initial_stake_balances = {}
    for hotkey_ss58 in [x[1] for x in hotkeys_to_stake_to]:
        initial_stake_balances[hotkey_ss58] = {}
        for netuid in netuids:
            initial_stake_balances[hotkey_ss58][netuid] = Balance.from_rao(0)

    for stake_info in stake_info_dict[wallet.coldkeypub.ss58_address]:
        if stake_info.hotkey_ss58 in initial_stake_balances:
            initial_stake_balances[stake_info.hotkey_ss58][stake_info.netuid] = (
                stake_info.stake
            )

    for hk_name, hk_ss58 in hotkeys_to_stake_to:
        if not is_valid_ss58_address(hk_ss58):
            print_error(
                f"The entered hotkey ss58 address is incorrect: {hk_name} | {hk_ss58}"
            )
            return False
    for hotkey in hotkeys_to_stake_to:
        for netuid in netuids:
            # Check that the subnet exists.
            dynamic_info = all_dynamic_info.get(netuid)
            if not dynamic_info:
                err_console.print(f"Subnet with netuid: {netuid} does not exist.")
                continue
            current_stake_balances.append(initial_stake_balances[hotkey[1]][netuid])

            # Get the amount.
            amount_to_stake_as_balance = Balance(0)
            if amount:
                amount_to_stake_as_balance = Balance.from_tao(amount)
            elif stake_all:
                amount_to_stake_as_balance = current_wallet_balance / len(netuids)
            elif not amount and not max_stake:
                if Confirm.ask(f"Stake all: [bold]{remaining_wallet_balance}[/bold]?"):
                    amount_to_stake_as_balance = remaining_wallet_balance
                else:
                    try:
                        amount = FloatPrompt.ask(
                            f"Enter amount to stake in {Balance.get_unit(0)} to subnet: {netuid}"
                        )
                        amount_to_stake_as_balance = Balance.from_tao(amount)
                    except ValueError:
                        err_console.print(
                            f":cross_mark:[red]Invalid amount: {amount}[/red]"
                        )
                        return False
            stake_amount_balance.append(amount_to_stake_as_balance)

            # Check enough to stake.
            amount_to_stake_as_balance.set_unit(0)
            if amount_to_stake_as_balance > remaining_wallet_balance:
                err_console.print(
                    f"[red]Not enough stake[/red]:[bold white]\n wallet balance:{remaining_wallet_balance} < "
                    f"staking amount: {amount_to_stake_as_balance}[/bold white]"
                )
                return False
            remaining_wallet_balance -= amount_to_stake_as_balance

            # Slippage warning
            received_amount, _, slippage_pct_float = (
                dynamic_info.tao_to_alpha_with_slippage(amount_to_stake_as_balance)
            )
            if dynamic_info.is_dynamic:
                slippage_pct = f"{slippage_pct_float:.4f} %"
                rate = str(1 / (float(dynamic_info.price) or 1))
            else:
                slippage_pct_float = 0
                slippage_pct = f"[{COLOR_PALETTE['STAKE']['SLIPPAGE_TEXT']}]N/A[/{COLOR_PALETTE['STAKE']['SLIPPAGE_TEXT']}]"
                rate = str(1)
            max_slippage = max(slippage_pct_float, max_slippage)
            rows.append(
                (
                    str(netuid),
                    # f"{staking_address_ss58[:3]}...{staking_address_ss58[-3:]}",
                    f"{hotkey[1]}",
                    str(amount_to_stake_as_balance),
                    rate + f" {Balance.get_unit(netuid)}/{Balance.get_unit(0)} ",
                    str(received_amount.set_unit(netuid)),
                    str(slippage_pct),
                )
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
    for row in rows:
        table.add_row(*row)
    console.print(table)
    message = ""
    if max_slippage > 5:
        message += f"[{COLOR_PALETTE['STAKE']['SLIPPAGE_TEXT']}]-------------------------------------------------------------------------------------------------------------------\n"
        message += f"[bold]WARNING:[/bold]  The slippage on one of your operations is high: [{COLOR_PALETTE['STAKE']['SLIPPAGE_PERCENT']}]{max_slippage} %[/{COLOR_PALETTE['STAKE']['SLIPPAGE_PERCENT']}], this may result in a loss of funds.\n"
        message += "-------------------------------------------------------------------------------------------------------------------\n"
        console.print(message)
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
    if prompt:
        if not Confirm.ask("Would you like to continue?"):
            raise typer.Exit()

    async def send_extrinsic(
        netuid_i, amount_, current, staking_address_ss58, status=None
    ):
        err_out = partial(print_error, status=status)
        failure_prelude = (
            f":cross_mark: [red]Failed[/red] to stake {amount} on Netuid {netuid_i}"
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
            call=call, keypair=wallet.coldkey
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
        if not prompt:  # TODO verbose?
            console.print(
                f":white_heavy_check_mark: [{COLOR_PALETTE['STAKE']['STAKE_AMOUNT']}]Submitted {amount_} to {netuid_i}[{COLOR_PALETTE['STAKE']['STAKE_AMOUNT']}]"
            )
        else:
            await response.process_events()
            if not await response.is_success:
                err_out(
                    f"\n{failure_prelude} with error: {format_error_message(await response.error_message, subtensor.substrate)}"
                )
            else:
                new_balance_, stake_info_dict = await asyncio.gather(
                    subtensor.get_balance(wallet.coldkeypub.ss58_address),
                    subtensor.get_stake_for_coldkeys(
                        coldkey_ss58_list=[wallet.coldkeypub.ss58_address],
                    ),
                )
                new_balance = new_balance_[wallet.coldkeypub.ss58_address]
                new_stake = Balance.from_rao(0)
                for stake_info in stake_info_dict[wallet.coldkeypub.ss58_address]:
                    if (
                        stake_info.hotkey_ss58 == staking_address_ss58
                        and stake_info.netuid == netuid_i
                    ):
                        new_stake = stake_info.stake.set_unit(netuid_i)
                        break

                console.print(
                    f"Balance:\n  [blue]{current_wallet_balance}[/blue] :arrow_right: [{COLOR_PALETTE['STAKE']['STAKE_AMOUNT']}]{new_balance}"
                )
                console.print(
                    f"Subnet: [{COLOR_PALETTE['GENERAL']['SUBHEADING']}]{netuid_i}[/{COLOR_PALETTE['GENERAL']['SUBHEADING']}] Stake:\n  [blue]{current}[/blue] :arrow_right: [{COLOR_PALETTE['STAKE']['STAKE_AMOUNT']}]{new_stake}"
                )

    # Perform staking operation.
    try:
        wallet.unlock_coldkey()
    except KeyFileError:
        err_console.print("Error decrypting coldkey (possibly incorrect password)")
        return False
    extrinsics_coroutines = [
        send_extrinsic(ni, am, curr, staking_address)
        for i, (ni, am, curr) in enumerate(
            zip(netuids, stake_amount_balance, current_stake_balances)
        )
        for _, staking_address in hotkeys_to_stake_to
    ]
    if len(extrinsics_coroutines) == 1:
        with console.status(f"\n:satellite: Staking on netuid(s): {netuids} ..."):
            await extrinsics_coroutines[0]
    else:
        with console.status(":satellite: Checking transaction rate limit ..."):
            tx_rate_limit_blocks = await subtensor.substrate.query(
                module="SubtensorModule", storage_function="TxRateLimit"
            )
        netuid_hk_pairs = [(ni, hk) for ni in netuids for hk in hotkeys_to_stake_to]
        for item, kp in zip(extrinsics_coroutines, netuid_hk_pairs):
            ni, hk = kp
            with console.status(
                f"\n:satellite: Staking on netuid {ni} with hotkey {hk}... ..."
            ):
                await item
            if tx_rate_limit_blocks > 0:
                with console.status(
                    f":hourglass: [yellow]Waiting for tx rate limit:"
                    f" [white]{tx_rate_limit_blocks}[/white] blocks[/yellow]"
                ):
                    await asyncio.sleep(tx_rate_limit_blocks * 12)  # 12 sec per block


async def unstake_selection(
    subtensor: "SubtensorInterface",
    wallet: Wallet,
    dynamic_info,
    identities,
    old_identities,
    netuid: Optional[int] = None,
):
    stake_infos = await subtensor.get_stake_for_coldkey(
        coldkey_ss58=wallet.coldkeypub.ss58_address
    )

    if not stake_infos:
        print_error("You have no stakes to unstake.")
        raise typer.Exit()

    hotkey_stakes = {}
    for stake_info in stake_infos:
        if netuid is not None and stake_info.netuid != netuid:
            continue
        hotkey_ss58 = stake_info.hotkey_ss58
        netuid_ = stake_info.netuid
        stake_amount = stake_info.stake
        if stake_amount.tao > 0:
            hotkey_stakes.setdefault(hotkey_ss58, {})[netuid_] = stake_amount

    if not hotkey_stakes:
        if netuid is not None:
            print_error(f"You have no stakes to unstake in subnet {netuid}.")
        else:
            print_error("You have no stakes to unstake.")
        raise typer.Exit()

    hotkeys_info = []
    for idx, (hotkey_ss58, netuid_stakes) in enumerate(hotkey_stakes.items()):
        if hk_identity := identities["hotkeys"].get(hotkey_ss58):
            hotkey_name = hk_identity.get("identity", {}).get(
                "name", ""
            ) or hk_identity.get("display", "~")
        elif old_identity := old_identities.get(hotkey_ss58):
            hotkey_name = old_identity.display
        else:
            hotkey_name = "~"
        # TODO: Add wallet ids here.

        hotkeys_info.append(
            {
                "index": idx,
                "identity": hotkey_name,
                "netuids": list(netuid_stakes.keys()),
                "hotkey_ss58": hotkey_ss58,
            }
        )

    # Display existing hotkeys, id, and staked netuids.
    subnet_filter = f" for Subnet {netuid}" if netuid is not None else ""
    table = Table(
        title=f"\n[{COLOR_PALETTE['GENERAL']['HEADER']}]Hotkeys with Stakes{subnet_filter}\n",
        show_footer=True,
        show_edge=False,
        header_style="bold white",
        border_style="bright_black",
        style="bold",
        title_justify="center",
        show_lines=False,
        pad_edge=True,
    )
    table.add_column("Index", justify="right")
    table.add_column("Identity", style=COLOR_PALETTE["GENERAL"]["SUBHEADING"])
    table.add_column("Netuids", style=COLOR_PALETTE["GENERAL"]["NETUID"])
    table.add_column("Hotkey Address", style=COLOR_PALETTE["GENERAL"]["HOTKEY"])

    for hotkey_info in hotkeys_info:
        index = str(hotkey_info["index"])
        identity = hotkey_info["identity"]
        netuids = group_subnets([n for n in hotkey_info["netuids"]])
        hotkey_ss58 = hotkey_info["hotkey_ss58"]
        table.add_row(index, identity, netuids, hotkey_ss58)

    console.print("\n", table)

    # Prompt to select hotkey to unstake.
    hotkey_options = [str(hotkey_info["index"]) for hotkey_info in hotkeys_info]
    hotkey_idx = Prompt.ask(
        "\nEnter the index of the hotkey you want to unstake from",
        choices=hotkey_options,
    )
    selected_hotkey_info = hotkeys_info[int(hotkey_idx)]
    selected_hotkey_ss58 = selected_hotkey_info["hotkey_ss58"]
    selected_hotkey_name = selected_hotkey_info["identity"]
    netuid_stakes = hotkey_stakes[selected_hotkey_ss58]

    # Display hotkey's staked netuids with amount.
    table = Table(
        title=f"\n[{COLOR_PALETTE['GENERAL']['HEADER']}]Stakes for hotkey \n[{COLOR_PALETTE['GENERAL']['SUBHEADING']}]{selected_hotkey_name}\n{selected_hotkey_ss58}\n",
        show_footer=True,
        show_edge=False,
        header_style="bold white",
        border_style="bright_black",
        style="bold",
        title_justify="center",
        show_lines=False,
        pad_edge=True,
    )
    table.add_column("Subnet", justify="right")
    table.add_column("Symbol", style=COLOR_PALETTE["GENERAL"]["SYMBOL"])
    table.add_column("Stake Amount", style=COLOR_PALETTE["STAKE"]["STAKE_AMOUNT"])
    table.add_column(
        f"[bold white]RATE ({Balance.get_unit(0)}_in/{Balance.get_unit(1)}_in)",
        style=COLOR_PALETTE["POOLS"]["RATE"],
        justify="left",
    )

    for netuid_, stake_amount in netuid_stakes.items():
        symbol = dynamic_info[netuid_].symbol
        rate = f"{dynamic_info[netuid_].price.tao:.4f} τ/{symbol}"
        table.add_row(str(netuid_), symbol, str(stake_amount), rate)
    console.print("\n", table, "\n")

    # Ask which netuids to unstake from for the selected hotkey.
    unstake_all = False
    if netuid is not None:
        selected_netuids = [netuid]
    else:
        while True:
            netuid_input = Prompt.ask(
                "\nEnter the netuids of the [blue]subnets to unstake[/blue] from (comma-separated), or '[blue]all[/blue]' to unstake from all",
                default="all",
            )

            if netuid_input.lower() == "all":
                selected_netuids = list(netuid_stakes.keys())
                unstake_all = True
                break
            else:
                try:
                    netuid_list = [int(n.strip()) for n in netuid_input.split(",")]
                    invalid_netuids = [n for n in netuid_list if n not in netuid_stakes]
                    if invalid_netuids:
                        print_error(
                            f"The following netuids are invalid or not available: {', '.join(map(str, invalid_netuids))}. Please try again."
                        )
                    else:
                        selected_netuids = netuid_list
                        break
                except ValueError:
                    print_error(
                        "Please enter valid netuids (numbers), separated by commas, or 'all'."
                    )

    hotkeys_to_unstake_from = []
    for netuid_ in selected_netuids:
        hotkeys_to_unstake_from.append(
            (selected_hotkey_name, selected_hotkey_ss58, netuid_)
        )
    return hotkeys_to_unstake_from, unstake_all


def ask_unstake_amount(
    current_stake_balance: Balance,
    netuid: int,
    staking_address_name: str,
    staking_address_ss58: str,
    interactive: bool,
) -> Optional[Balance]:
    """Prompt the user to decide the amount to unstake."""
    while True:
        response = Prompt.ask(
            f"Unstake all: [{COLOR_PALETTE['STAKE']['STAKE_AMOUNT']}]{current_stake_balance}[/{COLOR_PALETTE['STAKE']['STAKE_AMOUNT']}]"
            f" from [{COLOR_PALETTE['STAKE']['STAKE_AMOUNT']}]{staking_address_name if staking_address_name else staking_address_ss58}[/{COLOR_PALETTE['STAKE']['STAKE_AMOUNT']}]"
            f" on netuid: [{COLOR_PALETTE['STAKE']['STAKE_AMOUNT']}]{netuid}[/{COLOR_PALETTE['STAKE']['STAKE_AMOUNT']}]? [y/n/q]",
            choices=["y", "n", "q"],
            default="n" if interactive else "y",
            show_choices=True,
        ).lower()

        if response == "q":
            return None  # Quit

        elif response == "y":
            return current_stake_balance

        elif response == "n":
            while True:
                amount_input = Prompt.ask(
                    f"Enter amount to unstake in [{COLOR_PALETTE['STAKE']['STAKE_AMOUNT']}]{Balance.get_unit(netuid)}[/{COLOR_PALETTE['STAKE']['STAKE_AMOUNT']}]"
                    f" from subnet: [{COLOR_PALETTE['STAKE']['STAKE_AMOUNT']}]{netuid}[/{COLOR_PALETTE['STAKE']['STAKE_AMOUNT']}]"
                    f" (Max: [{COLOR_PALETTE['STAKE']['STAKE_AMOUNT']}]{current_stake_balance}[/{COLOR_PALETTE['STAKE']['STAKE_AMOUNT']}])"
                )
                if amount_input.lower() == "q":
                    return None  # Quit

                try:
                    amount_value = float(amount_input)
                    if amount_value <= 0:
                        console.print("[red]Amount must be greater than zero.[/red]")
                        continue  # Re-prompt

                    amount_to_unstake = Balance.from_tao(amount_value)
                    amount_to_unstake.set_unit(netuid)
                    if amount_to_unstake > current_stake_balance:
                        console.print(
                            f"[red]Amount exceeds current stake balance of {current_stake_balance}.[/red]"
                        )
                        continue  # Re-prompt

                    return amount_to_unstake

                except ValueError:
                    console.print(
                        "[red]Invalid input. Please enter a numeric value or 'q' to quit.[/red]"
                    )

        else:
            console.print("[red]Invalid input. Please enter 'y', 'n', or 'q'.[/red]")


async def _unstake_all(
    wallet: Wallet,
    subtensor: "SubtensorInterface",
    unstake_all_alpha: bool = False,
    prompt: bool = True,
) -> bool:
    """Unstakes all stakes from all hotkeys in all subnets."""

    with console.status(
        f"Retrieving stake information & identities from {subtensor.network}...",
        spinner="earth",
    ):
        (
            stake_info,
            ck_hk_identities,
            old_identities,
            all_sn_dynamic_info_,
            current_wallet_balance,
        ) = await asyncio.gather(
            subtensor.get_stake_for_coldkey(wallet.coldkeypub.ss58_address),
            subtensor.fetch_coldkey_hotkey_identities(),
            subtensor.get_delegate_identities(),
            subtensor.all_subnets(),
            subtensor.get_balance(wallet.coldkeypub.ss58_address),
        )

        if unstake_all_alpha:
            stake_info = [stake for stake in stake_info if stake.netuid != 0]

        if not stake_info:
            console.print("[red]No stakes found to unstake[/red]")
            return False

        all_sn_dynamic_info = {info.netuid: info for info in all_sn_dynamic_info_}

        # Calculate total value and slippage for all stakes
        total_received_value = Balance(0)
        table_title = (
            "Unstaking Summary - All Stakes"
            if not unstake_all_alpha
            else "Unstaking Summary - All Alpha Stakes"
        )
        table = Table(
            title=f"\n[{COLOR_PALETTE['GENERAL']['HEADER']}]{table_title}\nWallet: [{COLOR_PALETTE['GENERAL']['COLDKEY']}]{wallet.name}[/{COLOR_PALETTE['GENERAL']['COLDKEY']}], Coldkey ss58: [{COLOR_PALETTE['GENERAL']['COLDKEY']}]{wallet.coldkeypub.ss58_address}[/{COLOR_PALETTE['GENERAL']['COLDKEY']}]\nNetwork: {subtensor.network}[/{COLOR_PALETTE['GENERAL']['HEADER']}]\n",
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
            f"Current Stake ({Balance.get_unit(1)})",
            justify="center",
            style=COLOR_PALETTE["STAKE"]["STAKE_ALPHA"],
        )
        table.add_column(
            f"Rate ({Balance.unit}/{Balance.get_unit(1)})",
            justify="center",
            style=COLOR_PALETTE["POOLS"]["RATE"],
        )
        table.add_column(
            f"Recieved ({Balance.unit})",
            justify="center",
            style=COLOR_PALETTE["POOLS"]["TAO_EQUIV"],
        )
        table.add_column(
            "Slippage",
            justify="center",
            style=COLOR_PALETTE["STAKE"]["SLIPPAGE_PERCENT"],
        )
        max_slippage = 0.0
        for stake in stake_info:
            if stake.stake.rao == 0:
                continue

            dynamic_info = all_sn_dynamic_info.get(stake.netuid)
            stake_amount = stake.stake
            received_amount, _, slippage_pct_float = (
                dynamic_info.alpha_to_tao_with_slippage(stake_amount)
            )

            total_received_value += received_amount

            # Get hotkey identity
            if hk_identity := ck_hk_identities["hotkeys"].get(stake.hotkey_ss58):
                hotkey_name = hk_identity.get("identity", {}).get(
                    "name", ""
                ) or hk_identity.get("display", "~")
                hotkey_display = f"{hotkey_name}"
            elif old_identity := old_identities.get(stake.hotkey_ss58):
                hotkey_name = old_identity.display
                hotkey_display = f"{hotkey_name}"
            else:
                hotkey_display = stake.hotkey_ss58

            if dynamic_info.is_dynamic:
                slippage_pct = f"{slippage_pct_float:.4f} %"
            else:
                slippage_pct_float = 0
                slippage_pct = "[red]N/A[/red]"

            max_slippage = max(max_slippage, slippage_pct_float)

            table.add_row(
                str(stake.netuid),
                hotkey_display,
                str(stake_amount),
                str(float(dynamic_info.price))
                + f"({Balance.get_unit(0)}/{Balance.get_unit(stake.netuid)})",
                str(received_amount),
                slippage_pct,
            )
    console.print(table)
    message = ""
    if max_slippage > 5:
        message += f"[{COLOR_PALETTE['STAKE']['SLIPPAGE_TEXT']}]-------------------------------------------------------------------------------------------------------------------\n"
        message += f"[bold]WARNING:[/bold] The slippage on one of your operations is high: [{COLOR_PALETTE['STAKE']['SLIPPAGE_PERCENT']}]{max_slippage:.4f}%[/{COLOR_PALETTE['STAKE']['SLIPPAGE_PERCENT']}], this may result in a loss of funds.\n"
        message += "-------------------------------------------------------------------------------------------------------------------\n"
        console.print(message)

    console.print(
        f"Expected return after slippage: [{COLOR_PALETTE['STAKE']['STAKE_AMOUNT']}]{total_received_value}"
    )

    if prompt and not Confirm.ask(
        "\nDo you want to proceed with unstaking everything?"
    ):
        return False

    try:
        wallet.unlock_coldkey()
    except KeyFileError:
        err_console.print("Error decrypting coldkey (possibly incorrect password)")
        return False

    console_status = (
        ":satellite: Unstaking all Alpha stakes..."
        if unstake_all_alpha
        else ":satellite: Unstaking all stakes..."
    )
    with console.status(console_status):
        call_function = "unstake_all_alpha" if unstake_all_alpha else "unstake_all"
        call = await subtensor.substrate.compose_call(
            call_module="SubtensorModule",
            call_function=call_function,
            call_params={"hotkey": wallet.hotkey.ss58_address},
        )
        success, error_message = await subtensor.sign_and_send_extrinsic(
            call=call,
            wallet=wallet,
            wait_for_inclusion=True,
            wait_for_finalization=False,
        )

        if success:
            success_message = (
                ":white_heavy_check_mark: [green]Successfully unstaked all stakes[/green]"
                if not unstake_all_alpha
                else ":white_heavy_check_mark: [green]Successfully unstaked all Alpha stakes[/green]"
            )
            console.print(success_message)
            new_balance_ = await subtensor.get_balance(wallet.coldkeypub.ss58_address)
            new_balance = new_balance_[wallet.coldkeypub.ss58_address]
            console.print(
                f"Balance:\n [blue]{current_wallet_balance[wallet.coldkeypub.ss58_address]}[/blue] :arrow_right: [{COLOR_PALETTE['STAKE']['STAKE_AMOUNT']}]{new_balance}"
            )
            return True
        else:
            err_console.print(
                f":cross_mark: [red]Failed to unstake[/red]: {error_message}"
            )
            return False


async def unstake(
    wallet: Wallet,
    subtensor: "SubtensorInterface",
    hotkey_ss58_address: str,
    all_hotkeys: bool,
    include_hotkeys: list[str],
    exclude_hotkeys: list[str],
    amount: float,
    keep_stake: float,
    unstake_all: bool,
    prompt: bool,
    interactive: bool = False,
    netuid: Optional[int] = None,
    unstake_all_alpha: bool = False,
):
    """Unstake tokens from hotkey(s)."""

    if unstake_all or unstake_all_alpha:
        return await _unstake_all(wallet, subtensor, unstake_all_alpha, prompt)

    unstake_all_from_hk = False
    with console.status(
        f"Retrieving subnet data & identities from {subtensor.network}...",
        spinner="earth",
    ):
        all_sn_dynamic_info_, ck_hk_identities, old_identities = await asyncio.gather(
            subtensor.all_subnets(),
            subtensor.fetch_coldkey_hotkey_identities(),
            subtensor.get_delegate_identities(),
        )
        all_sn_dynamic_info = {info.netuid: info for info in all_sn_dynamic_info_}

    if interactive:
        hotkeys_to_unstake_from, unstake_all_from_hk = await unstake_selection(
            subtensor,
            wallet,
            all_sn_dynamic_info,
            ck_hk_identities,
            old_identities,
            netuid=netuid,
        )
        if not hotkeys_to_unstake_from:
            console.print("[red]No unstake operations to perform.[/red]")
            return False
        netuids = list({netuid for _, _, netuid in hotkeys_to_unstake_from})

    else:
        netuids = (
            [int(netuid)]
            if netuid is not None
            else await subtensor.get_all_subnet_netuids()
        )

        # Get the hotkey_names (if any) and the hotkey_ss58s.
        hotkeys_to_unstake_from: list[tuple[Optional[str], str]] = []
        if hotkey_ss58_address:
            print_verbose(f"Unstaking from ss58 ({hotkey_ss58_address})")
            # Unstake from specific hotkey.
            hotkeys_to_unstake_from = [(None, hotkey_ss58_address)]
        elif all_hotkeys:
            print_verbose("Unstaking from all hotkeys")
            # Unstake from all hotkeys.
            all_hotkeys_: list[Wallet] = get_hotkey_wallets_for_wallet(wallet=wallet)
            # Exclude hotkeys that are specified.
            hotkeys_to_unstake_from = [
                (wallet.hotkey_str, wallet.hotkey.ss58_address)
                for wallet in all_hotkeys_
                if wallet.hotkey_str not in exclude_hotkeys
            ]
        elif include_hotkeys:
            print_verbose("Unstaking from included hotkeys")
            # Unstake from specific hotkeys.
            for hotkey_identifier in include_hotkeys:
                if is_valid_ss58_address(hotkey_identifier):
                    # If the hotkey is a valid ss58 address, we add it to the list.
                    hotkeys_to_unstake_from.append((None, hotkey_identifier))
                else:
                    # If the hotkey is not a valid ss58 address, we assume it is a hotkey name.
                    # We then get the hotkey from the wallet and add it to the list.
                    wallet_ = Wallet(
                        name=wallet.name,
                        path=wallet.path,
                        hotkey=hotkey_identifier,
                    )
                    hotkeys_to_unstake_from.append(
                        (wallet_.hotkey_str, wallet_.hotkey.ss58_address)
                    )
        else:
            # Only cli.config.wallet.hotkey is specified.
            # So we unstake from that single hotkey.
            print_verbose(
                f"Unstaking from wallet: ({wallet.name}) from hotkey: ({wallet.hotkey_str})"
            )
            assert wallet.hotkey is not None
            hotkeys_to_unstake_from = [(wallet.hotkey_str, wallet.hotkey.ss58_address)]

    with console.status(
        f"Retrieving stake data from {subtensor.network}...",
        spinner="earth",
    ):
        # Prepare unstaking transactions
        unstake_operations = []
        total_received_amount = Balance.from_tao(0)
        current_wallet_balance: Balance = (
            await subtensor.get_balance(wallet.coldkeypub.ss58_address)
        )[wallet.coldkeypub.ss58_address]
        max_float_slippage = 0

        # Fetch stake balances
        chain_head = await subtensor.substrate.get_chain_head()
        stake_info_dict = await subtensor.get_stake_for_coldkeys(
            coldkey_ss58_list=[wallet.coldkeypub.ss58_address],
            block_hash=chain_head,
        )
        stake_in_netuids = {}
        for _, stake_info_list in stake_info_dict.items():
            hotkey_stakes = {}
            for stake_info in stake_info_list:
                if stake_info.hotkey_ss58 not in hotkey_stakes:
                    hotkey_stakes[stake_info.hotkey_ss58] = {}
                hotkey_stakes[stake_info.hotkey_ss58][stake_info.netuid] = (
                    stake_info.stake
                )

        stake_in_netuids = hotkey_stakes

    # Flag to check if user wants to quit
    skip_remaining_subnets = False
    if hotkeys_to_unstake_from:
        console.print(
            "[dark_sea_green3]Tip: Enter 'q' any time to skip further entries and process existing unstakes"
        )

    # Iterate over hotkeys and netuids to collect unstake operations
    unstake_all_hk_ss58 = None
    for hotkey in hotkeys_to_unstake_from:
        if skip_remaining_subnets:
            break

        if interactive:
            staking_address_name, staking_address_ss58, netuid = hotkey
            netuids_to_process = [netuid]
        else:
            staking_address_name, staking_address_ss58 = hotkey
            netuids_to_process = netuids

        initial_amount = amount

        if len(netuids_to_process) > 1:
            console.print(
                "[dark_sea_green3]Tip: Enter 'q' any time to stop going over remaining subnets and process current unstakes.\n"
            )

        for netuid in netuids_to_process:
            if skip_remaining_subnets:
                break  # Exit the loop over netuids

            dynamic_info = all_sn_dynamic_info.get(netuid)
            current_stake_balance = stake_in_netuids[staking_address_ss58][netuid]
            if current_stake_balance.tao == 0:
                continue  # No stake to unstake

            # Determine the amount we are unstaking.
            if unstake_all_from_hk or unstake_all:
                amount_to_unstake_as_balance = current_stake_balance
                unstake_all_hk_ss58 = staking_address_ss58
            elif initial_amount:
                amount_to_unstake_as_balance = Balance.from_tao(initial_amount)
            else:
                amount_to_unstake_as_balance = ask_unstake_amount(
                    current_stake_balance,
                    netuid,
                    staking_address_name
                    if staking_address_name
                    else staking_address_ss58,
                    staking_address_ss58,
                    interactive,
                )
                if amount_to_unstake_as_balance is None:
                    skip_remaining_subnets = True
                    break

            # Check enough stake to remove.
            amount_to_unstake_as_balance.set_unit(netuid)
            if amount_to_unstake_as_balance > current_stake_balance:
                err_console.print(
                    f"[red]Not enough stake to remove[/red]:\n Stake balance: [dark_orange]{current_stake_balance}[/dark_orange]"
                    f" < Unstaking amount: [dark_orange]{amount_to_unstake_as_balance}[/dark_orange]"
                )
                continue  # Skip to the next subnet - useful when single amount is specified for all subnets

            received_amount, _, slippage_pct_float = (
                dynamic_info.alpha_to_tao_with_slippage(amount_to_unstake_as_balance)
            )
            total_received_amount += received_amount
            if dynamic_info.is_dynamic:
                slippage_pct = f"{slippage_pct_float:.4f} %"
            else:
                slippage_pct_float = 0
                slippage_pct = "[red]N/A[/red]"
            max_float_slippage = max(max_float_slippage, slippage_pct_float)

            unstake_operations.append(
                {
                    "netuid": netuid,
                    "hotkey_name": staking_address_name
                    if staking_address_name
                    else staking_address_ss58,
                    "hotkey_ss58": staking_address_ss58,
                    "amount_to_unstake": amount_to_unstake_as_balance,
                    "current_stake_balance": current_stake_balance,
                    "received_amount": received_amount,
                    "slippage_pct": slippage_pct,
                    "slippage_pct_float": slippage_pct_float,
                    "dynamic_info": dynamic_info,
                }
            )

    if not unstake_operations:
        console.print("[red]No unstake operations to perform.[/red]")
        return False

    # Build the table
    table = Table(
        title=f"\n[{COLOR_PALETTE['GENERAL']['HEADER']}]Unstaking to: \nWallet: [{COLOR_PALETTE['GENERAL']['COLDKEY']}]{wallet.name}[/{COLOR_PALETTE['GENERAL']['COLDKEY']}],"
        f" Coldkey ss58: [{COLOR_PALETTE['GENERAL']['COLDKEY']}]{wallet.coldkeypub.ss58_address}[/{COLOR_PALETTE['GENERAL']['COLDKEY']}]\n"
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
        f"Amount ({Balance.get_unit(1)})",
        justify="center",
        style=COLOR_PALETTE["POOLS"]["TAO"],
    )
    table.add_column(
        f"Rate ({Balance.get_unit(0)}/{Balance.get_unit(1)})",
        justify="center",
        style=COLOR_PALETTE["POOLS"]["RATE"],
    )
    table.add_column(
        f"Received ({Balance.get_unit(0)})",
        justify="center",
        style=COLOR_PALETTE["POOLS"]["TAO_EQUIV"],
        footer=f"{total_received_amount}",
    )
    table.add_column(
        "Slippage", justify="center", style=COLOR_PALETTE["STAKE"]["SLIPPAGE_PERCENT"]
    )

    for op in unstake_operations:
        dynamic_info = op["dynamic_info"]
        table.add_row(
            str(op["netuid"]),
            op["hotkey_name"],
            str(op["amount_to_unstake"]),
            str(float(dynamic_info.price))
            + f"({Balance.get_unit(0)}/{Balance.get_unit(op['netuid'])})",
            str(op["received_amount"]),
            op["slippage_pct"],
        )

    console.print(table)

    if max_float_slippage > 5:
        console.print(
            "\n"
            f"[{COLOR_PALETTE['STAKE']['SLIPPAGE_TEXT']}]-------------------------------------------------------------------------------------------------------------------\n"
            f"[bold]WARNING:[/bold]  The slippage on one of your operations is high: [{COLOR_PALETTE['STAKE']['SLIPPAGE_PERCENT']}]{max_float_slippage} %[/{COLOR_PALETTE['STAKE']['SLIPPAGE_PERCENT']}],"
            " this may result in a loss of funds.\n"
            f"-------------------------------------------------------------------------------------------------------------------\n"
        )

    console.print(
        """
[bold white]Description[/bold white]:
The table displays information about the stake remove operation you are about to perform.
The columns are as follows:
    - [bold white]Netuid[/bold white]: The netuid of the subnet you are unstaking from.
    - [bold white]Hotkey[/bold white]: The ss58 address or identity of the hotkey you are unstaking from. 
    - [bold white]Amount[/bold white]: The stake amount you are removing from this key.
    - [bold white]Rate[/bold white]: The rate of exchange between TAO and the subnet's stake.
    - [bold white]Received[/bold white]: The amount of free balance TAO you will receive on this subnet after slippage.
    - [bold white]Slippage[/bold white]: The slippage percentage of the unstake operation. (0% if the subnet is not dynamic i.e. root).
"""
    )
    if prompt:
        if not Confirm.ask("Would you like to continue?"):
            raise typer.Exit()

    # Perform unstaking operations
    try:
        wallet.unlock_coldkey()
    except KeyFileError:
        err_console.print("Error decrypting coldkey (possibly incorrect password)")
        return False

    with console.status("\n:satellite: Performing unstaking operations...") as status:
        if unstake_all_from_hk:
            call = await subtensor.substrate.compose_call(
                call_module="SubtensorModule",
                call_function="unstake_all",
                call_params={
                    "hotkey": unstake_all_hk_ss58,
                },
            )
            extrinsic = await subtensor.substrate.create_signed_extrinsic(
                call=call, keypair=wallet.coldkey
            )
            response = await subtensor.substrate.submit_extrinsic(
                extrinsic, wait_for_inclusion=True, wait_for_finalization=False
            )
            if not prompt:
                console.print(":white_heavy_check_mark: [green]Sent[/green]")
            else:
                await response.process_events()
                if not await response.is_success:
                    print_error(
                        f":cross_mark: [red]Failed[/red] with error: "
                        f"{format_error_message(await response.error_message, subtensor.substrate)}",
                        status,
                    )
                else:
                    new_balance_ = await subtensor.get_balance(
                        wallet.coldkeypub.ss58_address
                    )
                    new_balance = new_balance_[wallet.coldkeypub.ss58_address]
                    console.print(
                        f"Balance:\n  [blue]{current_wallet_balance}[/blue] :arrow_right: [{COLOR_PALETTE['STAKE']['STAKE_AMOUNT']}]{new_balance}"
                    )
        else:
            for op in unstake_operations:
                netuid_i = op["netuid"]
                staking_address_name = op["hotkey_name"]
                staking_address_ss58 = op["hotkey_ss58"]
                amount = op["amount_to_unstake"]
                current_stake_balance = op["current_stake_balance"]

                status.update(
                    f"\n:satellite: Unstaking {amount} from {staking_address_name} on netuid: {netuid_i} ..."
                )

                call = await subtensor.substrate.compose_call(
                    call_module="SubtensorModule",
                    call_function="remove_stake",
                    call_params={
                        "hotkey": staking_address_ss58,
                        "netuid": netuid_i,
                        "amount_unstaked": amount.rao,
                    },
                )
                extrinsic = await subtensor.substrate.create_signed_extrinsic(
                    call=call, keypair=wallet.coldkey
                )
                response = await subtensor.substrate.submit_extrinsic(
                    extrinsic, wait_for_inclusion=True, wait_for_finalization=False
                )
                if not prompt:
                    console.print(":white_heavy_check_mark: [green]Sent[/green]")
                else:
                    await response.process_events()
                    if not await response.is_success:
                        print_error(
                            f":cross_mark: [red]Failed[/red] with error: "
                            f"{format_error_message(await response.error_message, subtensor.substrate)}",
                            status,
                        )
                    else:
                        new_balance_ = await subtensor.get_balance(
                            wallet.coldkeypub.ss58_address
                        )
                        new_balance = new_balance_[wallet.coldkeypub.ss58_address]
                        new_stake_info = await subtensor.get_stake_for_coldkeys(
                            coldkey_ss58_list=[wallet.coldkeypub.ss58_address],
                        )
                        new_stake = Balance.from_rao(0)
                        for stake_info in new_stake_info[
                            wallet.coldkeypub.ss58_address
                        ]:
                            if (
                                stake_info.hotkey_ss58 == staking_address_ss58
                                and stake_info.netuid == netuid_i
                            ):
                                new_stake = stake_info.stake.set_unit(netuid_i)
                                break
                        console.print(
                            f"Balance:\n  [blue]{current_wallet_balance}[/blue] :arrow_right: [{COLOR_PALETTE['STAKE']['STAKE_AMOUNT']}]{new_balance}"
                        )
                        console.print(
                            f"Subnet: [{COLOR_PALETTE['GENERAL']['SUBHEADING']}]{netuid_i}[/{COLOR_PALETTE['GENERAL']['SUBHEADING']}]"
                            f" Stake:\n  [blue]{current_stake_balance}[/blue] :arrow_right: [{COLOR_PALETTE['STAKE']['STAKE_AMOUNT']}]{new_stake}"
                        )
    console.print(
        f"[{COLOR_PALETTE['STAKE']['STAKE_AMOUNT']}]Unstaking operations completed."
    )


async def stake_list(
    wallet: Wallet,
    coldkey_ss58: str,
    subtensor: "SubtensorInterface",
    live: bool = False,
    verbose: bool = False,
    prompt: bool = False,
):
    coldkey_address = coldkey_ss58 if coldkey_ss58 else wallet.coldkeypub.ss58_address

    async def get_stake_data(block_hash: str = None):
        (
            substakes,
            registered_delegate_info,
            _dynamic_info,
        ) = await asyncio.gather(
            subtensor.get_stake_for_coldkeys(
                coldkey_ss58_list=[coldkey_address], block_hash=block_hash
            ),
            subtensor.get_delegate_identities(block_hash=block_hash),
            subtensor.all_subnets(),
        )
        sub_stakes = substakes[coldkey_address]
        dynamic_info = {info.netuid: info for info in _dynamic_info}
        return (
            sub_stakes,
            registered_delegate_info,
            dynamic_info,
        )

    def define_table(
        hotkey_name: str,
        rows: list[list[str]],
        total_tao_ownership: Balance,
        total_tao_value: Balance,
        total_swapped_tao_value: Balance,
        live: bool = False,
    ):
        title = f"\n[{COLOR_PALETTE['GENERAL']['HEADER']}]Hotkey: {hotkey_name}\nNetwork: {subtensor.network}\n\n"
        # TODO: Add hint back in after adding columns descriptions
        # if not live:
        #     title += f"[{COLOR_PALETTE['GENERAL']['HINT']}]See below for an explanation of the columns\n"
        table = Table(
            title=title,
            show_footer=True,
            show_edge=False,
            header_style="bold white",
            border_style="bright_black",
            style="bold",
            title_justify="center",
            show_lines=False,
            pad_edge=True,
        )
        table.add_column(
            "[white]Netuid",
            footer=f"{len(rows)}",
            footer_style="overline white",
            style="grey89",
        )
        table.add_column(
            "[white]Name",
            style="cyan",
            justify="left",
            no_wrap=True,
        )
        table.add_column(
            f"[white]Value \n({Balance.get_unit(1)} x {Balance.unit}/{Balance.get_unit(1)})",
            footer_style="overline white",
            style=COLOR_PALETTE["STAKE"]["TAO"],
            justify="right",
            footer=f"τ {millify_tao(total_tao_value.tao)}"
            if not verbose
            else f"{total_tao_value}",
        )
        table.add_column(
            f"[white]Stake ({Balance.get_unit(1)})",
            footer_style="overline white",
            style=COLOR_PALETTE["STAKE"]["STAKE_ALPHA"],
            justify="center",
        )
        table.add_column(
            f"[white]Price \n({Balance.unit}_in/{Balance.get_unit(1)}_in)",
            footer_style="white",
            style=COLOR_PALETTE["POOLS"]["RATE"],
            justify="center",
        )
        table.add_column(
            f"[white]Swap ({Balance.get_unit(1)} -> {Balance.unit})",
            footer_style="overline white",
            style=COLOR_PALETTE["STAKE"]["STAKE_SWAP"],
            justify="right",
            footer=f"τ {millify_tao(total_swapped_tao_value.tao)}"
            if not verbose
            else f"{total_swapped_tao_value}",
        )
        table.add_column(
            "[white]Registered",
            style=COLOR_PALETTE["STAKE"]["STAKE_ALPHA"],
            justify="right",
        )
        table.add_column(
            f"[white]Emission \n({Balance.get_unit(1)}/block)",
            style=COLOR_PALETTE["POOLS"]["EMISSION"],
            justify="right",
        )
        return table

    def create_table(hotkey_: str, substakes: list[StakeInfo]):
        name = (
            f"{registered_delegate_info[hotkey_].display} ({hotkey_})"
            if hotkey_ in registered_delegate_info
            else hotkey_
        )
        rows = []
        total_tao_ownership = Balance(0)
        total_tao_value = Balance(0)
        total_swapped_tao_value = Balance(0)
        root_stakes = [s for s in substakes if s.netuid == 0]
        other_stakes = sorted(
            [s for s in substakes if s.netuid != 0],
            key=lambda x: dynamic_info[x.netuid]
            .alpha_to_tao(Balance.from_rao(int(x.stake.rao)).set_unit(x.netuid))
            .tao,
            reverse=True,
        )
        sorted_substakes = root_stakes + other_stakes
        for substake_ in sorted_substakes:
            netuid = substake_.netuid
            pool = dynamic_info[netuid]
            symbol = f"{Balance.get_unit(netuid)}\u200e"
            # TODO: what is this price var for?
            price = (
                "{:.4f}{}".format(
                    pool.price.__float__(), f" τ/{Balance.get_unit(netuid)}\u200e"
                )
                if pool.is_dynamic
                else (f" 1.0000 τ/{symbol} ")
            )

            # Alpha value cell
            alpha_value = Balance.from_rao(int(substake_.stake.rao)).set_unit(netuid)

            # TAO value cell
            tao_value = pool.alpha_to_tao(alpha_value)
            total_tao_value += tao_value

            # Swapped TAO value and slippage cell
            swapped_tao_value, _, slippage_percentage_ = (
                pool.alpha_to_tao_with_slippage(substake_.stake)
            )
            total_swapped_tao_value += swapped_tao_value

            # Slippage percentage cell
            if pool.is_dynamic:
                slippage_percentage = f"[{COLOR_PALETTE['STAKE']['SLIPPAGE_PERCENT']}]{slippage_percentage_:.3f}%[/{COLOR_PALETTE['STAKE']['SLIPPAGE_PERCENT']}]"
            else:
                slippage_percentage = f"[{COLOR_PALETTE['STAKE']['SLIPPAGE_PERCENT']}]0.000%[/{COLOR_PALETTE['STAKE']['SLIPPAGE_PERCENT']}]"

            if netuid == 0:
                swap_value = f"[{COLOR_PALETTE['STAKE']['NOT_REGISTERED']}]N/A[/{COLOR_PALETTE['STAKE']['NOT_REGISTERED']}] ({slippage_percentage})"
            else:
                swap_value = (
                    f"τ {millify_tao(swapped_tao_value.tao)} ({slippage_percentage})"
                    if not verbose
                    else f"{swapped_tao_value} ({slippage_percentage})"
                )

            # TAO locked cell
            tao_locked = pool.tao_in

            # Issuance cell
            issuance = pool.alpha_out if pool.is_dynamic else tao_locked

            # Per block emission cell
            per_block_emission = substake_.emission.tao / pool.tempo
            # Alpha ownership and TAO ownership cells
            if alpha_value.tao > 0.00009:
                if issuance.tao != 0:
                    alpha_ownership = "{:.4f}".format(
                        (alpha_value.tao / issuance.tao) * 100
                    )
                    tao_ownership = Balance.from_tao(
                        (alpha_value.tao / issuance.tao) * tao_locked.tao
                    )
                    total_tao_ownership += tao_ownership
                else:
                    # TODO what's this var for?
                    alpha_ownership = "0.0000"
                    tao_ownership = Balance.from_tao(0)

                stake_value = (
                    millify_tao(substake_.stake.tao)
                    if not verbose
                    else f"{substake_.stake.tao:,.4f}"
                )
                subnet_name_cell = f"[{COLOR_PALETTE['GENERAL']['SYMBOL']}]{symbol if netuid != 0 else 'τ'}[/{COLOR_PALETTE['GENERAL']['SYMBOL']}] {get_subnet_name(dynamic_info[netuid])}"

                rows.append(
                    [
                        str(netuid),  # Number
                        subnet_name_cell,  # Symbol + name
                        f"τ {millify_tao(tao_value.tao)}"
                        if not verbose
                        else f"{tao_value}",  # Value (α x τ/α)
                        f"{stake_value} {symbol}"
                        if netuid != 0
                        else f"{symbol} {stake_value}",  # Stake (a)
                        f"{pool.price.tao:.4f} τ/{symbol}",  # Rate (t/a)
                        # f"τ {millify_tao(tao_ownership.tao)}" if not verbose else f"{tao_ownership}",  # TAO equiv
                        swap_value,  # Swap(α) -> τ
                        "YES"
                        if substake_.is_registered
                        else f"[{COLOR_PALETTE['STAKE']['NOT_REGISTERED']}]NO",  # Registered
                        str(Balance.from_tao(per_block_emission).set_unit(netuid)),
                        # Removing this flag for now, TODO: Confirm correct values are here w.r.t CHKs
                        # if substake_.is_registered
                        # else f"[{COLOR_PALETTE['STAKE']['NOT_REGISTERED']}]N/A",  # Emission(α/block)
                    ]
                )
        table = define_table(
            name, rows, total_tao_ownership, total_tao_value, total_swapped_tao_value
        )
        for row in rows:
            table.add_row(*row)
        console.print(table)
        return total_tao_ownership, total_tao_value

    def create_live_table(
        substakes: list,
        registered_delegate_info: dict,
        dynamic_info: dict,
        hotkey_name: str,
        previous_data: Optional[dict] = None,
    ) -> tuple[Table, dict, Balance, Balance, Balance]:
        rows = []
        current_data = {}

        total_tao_ownership = Balance(0)
        total_tao_value = Balance(0)
        total_swapped_tao_value = Balance(0)

        def format_cell(
            value, previous_value, unit="", unit_first=False, precision=4, millify=False
        ):
            if previous_value is not None:
                change = value - previous_value
                if abs(change) > 10 ** (-precision):
                    formatted_change = (
                        f"{change:.{precision}f}"
                        if not millify
                        else f"{millify_tao(change)}"
                    )
                    change_text = (
                        f" [pale_green3](+{formatted_change})[/pale_green3]"
                        if change > 0
                        else f" [hot_pink3]({formatted_change})[/hot_pink3]"
                    )
                else:
                    change_text = ""
            else:
                change_text = ""
            formatted_value = (
                f"{value:,.{precision}f}" if not millify else f"{millify_tao(value)}"
            )
            return (
                f"{formatted_value} {unit}{change_text}"
                if not unit_first
                else f"{unit} {formatted_value}{change_text}"
            )

        # Sort subnets by value
        root_stakes = [s for s in substakes if s.netuid == 0]
        other_stakes = sorted(
            [s for s in substakes if s.netuid != 0],
            key=lambda x: dynamic_info[x.netuid]
            .alpha_to_tao(Balance.from_rao(int(x.stake.rao)).set_unit(x.netuid))
            .tao,
            reverse=True,
        )
        sorted_substakes = root_stakes + other_stakes

        # Process each stake
        for substake in sorted_substakes:
            netuid = substake.netuid
            pool = dynamic_info.get(netuid)
            if substake.stake.rao == 0 or not pool:
                continue

            # Calculate base values
            symbol = f"{Balance.get_unit(netuid)}\u200e"
            alpha_value = Balance.from_rao(int(substake.stake.rao)).set_unit(netuid)
            tao_value = pool.alpha_to_tao(alpha_value)
            total_tao_value += tao_value
            swapped_tao_value, slippage = pool.alpha_to_tao_with_slippage(
                substake.stake
            )
            total_swapped_tao_value += swapped_tao_value

            # Calculate TAO ownership
            tao_locked = pool.tao_in
            issuance = pool.alpha_out if pool.is_dynamic else tao_locked
            if alpha_value.tao > 0.00009 and issuance.tao != 0:
                tao_ownership = Balance.from_tao(
                    (alpha_value.tao / issuance.tao) * tao_locked.tao
                )
                total_tao_ownership += tao_ownership
            else:
                tao_ownership = Balance.from_tao(0)

            # Store current values for future delta tracking
            current_data[netuid] = {
                "stake": alpha_value.tao,
                "price": pool.price.tao,
                "tao_value": tao_value.tao,
                "swapped_value": swapped_tao_value.tao,
                "emission": substake.emission.tao / pool.tempo,
                "tao_ownership": tao_ownership.tao,
            }

            # Get previous values for delta tracking
            prev = previous_data.get(netuid, {}) if previous_data else {}
            unit_first = True if netuid == 0 else False

            stake_cell = format_cell(
                alpha_value.tao,
                prev.get("stake"),
                unit=symbol,
                unit_first=unit_first,
                precision=4,
                millify=True if not verbose else False,
            )

            rate_cell = format_cell(
                pool.price.tao,
                prev.get("price"),
                unit=f"τ/{symbol}",
                unit_first=False,
                precision=5,
                millify=True if not verbose else False,
            )

            exchange_cell = format_cell(
                tao_value.tao,
                prev.get("tao_value"),
                unit="τ",
                unit_first=True,
                precision=4,
                millify=True if not verbose else False,
            )

            if pool.is_dynamic:
                slippage_pct = (
                    100 * float(slippage) / float(slippage + swapped_tao_value)
                    if slippage + swapped_tao_value != 0
                    else 0
                )
            else:
                slippage_pct = 0

            if netuid != 0:
                swap_cell = (
                    format_cell(
                        swapped_tao_value.tao,
                        prev.get("swapped_value"),
                        unit="τ",
                        unit_first=True,
                        precision=4,
                        millify=True if not verbose else False,
                    )
                    + f" ({slippage_pct:.2f}%)"
                )
            else:
                swap_cell = f"[{COLOR_PALETTE['STAKE']['NOT_REGISTERED']}]N/A[/{COLOR_PALETTE['STAKE']['NOT_REGISTERED']}] ({slippage_pct}%)"

            emission_value = substake.emission.tao / pool.tempo
            emission_cell = format_cell(
                emission_value,
                prev.get("emission"),
                unit=symbol,
                unit_first=unit_first,
                precision=4,
            )
            subnet_name_cell = (
                f"[{COLOR_PALETTE['GENERAL']['SYMBOL']}]{symbol if netuid != 0 else 'τ'}[/{COLOR_PALETTE['GENERAL']['SYMBOL']}]"
                f" {get_subnet_name(dynamic_info[netuid])}"
            )

            rows.append(
                [
                    str(netuid),  # Netuid
                    subnet_name_cell,
                    exchange_cell,  # Exchange value
                    stake_cell,  # Stake amount
                    rate_cell,  # Rate
                    swap_cell,  # Swap value with slippage
                    "YES"
                    if substake.is_registered
                    else f"[{COLOR_PALETTE['STAKE']['NOT_REGISTERED']}]NO",  # Registration status
                    emission_cell,  # Emission rate
                ]
            )

        table = define_table(
            hotkey_name,
            rows,
            total_tao_ownership,
            total_tao_value,
            total_swapped_tao_value,
            live=True,
        )

        for row in rows:
            table.add_row(*row)

        return table, current_data

    # Main execution
    (
        sub_stakes,
        registered_delegate_info,
        dynamic_info,
    ) = await get_stake_data()
    balance = await subtensor.get_balance(coldkey_address)

    # Iterate over substakes and aggregate them by hotkey.
    hotkeys_to_substakes: dict[str, list[StakeInfo]] = {}

    for substake in sub_stakes:
        hotkey = substake.hotkey_ss58
        if substake.stake.rao == 0:
            continue
        if hotkey not in hotkeys_to_substakes:
            hotkeys_to_substakes[hotkey] = []
        hotkeys_to_substakes[hotkey].append(substake)

    if not hotkeys_to_substakes:
        print_error(f"No stakes found for coldkey ss58: ({coldkey_address})")
        raise typer.Exit()

    if live:
        # Select one hokkey for live monitoring
        if len(hotkeys_to_substakes) > 1:
            console.print(
                "\n[bold]Multiple hotkeys found. Please select one for live monitoring:[/bold]"
            )
            for idx, hotkey in enumerate(hotkeys_to_substakes.keys()):
                name = (
                    f"{registered_delegate_info[hotkey].display} ({hotkey})"
                    if hotkey in registered_delegate_info
                    else hotkey
                )
                console.print(f"[{idx}] [{COLOR_PALETTE['GENERAL']['HEADER']}]{name}")

            selected_idx = Prompt.ask(
                "Enter hotkey index",
                choices=[str(i) for i in range(len(hotkeys_to_substakes))],
            )
            selected_hotkey = list(hotkeys_to_substakes.keys())[int(selected_idx)]
            selected_stakes = hotkeys_to_substakes[selected_hotkey]
        else:
            selected_hotkey = list(hotkeys_to_substakes.keys())[0]
            selected_stakes = hotkeys_to_substakes[selected_hotkey]

        hotkey_name = (
            f"{registered_delegate_info[selected_hotkey].display} ({selected_hotkey})"
            if selected_hotkey in registered_delegate_info
            else selected_hotkey
        )

        refresh_interval = 10  # seconds
        progress = Progress(
            TextColumn("[progress.description]{task.description}"),
            BarColumn(bar_width=20),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            console=console,
        )
        progress_task = progress.add_task("Updating: ", total=refresh_interval)

        previous_block = None
        current_block = None
        previous_data = None

        with Live(console=console, screen=True, auto_refresh=True) as live:
            try:
                while True:
                    block_hash = await subtensor.substrate.get_chain_head()
                    (
                        sub_stakes,
                        registered_delegate_info,
                        dynamic_info_,
                    ) = await get_stake_data(block_hash)
                    selected_stakes = [
                        stake
                        for stake in sub_stakes
                        if stake.hotkey_ss58 == selected_hotkey
                    ]

                    block_number = await subtensor.substrate.get_block_number(None)

                    previous_block = current_block
                    current_block = block_number
                    new_blocks = (
                        "N/A"
                        if previous_block is None
                        else str(current_block - previous_block)
                    )

                    table, current_data = create_live_table(
                        selected_stakes,
                        registered_delegate_info,
                        dynamic_info,
                        hotkey_name,
                        previous_data,
                    )

                    previous_data = current_data
                    progress.reset(progress_task)
                    start_time = asyncio.get_event_loop().time()

                    block_info = (
                        f"Previous: [dark_sea_green]{previous_block}[/dark_sea_green] "
                        f"Current: [dark_sea_green]{current_block}[/dark_sea_green] "
                        f"Diff: [dark_sea_green]{new_blocks}[/dark_sea_green]"
                    )

                    message = f"\nLive stake view - Press [bold red]Ctrl+C[/bold red] to exit\n{block_info}"
                    live_render = Group(message, progress, table)
                    live.update(live_render)

                    while not progress.finished:
                        await asyncio.sleep(0.1)
                        elapsed = asyncio.get_event_loop().time() - start_time
                        progress.update(
                            progress_task, completed=min(elapsed, refresh_interval)
                        )

            except KeyboardInterrupt:
                console.print("\n[bold]Stopped live updates[/bold]")
                return

    else:
        # Iterate over each hotkey and make a table
        counter = 0
        num_hotkeys = len(hotkeys_to_substakes)
        all_hotkeys_total_global_tao = Balance(0)
        all_hotkeys_total_tao_value = Balance(0)
        for hotkey in hotkeys_to_substakes.keys():
            counter += 1
            stake, value = create_table(hotkey, hotkeys_to_substakes[hotkey])
            all_hotkeys_total_global_tao += stake
            all_hotkeys_total_tao_value += value

            if num_hotkeys > 1 and counter < num_hotkeys and prompt:
                console.print("\nPress Enter to continue to the next hotkey...")
                input()

        total_tao_value = (
            f"τ {millify_tao(all_hotkeys_total_tao_value.tao)}"
            if not verbose
            else all_hotkeys_total_tao_value
        )
        total_tao_ownership = (
            f"τ {millify_tao(all_hotkeys_total_global_tao.tao)}"
            if not verbose
            else all_hotkeys_total_global_tao
        )

        console.print("\n\n")
        console.print(
            f"Wallet:\n"
            f"  Coldkey SS58: [{COLOR_PALETTE['GENERAL']['COLDKEY']}]{coldkey_address}[/{COLOR_PALETTE['GENERAL']['COLDKEY']}]\n"
            f"  Free Balance: [{COLOR_PALETTE['GENERAL']['BALANCE']}]{balance[coldkey_address]}[/{COLOR_PALETTE['GENERAL']['BALANCE']}]\n"
            f"  Total TAO ({Balance.unit}): [{COLOR_PALETTE['GENERAL']['BALANCE']}]{total_tao_ownership}[/{COLOR_PALETTE['GENERAL']['BALANCE']}]\n"
            f"  Total Value ({Balance.unit}): [{COLOR_PALETTE['GENERAL']['BALANCE']}]{total_tao_value}[/{COLOR_PALETTE['GENERAL']['BALANCE']}]"
        )
        if not sub_stakes:
            console.print(
                f"\n[blue]No stakes found for coldkey ss58: ({coldkey_address})"
            )
        else:
            # TODO: Temporarily returning till we update docs
            return
            display_table = Prompt.ask(
                "\nPress Enter to view column descriptions or type 'q' to skip:",
                choices=["", "q"],
                default="",
                show_choices=True,
            ).lower()

            if display_table == "q":
                console.print(
                    f"[{COLOR_PALETTE['GENERAL']['SUBHEADING_EXTRA_1']}]Column descriptions skipped."
                )
            else:
                header = """
            [bold white]Description[/bold white]: Each table displays information about stake associated with a hotkey. The columns are as follows:
            """
                console.print(header)
                description_table = Table(
                    show_header=False, box=box.SIMPLE, show_edge=False, show_lines=True
                )

                fields = [
                    ("[bold tan]Netuid[/bold tan]", "The netuid of the subnet."),
                    (
                        "[bold tan]Symbol[/bold tan]",
                        "The symbol for the subnet's dynamic TAO token.",
                    ),
                    (
                        "[bold tan]Stake (α)[/bold tan]",
                        "The stake amount this hotkey holds in the subnet, expressed in subnet's alpha token currency. This can change whenever staking or unstaking occurs on this hotkey in this subnet. \nFor more, see [blue]https://docs.bittensor.com/dynamic-tao/dtao-guide#staking[/blue].",
                    ),
                    (
                        "[bold tan]TAO Reserves (τ_in)[/bold tan]",
                        'Number of TAO in the TAO reserves of the pool for this subnet. Attached to every subnet is a subnet pool, containing a TAO reserve and the alpha reserve. See also "Alpha Pool (α_in)" description. This can change every block. \nFor more, see [blue]https://docs.bittensor.com/dynamic-tao/dtao-guide#subnet-pool[/blue].',
                    ),
                    (
                        "[bold tan]Alpha Reserves (α_in)[/bold tan]",
                        "Number of subnet alpha tokens in the alpha reserves of the pool for this subnet. This reserve, together with 'TAO Pool (τ_in)', form the subnet pool for every subnet. This can change every block. \nFor more, see [blue]https://docs.bittensor.com/dynamic-tao/dtao-guide#subnet-pool[/blue].",
                    ),
                    (
                        "[bold tan]RATE (τ_in/α_in)[/bold tan]",
                        "Exchange rate between TAO and subnet dTAO token. Calculated as the reserve ratio: (TAO Pool (τ_in) / Alpha Pool (α_in)). Note that the terms relative price, alpha token price, alpha price are the same as exchange rate. This rate can change every block. \nFor more, see [blue]https://docs.bittensor.com/dynamic-tao/dtao-guide#rate-%CF%84_in%CE%B1_in[/blue].",
                    ),
                    (
                        "[bold tan]Alpha out (α_out)[/bold tan]",
                        "Total stake in the subnet, expressed in subnet's alpha token currency. This is the sum of all the stakes present in all the hotkeys in this subnet. This can change every block. \nFor more, see [blue]https://docs.bittensor.com/dynamic-tao/dtao-guide#stake-%CE%B1_out-or-alpha-out-%CE%B1_out",
                    ),
                    (
                        "[bold tan]TAO Equiv (τ_in x α/α_out)[/bold tan]",
                        'TAO-equivalent value of the hotkeys stake α (i.e., Stake(α)). Calculated as (TAO Reserves(τ_in) x (Stake(α) / ALPHA Out(α_out)). This value is weighted with (1-γ), where γ is the local weight coefficient, and used in determining the overall stake weight of the hotkey in this subnet. Also see the "Local weight coeff (γ)" column of "btcli subnet list" command output. This can change every block. \nFor more, see [blue]https://docs.bittensor.com/dynamic-tao/dtao-guide#local-weight-or-tao-equiv-%CF%84_in-x-%CE%B1%CE%B1_out[/blue].',
                    ),
                    (
                        "[bold tan]Exchange Value (α x τ/α)[/bold tan]",
                        "This is the potential τ you will receive, without considering slippage, if you unstake from this hotkey now on this subnet. See Swap(α → τ) column description. Note: The TAO Equiv(τ_in x α/α_out) indicates validator stake weight while this Exchange Value shows τ you will receive if you unstake now. This can change every block. \nFor more, see [blue]https://docs.bittensor.com/dynamic-tao/dtao-guide#exchange-value-%CE%B1-x-%CF%84%CE%B1[/blue].",
                    ),
                    (
                        "[bold tan]Swap (α → τ)[/bold tan]",
                        "This is the actual τ you will receive, after factoring in the slippage charge, if you unstake from this hotkey now on this subnet. The slippage is calculated as 1 - (Swap(α → τ)/Exchange Value(α x τ/α)), and is displayed in brackets. This can change every block. \nFor more, see [blue]https://docs.bittensor.com/dynamic-tao/dtao-guide#swap-%CE%B1--%CF%84[/blue].",
                    ),
                    (
                        "[bold tan]Registered[/bold tan]",
                        "Indicates if the hotkey is registered in this subnet or not. \nFor more, see [blue]https://docs.bittensor.com/learn/anatomy-of-incentive-mechanism#tempo[/blue].",
                    ),
                    (
                        "[bold tan]Emission (α/block)[/bold tan]",
                        "Shows the portion of the one α/block emission into this subnet that is received by this hotkey, according to YC2 in this subnet. This can change every block. \nFor more, see [blue]https://docs.bittensor.com/dynamic-tao/dtao-guide#emissions[/blue].",
                    ),
                ]

                description_table.add_column(
                    "Field",
                    no_wrap=True,
                    style="bold tan",
                )
                description_table.add_column("Description", overflow="fold")
                for field_name, description in fields:
                    description_table.add_row(field_name, description)
                console.print(description_table)
