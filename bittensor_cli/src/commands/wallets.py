import asyncio
import itertools
import json
import os
from collections import defaultdict
from typing import Generator, Optional

import aiohttp
from bittensor_wallet import Wallet, Keypair
from bittensor_wallet.errors import KeyFileError
from bittensor_wallet.keyfile import Keyfile
from rich import box
from rich.align import Align
from rich.table import Column, Table
from rich.tree import Tree
from rich.padding import Padding
from rich.prompt import Confirm

from bittensor_cli.src import COLOR_PALETTE, COLORS, Constants
from bittensor_cli.src.bittensor import utils
from bittensor_cli.src.bittensor.balances import Balance
from bittensor_cli.src.bittensor.chain_data import (
    DelegateInfo,
    NeuronInfoLite,
)
from bittensor_cli.src.bittensor.extrinsics.registration import (
    run_faucet_extrinsic,
    swap_hotkey_extrinsic,
)
from bittensor_cli.src.bittensor.extrinsics.transfer import transfer_extrinsic
from bittensor_cli.src.bittensor.networking import int_to_ip
from bittensor_cli.src.bittensor.subtensor_interface import SubtensorInterface
from bittensor_cli.src.bittensor.utils import (
    RAO_PER_TAO,
    console,
    convert_blocks_to_time,
    err_console,
    json_console,
    print_error,
    print_verbose,
    get_all_wallets_for_path,
    get_hotkey_wallets_for_wallet,
    is_valid_ss58_address,
    validate_coldkey_presence,
    get_subnet_name,
    millify_tao,
    unlock_key,
    WalletLike,
    blocks_to_duration,
    decode_account_id,
)


async def associate_hotkey(
    wallet: Wallet,
    subtensor: SubtensorInterface,
    hotkey_ss58: str,
    hotkey_display: str,
    prompt: bool = False,
):
    """Associates a hotkey with a wallet"""

    owner_ss58 = await subtensor.get_hotkey_owner(hotkey_ss58)
    if owner_ss58:
        if owner_ss58 == wallet.coldkeypub.ss58_address:
            console.print(
                f":white_heavy_check_mark: {hotkey_display.capitalize()} is already "
                f"associated with \nwallet [blue]{wallet.name}[/blue], "
                f"SS58: [{COLORS.GENERAL.CK}]{owner_ss58}[/{COLORS.GENERAL.CK}]"
            )
            return True
        else:
            owner_wallet = _get_wallet_by_ss58(wallet.path, owner_ss58)
            wallet_name = owner_wallet.name if owner_wallet else "unknown wallet"
            console.print(
                f"[yellow]Warning[/yellow]: {hotkey_display.capitalize()} is already associated with \n"
                f"wallet: [blue]{wallet_name}[/blue], SS58: [{COLORS.GENERAL.CK}]{owner_ss58}[/{COLORS.GENERAL.CK}]"
            )
            return False
    else:
        console.print(
            f"{hotkey_display.capitalize()} is not associated with any wallet"
        )

    if prompt and not Confirm.ask("Do you want to continue with the association?"):
        return False

    if not unlock_key(wallet).success:
        return False

    call = await subtensor.substrate.compose_call(
        call_module="SubtensorModule",
        call_function="try_associate_hotkey",
        call_params={
            "hotkey": hotkey_ss58,
        },
    )

    with console.status(":satellite: Associating hotkey on-chain..."):
        success, err_msg = await subtensor.sign_and_send_extrinsic(
            call,
            wallet,
            wait_for_inclusion=True,
            wait_for_finalization=False,
        )

        if not success:
            console.print(
                f"[red]:cross_mark: Failed to associate hotkey: {err_msg}[/red]"
            )
            return False

        console.print(
            f":white_heavy_check_mark: Successfully associated {hotkey_display} with \n"
            f"wallet [blue]{wallet.name}[/blue], "
            f"SS58: [{COLORS.GENERAL.CK}]{wallet.coldkeypub.ss58_address}[/{COLORS.GENERAL.CK}]"
        )
        return True


async def regen_coldkey(
    wallet: Wallet,
    mnemonic: Optional[str],
    seed: Optional[str] = None,
    json_path: Optional[str] = None,
    json_password: Optional[str] = "",
    use_password: Optional[bool] = True,
    overwrite: Optional[bool] = False,
    json_output: bool = False,
):
    """Creates a new coldkey under this wallet"""
    json_str: Optional[str] = None
    if json_path:
        if not os.path.exists(json_path) or not os.path.isfile(json_path):
            raise ValueError("File {} does not exist".format(json_path))
        with open(json_path, "r") as f:
            json_str = f.read()
    try:
        new_wallet = wallet.regenerate_coldkey(
            mnemonic=mnemonic,
            seed=seed,
            json=(json_str, json_password) if all([json_str, json_password]) else None,
            use_password=use_password,
            overwrite=overwrite,
        )
        if isinstance(new_wallet, Wallet):
            console.print(
                "\n✅ [dark_sea_green]Regenerated coldkey successfully!\n",
                f"[dark_sea_green]Wallet name: ({new_wallet.name}), "
                f"path: ({new_wallet.path}), "
                f"coldkey ss58: ({new_wallet.coldkeypub.ss58_address})",
            )
            if json_output:
                json_console.print(
                    json.dumps(
                        {
                            "success": True,
                            "data": {
                                "name": new_wallet.name,
                                "path": new_wallet.path,
                                "hotkey": new_wallet.hotkey_str,
                                "hotkey_ss58": new_wallet.hotkey.ss58_address,
                                "coldkey_ss58": new_wallet.coldkeypub.ss58_address,
                            },
                            "error": "",
                        }
                    )
                )
    except ValueError:
        print_error("Mnemonic phrase is invalid")
        if json_output:
            json_console.print(
                '{"success": false, "error": "Mnemonic phrase is invalid", "data": null}'
            )
    except KeyFileError:
        print_error("KeyFileError: File is not writable")
        if json_output:
            json_console.print(
                '{"success": false, "error": "Keyfile is not writable", "data": null}'
            )


async def regen_coldkey_pub(
    wallet: Wallet,
    ss58_address: str,
    public_key_hex: str,
    overwrite: Optional[bool] = False,
    json_output: bool = False,
):
    """Creates a new coldkeypub under this wallet."""
    try:
        new_coldkeypub = wallet.regenerate_coldkeypub(
            ss58_address=ss58_address,
            public_key=public_key_hex,
            overwrite=overwrite,
        )
        if isinstance(new_coldkeypub, Wallet):
            console.print(
                "\n✅ [dark_sea_green]Regenerated coldkeypub successfully!\n",
                f"[dark_sea_green]Wallet name: ({new_coldkeypub.name}), path: ({new_coldkeypub.path}), "
                f"coldkey ss58: ({new_coldkeypub.coldkeypub.ss58_address})",
            )
            if json_output:
                json_console.print(
                    json.dumps(
                        {
                            "success": True,
                            "data": {
                                "name": new_coldkeypub.name,
                                "path": new_coldkeypub.path,
                                "hotkey": new_coldkeypub.hotkey_str,
                                "hotkey_ss58": new_coldkeypub.hotkey.ss58_address,
                                "coldkey_ss58": new_coldkeypub.coldkeypub.ss58_address,
                            },
                            "error": "",
                        }
                    )
                )
    except KeyFileError:
        print_error("KeyFileError: File is not writable")
        if json_output:
            json_console.print(
                '{"success": false, "error": "Keyfile is not writable", "data": null}'
            )


async def regen_hotkey(
    wallet: Wallet,
    mnemonic: Optional[str],
    seed: Optional[str],
    json_path: Optional[str],
    json_password: Optional[str] = "",
    use_password: Optional[bool] = False,
    overwrite: Optional[bool] = False,
    json_output: bool = False,
):
    """Creates a new hotkey under this wallet."""
    json_str: Optional[str] = None
    if json_path:
        if not os.path.exists(json_path) or not os.path.isfile(json_path):
            err_console.print(f"File {json_path} does not exist")
            return False
        with open(json_path, "r") as f:
            json_str = f.read()

    try:
        new_hotkey_ = wallet.regenerate_hotkey(
            mnemonic=mnemonic,
            seed=seed,
            json=(json_str, json_password) if all([json_str, json_password]) else None,
            use_password=use_password,
            overwrite=overwrite,
        )
        if isinstance(new_hotkey_, Wallet):
            console.print(
                "\n✅ [dark_sea_green]Regenerated hotkey successfully!\n",
                f"[dark_sea_green]Wallet name: ({new_hotkey_.name}), path: ({new_hotkey_.path}), "
                f"hotkey ss58: ({new_hotkey_.hotkey.ss58_address})",
            )
            if json_output:
                json_console.print(
                    json.dumps(
                        {
                            "success": True,
                            "data": {
                                "name": new_hotkey_.name,
                                "path": new_hotkey_.path,
                                "hotkey": new_hotkey_.hotkey_str,
                                "hotkey_ss58": new_hotkey_.hotkey.ss58_address,
                                "coldkey_ss58": new_hotkey_.coldkeypub.ss58_address,
                            },
                            "error": "",
                        }
                    )
                )
    except ValueError:
        print_error("Mnemonic phrase is invalid")
        if json_output:
            json_console.print(
                '{"success": false, "error": "Mnemonic phrase is invalid", "data": null}'
            )
    except KeyFileError:
        print_error("KeyFileError: File is not writable")
        if json_output:
            json_console.print(
                '{"success": false, "error": "Keyfile is not writable", "data": null}'
            )


async def new_hotkey(
    wallet: Wallet,
    n_words: int,
    use_password: bool,
    uri: Optional[str] = None,
    overwrite: Optional[bool] = False,
    json_output: bool = False,
):
    """Creates a new hotkey under this wallet."""
    try:
        if uri:
            try:
                keypair = Keypair.create_from_uri(uri)
            except Exception as e:
                print_error(f"Failed to create keypair from URI {uri}: {str(e)}")
                return
            wallet.set_hotkey(keypair=keypair, encrypt=use_password)
            console.print(
                f"[dark_sea_green]Hotkey created from URI: {uri}[/dark_sea_green]"
            )
        else:
            wallet.create_new_hotkey(
                n_words=n_words,
                use_password=use_password,
                overwrite=overwrite,
            )
            console.print("[dark_sea_green]Hotkey created[/dark_sea_green]")
        if json_output:
            json_console.print(
                json.dumps(
                    {
                        "success": True,
                        "data": {
                            "name": wallet.name,
                            "path": wallet.path,
                            "hotkey": wallet.hotkey_str,
                            "hotkey_ss58": wallet.hotkey.ss58_address,
                            "coldkey_ss58": wallet.coldkeypub.ss58_address,
                        },
                        "error": "",
                    }
                )
            )
    except KeyFileError:
        print_error("KeyFileError: File is not writable")
        if json_output:
            json_console.print(
                '{"success": false, "error": "Keyfile is not writable", "data": null}'
            )


async def new_coldkey(
    wallet: Wallet,
    n_words: int,
    use_password: bool,
    uri: Optional[str] = None,
    overwrite: Optional[bool] = False,
    json_output: bool = False,
):
    """Creates a new coldkey under this wallet."""
    try:
        if uri:
            try:
                keypair = Keypair.create_from_uri(uri)
            except Exception as e:
                print_error(f"Failed to create keypair from URI {uri}: {str(e)}")
            wallet.set_coldkey(keypair=keypair, encrypt=False, overwrite=False)
            wallet.set_coldkeypub(keypair=keypair, encrypt=False, overwrite=False)
            console.print(
                f"[dark_sea_green]Coldkey created from URI: {uri}[/dark_sea_green]"
            )
        else:
            wallet.create_new_coldkey(
                n_words=n_words,
                use_password=use_password,
                overwrite=overwrite,
            )
            console.print("[dark_sea_green]Coldkey created[/dark_sea_green]")
        if json_output:
            json_console.print(
                json.dumps(
                    {
                        "success": True,
                        "data": {
                            "name": wallet.name,
                            "path": wallet.path,
                            "coldkey_ss58": wallet.coldkeypub.ss58_address,
                        },
                        "error": "",
                    }
                )
            )
    except KeyFileError as e:
        print_error("KeyFileError: File is not writable")
        if json_output:
            json_console.print(
                json.dumps(
                    {
                        "success": False,
                        "error": f"Keyfile is not writable: {e}",
                        "data": None,
                    }
                )
            )


async def wallet_create(
    wallet: Wallet,
    n_words: int = 12,
    use_password: bool = True,
    uri: Optional[str] = None,
    overwrite: Optional[bool] = False,
    json_output: bool = False,
):
    """Creates a new wallet."""
    output_dict = {"success": False, "error": "", "data": None}
    if uri:
        try:
            keypair = Keypair.create_from_uri(uri)
            wallet.set_coldkey(keypair=keypair, encrypt=False, overwrite=False)
            wallet.set_coldkeypub(keypair=keypair, encrypt=False, overwrite=False)
            wallet.set_hotkey(keypair=keypair, encrypt=False, overwrite=False)
            output_dict["success"] = True
            output_dict["data"] = {
                "name": wallet.name,
                "path": wallet.path,
                "hotkey": wallet.hotkey_str,
                "hotkey_ss58": wallet.hotkey.ss58_address,
                "coldkey_ss58": wallet.coldkeypub.ss58_address,
            }
        except Exception as e:
            err = f"Failed to create keypair from URI: {str(e)}"
            print_error(err)
            output_dict["error"] = err
        console.print(
            f"[dark_sea_green]Wallet created from URI: {uri}[/dark_sea_green]"
        )
    else:
        try:
            wallet.create_new_coldkey(
                n_words=n_words,
                use_password=use_password,
                overwrite=overwrite,
            )
            console.print("[dark_sea_green]Coldkey created[/dark_sea_green]")
            output_dict["success"] = True
            output_dict["data"] = {
                "name": wallet.name,
                "path": wallet.path,
                "hotkey": wallet.hotkey_str,
                "coldkey_ss58": wallet.coldkeypub.ss58_address,
            }
        except KeyFileError as error:
            err = str(error)
            print_error(err)
            output_dict["error"] = err
        try:
            wallet.create_new_hotkey(
                n_words=n_words,
                use_password=False,
                overwrite=overwrite,
            )
            console.print("[dark_sea_green]Hotkey created[/dark_sea_green]")
            output_dict["success"] = True
            output_dict["data"] = {
                "name": wallet.name,
                "path": wallet.path,
                "hotkey": wallet.hotkey_str,
                "hotkey_ss58": wallet.hotkey.ss58_address,
            }
        except KeyFileError as error:
            err = str(error)
            print_error(err)
            output_dict["error"] = err
    if json_output:
        json_console.print(json.dumps(output_dict))


def get_coldkey_wallets_for_path(path: str) -> list[Wallet]:
    """Get all coldkey wallet names from path."""
    try:
        wallet_names = next(os.walk(os.path.expanduser(path)))[1]
        return [Wallet(path=path, name=name) for name in wallet_names]
    except StopIteration:
        # No wallet files found.
        wallets = []
    return wallets


def _get_wallet_by_ss58(path: str, ss58_address: str) -> Optional[Wallet]:
    """Find a wallet by its SS58 address in the given path."""
    ss58_addresses, wallet_names = _get_coldkey_ss58_addresses_for_path(path)
    for wallet_name, addr in zip(wallet_names, ss58_addresses):
        if addr == ss58_address:
            return Wallet(path=path, name=wallet_name)
    return None


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
    wallet: Optional[Wallet],
    subtensor: SubtensorInterface,
    all_balances: bool,
    ss58_addresses: Optional[str] = None,
    json_output: bool = False,
):
    """Retrieves the current balance of the specified wallet"""
    if ss58_addresses:
        coldkeys = ss58_addresses
        wallet_names = [f"Provided Address {i + 1}" for i in range(len(ss58_addresses))]

    elif not all_balances:
        if not wallet.coldkeypub_file.exists_on_device():
            err_console.print("[bold red]No wallets found.[/bold red]")
            return

    with console.status("Retrieving balances", spinner="aesthetic") as status:
        if ss58_addresses:
            print_verbose(f"Fetching data for ss58 address: {ss58_addresses}", status)
        elif all_balances:
            print_verbose("Fetching data for all wallets", status)
            coldkeys, wallet_names = _get_coldkey_ss58_addresses_for_path(wallet.path)
        else:
            print_verbose(f"Fetching data for wallet: {wallet.name}", status)
            coldkeys = [wallet.coldkeypub.ss58_address]
            wallet_names = [wallet.name]

        block_hash = await subtensor.substrate.get_chain_head()
        free_balances, staked_balances = await asyncio.gather(
            subtensor.get_balances(*coldkeys, block_hash=block_hash),
            subtensor.get_total_stake_for_coldkey(*coldkeys, block_hash=block_hash),
        )

    total_free_balance = sum(free_balances.values())
    total_staked_balance = sum(stake[0] for stake in staked_balances.values())

    balances = {
        name: (
            coldkey,
            free_balances[coldkey],
            staked_balances[coldkey][0],
        )
        for (name, coldkey) in zip(wallet_names, coldkeys)
    }

    table = Table(
        Column(
            "[white]Wallet Name",
            style=COLOR_PALETTE["GENERAL"]["SUBHEADING_MAIN"],
            no_wrap=True,
        ),
        Column(
            "[white]Coldkey Address",
            style=COLOR_PALETTE["GENERAL"]["COLDKEY"],
            no_wrap=True,
        ),
        Column(
            "[white]Free Balance",
            justify="right",
            style=COLOR_PALETTE["GENERAL"]["BALANCE"],
            no_wrap=True,
        ),
        Column(
            "[white]Staked Value",
            justify="right",
            style=COLOR_PALETTE["STAKE"]["STAKE_ALPHA"],
            no_wrap=True,
        ),
        Column(
            "[white]Total Balance",
            justify="right",
            style=COLOR_PALETTE["GENERAL"]["BALANCE"],
            no_wrap=True,
        ),
        title=f"\n[{COLOR_PALETTE['GENERAL']['HEADER']}]Wallet Coldkey Balance[/{COLOR_PALETTE['GENERAL']['HEADER']}]\n[{COLOR_PALETTE['GENERAL']['HEADER']}]Network: {subtensor.network}\n",
        show_footer=True,
        show_edge=False,
        border_style="bright_black",
        box=box.SIMPLE_HEAVY,
        pad_edge=False,
        width=None,
        leading=True,
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
        "Total Balance",
        "",
        str(total_free_balance),
        str(total_staked_balance),
        str(total_free_balance + total_staked_balance),
    )
    console.print(Padding(table, (0, 0, 0, 4)))
    await subtensor.substrate.close()
    if json_output:
        output_balances = {
            key: {
                "coldkey": value[0],
                "free": value[1].tao,
                "staked": value[2].tao,
                "total": (value[1] + value[2]).tao,
            }
            for (key, value) in balances.items()
        }
        output_dict = {
            "balances": output_balances,
            "totals": {
                "free": total_free_balance.tao,
                "staked": total_staked_balance.tao,
                "total": (total_free_balance + total_staked_balance).tao,
            },
        }
        json_console.print(json.dumps(output_dict))
    return total_free_balance


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

    taostats_url_base = "https://taostats.io/extrinsic"

    # Create a table
    table = Table(
        show_footer=True,
        box=box.SIMPLE,
        pad_edge=False,
        leading=True,
        expand=False,
        title="[underline dark_orange]Wallet Transfers[/underline dark_orange]\n\n[dark_orange]Network: finney",
    )

    table.add_column(
        "[white]ID", style="dark_orange", no_wrap=True, justify="left", ratio=1.4
    )
    table.add_column(
        "[white]From", style="bright_magenta", overflow="fold", justify="right", ratio=2
    )
    table.add_column(
        "[white]To", style="bright_magenta", overflow="fold", justify="right", ratio=2
    )
    table.add_column(
        "[white]Amount (Tao)",
        style="light_goldenrod2",
        no_wrap=True,
        justify="right",
        ratio=1,
    )
    table.add_column(
        "[white]Extrinsic Id",
        style="rgb(42,161,152)",
        no_wrap=True,
        justify="right",
        ratio=0.75,
    )
    table.add_column(
        "[white]Block Number",
        style="dark_sea_green",
        no_wrap=True,
        justify="right",
        ratio=1,
    )
    table.add_column(
        "[white]URL (taostats)",
        style="bright_cyan",
        overflow="fold",
        justify="right",
        ratio=2,
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
            f"{taostats_url_base}/{item['blockNumber']}-{item['extrinsicId']:04}",
        )
    table.add_row()
    return table


async def wallet_history(wallet: Wallet):
    """Check the transfer history of the provided wallet."""
    print_verbose(f"Fetching history for wallet: {wallet.name}")
    wallet_address = wallet.get_coldkeypub().ss58_address
    transfers = await get_wallet_transfers(wallet_address)
    table = create_transfer_history_table(transfers)
    console.print(table)


async def wallet_list(wallet_path: str, json_output: bool):
    """Lists wallets."""
    wallets = utils.get_coldkey_wallets_for_path(wallet_path)
    print_verbose(f"Using wallets path: {wallet_path}")
    if not wallets:
        err_console.print(f"[red]No wallets found in dir: {wallet_path}[/red]")

    root = Tree("Wallets")
    main_data_dict = {"wallets": []}
    for wallet in wallets:
        if (
            wallet.coldkeypub_file.exists_on_device()
            and not wallet.coldkeypub_file.is_encrypted()
        ):
            coldkeypub_str = wallet.coldkeypub.ss58_address
        else:
            coldkeypub_str = "?"

        wallet_tree = root.add(
            f"[bold blue]Coldkey[/bold blue] [green]{wallet.name}[/green]  ss58_address [green]{coldkeypub_str}[/green]"
        )
        wallet_hotkeys = []
        wallet_dict = {
            "name": wallet.name,
            "ss58_address": coldkeypub_str,
            "hotkeys": wallet_hotkeys,
        }
        main_data_dict["wallets"].append(wallet_dict)
        hotkeys = utils.get_hotkey_wallets_for_wallet(
            wallet, show_nulls=True, show_encrypted=True
        )
        for hkey in hotkeys:
            data = f"[bold red]Hotkey[/bold red][green] {hkey}[/green] (?)"
            hk_data = {"name": hkey.name, "ss58_address": "?"}
            if hkey:
                try:
                    data = (
                        f"[bold red]Hotkey[/bold red] [green]{hkey.hotkey_str}[/green]  "
                        f"ss58_address [green]{hkey.hotkey.ss58_address}[/green]\n"
                    )
                    hk_data["name"] = hkey.hotkey_str
                    hk_data["ss58_address"] = hkey.hotkey.ss58_address
                except UnicodeDecodeError:
                    pass
            wallet_tree.add(data)
            wallet_hotkeys.append(hk_data)

    if not wallets:
        print_verbose(f"No wallets found in path: {wallet_path}")
        root.add("[bold red]No wallets found.")
    if json_output:
        json_console.print(json.dumps(main_data_dict))
    else:
        console.print(root)


async def _get_total_balance(
    total_balance: Balance,
    subtensor: SubtensorInterface,
    wallet: Wallet,
    all_wallets: bool = False,
    block_hash: Optional[str] = None,
) -> tuple[list[Wallet], Balance]:
    """
    Retrieves total balance of all or specified wallets
    :param total_balance: Balance object for which to add the retrieved balance(s)
    :param subtensor: SubtensorInterface object used to make the queries
    :param wallet: Wallet object from which to derive the queries (or path if all_wallets is set)
    :param all_wallets: Flag on whether to use all wallets in the wallet.path or just the specified wallet
    :return: (all hotkeys used to derive the balance, total balance of these)
    """
    if all_wallets:
        cold_wallets = utils.get_coldkey_wallets_for_path(wallet.path)
        _balance_cold_wallets = [
            cold_wallet
            for cold_wallet in cold_wallets
            if (
                cold_wallet.coldkeypub_file.exists_on_device()
                and not cold_wallet.coldkeypub_file.is_encrypted()
            )
        ]
        total_balance += sum(
            (
                await subtensor.get_balances(
                    *(x.coldkeypub.ss58_address for x in _balance_cold_wallets),
                    block_hash=block_hash,
                )
            ).values()
        )
        all_hotkeys = []
        for w in cold_wallets:
            hotkeys_for_wallet = utils.get_hotkey_wallets_for_wallet(w)
            if hotkeys_for_wallet:
                all_hotkeys.extend(hotkeys_for_wallet)
            else:
                print_error(f"[red]No hotkeys found for wallet: ({w.name})")
    else:
        # We are only printing keys for a single coldkey
        coldkey_wallet = wallet
        if (
            coldkey_wallet.coldkeypub_file.exists_on_device()
            and not coldkey_wallet.coldkeypub_file.is_encrypted()
        ):
            total_balance = sum(
                (
                    await subtensor.get_balances(
                        coldkey_wallet.coldkeypub.ss58_address, block_hash=block_hash
                    )
                ).values()
            )
        if not coldkey_wallet.coldkeypub_file.exists_on_device():
            return [], None
        all_hotkeys = utils.get_hotkey_wallets_for_wallet(coldkey_wallet)

        if not all_hotkeys:
            print_error(f"No hotkeys found for wallet ({coldkey_wallet.name})")

    return all_hotkeys, total_balance


async def overview(
    wallet: Wallet,
    subtensor: SubtensorInterface,
    all_wallets: bool = False,
    sort_by: Optional[str] = None,
    sort_order: Optional[str] = None,
    include_hotkeys: Optional[list[str]] = None,
    exclude_hotkeys: Optional[list[str]] = None,
    netuids_filter: Optional[list[int]] = None,
    verbose: bool = False,
    json_output: bool = False,
):
    """Prints an overview for the wallet's coldkey."""

    total_balance = Balance(0)

    with console.status(
        f":satellite: Synchronizing with chain [white]{subtensor.network}[/white]",
        spinner="aesthetic",
    ) as status:
        # We are printing for every coldkey.
        block_hash = await subtensor.substrate.get_chain_head()
        (
            (all_hotkeys, total_balance),
            _dynamic_info,
            block,
            all_netuids,
        ) = await asyncio.gather(
            _get_total_balance(
                total_balance, subtensor, wallet, all_wallets, block_hash=block_hash
            ),
            subtensor.all_subnets(block_hash=block_hash),
            subtensor.substrate.get_block_number(block_hash=block_hash),
            subtensor.get_all_subnet_netuids(block_hash=block_hash),
        )
        dynamic_info = {info.netuid: info for info in _dynamic_info}

        # We are printing for a select number of hotkeys from all_hotkeys.
        if include_hotkeys or exclude_hotkeys:
            all_hotkeys = _get_hotkeys(include_hotkeys, exclude_hotkeys, all_hotkeys)

        # Check we have keys to display.
        if not all_hotkeys:
            print_error("Aborting as no hotkeys found to process", status)
            return

        # Pull neuron info for all keys.
        neurons: dict[str, list[NeuronInfoLite]] = {}

        netuids = await subtensor.filter_netuids_by_registered_hotkeys(
            all_netuids, netuids_filter, all_hotkeys, reuse_block=True
        )

        for netuid in netuids:
            neurons[str(netuid)] = []

        all_wallet_data = {(wallet.name, wallet.path) for wallet in all_hotkeys}

        all_coldkey_wallets = [
            Wallet(name=wallet_name, path=wallet_path)
            for wallet_name, wallet_path in all_wallet_data
        ]

        all_coldkey_wallets, invalid_wallets = validate_coldkey_presence(
            all_coldkey_wallets
        )
        for invalid_wallet in invalid_wallets:
            print_error(
                f"No coldkeypub found for wallet: ({invalid_wallet.name})", status
            )
        all_hotkeys, _ = validate_coldkey_presence(all_hotkeys)

        all_hotkey_addresses, hotkey_coldkey_to_hotkey_wallet = _get_key_address(
            all_hotkeys
        )

        results = await _get_neurons_for_netuids(
            subtensor, netuids, all_hotkey_addresses
        )
        neurons = _process_neuron_results(results, neurons, netuids)
        # Setup outer table.
        grid = Table.grid(pad_edge=True)
        data_dict = {
            "wallet": "",
            "network": subtensor.network,
            "subnets": [],
            "total_balance": 0.0,
        }

        # Add title
        if not all_wallets:
            title = "[underline dark_orange]Wallet[/underline dark_orange]\n"
            details = (
                f"[bright_cyan]{wallet.name}[/bright_cyan] : "
                f"[bright_magenta]{wallet.coldkeypub.ss58_address}[/bright_magenta]"
            )
            grid.add_row(Align(title, vertical="middle", align="center"))
            grid.add_row(Align(details, vertical="middle", align="center"))
            data_dict["wallet"] = f"{wallet.name}|{wallet.coldkeypub.ss58_address}"
        else:
            title = "[underline dark_orange]All Wallets:[/underline dark_orange]"
            grid.add_row(Align(title, vertical="middle", align="center"))
            data_dict["wallet"] = "All"

        grid.add_row(
            Align(
                f"[dark_orange]Network: {subtensor.network}",
                vertical="middle",
                align="center",
            )
        )
        # Generate rows per netuid
        tempos = await asyncio.gather(
            *[
                subtensor.get_hyperparameter("Tempo", netuid, block_hash)
                for netuid in netuids
            ]
        )
    for netuid, subnet_tempo in zip(netuids, tempos):
        table_data = []
        subnet_dict = {
            "netuid": netuid,
            "tempo": subnet_tempo,
            "neurons": [],
            "name": "",
            "symbol": "",
        }
        data_dict["subnets"].append(subnet_dict)
        total_rank = 0.0
        total_trust = 0.0
        total_consensus = 0.0
        total_validator_trust = 0.0
        total_incentive = 0.0
        total_dividends = 0.0
        total_emission = 0
        total_stake = 0
        total_neurons = 0

        for nn in neurons[str(netuid)]:
            hotwallet = hotkey_coldkey_to_hotkey_wallet.get(nn.hotkey, {}).get(
                nn.coldkey, None
            )
            if not hotwallet:
                # Indicates a mismatch between what the chain says the coldkey
                # is for this hotkey and the local wallet coldkey-hotkey pair
                hotwallet = WalletLike(name=nn.coldkey[:7], hotkey_str=nn.hotkey[:7])

            nn: NeuronInfoLite
            uid = nn.uid
            active = nn.active
            stake = nn.total_stake.tao
            rank = nn.rank
            trust = nn.trust
            consensus = nn.consensus
            validator_trust = nn.validator_trust
            incentive = nn.incentive
            dividends = nn.dividends
            emission = int(nn.emission / (subnet_tempo + 1) * 1e9)  # Per block
            last_update = int(block - nn.last_update)
            validator_permit = nn.validator_permit
            row = [
                hotwallet.name,
                hotwallet.hotkey_str,
                str(uid),
                str(active),
                f"{stake:.4f}" if verbose else millify_tao(stake),
                f"{rank:.4f}" if verbose else millify_tao(rank),
                f"{trust:.4f}" if verbose else millify_tao(trust),
                f"{consensus:.4f}" if verbose else millify_tao(consensus),
                f"{incentive:.4f}" if verbose else millify_tao(incentive),
                f"{dividends:.4f}" if verbose else millify_tao(dividends),
                f"{emission:.4f}",
                f"{validator_trust:.4f}" if verbose else millify_tao(validator_trust),
                "*" if validator_permit else "",
                str(last_update),
                (
                    int_to_ip(nn.axon_info.ip) + ":" + str(nn.axon_info.port)
                    if nn.axon_info.port != 0
                    else "[yellow]none[/yellow]"
                ),
                nn.hotkey[:10],
            ]
            neuron_dict = {
                "coldkey": hotwallet.name,
                "hotkey": hotwallet.hotkey_str,
                "uid": uid,
                "active": active,
                "stake": stake,
                "rank": rank,
                "trust": trust,
                "consensus": consensus,
                "incentive": incentive,
                "dividends": dividends,
                "emission": emission,
                "validator_trust": validator_trust,
                "validator_permit": validator_permit,
                "last_update": last_update,
                "axon": int_to_ip(nn.axon_info.ip) + ":" + str(nn.axon_info.port)
                if nn.axon_info.port != 0
                else None,
                "hotkey_ss58": nn.hotkey,
            }

            total_rank += rank
            total_trust += trust
            total_consensus += consensus
            total_incentive += incentive
            total_dividends += dividends
            total_emission += emission
            total_validator_trust += validator_trust
            total_stake += stake
            total_neurons += 1

            table_data.append(row)
            subnet_dict["neurons"].append(neuron_dict)

        # Add subnet header
        sn_name = get_subnet_name(dynamic_info[netuid])
        sn_symbol = dynamic_info[netuid].symbol
        grid.add_row(
            f"Subnet: [dark_orange]{netuid}: {sn_name} {sn_symbol}[/dark_orange]"
        )
        subnet_dict["name"] = sn_name
        subnet_dict["symbol"] = sn_symbol
        width = console.width
        table = Table(
            show_footer=False,
            pad_edge=True,
            box=box.SIMPLE,
            expand=True,
            width=width - 5,
        )

        table.add_column("[white]COLDKEY", style="bold bright_cyan", ratio=2)
        table.add_column("[white]HOTKEY", style="bright_cyan", ratio=2)
        table.add_column(
            "[white]UID", str(total_neurons), style="rgb(42,161,152)", ratio=1
        )
        table.add_column(
            "[white]ACTIVE", justify="right", style="#8787ff", no_wrap=True, ratio=1
        )

        _total_stake_formatted = (
            f"{total_stake:.4f}" if verbose else millify_tao(total_stake)
        )
        table.add_column(
            "[white]STAKE(\u03c4)"
            if netuid == 0
            else f"[white]STAKE({Balance.get_unit(netuid)})",
            f"{_total_stake_formatted} {Balance.get_unit(netuid)}"
            if netuid != 0
            else f"{Balance.get_unit(netuid)} {_total_stake_formatted}",
            justify="right",
            style="dark_orange",
            no_wrap=True,
            ratio=1.5,
        )
        table.add_column(
            "[white]RANK",
            f"{total_rank:.4f}",
            justify="right",
            style="medium_purple",
            no_wrap=True,
            ratio=1.5,
        )
        table.add_column(
            "[white]TRUST",
            f"{total_trust:.4f}",
            justify="right",
            style="green",
            no_wrap=True,
            ratio=1.5,
        )
        table.add_column(
            "[white]CONSENSUS",
            f"{total_consensus:.4f}",
            justify="right",
            style="rgb(42,161,152)",
            no_wrap=True,
            ratio=1.5,
        )
        table.add_column(
            "[white]INCENTIVE",
            f"{total_incentive:.4f}",
            justify="right",
            style="#5fd7ff",
            no_wrap=True,
            ratio=1.5,
        )
        table.add_column(
            "[white]DIVIDENDS",
            f"{total_dividends:.4f}",
            justify="right",
            style="#8787d7",
            no_wrap=True,
            ratio=1.5,
        )
        table.add_column(
            "[white]EMISSION(\u03c1)",
            f"\u03c1{total_emission}",
            justify="right",
            style="#d7d7ff",
            no_wrap=True,
            ratio=1.5,
        )
        table.add_column(
            "[white]VTRUST",
            f"{total_validator_trust:.4f}",
            justify="right",
            style="magenta",
            no_wrap=True,
            ratio=1.5,
        )
        table.add_column("[white]VPERMIT", justify="center", no_wrap=True, ratio=0.75)
        table.add_column("[white]UPDATED", justify="right", no_wrap=True, ratio=1)
        table.add_column(
            "[white]AXON", justify="left", style="light_goldenrod2", ratio=2.5
        )
        table.add_column("[white]HOTKEY_SS58", style="bright_magenta", ratio=2)
        table.show_footer = True

        if sort_by:
            column_to_sort_by: int = 0
            sort_descending: bool = False  # Default sort_order to ascending

            for index, column in zip(range(len(table.columns)), table.columns):
                column_name = column.header.lower().replace("[white]", "")
                if column_name == sort_by.lower().strip():
                    column_to_sort_by = index

            if sort_order.lower() in {"desc", "descending", "reverse"}:
                # Sort descending if the sort_order matches desc, descending, or reverse
                sort_descending = True

            def overview_sort_function(row_):
                data = row_[column_to_sort_by]
                # Try to convert to number if possible
                try:
                    data = float(data)
                except ValueError:
                    pass
                return data

            table_data.sort(key=overview_sort_function, reverse=sort_descending)

        for row in table_data:
            table.add_row(*row)

        grid.add_row(table)

    caption = (
        f"\n[italic][dim][bright_cyan]Wallet free balance: [dark_orange]{total_balance}"
    )
    data_dict["total_balance"] = total_balance.tao
    grid.add_row(Align(caption, vertical="middle", align="center"))

    if console.width < 150:
        console.print(
            "[yellow]Warning: Your terminal width might be too small to view all information clearly"
        )
    # Print the entire table/grid
    if not json_output:
        console.print(grid, width=None)
    else:
        json_console.print(json.dumps(data_dict))


def _get_hotkeys(
    include_hotkeys: list[str], exclude_hotkeys: list[str], all_hotkeys: list[Wallet]
) -> list[Wallet]:
    """Filters a set of hotkeys (all_hotkeys) based on whether they are included or excluded."""

    def is_hotkey_matched(wallet: Wallet, item: str) -> bool:
        if is_valid_ss58_address(item):
            return wallet.hotkey.ss58_address == item
        else:
            return wallet.hotkey_str == item

    if include_hotkeys:
        # We are only showing hotkeys that are specified.
        all_hotkeys = [
            hotkey
            for hotkey in all_hotkeys
            if any(is_hotkey_matched(hotkey, item) for item in include_hotkeys)
        ]
    else:
        # We are excluding the specified hotkeys from all_hotkeys.
        all_hotkeys = [
            hotkey
            for hotkey in all_hotkeys
            if not any(is_hotkey_matched(hotkey, item) for item in exclude_hotkeys)
        ]
    return all_hotkeys


def _get_key_address(all_hotkeys: list[Wallet]) -> tuple[list[str], dict[str, Wallet]]:
    """
    Maps the hotkeys specified to their respective addresses

    :param all_hotkeys: list of hotkeys from which to derive the addresses

    :return: (list of all hotkey addresses, mapping of them vs their coldkeys to respective wallets)
    """
    hotkey_coldkey_to_hotkey_wallet = {}
    for hotkey_wallet in all_hotkeys:
        if hotkey_wallet.coldkeypub:
            if hotkey_wallet.hotkey.ss58_address not in hotkey_coldkey_to_hotkey_wallet:
                hotkey_coldkey_to_hotkey_wallet[hotkey_wallet.hotkey.ss58_address] = {}
            hotkey_coldkey_to_hotkey_wallet[hotkey_wallet.hotkey.ss58_address][
                hotkey_wallet.coldkeypub.ss58_address
            ] = hotkey_wallet
        else:
            # occurs when there is a hotkey without an associated coldkeypub
            # TODO log this, maybe display
            pass

    all_hotkey_addresses = list(hotkey_coldkey_to_hotkey_wallet.keys())

    return all_hotkey_addresses, hotkey_coldkey_to_hotkey_wallet


async def _calculate_total_coldkey_stake(
    neurons: dict[str, list["NeuronInfoLite"]],
) -> dict[str, Balance]:
    """Maps coldkeys to their stakes (Balance) in the specified neurons"""
    total_coldkey_stake_from_metagraph = defaultdict(lambda: Balance(0.0))
    checked_hotkeys = set()
    for neuron_list in neurons.values():
        for neuron in neuron_list:
            if neuron.hotkey in checked_hotkeys:
                continue
            total_coldkey_stake_from_metagraph[neuron.coldkey] += neuron.stake_dict[
                neuron.coldkey
            ]
            checked_hotkeys.add(neuron.hotkey)
    return total_coldkey_stake_from_metagraph


def _process_neuron_results(
    results: list[tuple[int, list["NeuronInfoLite"], Optional[str]]],
    neurons: dict[str, list["NeuronInfoLite"]],
    netuids: list[int],
) -> dict[str, list["NeuronInfoLite"]]:
    """
    Filters a list of Neurons for their netuid, neuron info, and errors

    :param results: [(netuid, neurons result, error message), ...]
    :param neurons: {netuid: [], ...}
    :param netuids: list of netuids to filter the neurons

    :return: the filtered neurons dict
    """
    for result in results:
        netuid, neurons_result, err_msg = result
        if err_msg is not None:
            console.print(f"netuid '{netuid}': {err_msg}")

        if len(neurons_result) == 0:
            # Remove netuid from overview if no neurons are found.
            netuids.remove(netuid)
            del neurons[str(netuid)]
        else:
            # Add neurons to overview.
            neurons[str(netuid)] = neurons_result
    return neurons


def _map_hotkey_to_neurons(
    all_neurons: list["NeuronInfoLite"],
    hot_wallets: list[str],
    netuid: int,
) -> tuple[int, list["NeuronInfoLite"], Optional[str]]:
    """Maps the hotkeys to their respective neurons"""
    result: list["NeuronInfoLite"] = []
    hotkey_to_neurons = {n.hotkey: n.uid for n in all_neurons}
    try:
        for hot_wallet_addr in hot_wallets:
            uid = hotkey_to_neurons.get(hot_wallet_addr)
            if uid is not None:
                nn = all_neurons[uid]
                result.append(nn)
    except Exception as e:
        return netuid, [], f"Error: {e}"

    return netuid, result, None


async def _fetch_neuron_for_netuid(
    netuid: int, subtensor: SubtensorInterface
) -> tuple[int, list[NeuronInfoLite]]:
    """
    Retrieves all neurons for a specified netuid

    :param netuid: the netuid to query
    :param subtensor: the SubtensorInterface to make the query

    :return: the original netuid, and a mapping of the neurons to their NeuronInfoLite objects
    """
    neurons = await subtensor.neurons_lite(netuid=netuid)
    return netuid, neurons


async def _fetch_all_neurons(
    netuids: list[int], subtensor
) -> list[tuple[int, list[NeuronInfoLite]]]:
    """Retrieves all neurons for each of the specified netuids"""
    return list(
        await asyncio.gather(
            *[_fetch_neuron_for_netuid(netuid, subtensor) for netuid in netuids]
        )
    )


async def _get_neurons_for_netuids(
    subtensor: SubtensorInterface, netuids: list[int], hot_wallets: list[str]
) -> list[tuple[int, list["NeuronInfoLite"], Optional[str]]]:
    all_neurons = await _fetch_all_neurons(netuids, subtensor)
    return [
        _map_hotkey_to_neurons(neurons, hot_wallets, netuid)
        for netuid, neurons in all_neurons
    ]


async def transfer(
    wallet: Wallet,
    subtensor: SubtensorInterface,
    destination: str,
    amount: float,
    transfer_all: bool,
    era: int,
    prompt: bool,
    json_output: bool,
):
    """Transfer token of amount to destination."""
    result = await transfer_extrinsic(
        subtensor=subtensor,
        wallet=wallet,
        destination=destination,
        amount=Balance.from_tao(amount),
        transfer_all=transfer_all,
        era=era,
        prompt=prompt,
    )
    if json_output:
        json_console.print(json.dumps({"success": result}))
    return result


async def inspect(
    wallet: Wallet,
    subtensor: SubtensorInterface,
    netuids_filter: list[int],
    all_wallets: bool = False,
):
    # TODO add json_output when this is re-enabled and updated for dTAO
    def delegate_row_maker(
        delegates_: list[tuple[DelegateInfo, Balance]],
    ) -> Generator[list[str], None, None]:
        for d_, staked in delegates_:
            if not staked.tao > 0:
                continue
            if d_.hotkey_ss58 in registered_delegate_info:
                delegate_name = registered_delegate_info[d_.hotkey_ss58].display
            else:
                delegate_name = d_.hotkey_ss58
            yield (
                [""] * 2
                + [
                    str(delegate_name),
                    str(staked),
                    str(
                        d_.total_daily_return.tao * (staked.tao / d_.total_stake.tao)
                        if d_.total_stake.tao != 0
                        else 0
                    ),
                ]
                + [""] * 4
            )

    def neuron_row_maker(
        wallet_, all_netuids_, nsd
    ) -> Generator[list[str], None, None]:
        hotkeys = get_hotkey_wallets_for_wallet(wallet_)
        for netuid in all_netuids_:
            for n in nsd[netuid]:
                if n.coldkey == wallet_.coldkeypub.ss58_address:
                    hotkey_name: str = ""
                    if hotkey_names := [
                        w.hotkey_str
                        for w in hotkeys
                        if w.hotkey.ss58_address == n.hotkey
                    ]:
                        hotkey_name = f"{hotkey_names[0]}-"
                    yield [""] * 5 + [
                        str(netuid),
                        f"{hotkey_name}{n.hotkey}",
                        str(n.stake),
                        str(Balance.from_tao(n.emission)),
                    ]

    if all_wallets:
        print_verbose("Fetching data for all wallets")
        wallets = get_coldkey_wallets_for_path(wallet.path)
        all_hotkeys = get_all_wallets_for_path(
            wallet.path
        )  # TODO verify this is correct

    else:
        print_verbose(f"Fetching data for wallet: {wallet.name}")
        wallets = [wallet]
        all_hotkeys = get_hotkey_wallets_for_wallet(wallet)

    with console.status("Synchronising with chain...", spinner="aesthetic") as status:
        block_hash = await subtensor.substrate.get_chain_head()
        await subtensor.substrate.init_runtime(block_hash=block_hash)

        print_verbose("Fetching netuids of registered hotkeys", status)
        all_netuids = await subtensor.filter_netuids_by_registered_hotkeys(
            (await subtensor.get_all_subnet_netuids(block_hash)),
            netuids_filter,
            all_hotkeys,
            block_hash=block_hash,
        )
    # bittensor.logging.debug(f"Netuids to check: {all_netuids}")
    with console.status("Pulling delegates info...", spinner="aesthetic"):
        registered_delegate_info = await subtensor.get_delegate_identities()
        if not registered_delegate_info:
            console.print(
                ":warning:[yellow]Could not get delegate info from chain.[/yellow]"
            )

    table = Table(
        Column("[bold white]Coldkey", style="dark_orange"),
        Column("[bold white]Balance", style="dark_sea_green"),
        Column("[bold white]Delegate", style="bright_cyan", overflow="fold"),
        Column("[bold white]Stake", style="light_goldenrod2"),
        Column("[bold white]Emission", style="rgb(42,161,152)"),
        Column("[bold white]Netuid", style="dark_orange"),
        Column("[bold white]Hotkey", style="bright_magenta", overflow="fold"),
        Column("[bold white]Stake", style="light_goldenrod2"),
        Column("[bold white]Emission", style="rgb(42,161,152)"),
        title=f"[underline dark_orange]Wallets[/underline dark_orange]\n[dark_orange]Network: {subtensor.network}\n",
        show_edge=False,
        expand=True,
        box=box.MINIMAL,
        border_style="bright_black",
    )
    rows = []
    wallets_with_ckp_file = [
        wallet for wallet in wallets if wallet.coldkeypub_file.exists_on_device()
    ]
    all_delegates: list[list[tuple[DelegateInfo, Balance]]]
    with console.status("Pulling balance data...", spinner="aesthetic"):
        balances, all_neurons, all_delegates = await asyncio.gather(
            subtensor.get_balances(
                *[w.coldkeypub.ss58_address for w in wallets_with_ckp_file],
                block_hash=block_hash,
            ),
            asyncio.gather(
                *[
                    subtensor.neurons_lite(netuid=netuid, block_hash=block_hash)
                    for netuid in all_netuids
                ]
            ),
            asyncio.gather(
                *[
                    subtensor.get_delegated(w.coldkeypub.ss58_address)
                    for w in wallets_with_ckp_file
                ]
            ),
        )
    neuron_state_dict = {}
    for netuid, neuron in zip(all_netuids, all_neurons):
        neuron_state_dict[netuid] = neuron if neuron else []

    for wall, d in zip(wallets_with_ckp_file, all_delegates):
        rows.append([wall.name, str(balances[wall.coldkeypub.ss58_address])] + [""] * 7)
        for row in itertools.chain(
            delegate_row_maker(d),
            neuron_row_maker(wall, all_netuids, neuron_state_dict),
        ):
            rows.append(row)

    for i, row in enumerate(rows):
        is_last_row = i + 1 == len(rows)
        table.add_row(*row)

        # If last row or new coldkey starting next
        if is_last_row or (rows[i + 1][0] != ""):
            table.add_row(end_section=True)

    return console.print(table)


async def faucet(
    wallet: Wallet,
    subtensor: SubtensorInterface,
    threads_per_block: int,
    update_interval: int,
    processes: int,
    use_cuda: bool,
    dev_id: int,
    output_in_place: bool,
    log_verbose: bool,
    max_successes: int = 3,
    prompt: bool = True,
):
    # TODO: - work out prompts to be passed through the cli
    success = await run_faucet_extrinsic(
        subtensor,
        wallet,
        tpb=threads_per_block,
        prompt=prompt,
        update_interval=update_interval,
        num_processes=processes,
        cuda=use_cuda,
        dev_id=dev_id,
        output_in_place=output_in_place,
        log_verbose=log_verbose,
        max_successes=max_successes,
    )
    if not success:
        err_console.print("Faucet run failed.")


async def swap_hotkey(
    original_wallet: Wallet,
    new_wallet: Wallet,
    subtensor: SubtensorInterface,
    netuid: Optional[int],
    prompt: bool,
    json_output: bool,
):
    """Swap your hotkey for all registered axons on the network."""
    result = await swap_hotkey_extrinsic(
        subtensor,
        original_wallet,
        new_wallet,
        netuid=netuid,
        prompt=prompt,
    )
    if json_output:
        json_console.print(json.dumps({"success": result}))
    return result


def create_identity_table(title: str = None):
    if not title:
        title = "On-Chain Identity"

    table = Table(
        Column(
            "Item",
            justify="right",
            style=COLOR_PALETTE["GENERAL"]["SUBHEADING_MAIN"],
            no_wrap=True,
        ),
        Column("Value", style=COLOR_PALETTE["GENERAL"]["SUBHEADING"]),
        title=f"\n[{COLOR_PALETTE['GENERAL']['HEADER']}]{title}",
        show_footer=True,
        show_edge=False,
        header_style="bold white",
        border_style="bright_black",
        style="bold",
        title_justify="center",
        show_lines=False,
        pad_edge=True,
    )
    return table


async def set_id(
    wallet: Wallet,
    subtensor: SubtensorInterface,
    name: str,
    web_url: str,
    image_url: str,
    discord: str,
    description: str,
    additional: str,
    github_repo: str,
    prompt: bool,
    json_output: bool = False,
):
    """Create a new or update existing identity on-chain."""
    output_dict = {"success": False, "identity": None, "error": ""}
    identity_data = {
        "name": name.encode(),
        "url": web_url.encode(),
        "image": image_url.encode(),
        "discord": discord.encode(),
        "description": description.encode(),
        "additional": additional.encode(),
        "github_repo": github_repo.encode(),
    }

    if not unlock_key(wallet).success:
        return False

    call = await subtensor.substrate.compose_call(
        call_module="SubtensorModule",
        call_function="set_identity",
        call_params=identity_data,
    )

    with console.status(
        " :satellite: [dark_sea_green3]Updating identity on-chain...", spinner="earth"
    ):
        success, err_msg = await subtensor.sign_and_send_extrinsic(call, wallet)

        if not success:
            err_console.print(f"[red]:cross_mark: Failed![/red] {err_msg}")
            output_dict["error"] = err_msg
            if json_output:
                json_console.print(json.dumps(output_dict))
            return
        else:
            console.print(":white_heavy_check_mark: [dark_sea_green3]Success!")
            output_dict["success"] = True
            identity = await subtensor.query_identity(wallet.coldkeypub.ss58_address)

    table = create_identity_table(title="New on-chain Identity")
    table.add_row("Address", wallet.coldkeypub.ss58_address)
    for key, value in identity.items():
        table.add_row(key, str(value) if value else "~")
    output_dict["identity"] = identity
    console.print(table)
    if json_output:
        json_console.print(json.dumps(output_dict))


async def get_id(
    subtensor: SubtensorInterface,
    ss58_address: str,
    title: str = None,
    json_output: bool = False,
):
    with console.status(
        ":satellite: [bold green]Querying chain identity...", spinner="earth"
    ):
        identity = await subtensor.query_identity(ss58_address)

    if not identity:
        err_console.print(
            f"[blue]Existing identity not found[/blue]"
            f" for [{COLOR_PALETTE['GENERAL']['COLDKEY']}]{ss58_address}[/{COLOR_PALETTE['GENERAL']['COLDKEY']}]"
            f" on {subtensor}"
        )
        if json_output:
            json_console.print("{}")
        return {}

    table = create_identity_table(title)
    table.add_row("Address", ss58_address)
    for key, value in identity.items():
        table.add_row(key, str(value) if value else "~")

    console.print(table)
    if json_output:
        json_console.print(json.dumps(identity))
    return identity


async def check_coldkey_swap(wallet: Wallet, subtensor: SubtensorInterface):
    arbitration_check = len(  # TODO verify this works
        (
            await subtensor.query(
                module="SubtensorModule",
                storage_function="ColdkeySwapDestinations",
                params=[wallet.coldkeypub.ss58_address],
            )
        )
    )
    if arbitration_check == 0:
        console.print(
            "[green]There has been no previous key swap initiated for your coldkey.[/green]"
        )
    elif arbitration_check == 1:
        arbitration_block = await subtensor.query(
            module="SubtensorModule",
            storage_function="ColdkeyArbitrationBlock",
            params=[wallet.coldkeypub.ss58_address],
        )
        arbitration_remaining = (
            arbitration_block.value - await subtensor.substrate.get_block_number(None)
        )

        hours, minutes, seconds = convert_blocks_to_time(arbitration_remaining)
        console.print(
            "[yellow]There has been 1 swap request made for this coldkey already."
            " By adding another swap request, the key will enter arbitration."
            f" Your key swap is scheduled for {hours} hours, {minutes} minutes, {seconds} seconds"
            " from now.[/yellow]"
        )
    elif arbitration_check > 1:
        console.print(
            f"[red]This coldkey is currently in arbitration with a total swaps of {arbitration_check}.[/red]"
        )


async def sign(
    wallet: Wallet, message: str, use_hotkey: str, json_output: bool = False
):
    """Sign a message using the provided wallet or hotkey."""

    if not use_hotkey:
        if not unlock_key(wallet, "cold").success:
            return False
        keypair = wallet.coldkey
        print_verbose(
            f"Signing using [{COLOR_PALETTE['GENERAL']['COLDKEY']}]coldkey: {wallet.name}"
        )
    else:
        if not unlock_key(wallet, "hot").success:
            return False
        keypair = wallet.hotkey
        print_verbose(
            f"Signing using [{COLOR_PALETTE['GENERAL']['HOTKEY']}]hotkey: {wallet.hotkey_str}"
        )

    signed_message = keypair.sign(message.encode("utf-8")).hex()
    console.print("[dark_sea_green3]Message signed successfully:")
    if json_output:
        json_console.print(json.dumps({"signed_message": signed_message}))
    console.print(signed_message)


async def schedule_coldkey_swap(
    wallet: Wallet,
    subtensor: SubtensorInterface,
    new_coldkey_ss58: str,
    force_swap: bool = False,
) -> bool:
    """Schedules a coldkey swap operation to be executed at a future block.

    Args:
        wallet (Wallet): The wallet initiating the coldkey swap
        subtensor (SubtensorInterface): Connection to the Bittensor network
        new_coldkey_ss58 (str): SS58 address of the new coldkey
        force_swap (bool, optional): Whether to force the swap even if the new coldkey is already scheduled for a swap. Defaults to False.
    Returns:
        bool: True if the swap was scheduled successfully, False otherwise
    """
    if not is_valid_ss58_address(new_coldkey_ss58):
        print_error(f"Invalid SS58 address format: {new_coldkey_ss58}")
        return False

    scheduled_coldkey_swap = await subtensor.get_scheduled_coldkey_swap()
    if wallet.coldkeypub.ss58_address in scheduled_coldkey_swap:
        print_error(
            f"Coldkey {wallet.coldkeypub.ss58_address} is already scheduled for a swap."
        )
        console.print("[dim]Use the force_swap (--force) flag to override this.[/dim]")
        if not force_swap:
            return False
        else:
            console.print(
                "[yellow]Continuing with the swap due to force_swap flag.[/yellow]\n"
            )

    prompt = (
        "You are [red]swapping[/red] your [blue]coldkey[/blue] to a new address.\n"
        f"Current ss58: [{COLORS.G.CK}]{wallet.coldkeypub.ss58_address}[/{COLORS.G.CK}]\n"
        f"New ss58: [{COLORS.G.CK}]{new_coldkey_ss58}[/{COLORS.G.CK}]\n"
        "Are you sure you want to continue?"
    )
    if not Confirm.ask(prompt):
        return False

    if not unlock_key(wallet).success:
        return False

    block_pre_call, call = await asyncio.gather(
        subtensor.substrate.get_block_number(),
        subtensor.substrate.compose_call(
            call_module="SubtensorModule",
            call_function="schedule_swap_coldkey",
            call_params={
                "new_coldkey": new_coldkey_ss58,
            },
        ),
    )

    with console.status(":satellite: Scheduling coldkey swap on-chain..."):
        success, err_msg = await subtensor.sign_and_send_extrinsic(
            call,
            wallet,
            wait_for_inclusion=True,
            wait_for_finalization=True,
        )
        block_post_call = await subtensor.substrate.get_block_number()

        if not success:
            print_error(f"Failed to schedule coldkey swap: {err_msg}")
            return False

        console.print(
            ":white_heavy_check_mark: [green]Successfully scheduled coldkey swap"
        )

    swap_info = await find_coldkey_swap_extrinsic(
        subtensor=subtensor,
        start_block=block_pre_call,
        end_block=block_post_call,
        wallet_ss58=wallet.coldkeypub.ss58_address,
    )

    if not swap_info:
        console.print(
            "[yellow]Warning: Could not find the swap extrinsic in recent blocks"
        )
        return True

    console.print(
        "\n[green]Coldkey swap details:[/green]"
        f"\nBlock number: {swap_info['block_num']}"
        f"\nOriginal address: [{COLORS.G.CK}]{wallet.coldkeypub.ss58_address}[/{COLORS.G.CK}]"
        f"\nDestination address: [{COLORS.G.CK}]{swap_info['dest_coldkey']}[/{COLORS.G.CK}]"
        f"\nThe swap will be completed at block: [green]{swap_info['execution_block']}[/green]"
        f"\n[dim]You can provide the block number to `btcli wallet swap-check`[/dim]"
    )


async def find_coldkey_swap_extrinsic(
    subtensor: SubtensorInterface,
    start_block: int,
    end_block: int,
    wallet_ss58: str,
) -> dict:
    """Search for a coldkey swap event in a range of blocks.

    Args:
        subtensor: SubtensorInterface for chain queries
        start_block: Starting block number to search
        end_block: Ending block number to search (inclusive)
        wallet_ss58: SS58 address of the signing wallet

    Returns:
        dict: Contains the following keys if found:
            - block_num: Block number where swap was scheduled
            - dest_coldkey: SS58 address of destination coldkey
            - execution_block: Block number when swap will execute
        Empty dict if not found
    """

    current_block, genesis_block = await asyncio.gather(
        subtensor.substrate.get_block_number(), subtensor.substrate.get_block_hash(0)
    )
    if (
        current_block - start_block > 300
        and genesis_block == Constants.genesis_block_hash_map["finney"]
    ):
        console.print("Querying archive node for coldkey swap events...")
        await subtensor.substrate.close()
        subtensor = SubtensorInterface("archive")

    block_hashes = await asyncio.gather(
        *[
            subtensor.substrate.get_block_hash(block_num)
            for block_num in range(start_block, end_block + 1)
        ]
    )
    block_events = await asyncio.gather(
        *[
            subtensor.substrate.get_events(block_hash=block_hash)
            for block_hash in block_hashes
        ]
    )

    for block_num, events in zip(range(start_block, end_block + 1), block_events):
        for event in events:
            if (
                event.get("event", {}).get("module_id") == "SubtensorModule"
                and event.get("event", {}).get("event_id") == "ColdkeySwapScheduled"
            ):
                attributes = event["event"].get("attributes", {})
                old_coldkey = decode_account_id(attributes["old_coldkey"][0])

                if old_coldkey == wallet_ss58:
                    return {
                        "block_num": block_num,
                        "dest_coldkey": decode_account_id(attributes["new_coldkey"][0]),
                        "execution_block": attributes["execution_block"],
                    }

    return {}


async def check_swap_status(
    subtensor: SubtensorInterface,
    origin_ss58: Optional[str] = None,
    expected_block_number: Optional[int] = None,
) -> None:
    """
    Check the status of a coldkey swap.

    Args:
        subtensor: Connection to the network
        origin_ss58: The SS58 address of the original coldkey
        expected_block_number: Optional block number where the swap was scheduled

    """

    if not origin_ss58:
        scheduled_swaps = await subtensor.get_scheduled_coldkey_swap()
        if not scheduled_swaps:
            console.print("[yellow]No pending coldkey swaps found.[/yellow]")
            return

        table = Table(
            Column(
                "Original Coldkey",
                justify="Left",
                style=COLOR_PALETTE["GENERAL"]["SUBHEADING_MAIN"],
                no_wrap=True,
            ),
            Column("Status", style="dark_sea_green3"),
            title=f"\n[{COLOR_PALETTE['GENERAL']['HEADER']}]Pending Coldkey Swaps\n",
            show_header=True,
            show_edge=False,
            header_style="bold white",
            border_style="bright_black",
            style="bold",
            title_justify="center",
            show_lines=False,
            pad_edge=True,
        )

        for coldkey in scheduled_swaps:
            table.add_row(coldkey, "Pending")

        console.print(table)
        console.print(
            "\n[dim]Tip: Check specific swap details by providing the original coldkey "
            "SS58 address and the block number.[/dim]"
        )
        return
    chain_reported_completion_block, destination_address = await subtensor.query(
        "SubtensorModule", "ColdkeySwapScheduled", [origin_ss58]
    )
    if (
        chain_reported_completion_block != 0
        and destination_address != "5C4hrfjw9DjXZTzV3MwzrrAr9P1MJhSrvWGWqi1eSuyUpnhM"
    ):
        is_pending = True
    else:
        is_pending = False

    if not is_pending:
        console.print(
            f"[red]No pending swap found for coldkey:[/red] [{COLORS.G.CK}]{origin_ss58}[/{COLORS.G.CK}]"
        )
        return

    console.print(
        f"[green]Found pending swap for coldkey:[/green] [{COLORS.G.CK}]{origin_ss58}[/{COLORS.G.CK}]"
    )

    if expected_block_number is None:
        expected_block_number = chain_reported_completion_block

    current_block = await subtensor.substrate.get_block_number()
    remaining_blocks = expected_block_number - current_block

    if remaining_blocks <= 0:
        console.print("[green]Swap period has completed![/green]")
        return

    console.print(
        "\n[green]Coldkey swap details:[/green]"
        f"\nOriginal address: [{COLORS.G.CK}]{origin_ss58}[/{COLORS.G.CK}]"
        f"\nDestination address: [{COLORS.G.CK}]{destination_address}[/{COLORS.G.CK}]"
        f"\nCompletion block: {chain_reported_completion_block}"
        f"\nTime remaining: {blocks_to_duration(remaining_blocks)}"
    )
