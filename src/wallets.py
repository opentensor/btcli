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


import os
from typing import Optional

from bittensor_wallet import Wallet
from bittensor_wallet.keyfile import Keyfile
from rich.table import Table
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


async def wallet_balance(wallet: Wallet, subtensor: SubtensorInterface, all_balances: bool):
    if not wallet.coldkeypub_file.exists_on_device():
        err_console.print("[bold red]No wallets found.[/bold red]")
        return

    if all_balances:
        coldkeys, wallet_names = _get_coldkey_ss58_addresses_for_path(wallet.path)
    else:
        coldkeys = [wallet.coldkeypub.ss58_address]
        wallet_names = [wallet.name]

    async with subtensor:
        # look into gathering
        free_balances = await subtensor.get_balance(*coldkeys)
        staked_balances = await subtensor.get_total_stake_for_coldkey(*coldkeys)

    total_free_balance = sum(free_balances)
    total_staked_balance = sum(staked_balances)

    balances = {
        name: (coldkey, free, staked)
        for name, coldkey, free, staked in sorted(
            zip(wallet_names, coldkeys, free_balances, staked_balances)
        )
    }

    table = Table(show_footer=False)
    table.title = "[white]Wallet Coldkey Balances"
    table.add_column(
        "[white]Wallet Name",
        header_style="overline white",
        footer_style="overline white",
        style="rgb(50,163,219)",
        no_wrap=True,
    )

    table.add_column(
        "[white]Coldkey Address",
        header_style="overline white",
        footer_style="overline white",
        style="rgb(50,163,219)",
        no_wrap=True,
    )

    for type_str in ["Free", "Staked", "Total"]:
        table.add_column(
            f"[white]{type_str} Balance",
            header_style="overline white",
            footer_style="overline white",
            justify="right",
            style="green",
            no_wrap=True,
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
    table.show_footer = True

    table.box = None
    table.pad_edge = False
    table.width = None
    console.print(table)
