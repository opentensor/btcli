import asyncio
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
import itertools
import os
from sys import getsizeof
from typing import Optional, Any, Collection, Generator

import aiohttp
from bittensor_wallet import Wallet
from bittensor_wallet.errors import KeyFileError
from bittensor_wallet.keyfile import Keyfile
from fuzzywuzzy import fuzz
from rich.align import Align
from rich.prompt import Confirm, Prompt
from rich.table import Table, Column
from rich.tree import Tree
import scalecodec
import typer
from scalecodec import ScaleBytes

from bittensor_cli.src import utils, TYPE_REGISTRY, DelegatesDetails, Constants
from bittensor_cli.src.bittensor.chain_data import (
    NeuronInfoLite,
    custom_rpc_type_registry,
    StakeInfo,
    DelegateInfo,
)
from bittensor_cli.src.bittensor.networking import int_to_ip
from bittensor_cli.src.utils import (
    console,
    err_console,
    RAO_PER_TAO,
    decode_scale_bytes,
    get_all_wallets_for_path,
    get_hotkey_wallets_for_wallet,
    get_delegates_details_from_github,
    convert_blocks_to_time,
)
from bittensor_cli.src.subtensor_interface import SubtensorInterface
from bittensor_cli.src.bittensor.balances import Balance
from bittensor_cli.src.bittensor.extrinsics.transfer import transfer_extrinsic
from bittensor_cli.src.bittensor.extrinsics.registration import (
    run_faucet_extrinsic,
    swap_hotkey_extrinsic,
)


async def regen_coldkey(
    wallet: Wallet,
    mnemonic: Optional[str],
    seed: Optional[str] = None,
    json_path: Optional[str] = None,
    json_password: Optional[str] = "",
    use_password: Optional[bool] = True,
    overwrite_coldkey: Optional[bool] = False,
):
    """Creates a new coldkey under this wallet"""
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
    wallet: Wallet, ss58_address: str, public_key_hex: str, overwrite_coldkeypub: bool
):
    """Creates a new coldkeypub under this wallet."""
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
    """Creates a new hotkey under this wallet."""
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
    """Creates a new hotkey under this wallet."""
    wallet.create_new_hotkey(
        n_words=n_words,
        use_password=use_password,
        overwrite=overwrite_hotkey,
    )


async def new_coldkey(
    wallet: Wallet, n_words: int, use_password: bool, overwrite_coldkey: bool
):
    """Creates a new coldkey under this wallet."""
    wallet.create_new_coldkey(
        n_words=n_words,
        use_password=use_password,
        overwrite=overwrite_coldkey,
    )


async def wallet_create(
    wallet: Wallet,
    n_words: int = 12,
    use_password: bool = True,
    overwrite_coldkey: bool = False,
    overwrite_hotkey: bool = False,
):
    """Creates a new wallet."""
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


def get_coldkey_wallets_for_path(path: str) -> list[Wallet]:
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
    """Retrieves the current balance of the specified wallet"""
    if not wallet.coldkeypub_file.exists_on_device():
        err_console.print("[bold red]No wallets found.[/bold red]")
        return

    with console.status("Retrieving balances", spinner="aesthetic"):
        if all_balances:
            coldkeys, wallet_names = _get_coldkey_ss58_addresses_for_path(wallet.path)
        else:
            coldkeys = [wallet.coldkeypub.ss58_address]
            wallet_names = [wallet.name]

        await subtensor.substrate.get_chain_head()
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
    await subtensor.substrate.close()


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
    """Lists wallets."""
    wallets = utils.get_coldkey_wallets_for_path(wallet_path)
    if not wallets:
        err_console.print(f"[red]No wallets found in dir: {wallet_path}[/red]")

    root = Tree("Wallets")
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
        hotkeys = utils.get_hotkey_wallets_for_wallet(wallet, show_nulls=True)
        for hkey in hotkeys:
            data = f"[bold red]Hotkey[/bold red][green] {hkey}[/green] (?)"
            if hkey:
                try:
                    data = f"[bold red]Hotkey[/bold red] [green]{hkey.hotkey_str}[/green]  ss58_address [green]{hkey.hotkey.ss58_address}[/green]\n"
                except UnicodeDecodeError:
                    pass
            wallet_tree.add(data)

    if not wallets:
        root.add("[bold red]No wallets found.")

    console.print(root)


async def _get_total_balance(
    total_balance: Balance,
    subtensor: SubtensorInterface,
    wallet: Wallet,
    all_wallets: bool = False,
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
                await subtensor.get_balance(
                    *(x.coldkeypub.ss58_address for x in _balance_cold_wallets),
                    reuse_block=True,
                )
            ).values()
        )
        all_hotkeys = [
            hk for w in cold_wallets for hk in utils.get_hotkey_wallets_for_wallet(w)
        ]
    else:
        # We are only printing keys for a single coldkey
        coldkey_wallet = wallet
        if (
            coldkey_wallet.coldkeypub_file.exists_on_device()
            and not coldkey_wallet.coldkeypub_file.is_encrypted()
        ):
            total_balance = sum(
                (
                    await subtensor.get_balance(
                        coldkey_wallet.coldkeypub.ss58_address, reuse_block=True
                    )
                ).values()
            )
        if not coldkey_wallet.coldkeypub_file.exists_on_device():
            console.print("[bold red]No wallets found.")
            return [], None
        all_hotkeys = utils.get_hotkey_wallets_for_wallet(coldkey_wallet)

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
):
    """Prints an overview for the wallet's coldkey."""

    total_balance = Balance(0)
    with console.status(
        f":satellite: Synchronizing with chain [white]{subtensor.network}[/white]",
        spinner="aesthetic",
    ):
        # We are printing for every coldkey.
        block_hash = await subtensor.substrate.get_chain_head()
        all_hotkeys, total_balance = await _get_total_balance(
            total_balance, subtensor, wallet, all_wallets
        )

        # We are printing for a select number of hotkeys from all_hotkeys.
        if include_hotkeys:
            all_hotkeys = _get_hotkeys(include_hotkeys, exclude_hotkeys, all_hotkeys)

        # Check we have keys to display.
        if not all_hotkeys:
            err_console.print("[red]No wallets found.[/red]")
            return

        # Pull neuron info for all keys.
        neurons: dict[str, list[NeuronInfoLite]] = {}
        block, all_netuids = await asyncio.gather(
            subtensor.substrate.get_block_number(None),
            subtensor.get_all_subnet_netuids(),
        )

        netuids = await subtensor.filter_netuids_by_registered_hotkeys(
            all_netuids, netuids_filter, all_hotkeys, reuse_block=True
        )
        # bittensor.logging.debug(f"Netuids to check: {netuids}")

        for netuid in netuids:
            neurons[str(netuid)] = []

        all_wallet_names = {wallet.name for wallet in all_hotkeys}
        all_coldkey_wallets = [
            Wallet(name=wallet_name) for wallet_name in all_wallet_names
        ]

        all_hotkey_addresses, hotkey_coldkey_to_hotkey_wallet = _get_key_address(
            all_hotkeys
        )

        # Pull neuron info for all keys.:

        results = await _get_neurons_for_netuids(
            subtensor, netuids, all_hotkey_addresses
        )
        neurons = _process_neuron_results(results, neurons, netuids)
        total_coldkey_stake_from_metagraph = await _calculate_total_coldkey_stake(
            neurons
        )

        alerts_table = Table(show_header=True, header_style="bold magenta")
        alerts_table.add_column("🥩 alert!")

        coldkeys_to_check = []
        for coldkey_wallet in all_coldkey_wallets:
            if coldkey_wallet.coldkeypub:
                # Check if we have any stake with hotkeys that are not registered.
                total_coldkey_stake_from_chain = (
                    # TODO gathering here may make sense or may not
                    await subtensor.get_total_stake_for_coldkey(
                        coldkey_wallet.coldkeypub.ss58_address, reuse_block=True
                    )
                )
                difference = (
                    total_coldkey_stake_from_chain[
                        coldkey_wallet.coldkeypub.ss58_address
                    ]
                    - total_coldkey_stake_from_metagraph[
                        coldkey_wallet.coldkeypub.ss58_address
                    ]
                )
                if difference == 0:
                    continue  # We have all our stake registered.

                coldkeys_to_check.append(coldkey_wallet)
                alerts_table.add_row(
                    "Found {} stake with coldkey {} that is not registered.".format(
                        difference, coldkey_wallet.coldkeypub.ss58_address
                    )
                )

        if coldkeys_to_check:
            # We have some stake that is not with a registered hotkey.
            if "-1" not in neurons:
                neurons["-1"] = []

        # Check each coldkey wallet for de-registered stake.

        results = await asyncio.gather(
            *[
                _get_de_registered_stake_for_coldkey_wallet(
                    subtensor, all_hotkey_addresses, coldkey_wallet
                )
                for coldkey_wallet in coldkeys_to_check
            ]
        )

        for result in results:
            coldkey_wallet, de_registered_stake, err_msg = result
            if err_msg is not None:
                err_console.print(err_msg)

            if len(de_registered_stake) == 0:
                continue  # We have no de-registered stake with this coldkey.

            de_registered_neurons = []
            for hotkey_addr, our_stake in de_registered_stake:
                # Make a neuron info lite for this hotkey and coldkey.
                de_registered_neuron = NeuronInfoLite.get_null_neuron()
                de_registered_neuron.hotkey = hotkey_addr
                de_registered_neuron.coldkey = coldkey_wallet.coldkeypub.ss58_address
                de_registered_neuron.total_stake = Balance(our_stake)
                de_registered_neurons.append(de_registered_neuron)

                # Add this hotkey to the wallets dict
                wallet_ = Wallet(name=wallet)
                wallet_.hotkey_ss58 = hotkey_addr
                wallet.hotkey_str = hotkey_addr[:5]  # Max length of 5 characters
                # Indicates a hotkey not on local machine but exists in stake_info obj on-chain
                if hotkey_coldkey_to_hotkey_wallet.get(hotkey_addr) is None:
                    hotkey_coldkey_to_hotkey_wallet[hotkey_addr] = {}
                hotkey_coldkey_to_hotkey_wallet[hotkey_addr][
                    coldkey_wallet.coldkeypub.ss58_address
                ] = wallet_

            # Add neurons to overview.
            neurons["-1"].extend(de_registered_neurons)

        # Setup outer table.
        grid = Table.grid(pad_edge=False)

        # If there are any alerts, add them to the grid
        if len(alerts_table.rows) > 0:
            grid.add_row(alerts_table)

        if not all_wallets:
            title = f"[bold white italic]Wallet - {wallet.name}:{wallet.coldkeypub.ss58_address}"
        else:
            title = "[bold whit italic]All Wallets:"

        # Add title
        grid.add_row(Align(title, vertical="middle", align="center"))

        # Generate rows per netuid
        hotkeys_seen = set()
        total_neurons = 0
        total_stake = 0.0
        tempos = await asyncio.gather(
            *[
                subtensor.get_hyperparameter("Tempo", netuid, block_hash)
                for netuid in netuids
            ]
        )
    for netuid, subnet_tempo in zip(netuids, tempos):
        last_subnet = netuid == netuids[-1]
        table_data = []
        total_rank = 0.0
        total_trust = 0.0
        total_consensus = 0.0
        total_validator_trust = 0.0
        total_incentive = 0.0
        total_dividends = 0.0
        total_emission = 0

        for nn in neurons[str(netuid)]:
            hotwallet = hotkey_coldkey_to_hotkey_wallet.get(nn.hotkey, {}).get(
                nn.coldkey, None
            )
            if not hotwallet:
                # Indicates a mismatch between what the chain says the coldkey
                # is for this hotkey and the local wallet coldkey-hotkey pair
                hotwallet = Wallet(name=nn.coldkey[:7])
                hotwallet.hotkey_str = nn.hotkey[:7]

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
            emission = int(nn.emission / (subnet_tempo + 1) * 1e9)
            last_update = int(block - nn.last_update)
            validator_permit = nn.validator_permit
            row = [
                hotwallet.name,
                hotwallet.hotkey_str,
                str(uid),
                str(active),
                "{:.5f}".format(stake),
                "{:.5f}".format(rank),
                "{:.5f}".format(trust),
                "{:.5f}".format(consensus),
                "{:.5f}".format(incentive),
                "{:.5f}".format(dividends),
                "{:_}".format(emission),
                "{:.5f}".format(validator_trust),
                "*" if validator_permit else "",
                str(last_update),
                (
                    int_to_ip(nn.axon_info.ip) + ":" + str(nn.axon_info.port)
                    if nn.axon_info.port != 0
                    else "[yellow]none[/yellow]"
                ),
                nn.hotkey,
            ]

            total_rank += rank
            total_trust += trust
            total_consensus += consensus
            total_incentive += incentive
            total_dividends += dividends
            total_emission += emission
            total_validator_trust += validator_trust

            if (nn.hotkey, nn.coldkey) not in hotkeys_seen:
                # Don't double count stake on hotkey-coldkey pairs.
                hotkeys_seen.add((nn.hotkey, nn.coldkey))
                total_stake += stake

            # netuid -1 are neurons that are de-registered.
            if netuid != "-1":
                total_neurons += 1

            table_data.append(row)

        # Add subnet header
        if netuid == "-1":
            grid.add_row("Deregistered Neurons")
        else:
            grid.add_row(f"Subnet: [bold white]{netuid}[/bold white]")

        table = Table(
            show_footer=False,
            width=None,
            pad_edge=False,
            box=None,
        )
        if last_subnet:
            table.add_column(
                "[overline white]COLDKEY",
                str(total_neurons),
                footer_style="overline white",
                style="bold white",
            )
            table.add_column(
                "[overline white]HOTKEY",
                str(total_neurons),
                footer_style="overline white",
                style="white",
            )
        else:
            # No footer for non-last subnet.
            table.add_column("[overline white]COLDKEY", style="bold white")
            table.add_column("[overline white]HOTKEY", style="white")
        table.add_column(
            "[overline white]UID",
            str(total_neurons),
            footer_style="overline white",
            style="yellow",
        )
        table.add_column(
            "[overline white]ACTIVE", justify="right", style="green", no_wrap=True
        )
        if last_subnet:
            table.add_column(
                "[overline white]STAKE(\u03c4)",
                "\u03c4{:.5f}".format(total_stake),
                footer_style="overline white",
                justify="right",
                style="green",
                no_wrap=True,
            )
        else:
            # No footer for non-last subnet.
            table.add_column(
                "[overline white]STAKE(\u03c4)",
                justify="right",
                style="green",
                no_wrap=True,
            )
        table.add_column(
            "[overline white]RANK",
            "{:.5f}".format(total_rank),
            footer_style="overline white",
            justify="right",
            style="green",
            no_wrap=True,
        )
        table.add_column(
            "[overline white]TRUST",
            "{:.5f}".format(total_trust),
            footer_style="overline white",
            justify="right",
            style="green",
            no_wrap=True,
        )
        table.add_column(
            "[overline white]CONSENSUS",
            "{:.5f}".format(total_consensus),
            footer_style="overline white",
            justify="right",
            style="green",
            no_wrap=True,
        )
        table.add_column(
            "[overline white]INCENTIVE",
            "{:.5f}".format(total_incentive),
            footer_style="overline white",
            justify="right",
            style="green",
            no_wrap=True,
        )
        table.add_column(
            "[overline white]DIVIDENDS",
            "{:.5f}".format(total_dividends),
            footer_style="overline white",
            justify="right",
            style="green",
            no_wrap=True,
        )
        table.add_column(
            "[overline white]EMISSION(\u03c1)",
            "\u03c1{:_}".format(total_emission),
            footer_style="overline white",
            justify="right",
            style="green",
            no_wrap=True,
        )
        table.add_column(
            "[overline white]VTRUST",
            "{:.5f}".format(total_validator_trust),
            footer_style="overline white",
            justify="right",
            style="green",
            no_wrap=True,
        )
        table.add_column("[overline white]VPERMIT", justify="right", no_wrap=True)
        table.add_column("[overline white]UPDATED", justify="right", no_wrap=True)
        table.add_column(
            "[overline white]AXON", justify="left", style="dim blue", no_wrap=True
        )
        table.add_column("[overline white]HOTKEY_SS58", style="dim blue", no_wrap=False)
        table.show_footer = True

        if sort_by:
            column_to_sort_by: int = 0
            highest_matching_ratio: int = 0
            sort_descending: bool = False  # Default sort_order to ascending

            for index, column in zip(range(len(table.columns)), table.columns):
                # Fuzzy match the column name. Default to the first column.
                column_name = column.header.lower().replace("[overline white]", "")
                match_ratio = fuzz.ratio(sort_by.lower(), column_name)
                # Finds the best matching column
                if match_ratio > highest_matching_ratio:
                    highest_matching_ratio = match_ratio
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

    console.clear()

    caption = "[italic][dim][white]Wallet balance: [green]\u03c4" + str(
        total_balance.tao
    )
    grid.add_row(Align(caption, vertical="middle", align="center"))

    # Print the entire table/grid
    console.print(grid, width=None)


def _get_hotkeys(
    include_hotkeys: list[str], exclude_hotkeys: list[str], all_hotkeys: list[Wallet]
) -> list[Wallet]:
    """Filters a set of hotkeys (all_hotkeys) based on whether they are included or excluded."""
    if include_hotkeys:
        # We are only showing hotkeys that are specified.
        all_hotkeys = [
            hotkey for hotkey in all_hotkeys if hotkey.hotkey_str in include_hotkeys
        ]
    else:
        # We are excluding the specified hotkeys from all_hotkeys.
        all_hotkeys = [
            hotkey for hotkey in all_hotkeys if hotkey.hotkey_str not in exclude_hotkeys
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
) -> tuple[int, dict[str, list[ScaleBytes]]]:
    """
    Retrieves all neurons for a specified netuid

    :param netuid: the netuid to query
    :param subtensor: the SubtensorInterface to make the query

    :return: the original netuid, and a mapping of the neurons to their NeuronInfoLite objects
    """

    async def neurons_lite_for_uid(uid: int) -> dict[Any, Any]:
        call_definition = TYPE_REGISTRY["runtime_api"]["NeuronInfoRuntimeApi"][
            "methods"
        ]["get_neurons_lite"]
        data = await subtensor.encode_params(
            call_definition=call_definition, params=[uid]
        )
        block_hash = subtensor.substrate.last_block_hash
        hex_bytes_result = await subtensor.substrate.rpc_request(
            method="state_call",
            params=["NeuronInfoRuntimeApi_get_neurons_lite", data, block_hash],
            reuse_block_hash=True,
        )

        return hex_bytes_result

    neurons = await neurons_lite_for_uid(uid=netuid)
    return netuid, neurons


async def _fetch_all_neurons(
    netuids: list[int], subtensor
) -> list[tuple[int, list[ScaleBytes]]]:
    """Retrieves all neurons for each of the specified netuids"""
    return list(
        await asyncio.gather(
            *[_fetch_neuron_for_netuid(netuid, subtensor) for netuid in netuids]
        )
    )


def _partial_decode(args):
    """
    Helper function for passing to ProcessPoolExecutor that decodes scale bytes based on a set return type and
    rpc type registry, passing this back to the Executor with its specified netuid for easier mapping

    :param args: (return type, scale bytes object, custom rpc type registry, netuid)

    :return: (original netuid, decoded object)
    """
    return_type, as_scale_bytes, custom_rpc_type_registry_, netuid_ = args
    decoded = decode_scale_bytes(return_type, as_scale_bytes, custom_rpc_type_registry_)
    if decoded.startswith("0x"):
        bytes_result = bytes.fromhex(decoded[2:])
    else:
        bytes_result = bytes.fromhex(decoded)

    return netuid_, NeuronInfoLite.list_from_vec_u8(bytes_result)


def _process_neurons_for_netuids(
    netuids_with_all_neurons_hex_bytes: list[tuple[int, list[ScaleBytes]]],
) -> list[tuple[int, list[NeuronInfoLite]]]:
    """
    Using multiprocessing to decode a list of hex-bytes neurons with their respective netuid

    :param netuids_with_all_neurons_hex_bytes: netuids with hex-bytes neurons
    :return: netuids mapped to decoded neurons
    """

    def make_map(res_):
        netuid_, json_result = res_
        hex_bytes_result = json_result["result"]
        as_scale_bytes = scalecodec.ScaleBytes(hex_bytes_result)
        return [return_type, as_scale_bytes, custom_rpc_type_registry, netuid_]

    return_type = TYPE_REGISTRY["runtime_api"]["NeuronInfoRuntimeApi"]["methods"][
        "get_neurons_lite"
    ]["type"]

    preprocessed = [make_map(r) for r in netuids_with_all_neurons_hex_bytes]
    with ProcessPoolExecutor() as executor:
        results = list(executor.map(_partial_decode, preprocessed))

    all_results = [(netuid, result) for netuid, result in results]
    return all_results


async def _get_neurons_for_netuids(
    subtensor: SubtensorInterface, netuids: list[int], hot_wallets: list[str]
) -> list[tuple[int, list["NeuronInfoLite"], Optional[str]]]:
    all_neurons_hex_bytes = await _fetch_all_neurons(netuids, subtensor)

    all_processed_neurons = _process_neurons_for_netuids(all_neurons_hex_bytes)
    return [
        _map_hotkey_to_neurons(neurons, hot_wallets, netuid)
        for netuid, neurons in all_processed_neurons
    ]


async def _get_de_registered_stake_for_coldkey_wallet(
    subtensor: SubtensorInterface,
    all_hotkey_addresses: Collection[str],
    coldkey_wallet: Wallet,
) -> tuple[Wallet, list[tuple[str, float]], Optional[str]]:
    """
    Looks at the total stake of a coldkey, then filters this based on the supplied hotkey addresses
    depending on whether the hotkey is a delegate

    :param subtensor: SubtensorInterface to make queries with
    :param all_hotkey_addresses: collection of hotkey SS58 addresses
    :param coldkey_wallet: Wallet containing coldkey

    :return: (original wallet, [(hotkey SS58, stake in TAO), ...], error message)
    """
    # Pull all stake for our coldkey
    all_stake_info_for_coldkey = await subtensor.get_stake_info_for_coldkey(
        coldkey_ss58=coldkey_wallet.coldkeypub.ss58_address, reuse_block=True
    )

    # Filter out hotkeys that are in our wallets
    # Filter out hotkeys that are delegates.
    async def _filter_stake_info(stake_info: StakeInfo) -> bool:
        if stake_info.stake == 0:
            return False  # Skip hotkeys that we have no stake with.
        if stake_info.hotkey_ss58 in all_hotkey_addresses:
            return False  # Skip hotkeys that are in our wallets.
        return not await subtensor.is_hotkey_delegate(
            hotkey_ss58=stake_info.hotkey_ss58, reuse_block=True
        )

    all_staked = await asyncio.gather(
        *[_filter_stake_info(stake_info) for stake_info in all_stake_info_for_coldkey]
    )

    # Collecting all filtered stake info using async for loop
    all_staked_hotkeys = []
    for stake_info, staked in zip(all_stake_info_for_coldkey, all_staked):
        if staked:
            all_staked_hotkeys.append(
                (
                    stake_info.hotkey_ss58,
                    stake_info.stake.tao,
                )
            )

    return coldkey_wallet, all_staked_hotkeys, None


async def transfer(
    wallet: Wallet,
    subtensor: SubtensorInterface,
    destination: str,
    amount: float,
    prompt: bool,
):
    """Transfer token of amount to destination."""
    await transfer_extrinsic(
        subtensor, wallet, destination, Balance.from_tao(amount), prompt=prompt
    )


async def inspect(
    wallet: Wallet,
    subtensor: SubtensorInterface,
    netuids_filter: list[int],
    all_wallets: bool = False,
):
    def delegate_row_maker(
        delegates_: list[tuple[DelegateInfo, Balance]],
    ) -> Generator[list[str], None, None]:
        for d_, staked in delegates_:
            if d_.hotkey_ss58 in registered_delegate_info:
                delegate_name = registered_delegate_info[d_.hotkey_ss58].name
            else:
                delegate_name = d_.hotkey_ss58
            yield (
                [""] * 2
                + [
                    str(delegate_name),
                    str(staked),
                    str(d_.total_daily_return.tao * (staked.tao / d_.total_stake.tao)),
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
        wallets = get_coldkey_wallets_for_path(wallet.path)
        all_hotkeys = get_all_wallets_for_path(
            wallet.path
        )  # TODO verify this is correct
    else:
        wallets = [wallet]
        all_hotkeys = get_hotkey_wallets_for_wallet(wallet)
    with console.status("synchronising with chain"):
        block_hash = await subtensor.substrate.get_chain_head()
        await subtensor.substrate.init_runtime(block_hash=block_hash)
        all_netuids = await subtensor.filter_netuids_by_registered_hotkeys(
            (await subtensor.get_all_subnet_netuids(block_hash)),
            netuids_filter,
            all_hotkeys,
            block_hash=block_hash,
        )
    # bittensor.logging.debug(f"Netuids to check: {all_netuids}")
    with console.status("Pulling delegates info"):
        registered_delegate_info: dict[
            str, DelegatesDetails
        ] = await get_delegates_details_from_github(url=Constants.delegates_detail_url)
        if not registered_delegate_info:
            console.print(
                ":warning:[yellow]Could not get delegate info from chain.[/yellow]"
            )
    table_width = console.width - 20
    table = Table(
        Column("[bold white]Coldkey", style="dark_orange"),
        Column("[bold white]Balance", style="dark_sea_green"),
        Column("[bold white]Delegate", style="bright_cyan"),
        Column("[bold white]Stake", style="light_goldenrod2"),
        Column("[bold white]Emission", style="rgb(42,161,152)"),
        Column("[bold white]Netuid", style="dark_orange"),
        Column("[bold white]Hotkey", style="bright_magenta"),
        Column("[bold white]Stake", style="light_goldenrod2"),
        Column("[bold white]Emission", style="rgb(42,161,152)"),
        title="[dark_orange]Wallets\n",
        show_footer=True,
        show_edge=False,
        expand=True,
        width=table_width,
        border_style="bright_black",
    )
    rows = []
    wallets_with_ckp_file = [
        wallet for wallet in wallets if wallet.coldkeypub_file.exists_on_device()
    ]
    all_delegates: list[list[tuple[DelegateInfo, Balance]]]
    with console.status("Pulling balance data"):
        balances, all_neurons, all_delegates = await asyncio.gather(
            subtensor.get_balance(
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

    for row in rows:
        table.add_row(*row)

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
):
    # TODO: - work out prompts to be passed through the cli
    success = await run_faucet_extrinsic(
        subtensor,
        wallet,
        tpb=threads_per_block,
        prompt=False,
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
    original_wallet: Wallet, new_wallet: Wallet, subtensor: SubtensorInterface
):
    """Swap your hotkey for all registered axons on the network."""
    return await swap_hotkey_extrinsic(
        subtensor,
        original_wallet,
        new_wallet,
        wait_for_finalization=False,
        wait_for_inclusion=True,
        prompt=True,
    )


def set_id_prompts() -> tuple[str, str, str, str, str, str, str, str, str, bool]:
    """
    Used to prompt the user to input their info for setting the ID
    :return: (display_name, legal_name, web_url, riot_handle, email,pgp_fingerprint, image_url, info_, twitter_url,
             validator_id)
    """
    display_name = Prompt.ask(
        "Display Name: The display name for the identity.", default=""
    )
    legal_name = Prompt.ask("Legal Name: The legal name for the identity.", default="")
    web_url = Prompt.ask("Web URL: The web url for the identity.", default="")
    riot_handle = Prompt.ask(
        "Riot Handle: The riot handle for the identity.", default=""
    )
    email = Prompt.ask("Email: The email address for the identity.", default="")
    pgp_fingerprint = Prompt.ask(
        "PGP Fingerprint: The pgp fingerprint for the identity.", default=""
    )
    image_url = Prompt.ask("Image URL: The image url for the identity.", default="")
    info_ = Prompt.ask("Info: Info about the identity", default="")
    twitter_url = Prompt.ask("𝕏 URL: The 𝕏 (Twitter) url for the identity.")
    validator_id = Confirm.ask("Are you updating a validator hotkey identity?")

    return (
        display_name,
        legal_name,
        web_url,
        riot_handle,
        email,
        pgp_fingerprint,
        image_url,
        info_,
        twitter_url,
        validator_id,
    )


async def set_id(
    wallet: Wallet,
    subtensor: SubtensorInterface,
    display_name: str,
    legal_name: str,
    web_url: str,
    pgp_fingerprint: str,
    riot_handle: str,
    email: str,
    image: str,
    twitter: str,
    info_: str,
    validator_id: bool,
):
    """Create a new or update existing identity on-chain."""

    identified = wallet.hotkey.ss58_address if validator_id else None
    id_dict = {
        "display": display_name,
        "legal": legal_name,
        "web": web_url,
        "pgp_fingerprint": pgp_fingerprint,
        "riot": riot_handle,
        "email": email,
        "image": image,
        "twitter": twitter,
        "info": info_,
        "identified": identified,
    }

    for field, string in id_dict.items():
        if getsizeof(string) > 113:  # 64 + 49 overhead bytes for string
            raise ValueError(f"Identity value `{field}` must be <= 64 raw bytes")

    if not Confirm(
        "Cost to register an Identity is [bold white italic]0.1 Tao[/bold white italic],"
        " are you sure you wish to continue?"
    ):
        console.print(":cross_mark: Aborted!")
        raise typer.Exit()

    wallet.unlock_coldkey()

    with console.status(":satellite: [bold green]Updating identity on-chain..."):
        call = await subtensor.substrate.compose_call(
            call_module="Registry",
            call_function="set_identity",
            call_params=id_dict,
        )
        success, err_msg = await subtensor.sign_and_send_extrinsic(call, wallet)

        if not success:
            err_console.print(f"[red]:cross_mark: Failed![/red] {err_msg}")
            return

        console.print(":white_heavy_check_mark: Success!")
        identity = await subtensor.query_identity(
            identified or wallet.coldkey.ss58_address
        )

    table = Table(
        Column("Key", justify="right", style="cyan", no_wrap=True),
        Column("Value", style="magenta"),
        title="[bold white italic]Updated On-Chain Identity",
    )

    table.add_row("Address", identified or wallet.coldkey.ss58_address)
    for key, value in identity.items():
        table.add_row(key, str(value) if value is not None else "~")

    return console.print(table)


async def get_id(subtensor: SubtensorInterface, ss58_address: str):
    with console.status(":satellite: [bold green]Querying chain identity..."):
        identity = await subtensor.query_identity(ss58_address)

    table = Table(
        Column("Item", justify="right", style="cyan", no_wrap=True),
        Column("Value", style="magenta"),
        title="[bold white italic]On-Chain Identity",
    )

    table.add_row("Address", ss58_address)
    for key, value in identity.items():
        table.add_row(key, str(value) if value is not None else "~")

    return console.print(table)


async def check_coldkey_swap(wallet: Wallet, subtensor: SubtensorInterface):
    arbitration_check = len(
        (
            await subtensor.substrate.query(
                module="SubtensorModule",
                storage_function="ColdkeySwapDestinations",
                params=[wallet.coldkeypub.ss58_address],
            )
        ).decode()
    )
    if arbitration_check == 0:
        console.print(
            "[green]There has been no previous key swap initiated for your coldkey.[/green]"
        )
    elif arbitration_check == 1:
        arbitration_block = await subtensor.substrate.query(
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


async def sign(wallet: Wallet, message: str):
    """Sign a message using the provided wallet or hotkey."""

    try:
        wallet.unlock_coldkey()
    except KeyFileError:
        err_console.print(
            ":cross_mark: [red]Keyfile is corrupt, non-writable, non-readable or the password used to decrypt is "
            "invalid[/red]:[bold white]\n  [/bold white]"
        )

    keypair = wallet.coldkey

    # Use a hotkey if the user specified it
    if wallet.hotkey:
        keypair = wallet.hotkey

    signed_message = keypair.sign(message.encode("utf-8")).hex()
    console.print("[bold green]Message signed successfully:")
    console.print(signed_message)