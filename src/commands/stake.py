import asyncio
from typing import TYPE_CHECKING, Union

from bittensor_wallet import Wallet
from rich.table import Table, Column

from src import Constants
from src.bittensor.balances import Balance
from src.bittensor.chain_data import NeuronInfo
from src.utils import (
    get_delegates_details_from_github,
    get_hotkey_wallets_for_wallet,
    get_coldkey_wallets_for_path,
    console,
)

if TYPE_CHECKING:
    from src.subtensor_interface import SubtensorInterface


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
