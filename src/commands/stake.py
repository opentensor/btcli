import asyncio
from typing import TYPE_CHECKING, Union

from bittensor_wallet import Wallet
from rich.prompt import Confirm
from rich.table import Table, Column
from substrateinterface.exceptions import SubstrateRequestException

from src import Constants
from src.bittensor.balances import Balance
from src.utils import (
    get_delegates_details_from_github,
    get_hotkey_wallets_for_wallet,
    get_coldkey_wallets_for_path,
    console,
    err_console,
    is_valid_ss58_address,
    float_to_u64,
)

if TYPE_CHECKING:
    from src.subtensor_interface import SubtensorInterface


# Helpers and Extrinsics


async def set_children_extrinsic(
    subtensor: "SubtensorInterface",
    wallet: Wallet,
    hotkey: str,
    netuid: int,
    children_with_proportions: list[tuple[float, str]],
    wait_for_inclusion: bool = True,
    wait_for_finalization: bool = False,
    prompt: bool = False,
) -> tuple[bool, str]:
    """
    Sets children hotkeys with proportions assigned from the parent.

    :param: subtensor: Subtensor endpoint to use.
    :param: wallet: Bittensor wallet object.
    :param: hotkey: Parent hotkey.
    :param: children_with_proportions: Children hotkeys.
    :param: netuid: Unique identifier of for the subnet.
    :param: wait_for_inclusion: If set, waits for the extrinsic to enter a block before returning `True`, or returns
                                `False` if the extrinsic fails to enter the block within the timeout.
    :param: wait_for_finalization: If set, waits for the extrinsic to be finalized on the chain before returning `
                                   `True`, or returns `False` if the extrinsic fails to be finalized within the timeout.
    :param: prompt: If `True`, the call waits for confirmation from the user before proceeding.

    :return: A tuple containing a success flag and an optional error message.
    """
    # Check if all children are being revoked
    all_revoked = all(prop == 0.0 for prop, _ in children_with_proportions)

    operation = "Revoke all children hotkeys" if all_revoked else "Set children hotkeys"

    # Ask before moving on.
    if prompt:
        if all_revoked:
            if not Confirm.ask(
                f"Do you want to revoke all children hotkeys for hotkey {hotkey}?"
            ):
                return False, "Operation Cancelled"
        else:
            if not Confirm.ask(
                "Do you want to set children hotkeys:\n[bold white]{}[/bold white]?".format(
                    "\n".join(
                        f"  {child[1]}: {child[0]}"
                        for child in children_with_proportions
                    )
                )
            ):
                return False, "Operation Cancelled"

    with console.status(
        f":satellite: {operation} on [white]{subtensor.network}[/white] ..."
    ):
        normalized_children = (
            prepare_child_proportions(children_with_proportions)
            if not all_revoked
            else children_with_proportions
        )
        call = await subtensor.substrate.compose_call(
            call_module="SubtensorModule",
            call_function="set_children",
            call_params={
                "hotkey": hotkey,
                "children": normalized_children,
                "netuid": netuid,
            },
        )
        success, error_message = await subtensor.sign_and_send_extrinsic(
            call, wallet, wait_for_inclusion, wait_for_finalization
        )

        if not wait_for_finalization and not wait_for_inclusion:
            return (
                True,
                f"Not waiting for finalization or inclusion. {operation} initiated.",
            )

        if success:
            console.print(":white_heavy_check_mark: [green]Finalized[/green]")
            # bittensor.logging.success(
            #     prefix=operation,
            #     suffix="<green>Finalized: </green>" + str(success),
            # )
            return True, f"Successfully {operation.lower()} and Finalized."
        else:
            err_console.print(f":cross_mark: [red]Failed[/red]: {error_message}")
            # bittensor.logging.warning(
            #     prefix=operation,
            #     suffix="<red>Failed: </red>" + str(error_message),
            # )
            return False, error_message


def prepare_child_proportions(children_with_proportions):
    """
    Convert proportions to u64 and normalize
    """
    children_u64 = [
        (float_to_u64(prop), child) for prop, child in children_with_proportions
    ]
    normalized_children = normalize_children_and_proportions(children_u64)
    return normalized_children


def normalize_children_and_proportions(
    children: list[tuple[int, str]],
) -> list[tuple[int, str]]:
    """
    Normalizes the proportions of children so that they sum to u64::MAX.
    """
    total = sum(prop for prop, _ in children)
    u64_max = 2**64 - 1
    return [(int(prop * u64_max / total), child) for prop, child in children]


# Commands


async def show(wallet: Wallet, subtensor: "SubtensorInterface", all_wallets: bool):
    """Show all stake accounts."""
    if all_wallets:
        wallets = get_coldkey_wallets_for_path(wallet.path)
    else:
        wallets = [wallet]

    registered_delegate_info = await get_delegates_details_from_github(
        Constants.delegates_detail_url
    )

    async def get_stake_accounts(
        wallet_, block_hash: str
    ) -> dict[str, Union[str, Balance, dict[str, Union[str, Balance]]]]:
        """Get stake account details for the given wallet.

        :param wallet_: The wallet object to fetch the stake account details for.

        :return: A dictionary mapping SS58 addresses to their respective stake account details.
        """

        wallet_stake_accounts = {}

        # Get this wallet's coldkey balance.
        cold_balance_, stakes_from_hk, stakes_from_d = await asyncio.gather(
            subtensor.get_balance(
                wallet_.coldkeypub.ss58_address, block_hash=block_hash
            ),
            get_stakes_from_hotkeys(wallet_, block_hash=block_hash),
            get_stakes_from_delegates(wallet_, block_hash=block_hash),
        )

        cold_balance = cold_balance_[wallet_.coldkeypub.ss58_address]

        # Populate the stake accounts with local hotkeys data.
        wallet_stake_accounts.update(stakes_from_hk)

        # Populate the stake accounts with delegations data.
        wallet_stake_accounts.update(stakes_from_d)

        return {
            "name": wallet_.name,
            "balance": cold_balance,
            "accounts": wallet_stake_accounts,
        }

    async def get_stakes_from_hotkeys(
        wallet_, block_hash: str
    ) -> dict[str, dict[str, Union[str, Balance]]]:
        """Fetch stakes from hotkeys for the provided wallet.

        :param wallet_: The wallet object to fetch the stakes for.

        :return: A dictionary of stakes related to hotkeys.
        """

        async def get_all_neurons_for_pubkey(hk):
            netuids = await subtensor.get_netuids_for_hotkey(hk, block_hash=block_hash)
            uid_query = await asyncio.gather(
                *[
                    subtensor.substrate.query(
                        module="SubtensorModule",
                        storage_function="Uids",
                        params=[netuid, hk],
                        block_hash=block_hash,
                    )
                    for netuid in netuids
                ]
            )
            uids = [getattr(_result, "value", None) for _result in uid_query]
            neurons = await asyncio.gather(
                *[
                    subtensor.neuron_for_uid(uid, net)
                    for (uid, net) in zip(uids, netuids)
                ]
            )
            return neurons

        async def get_emissions_and_stake(hk: str):
            neurons, stake = await asyncio.gather(
                get_all_neurons_for_pubkey(hk),
                subtensor.substrate.query(
                    module="SubtensorModule",
                    storage_function="Stake",
                    params=[hk, wallet_.coldkeypub.ss58_address],
                    block_hash=block_hash,
                ),
            )
            emission_ = sum([n.emission for n in neurons]) if neurons else 0.0
            return emission_, Balance.from_rao(stake.value) if getattr(
                stake, "value", None
            ) else Balance(0)

        hotkeys = get_hotkey_wallets_for_wallet(wallet_)
        stakes = {}
        query = await asyncio.gather(
            *[get_emissions_and_stake(hot.hotkey.ss58_address) for hot in hotkeys]
        )
        for hot, (emission, hotkey_stake) in zip(hotkeys, query):
            stakes[hot.hotkey.ss58_address] = {
                "name": hot.hotkey_str,
                "stake": hotkey_stake,
                "rate": emission,
            }
        return stakes

    async def get_stakes_from_delegates(
        wallet_, block_hash: str
    ) -> dict[str, dict[str, Union[str, Balance]]]:
        """Fetch stakes from delegates for the provided wallet.

        :param wallet_: The wallet object to fetch the stakes for.

        :return: A dictionary of stakes related to delegates.
        """
        delegates = await subtensor.get_delegated(
            coldkey_ss58=wallet_.coldkeypub.ss58_address, block_hash=None
        )
        stakes = {}
        for dele, staked in delegates:
            for nom in dele.nominators:
                if nom[0] == wallet_.coldkeypub.ss58_address:
                    delegate_name = (
                        registered_delegate_info[dele.hotkey_ss58].name
                        if dele.hotkey_ss58 in registered_delegate_info
                        else dele.hotkey_ss58
                    )
                    stakes[dele.hotkey_ss58] = {
                        "name": delegate_name,
                        "stake": nom[1],
                        "rate": dele.total_daily_return.tao
                        * (nom[1] / dele.total_stake.tao),
                    }
        return stakes

    async def get_all_wallet_accounts(
        block_hash: str,
    ) -> list[dict[str, Union[str, Balance, dict[str, Union[str, Balance]]]]]:
        """Fetch stake accounts for all provided wallets using a ThreadPool.

        :param block_hash: The block hash to fetch the stake accounts for.

        :return: A list of dictionaries, each dictionary containing stake account details for each wallet.
        """

        accounts_ = await asyncio.gather(
            *[get_stake_accounts(w, block_hash=block_hash) for w in wallets]
        )
        return accounts_

    with console.status(":satellite:Retrieving account data..."):
        async with subtensor:
            block_hash_ = await subtensor.substrate.get_chain_head()
            accounts = await get_all_wallet_accounts(block_hash=block_hash_)

    await subtensor.substrate.close()

    total_stake = 0
    total_balance = 0
    total_rate = 0
    for acc in accounts:
        total_balance += acc["balance"].tao
        for key, value in acc["accounts"].items():
            total_stake += value["stake"].tao
            total_rate += float(value["rate"])
    table = Table(
        Column(
            "[overline white]Coldkey", footer_style="overline white", style="bold white"
        ),
        Column(
            "[overline white]Balance",
            "\u03c4{:.5f}".format(total_balance),
            footer_style="overline white",
            style="green",
        ),
        Column("[overline white]Account", footer_style="overline white", style="blue"),
        Column(
            "[overline white]Stake",
            "\u03c4{:.5f}".format(total_stake),
            footer_style="overline white",
            style="green",
        ),
        Column(
            "[overline white]Rate",
            "\u03c4{:.5f}/d".format(total_rate),
            footer_style="overline white",
            style="green",
        ),
        show_footer=True,
        pad_edge=False,
        box=None,
        expand=False,
    )
    for acc in accounts:
        table.add_row(acc["name"], acc["balance"], "", "")
        for key, value in acc["accounts"].items():
            table.add_row(
                "", "", value["name"], value["stake"], str(value["rate"]) + "/d"
            )
    console.print(table)


async def get_children(wallet: Wallet, subtensor: "SubtensorInterface", netuid: int):
    async def _get_children(hotkey):
        """
        Get the children of a hotkey on a specific network.

        :param hotkey: The hotkey to query.

        :return: List of (proportion, child_address) tuples, or None if an error occurred.
        """
        try:
            children = await subtensor.substrate.query(
                module="SubtensorModule",
                storage_function="ChildKeys",
                params=[hotkey, netuid],
            )
            if children:
                formatted_children = []
                for proportion, child in children:
                    # Convert U64 to int
                    int_proportion = (
                        proportion.value
                        if hasattr(proportion, "value")
                        else int(proportion)
                    )
                    formatted_children.append((int_proportion, child.value))
                return formatted_children
            else:
                console.print("[yellow]No children found.[/yellow]")
                return []
        except SubstrateRequestException as e:
            err_console.print(f"Error querying ChildKeys: {e}")
            return None

    async def get_total_stake_for_child_hk(child: tuple):
        child_hotkey = child[1]
        _result = await subtensor.substrate.query(
            module="SubtensorModule",
            storage_function="TotalHotkeyStake",
            params=[child_hotkey],
            reuse_block_hash=True,
        )
        return (
            Balance.from_rao(_result.value)
            if getattr(_result, "value", None)
            else Balance(0)
        )

    async def render_table(
        hk: str,
        children: list[tuple[int, str]],
        nuid: int,
    ):
        # Initialize Rich table for pretty printing
        table = Table(
            Column("Index", style="cyan", no_wrap=True, justify="right"),
            Column("ChildHotkey", style="cyan", no_wrap=True),
            Column("Proportion", style="cyan", no_wrap=True, justify="right"),
            Column("Total Stake", style="cyan", no_wrap=True, justify="right"),
            show_header=True,
            header_style="bold magenta",
            border_style="green",
            style="green",
        )

        if not children:
            console.print(table)

            command = (
                "btcli stake set_children --children <child_hotkey> --hotkey <parent_hotkey> "
                f"--netuid {nuid} --proportion <float>"
            )
            console.print(f"There are currently no child hotkeys on subnet {nuid}.")
            console.print(
                f"To add a child hotkey you can run the command: [white]{command}[/white]"
            )
            return

        console.print("ParentHotKey:", style="cyan", no_wrap=True)
        console.print(hk)

        # calculate totals
        total_proportion = 0
        total_stake = 0

        children_info = []
        child_stakes = await asyncio.gather(
            *[get_total_stake_for_child_hk(c) for c in children]
        )
        for child, child_stake in zip(children, child_stakes):
            proportion = child[0]
            child_hotkey = child[1]

            # add to totals
            total_proportion += proportion
            total_stake += child_stake

            children_info.append((proportion, child_hotkey, child_stake))

        children_info.sort(
            key=lambda x: x[0], reverse=True
        )  # sorting by proportion (highest first)

        # add the children info to the table
        for i, (proportion, hk, stake) in enumerate(children_info, 1):
            table.add_row(
                str(i),
                hk,
                str(proportion),
                str(stake),
            )

        # add totals row
        table.add_row("", "Total", str(total_proportion), str(total_stake), "")
        console.print(table)

    async with subtensor:
        children_ = await _get_children(wallet.hotkey)

        await render_table(wallet.hotkey, children_, netuid)

    return children_


async def set_children(
    wallet: Wallet,
    subtensor: "SubtensorInterface",
    netuid: int,
    children: list[str],
    proportions: list[float],
):
    # Validate children SS58 addresses
    for child in children:
        if not is_valid_ss58_address(child):
            err_console.print(f":cross_mark:[red] Invalid SS58 address: {child}[/red]")
            return

    total_proposed = sum(proportions)
    if total_proposed > 1:
        raise ValueError(
            f"Invalid proportion: The sum of all proportions cannot be greater than 1. "
            f"Proposed sum of proportions is {total_proposed}."
        )

    children_with_proportions = list(zip(proportions, children))

    async with subtensor:
        success, message = await set_children_extrinsic(
            subtensor=subtensor,
            wallet=wallet,
            netuid=netuid,
            hotkey=wallet.hotkey.ss58_address,
            children_with_proportions=children_with_proportions,
            prompt=True,
        )
    await subtensor.substrate.close()
    # Result
    if success:
        console.print(":white_heavy_check_mark: [green]Set children hotkeys.[/green]")
    else:
        console.print(
            f":cross_mark:[red] Unable to set children hotkeys.[/red] {message}"
        )
