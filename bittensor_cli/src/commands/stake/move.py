import asyncio

from typing import TYPE_CHECKING

from bittensor_wallet import Wallet
from rich.table import Table
from rich.prompt import Confirm, Prompt

from bittensor_cli.src import COLOR_PALETTE
from bittensor_cli.src.bittensor.balances import Balance
from bittensor_cli.src.bittensor.utils import (
    console,
    err_console,
    print_error,
    format_error_message,
    group_subnets,
    get_subnet_name,
    unlock_key,
)

if TYPE_CHECKING:
    from bittensor_cli.src.bittensor.subtensor_interface import SubtensorInterface

MIN_STAKE_FEE = Balance.from_rao(50_000)


# Helpers
async def display_stake_movement_cross_subnets(
    subtensor: "SubtensorInterface",
    origin_netuid: int,
    destination_netuid: int,
    origin_hotkey: str,
    destination_hotkey: str,
    amount_to_move: Balance,
    stake_fee: Balance,
) -> tuple[Balance, str]:
    """Calculate and display stake movement information"""

    if origin_netuid == destination_netuid:
        subnet = await subtensor.subnet(origin_netuid)
        received_amount_tao = subnet.alpha_to_tao(amount_to_move)
        received_amount_tao -= stake_fee

        if received_amount_tao < Balance.from_tao(0):
            print_error("Not enough Alpha to pay the transaction fee.")
            raise ValueError

        received_amount = subnet.tao_to_alpha(received_amount_tao)
        price = subnet.price.tao
        price_str = (
            str(float(price))
            + f"({Balance.get_unit(0)}/{Balance.get_unit(origin_netuid)})"
        )
    else:
        dynamic_origin, dynamic_destination = await asyncio.gather(
            subtensor.subnet(origin_netuid),
            subtensor.subnet(destination_netuid),
        )
        price_origin = dynamic_origin.price.tao
        price_destination = dynamic_destination.price.tao
        rate = price_origin / (price_destination or 1)

        received_amount_tao = dynamic_origin.alpha_to_tao(amount_to_move)
        received_amount_tao -= stake_fee
        received_amount = dynamic_destination.tao_to_alpha(received_amount_tao)
        received_amount.set_unit(destination_netuid)

        if received_amount < Balance.from_tao(0):
            print_error("Not enough Alpha to pay the transaction fee.")
            raise ValueError

        price_str = (
            f"{rate:.5f}"
            + f"({Balance.get_unit(destination_netuid)}/{Balance.get_unit(origin_netuid)})"
        )

    # Create and display table
    table = Table(
        title=(
            f"\n[{COLOR_PALETTE['GENERAL']['HEADER']}]"
            f"Moving stake from: "
            f"[{COLOR_PALETTE['GENERAL']['SUBHEADING']}]{Balance.get_unit(origin_netuid)}(Netuid: {origin_netuid})"
            f"[/{COLOR_PALETTE['GENERAL']['SUBHEADING']}] "
            f"to: "
            f"[{COLOR_PALETTE['GENERAL']['SUBHEADING']}]{Balance.get_unit(destination_netuid)}(Netuid: {destination_netuid})"
            f"[/{COLOR_PALETTE['GENERAL']['SUBHEADING']}]\nNetwork: {subtensor.network}\n"
            f"[/{COLOR_PALETTE['GENERAL']['HEADER']}]"
        ),
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
        "origin netuid", justify="center", style=COLOR_PALETTE["GENERAL"]["SYMBOL"]
    )
    table.add_column(
        "origin hotkey", justify="center", style=COLOR_PALETTE["GENERAL"]["HOTKEY"]
    )
    table.add_column(
        "dest netuid", justify="center", style=COLOR_PALETTE["GENERAL"]["SYMBOL"]
    )
    table.add_column(
        "dest hotkey", justify="center", style=COLOR_PALETTE["GENERAL"]["HOTKEY"]
    )
    table.add_column(
        f"amount ({Balance.get_unit(origin_netuid)})",
        justify="center",
        style=COLOR_PALETTE["STAKE"]["TAO"],
    )
    table.add_column(
        f"rate ({Balance.get_unit(destination_netuid)}/{Balance.get_unit(origin_netuid)})",
        justify="center",
        style=COLOR_PALETTE["POOLS"]["RATE"],
    )
    table.add_column(
        f"received ({Balance.get_unit(destination_netuid)})",
        justify="center",
        style=COLOR_PALETTE["POOLS"]["TAO_EQUIV"],
    )
    table.add_column(
        f"Fee ({Balance.get_unit(origin_netuid)})",
        justify="center",
        style=COLOR_PALETTE["STAKE"]["STAKE_AMOUNT"],
    )

    table.add_row(
        f"{Balance.get_unit(origin_netuid)}({origin_netuid})",
        f"{origin_hotkey[:3]}...{origin_hotkey[-3:]}",
        f"{Balance.get_unit(destination_netuid)}({destination_netuid})",
        f"{destination_hotkey[:3]}...{destination_hotkey[-3:]}",
        str(amount_to_move),
        price_str,
        str(received_amount),
        str(stake_fee.set_unit(origin_netuid)),
    )

    console.print(table)

    return received_amount, price_str


def prompt_stake_amount(
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
            f"\nEnter the amount to {action_name} "
            f"[{COLOR_PALETTE['STAKE']['STAKE_AMOUNT']}]{Balance.get_unit(netuid)}[/{COLOR_PALETTE['STAKE']['STAKE_AMOUNT']}] "
            f"[{COLOR_PALETTE['STAKE']['STAKE_AMOUNT']}](max: {current_balance})[/{COLOR_PALETTE['STAKE']['STAKE_AMOUNT']}] "
            f"or "
            f"[{COLOR_PALETTE['STAKE']['STAKE_AMOUNT']}]'all'[/{COLOR_PALETTE['STAKE']['STAKE_AMOUNT']}] "
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
                    f"[{COLOR_PALETTE['STAKE']['STAKE_AMOUNT']}]{current_balance}[/{COLOR_PALETTE['STAKE']['STAKE_AMOUNT']}]"
                    f"[/red]"
                )
                continue
            return Balance.from_tao(amount), False
        except ValueError:
            console.print("[red]Please enter a valid number or 'all'[/red]")


async def stake_move_transfer_selection(
    subtensor: "SubtensorInterface",
    wallet: Wallet,
):
    """Selection interface for moving stakes between hotkeys and subnets."""
    stakes, ck_hk_identities, old_identities = await asyncio.gather(
        subtensor.get_stake_for_coldkey(coldkey_ss58=wallet.coldkeypub.ss58_address),
        subtensor.fetch_coldkey_hotkey_identities(),
        subtensor.get_delegate_identities(),
    )

    hotkey_stakes = {}
    for stake in stakes:
        if stake.stake.tao > 0:
            hotkey = stake.hotkey_ss58
            netuid = stake.netuid
            stake_balance = stake.stake
            hotkey_stakes.setdefault(hotkey, {})[netuid] = stake_balance

    if not hotkey_stakes:
        print_error("You have no stakes to move.")
        raise ValueError

    # Display hotkeys with stakes
    table = Table(
        title=f"\n[{COLOR_PALETTE['GENERAL']['HEADER']}]Hotkeys with Stakes\n",
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

    hotkeys_info = []
    for idx, (hotkey_ss58, netuid_stakes) in enumerate(hotkey_stakes.items()):
        if hk_identity := ck_hk_identities["hotkeys"].get(hotkey_ss58):
            hotkey_name = hk_identity.get("identity", {}).get(
                "name", ""
            ) or hk_identity.get("display", "~")
        elif old_identity := old_identities.get(hotkey_ss58):
            hotkey_name = old_identity.display
        else:
            hotkey_name = "~"
        hotkeys_info.append(
            {
                "index": idx,
                "identity": hotkey_name,
                "hotkey_ss58": hotkey_ss58,
                "netuids": list(netuid_stakes.keys()),
                "stakes": netuid_stakes,
            }
        )
        table.add_row(
            str(idx),
            hotkey_name,
            group_subnets([n for n in netuid_stakes.keys()]),
            hotkey_ss58,
        )

    console.print("\n", table)

    # Select origin hotkey
    origin_idx = Prompt.ask(
        "\nEnter the index of the hotkey you want to move stake from",
        choices=[str(i) for i in range(len(hotkeys_info))],
    )
    origin_hotkey_info = hotkeys_info[int(origin_idx)]
    origin_hotkey_ss58 = origin_hotkey_info["hotkey_ss58"]

    # Display available netuids for selected hotkey
    table = Table(
        title=f"\n[{COLOR_PALETTE['GENERAL']['HEADER']}]Available Stakes for Hotkey\n[/{COLOR_PALETTE['GENERAL']['HEADER']}]"
        f"[{COLOR_PALETTE['GENERAL']['HOTKEY']}]{origin_hotkey_ss58}[/{COLOR_PALETTE['GENERAL']['HOTKEY']}]\n",
        show_edge=False,
        header_style="bold white",
        border_style="bright_black",
        title_justify="center",
        width=len(origin_hotkey_ss58) + 20,
    )
    table.add_column("Netuid", style="cyan")
    table.add_column("Stake Amount", style=COLOR_PALETTE["STAKE"]["STAKE_AMOUNT"])

    available_netuids = []
    for netuid in origin_hotkey_info["netuids"]:
        stake = origin_hotkey_info["stakes"][netuid]
        if stake.tao > 0:
            available_netuids.append(netuid)
            table.add_row(str(netuid), str(stake))

    console.print("\n", table)

    # Select origin netuid
    origin_netuid = Prompt.ask(
        "\nEnter the netuid you want to move stake from",
        choices=[str(netuid) for netuid in available_netuids],
    )
    origin_netuid = int(origin_netuid)
    origin_stake = origin_hotkey_info["stakes"][origin_netuid]

    # Ask for amount to move
    amount, stake_all = prompt_stake_amount(origin_stake, origin_netuid, "move")

    all_subnets = sorted(await subtensor.get_all_subnet_netuids())
    destination_netuid = Prompt.ask(
        "\nEnter the netuid of the subnet you want to move stake to"
        + f" ([dim]{group_subnets(all_subnets)}[/dim])",
        choices=[str(netuid) for netuid in all_subnets],
        show_choices=False,
    )

    return {
        "origin_hotkey": origin_hotkey_ss58,
        "origin_netuid": origin_netuid,
        "amount": amount.tao,
        "stake_all": stake_all,
        "destination_netuid": int(destination_netuid),
    }


async def stake_swap_selection(
    subtensor: "SubtensorInterface",
    wallet: Wallet,
) -> dict:
    """Selection interface for swapping stakes between subnets."""
    block_hash = await subtensor.substrate.get_chain_head()
    stakes, all_subnets = await asyncio.gather(
        subtensor.get_stake_for_coldkey(
            coldkey_ss58=wallet.coldkeypub.ss58_address, block_hash=block_hash
        ),
        subtensor.all_subnets(block_hash=block_hash),
    )
    subnet_dict = {di.netuid: di for di in all_subnets}

    # Filter stakes for this hotkey
    hotkey_stakes = {}
    for stake in stakes:
        if stake.hotkey_ss58 == wallet.hotkey.ss58_address and stake.stake.tao > 0:
            hotkey_stakes[stake.netuid] = {
                "stake": stake.stake,
                "is_registered": stake.is_registered,
            }

    if not hotkey_stakes:
        print_error(f"No stakes found for hotkey: {wallet.hotkey_str}")
        raise ValueError

    # Display available stakes
    table = Table(
        title=f"\n[{COLOR_PALETTE['GENERAL']['HEADER']}]Available Stakes for Hotkey\n[/{COLOR_PALETTE['GENERAL']['HEADER']}]"
        f"[{COLOR_PALETTE['GENERAL']['HOTKEY']}]{wallet.hotkey_str}: {wallet.hotkey.ss58_address}[/{COLOR_PALETTE['GENERAL']['HOTKEY']}]\n",
        show_edge=False,
        header_style="bold white",
        border_style="bright_black",
        title_justify="center",
        width=len(wallet.hotkey.ss58_address) + 20,
    )

    table.add_column("Index", justify="right", style="cyan")
    table.add_column("Netuid", style=COLOR_PALETTE["GENERAL"]["NETUID"])
    table.add_column("Name", style="cyan", justify="left")
    table.add_column("Stake Amount", style=COLOR_PALETTE["STAKE"]["STAKE_AMOUNT"])
    table.add_column("Registered", justify="center")

    available_netuids = []
    for idx, (netuid, stake_info) in enumerate(sorted(hotkey_stakes.items())):
        subnet_info = subnet_dict[netuid]
        subnet_name_cell = (
            f"[{COLOR_PALETTE['GENERAL']['SYMBOL']}]{subnet_info.symbol if netuid != 0 else 'τ'}[/{COLOR_PALETTE['GENERAL']['SYMBOL']}]"
            f" {get_subnet_name(subnet_info)}"
        )

        available_netuids.append(netuid)
        table.add_row(
            str(idx),
            str(netuid),
            subnet_name_cell,
            str(stake_info["stake"]),
            "[dark_sea_green3]YES"
            if stake_info["is_registered"]
            else f"[{COLOR_PALETTE['STAKE']['NOT_REGISTERED']}]NO",
        )

    console.print("\n", table)

    # Select origin netuid
    origin_idx = Prompt.ask(
        "\nEnter the index of the subnet you want to swap stake from",
        choices=[str(i) for i in range(len(available_netuids))],
    )
    origin_netuid = available_netuids[int(origin_idx)]
    origin_stake = hotkey_stakes[origin_netuid]["stake"]

    # Ask for amount to swap
    amount, _ = prompt_stake_amount(origin_stake, origin_netuid, "swap")

    all_netuids = sorted(await subtensor.get_all_subnet_netuids())
    destination_choices = [
        str(netuid) for netuid in all_netuids if netuid != origin_netuid
    ]
    destination_netuid = Prompt.ask(
        "\nEnter the netuid of the subnet you want to swap stake to"
        + f" ([dim]{group_subnets(all_netuids)}[/dim])",
        choices=destination_choices,
        show_choices=False,
    )

    return {
        "origin_netuid": origin_netuid,
        "amount": amount.tao,
        "destination_netuid": int(destination_netuid),
    }


# Commands
async def move_stake(
    subtensor: "SubtensorInterface",
    wallet: Wallet,
    origin_netuid: int,
    origin_hotkey: str,
    destination_netuid: int,
    destination_hotkey: str,
    amount: float,
    stake_all: bool,
    era: int,
    interactive_selection: bool = False,
    prompt: bool = True,
) -> bool:
    if interactive_selection:
        try:
            selection = await stake_move_transfer_selection(subtensor, wallet)
        except ValueError:
            return False
        origin_hotkey = selection["origin_hotkey"]
        origin_netuid = selection["origin_netuid"]
        amount = selection["amount"]
        stake_all = selection["stake_all"]
        destination_netuid = selection["destination_netuid"]

    # Get the wallet stake balances.
    block_hash = await subtensor.substrate.get_chain_head()
    origin_stake_balance, destination_stake_balance = await asyncio.gather(
        subtensor.get_stake(
            coldkey_ss58=wallet.coldkeypub.ss58_address,
            hotkey_ss58=origin_hotkey,
            netuid=origin_netuid,
            block_hash=block_hash,
        ),
        subtensor.get_stake(
            coldkey_ss58=wallet.coldkeypub.ss58_address,
            hotkey_ss58=destination_hotkey,
            netuid=destination_netuid,
            block_hash=block_hash,
        ),
    )

    if origin_stake_balance.tao == 0:
        print_error(
            f"Your balance is "
            f"[{COLOR_PALETTE['POOLS']['TAO']}]0[/{COLOR_PALETTE['POOLS']['TAO']}] "
            f"in Netuid: "
            f"[{COLOR_PALETTE['GENERAL']['SUBHEADING']}]{origin_netuid}[/{COLOR_PALETTE['GENERAL']['SUBHEADING']}]"
        )
        return False

    console.print(
        f"\nOrigin Netuid: "
        f"[{COLOR_PALETTE['GENERAL']['SUBHEADING']}]{origin_netuid}[/{COLOR_PALETTE['GENERAL']['SUBHEADING']}], "
        f"Origin stake: "
        f"[{COLOR_PALETTE['POOLS']['TAO']}]{origin_stake_balance}[/{COLOR_PALETTE['POOLS']['TAO']}]"
    )
    console.print(
        f"Destination netuid: "
        f"[{COLOR_PALETTE['GENERAL']['SUBHEADING']}]{destination_netuid}[/{COLOR_PALETTE['GENERAL']['SUBHEADING']}], "
        f"Destination stake: "
        f"[{COLOR_PALETTE['POOLS']['TAO']}]{destination_stake_balance}[/{COLOR_PALETTE['POOLS']['TAO']}]\n"
    )

    # Determine the amount we are moving.
    if amount:
        amount_to_move_as_balance = Balance.from_tao(amount)
    elif stake_all:
        amount_to_move_as_balance = origin_stake_balance
    else:
        amount_to_move_as_balance, _ = prompt_stake_amount(
            origin_stake_balance, origin_netuid, "move"
        )

    # Check enough to move.
    amount_to_move_as_balance.set_unit(origin_netuid)
    if amount_to_move_as_balance > origin_stake_balance:
        err_console.print(
            f"[red]Not enough stake[/red]:\n"
            f" Stake balance: [{COLOR_PALETTE['STAKE']['STAKE_AMOUNT']}]"
            f"{origin_stake_balance}[/{COLOR_PALETTE['STAKE']['STAKE_AMOUNT']}]"
            f" < Moving amount: [{COLOR_PALETTE['STAKE']['STAKE_AMOUNT']}]"
            f"{amount_to_move_as_balance}[/{COLOR_PALETTE['STAKE']['STAKE_AMOUNT']}]"
        )
        return False

    stake_fee = await subtensor.get_stake_fee(
        origin_hotkey_ss58=origin_hotkey,
        origin_netuid=origin_netuid,
        origin_coldkey_ss58=wallet.coldkeypub.ss58_address,
        destination_hotkey_ss58=destination_hotkey,
        destination_netuid=destination_netuid,
        destination_coldkey_ss58=wallet.coldkeypub.ss58_address,
        amount=amount_to_move_as_balance.rao,
    )

    # Display stake movement details
    if prompt:
        try:
            await display_stake_movement_cross_subnets(
                subtensor=subtensor,
                origin_netuid=origin_netuid,
                destination_netuid=destination_netuid,
                origin_hotkey=origin_hotkey,
                destination_hotkey=destination_hotkey,
                amount_to_move=amount_to_move_as_balance,
                stake_fee=stake_fee,
            )
        except ValueError:
            return False
        if not Confirm.ask("Would you like to continue?"):
            return False

    # Perform moving operation.
    if not unlock_key(wallet).success:
        return False
    with console.status(
        f"\n:satellite: Moving [blue]{amount_to_move_as_balance}[/blue] from [blue]{origin_hotkey}[/blue] on netuid: [blue]{origin_netuid}[/blue] \nto "
        f"[blue]{destination_hotkey}[/blue] on netuid: [blue]{destination_netuid}[/blue] ..."
    ):
        call = await subtensor.substrate.compose_call(
            call_module="SubtensorModule",
            call_function="move_stake",
            call_params={
                "origin_hotkey": origin_hotkey,
                "origin_netuid": origin_netuid,
                "destination_hotkey": destination_hotkey,
                "destination_netuid": destination_netuid,
                "alpha_amount": amount_to_move_as_balance.rao,
            },
        )
        extrinsic = await subtensor.substrate.create_signed_extrinsic(
            call=call, keypair=wallet.coldkey, era={"period": era}
        )
        response = await subtensor.substrate.submit_extrinsic(
            extrinsic, wait_for_inclusion=True, wait_for_finalization=False
        )

    if not prompt:
        console.print(":white_heavy_check_mark: [green]Sent[/green]")
        return True
    else:
        if not await response.is_success:
            err_console.print(
                f"\n:cross_mark: [red]Failed[/red] with error:"
                f" {format_error_message(await response.error_message)}"
            )
            return False
        else:
            console.print(
                ":white_heavy_check_mark: [dark_sea_green3]Stake moved.[/dark_sea_green3]"
            )
            block_hash = await subtensor.substrate.get_chain_head()
            (
                new_origin_stake_balance,
                new_destination_stake_balance,
            ) = await asyncio.gather(
                subtensor.get_stake(
                    coldkey_ss58=wallet.coldkeypub.ss58_address,
                    hotkey_ss58=origin_hotkey,
                    netuid=origin_netuid,
                    block_hash=block_hash,
                ),
                subtensor.get_stake(
                    coldkey_ss58=wallet.coldkeypub.ss58_address,
                    hotkey_ss58=destination_hotkey,
                    netuid=destination_netuid,
                    block_hash=block_hash,
                ),
            )

            console.print(
                f"Origin Stake:\n  [blue]{origin_stake_balance}[/blue] :arrow_right: "
                f"[{COLOR_PALETTE['STAKE']['STAKE_AMOUNT']}]{new_origin_stake_balance}"
            )
            console.print(
                f"Destination Stake:\n  [blue]{destination_stake_balance}[/blue] :arrow_right: "
                f"[{COLOR_PALETTE['STAKE']['STAKE_AMOUNT']}]{new_destination_stake_balance}"
            )
            return True


async def transfer_stake(
    wallet: Wallet,
    subtensor: "SubtensorInterface",
    amount: float,
    origin_hotkey: str,
    origin_netuid: int,
    dest_netuid: int,
    dest_coldkey_ss58: str,
    era: int,
    interactive_selection: bool = False,
    stake_all: bool = False,
    prompt: bool = True,
) -> bool:
    """Transfers stake from one network to another.

    Args:
        wallet (Wallet): Bittensor wallet object.
        subtensor (SubtensorInterface): Subtensor interface instance.
        amount (float): Amount to transfer.
        origin_hotkey (str): The hotkey SS58 to transfer the stake from.
        origin_netuid (int): The netuid to transfer stake from.
        dest_netuid (int): The netuid to transfer stake to.
        dest_coldkey_ss58 (str): The destination coldkey to transfer stake to.
        interactive_selection (bool): If true, prompts for selection of origin and destination subnets.
        prompt (bool): If true, prompts for confirmation before executing transfer.

    Returns:
        bool: True if transfer was successful, False otherwise.
    """
    if interactive_selection:
        selection = await stake_move_transfer_selection(subtensor, wallet)
        origin_netuid = selection["origin_netuid"]
        amount = selection["amount"]
        dest_netuid = selection["destination_netuid"]
        stake_all = selection["stake_all"]
        origin_hotkey = selection["origin_hotkey"]

    # Check if both subnets exist
    block_hash = await subtensor.substrate.get_chain_head()
    dest_exists, origin_exists = await asyncio.gather(
        subtensor.subnet_exists(netuid=dest_netuid, block_hash=block_hash),
        subtensor.subnet_exists(netuid=origin_netuid, block_hash=block_hash),
    )
    if not dest_exists:
        err_console.print(f"[red]Subnet {dest_netuid} does not exist[/red]")
        return False

    if not origin_exists:
        err_console.print(f"[red]Subnet {origin_netuid} does not exist[/red]")
        return False

    # Get current stake balances
    with console.status(f"Retrieving stake data from {subtensor.network}..."):
        current_stake = await subtensor.get_stake(
            coldkey_ss58=wallet.coldkeypub.ss58_address,
            hotkey_ss58=origin_hotkey,
            netuid=origin_netuid,
        )
        current_dest_stake = await subtensor.get_stake(
            coldkey_ss58=dest_coldkey_ss58,
            hotkey_ss58=origin_hotkey,
            netuid=dest_netuid,
        )

    if current_stake.tao == 0:
        err_console.print(
            f"[red]No stake found for hotkey: {origin_hotkey} on netuid: {origin_netuid}[/red]"
        )
        return False

    if amount:
        amount_to_transfer = Balance.from_tao(amount).set_unit(origin_netuid)
    elif stake_all:
        amount_to_transfer = current_stake
    else:
        amount_to_transfer, _ = prompt_stake_amount(
            current_stake, origin_netuid, "transfer"
        )

    # Check if enough stake to transfer
    if amount_to_transfer > current_stake:
        err_console.print(
            f"[red]Not enough stake to transfer[/red]:\n"
            f"Stake balance: [{COLOR_PALETTE['STAKE']['STAKE_AMOUNT']}]{current_stake}[/{COLOR_PALETTE['STAKE']['STAKE_AMOUNT']}] < "
            f"Transfer amount: [{COLOR_PALETTE['STAKE']['STAKE_AMOUNT']}]{amount_to_transfer}[/{COLOR_PALETTE['STAKE']['STAKE_AMOUNT']}]"
        )
        return False

    stake_fee = await subtensor.get_stake_fee(
        origin_hotkey_ss58=origin_hotkey,
        origin_netuid=origin_netuid,
        origin_coldkey_ss58=wallet.coldkeypub.ss58_address,
        destination_hotkey_ss58=origin_hotkey,
        destination_netuid=dest_netuid,
        destination_coldkey_ss58=dest_coldkey_ss58,
        amount=amount_to_transfer.rao,
    )

    # Display stake movement details
    if prompt:
        try:
            await display_stake_movement_cross_subnets(
                subtensor=subtensor,
                origin_netuid=origin_netuid,
                destination_netuid=dest_netuid,
                origin_hotkey=origin_hotkey,
                destination_hotkey=origin_hotkey,
                amount_to_move=amount_to_transfer,
                stake_fee=stake_fee,
            )
        except ValueError:
            return False

        if not Confirm.ask("Would you like to continue?"):
            return False

    # Perform transfer operation
    if not unlock_key(wallet).success:
        return False

    with console.status("\n:satellite: Transferring stake ..."):
        call = await subtensor.substrate.compose_call(
            call_module="SubtensorModule",
            call_function="transfer_stake",
            call_params={
                "destination_coldkey": dest_coldkey_ss58,
                "hotkey": origin_hotkey,
                "origin_netuid": origin_netuid,
                "destination_netuid": dest_netuid,
                "alpha_amount": amount_to_transfer.rao,
            },
        )

        extrinsic = await subtensor.substrate.create_signed_extrinsic(
            call=call, keypair=wallet.coldkey, era={"period": era}
        )

        response = await subtensor.substrate.submit_extrinsic(
            extrinsic, wait_for_inclusion=True, wait_for_finalization=False
        )

    if not prompt:
        console.print(":white_heavy_check_mark: [green]Sent[/green]")
        return True

    if not await response.is_success:
        err_console.print(
            f":cross_mark: [red]Failed[/red] with error: "
            f"{format_error_message(await response.error_message)}"
        )
        return False

    # Get and display new stake balances
    new_stake, new_dest_stake = await asyncio.gather(
        subtensor.get_stake(
            coldkey_ss58=wallet.coldkeypub.ss58_address,
            hotkey_ss58=origin_hotkey,
            netuid=origin_netuid,
        ),
        subtensor.get_stake(
            coldkey_ss58=dest_coldkey_ss58,
            hotkey_ss58=origin_hotkey,
            netuid=dest_netuid,
        ),
    )

    console.print(
        f"Origin Stake:\n  [blue]{current_stake}[/blue] :arrow_right: "
        f"[{COLOR_PALETTE['STAKE']['STAKE_AMOUNT']}]{new_stake}"
    )
    console.print(
        f"Destination Stake:\n  [blue]{current_dest_stake}[/blue] :arrow_right: "
        f"[{COLOR_PALETTE['STAKE']['STAKE_AMOUNT']}]{new_dest_stake}"
    )
    return True


async def swap_stake(
    wallet: Wallet,
    subtensor: "SubtensorInterface",
    origin_netuid: int,
    destination_netuid: int,
    amount: float,
    swap_all: bool = False,
    era: int = 3,
    interactive_selection: bool = False,
    prompt: bool = True,
    wait_for_inclusion: bool = True,
    wait_for_finalization: bool = False,
) -> bool:
    """Swaps stake between subnets while keeping the same coldkey-hotkey pair ownership.

    Args:
        wallet (Wallet): The wallet to swap stake from.
        subtensor (SubtensorInterface): Subtensor interface instance.
        origin_netuid (int): The netuid from which stake is removed.
        destination_netuid (int): The netuid to which stake is added.
        amount (float): The amount to swap.
        interactive_selection (bool): If true, prompts for selection of origin and destination subnets.
        prompt (bool): If true, prompts for confirmation before executing swap.
        wait_for_inclusion (bool): If true, waits for the transaction to be included in a block.
        wait_for_finalization (bool): If true, waits for the transaction to be finalized.

    Returns:
        bool: True if the swap was successful, False otherwise.
    """
    hotkey_ss58 = wallet.hotkey.ss58_address
    if interactive_selection:
        try:
            selection = await stake_swap_selection(subtensor, wallet)
        except ValueError:
            return False
        origin_netuid = selection["origin_netuid"]
        amount = selection["amount"]
        destination_netuid = selection["destination_netuid"]

    # Check if both subnets exist
    block_hash = await subtensor.substrate.get_chain_head()
    dest_exists, origin_exists = await asyncio.gather(
        subtensor.subnet_exists(netuid=destination_netuid, block_hash=block_hash),
        subtensor.subnet_exists(netuid=origin_netuid, block_hash=block_hash),
    )
    if not dest_exists:
        err_console.print(f"[red]Subnet {destination_netuid} does not exist[/red]")
        return False

    if not origin_exists:
        err_console.print(f"[red]Subnet {origin_netuid} does not exist[/red]")
        return False

    # Get current stake balances
    with console.status(f"Retrieving stake data from {subtensor.network}..."):
        current_stake = await subtensor.get_stake(
            coldkey_ss58=wallet.coldkeypub.ss58_address,
            hotkey_ss58=hotkey_ss58,
            netuid=origin_netuid,
        )
        current_dest_stake = await subtensor.get_stake(
            coldkey_ss58=wallet.coldkeypub.ss58_address,
            hotkey_ss58=hotkey_ss58,
            netuid=destination_netuid,
        )

    if swap_all:
        amount_to_swap = current_stake.set_unit(origin_netuid)
    else:
        amount_to_swap = Balance.from_tao(amount).set_unit(origin_netuid)

    # Check if enough stake to swap
    if amount_to_swap > current_stake:
        err_console.print(
            f"[red]Not enough stake to swap[/red]:\n"
            f"Stake balance: [{COLOR_PALETTE['STAKE']['STAKE_AMOUNT']}]{current_stake}[/{COLOR_PALETTE['STAKE']['STAKE_AMOUNT']}] < "
            f"Swap amount: [{COLOR_PALETTE['STAKE']['STAKE_AMOUNT']}]{amount_to_swap}[/{COLOR_PALETTE['STAKE']['STAKE_AMOUNT']}]"
        )
        return False

    stake_fee = await subtensor.get_stake_fee(
        origin_hotkey_ss58=hotkey_ss58,
        origin_netuid=origin_netuid,
        origin_coldkey_ss58=wallet.coldkeypub.ss58_address,
        destination_hotkey_ss58=hotkey_ss58,
        destination_netuid=destination_netuid,
        destination_coldkey_ss58=wallet.coldkeypub.ss58_address,
        amount=amount_to_swap.rao,
    )

    # Display stake movement details
    if prompt:
        try:
            await display_stake_movement_cross_subnets(
                subtensor=subtensor,
                origin_netuid=origin_netuid,
                destination_netuid=destination_netuid,
                origin_hotkey=hotkey_ss58,
                destination_hotkey=hotkey_ss58,
                amount_to_move=amount_to_swap,
                stake_fee=stake_fee,
            )
        except ValueError:
            return False

        if not Confirm.ask("Would you like to continue?"):
            return False

    # Perform swap operation
    if not unlock_key(wallet).success:
        return False

    with console.status(
        f"\n:satellite: Swapping stake from netuid [blue]{origin_netuid}[/blue] "
        f"to netuid [blue]{destination_netuid}[/blue]..."
    ):
        call = await subtensor.substrate.compose_call(
            call_module="SubtensorModule",
            call_function="swap_stake",
            call_params={
                "hotkey": hotkey_ss58,
                "origin_netuid": origin_netuid,
                "destination_netuid": destination_netuid,
                "alpha_amount": amount_to_swap.rao,
            },
        )

        extrinsic = await subtensor.substrate.create_signed_extrinsic(
            call=call, keypair=wallet.coldkey, era={"period": era}
        )

        response = await subtensor.substrate.submit_extrinsic(
            extrinsic,
            wait_for_inclusion=wait_for_inclusion,
            wait_for_finalization=wait_for_finalization,
        )

    if not prompt:
        console.print(":white_heavy_check_mark: [green]Sent[/green]")
        return True

    if not await response.is_success:
        err_console.print(
            f":cross_mark: [red]Failed[/red] with error: "
            f"{format_error_message(await response.error_message)}"
        )
        return False

    # Get and display new stake balances
    new_stake, new_dest_stake = await asyncio.gather(
        subtensor.get_stake(
            coldkey_ss58=wallet.coldkeypub.ss58_address,
            hotkey_ss58=hotkey_ss58,
            netuid=origin_netuid,
        ),
        subtensor.get_stake(
            coldkey_ss58=wallet.coldkeypub.ss58_address,
            hotkey_ss58=hotkey_ss58,
            netuid=destination_netuid,
        ),
    )

    console.print(
        f"Origin Stake:\n  [blue]{current_stake}[/blue] :arrow_right: "
        f"[{COLOR_PALETTE['STAKE']['STAKE_AMOUNT']}]{new_stake}"
    )
    console.print(
        f"Destination Stake:\n  [blue]{current_dest_stake}[/blue] :arrow_right: "
        f"[{COLOR_PALETTE['STAKE']['STAKE_AMOUNT']}]{new_dest_stake}"
    )
    return True
