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

# import argparse

from bittensor_wallet import Wallet
import os

import typer

# from rich.table import Table
from typing import Optional

from .utils import err_console
# from . import defaults
# import requests
# from ..utils import RAOPERTAO


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
