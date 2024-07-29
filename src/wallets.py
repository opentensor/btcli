# The MIT License (MIT)
# Copyright © 2021 Yuma Rao

# Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
# documentation files (the “Software”), to deal in the Software without restriction, including without limitation
# the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software,
# and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all copies or substantial portions of
# the Software.

# THE SOFTWARE IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO
# THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
# THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
# OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
# DEALINGS IN THE SOFTWARE.

import asyncio
import os
from pathlib import Path
from typing import Optional

import aiohttp
from bittensor_wallet import Wallet
from bittensor_wallet.keyfile import Keyfile
from rich.table import Table, Column
from rich.tree import Tree

import typer

from .utils import console, err_console, RAO_PER_TAO
from . import defaults
from src.subtensor_interface import SubtensorInterface


async def regen_coldkey(
    wallet,
    mnemonic: Optional[str],
    seed: Optional[str] = None,
    json_path: Optional[str] = None,
    json_password: Optional[str] = "",
    use_password: Optional[bool] = True,
    overwrite_coldkey: Optional[bool] = False,
):
    json_str: Optional[str] = None
    if json_path:
        if not os.path.exists(json_path) or not os.path.isfile(json_path):
            raise ValueError("File {} does not exist".format(json_path))
        with open(json_path, "r") as f:
            json_str = f.read()
    wallet.regenerate_coldkey(
        mnemonic=mnemonic,
        seed=seed,
        json=(json_str, json_password),
        use_password=use_password,
        overwrite=overwrite_coldkey,
    )


async def regen_coldkey_pub(
    wallet, ss58_address: str, public_key_hex: str, overwrite_coldkeypub: bool
):
    r"""Creates a new coldkeypub under this wallet."""
    wallet.regenerate_coldkeypub(
        ss58_address=ss58_address,
        public_key=public_key_hex,
        overwrite=overwrite_coldkeypub,
    )


async def regen_hotkey(
    wallet: Wallet,
    mnemonic: Optional[str],
    seed: Optional[str],
    json_path: Optional[str],
    json_password: Optional[str] = "",
    use_password: Optional[bool] = True,
    overwrite_hotkey: Optional[bool] = False,
):
    json_str: Optional[str] = None
    if json_path:
        if not os.path.exists(json_path) or not os.path.isfile(json_path):
            err_console.print(f"File {json_path} does not exist")
            raise typer.Exit()
        with open(json_path, "r") as f:
            json_str = f.read()

    wallet.regenerate_hotkey(
        mnemonic=mnemonic,
        seed=seed,
        json=(json_str, json_password),
        use_password=use_password,
        overwrite=overwrite_hotkey,
    )


async def new_hotkey(
    wallet: Wallet, n_words: int, use_password: bool, overwrite_hotkey: bool
):
    wallet.create_new_hotkey(
        n_words=n_words,
        use_password=use_password,
        overwrite=overwrite_hotkey,
    )


async def new_coldkey(
    wallet: Wallet, n_words: int, use_password: bool, overwrite_coldkey: bool
):
    wallet.create_new_coldkey(
        n_words=n_words,
        use_password=use_password,
        overwrite=overwrite_coldkey,
    )


def wallet_create(
    wallet: Wallet,
    n_words: int = 12,
    use_password: bool = True,
    overwrite_coldkey: bool = False,
    overwrite_hotkey: bool = False,
):
    wallet.create_new_coldkey(
        n_words=n_words,
        use_password=use_password,
        overwrite=overwrite_coldkey,
    )
    wallet.create_new_hotkey(
        n_words=n_words,
        use_password=False,
        overwrite=overwrite_hotkey,
    )


def _get_coldkey_wallets_for_path(path: str) -> list[Wallet]:
    """Get all coldkey wallet names from path."""
    try:
        wallet_names = next(os.walk(os.path.expanduser(path)))[1]
        return [Wallet(path=path, name=name) for name in wallet_names]
    except StopIteration:
        # No wallet files found.
        wallets = []
    return wallets


def _get_coldkey_ss58_addresses_for_path(path: str) -> tuple[list[str], list[str]]:
    """Get all coldkey ss58 addresses from path."""

    abs_path = os.path.abspath(os.path.expanduser(path))
    wallets = [
        name
        for name in os.listdir(abs_path)
        if os.path.isdir(os.path.join(abs_path, name))
    ]
    coldkey_paths = [
        os.path.join(abs_path, wallet, "coldkeypub.txt")
        for wallet in wallets
        if os.path.exists(os.path.join(abs_path, wallet, "coldkeypub.txt"))
    ]
    ss58_addresses = [Keyfile(path).keypair.ss58_address for path in coldkey_paths]

    return ss58_addresses, [
        os.path.basename(os.path.dirname(path)) for path in coldkey_paths
    ]


async def wallet_balance(
    wallet: Wallet, subtensor: SubtensorInterface, all_balances: bool
):
    if not wallet.coldkeypub_file.exists_on_device():
        err_console.print("[bold red]No wallets found.[/bold red]")
        return

    with console.status("Retrieving balances", spinner="aesthetic"):
        if all_balances:
            coldkeys, wallet_names = _get_coldkey_ss58_addresses_for_path(wallet.path)
        else:
            coldkeys = [wallet.coldkeypub.ss58_address]
            wallet_names = [wallet.name]

        async with subtensor:
            await subtensor.get_chain_head()
            free_balances, staked_balances = await asyncio.gather(
                subtensor.get_balance(*coldkeys, reuse_block=True),
                subtensor.get_total_stake_for_coldkey(*coldkeys, reuse_block=True),
            )

    total_free_balance = sum(free_balances.values())
    total_staked_balance = sum(staked_balances.values())

    balances = {
        name: (coldkey, free_balances[coldkey], staked_balances[coldkey])
        for (name, coldkey) in zip(wallet_names, coldkeys)
    }

    table = Table(
        Column(
            "[white]Wallet Name",
            header_style="overline white",
            footer_style="overline white",
            style="rgb(50,163,219)",
            no_wrap=True,
        ),
        Column(
            "[white]Coldkey Address",
            header_style="overline white",
            footer_style="overline white",
            style="rgb(50,163,219)",
            no_wrap=True,
        ),
        Column(
            "[white]Free Balance",
            header_style="overline white",
            footer_style="overline white",
            justify="right",
            style="green",
            no_wrap=True,
        ),
        Column(
            "[white]Staked Balance",
            header_style="overline white",
            footer_style="overline white",
            justify="right",
            style="green",
            no_wrap=True,
        ),
        Column(
            "[white]Total Balance",
            header_style="overline white",
            footer_style="overline white",
            justify="right",
            style="green",
            no_wrap=True,
        ),
        show_footer=True,
        title="[white]Wallet Coldkey Balances",
        box=None,
        pad_edge=False,
        width=None,
    )

    for name, (coldkey, free, staked) in balances.items():
        table.add_row(
            name,
            coldkey,
            str(free),
            str(staked),
            str(free + staked),
        )
    table.add_row()
    table.add_row(
        "Total Balance Across All Coldkeys",
        "",
        str(total_free_balance),
        str(total_staked_balance),
        str(total_free_balance + total_staked_balance),
    )
    console.print(table)


async def get_wallet_transfers(wallet_address: str) -> list[dict]:
    """Get all transfers associated with the provided wallet address."""

    api_url = "https://api.subquery.network/sq/TaoStats/bittensor-indexer"
    max_txn = 1000
    graphql_query = """
    query ($first: Int!, $after: Cursor, $filter: TransferFilter, $order: [TransfersOrderBy!]!) {
        transfers(first: $first, after: $after, filter: $filter, orderBy: $order) {
            nodes {
                id
                from
                to
                amount
                extrinsicId
                blockNumber
            }
            pageInfo {
                endCursor
                hasNextPage
                hasPreviousPage
            }
            totalCount
        }
    }
    """
    variables = {
        "first": max_txn,
        "filter": {
            "or": [
                {"from": {"equalTo": wallet_address}},
                {"to": {"equalTo": wallet_address}},
            ]
        },
        "order": "BLOCK_NUMBER_DESC",
    }
    async with aiohttp.ClientSession() as session:
        response = await session.post(
            api_url, json={"query": graphql_query, "variables": variables}
        )
        data = await response.json()

    # Extract nodes and pageInfo from the response
    transfer_data = data.get("data", {}).get("transfers", {})
    transfers = transfer_data.get("nodes", [])

    return transfers


def create_transfer_history_table(transfers: list[dict]) -> Table:
    """Get output transfer table"""

    # Define the column names
    column_names = [
        "Id",
        "From",
        "To",
        "Amount (Tao)",
        "Extrinsic Id",
        "Block Number",
        "URL (taostats)",
    ]
    taostats_url_base = "https://x.taostats.io/extrinsic"

    # Create a table
    table = Table(
        show_footer=True,
        box=None,
        pad_edge=False,
        width=None,
        title="[white]Wallet Transfers",
        header_style="overline white",
        footer_style="overline white",
    )

    column_style = "rgb(50,163,219)"
    no_wrap = True

    for column_name in column_names:
        table.add_column(
            f"[white]{column_name}",
            style=column_style,
            no_wrap=no_wrap,
            justify="left" if column_name == "Id" else "right",
        )

    for item in transfers:
        try:
            tao_amount = int(item["amount"]) / RAO_PER_TAO
        except ValueError:
            tao_amount = item["amount"]
        table.add_row(
            item["id"],
            item["from"],
            item["to"],
            f"{tao_amount:.3f}",
            str(item["extrinsicId"]),
            item["blockNumber"],
            f"{taostats_url_base}/{item['blockNumber']}-{item['extrinsicId']}",
        )
    table.add_row()
    return table


async def wallet_history(wallet: Wallet):
    """Check the transfer history of the provided wallet."""
    wallet_address = wallet.get_coldkeypub().ss58_address
    transfers = await get_wallet_transfers(wallet_address)
    table = create_transfer_history_table(transfers)
    console.print(table)


async def wallet_list(wallet_path: str):
    r"""Lists wallets."""
    wallet_path = Path(wallet_path).expanduser()
    wallets = [
        directory.name for directory in wallet_path.iterdir() if directory.is_dir()
    ]
    if not wallets:
        err_console.print(f"[red]No wallets found in dir: {wallet_path}[/red]")

    root = Tree("Wallets")
    for w_name in wallets:
        wallet_for_name = Wallet(path=str(wallet_path), name=w_name)
        if (
            wallet_for_name.coldkeypub_file.exists_on_device()
            and not wallet_for_name.coldkeypub_file.is_encrypted()
        ):
            coldkeypub_str = wallet_for_name.coldkeypub.ss58_address
        else:
            coldkeypub_str = "?"

        wallet_tree = root.add("\n[bold white]{} ({})".format(w_name, coldkeypub_str))
        hotkeys_path = wallet_path / w_name / "hotkeys"
        try:
            hotkeys = [entry.name for entry in hotkeys_path.iterdir()]
            if len(hotkeys) > 1:
                for h_name in hotkeys:
                    hotkey_for_name = Wallet(
                        path=str(wallet_path), name=w_name, hotkey=h_name
                    )
                    try:
                        if (
                            hotkey_for_name.hotkey_file.exists_on_device()
                            and not hotkey_for_name.hotkey_file.is_encrypted()
                        ):
                            hotkey_str = hotkey_for_name.hotkey.ss58_address
                        else:
                            hotkey_str = "?"
                        wallet_tree.add(f"[bold grey]{h_name} ({hotkey_str})")
                    except UnicodeDecodeError:  # usually an unrelated file like .DS_Store
                        continue

        except FileNotFoundError:
            # no hotkeys found
            continue

    if not wallets:
        root.add("[bold red]No wallets found.")

    console.print(root)
