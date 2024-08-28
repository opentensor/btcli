import math
import os
import sqlite3
import webbrowser
from pathlib import Path
from typing import TYPE_CHECKING, Any, Collection, Optional, Union

import aiohttp
import numpy as np
import scalecodec
from bittensor_wallet import Wallet
from bittensor_wallet.keyfile import Keypair
from bittensor_wallet.utils import SS58_FORMAT, ss58
from jinja2 import Template
from markupsafe import Markup
from numpy.typing import NDArray
from rich.console import Console
from scalecodec.base import RuntimeConfiguration
from scalecodec.type_registry import load_type_registry_preset
from src import DelegatesDetails
from src.bittensor.balances import Balance

if TYPE_CHECKING:
    from src.bittensor.chain_data import SubnetHyperparameters

console = Console()
err_console = Console(stderr=True)

RAO_PER_TAO = 1e9
U16_MAX = 65535
U64_MAX = 18446744073709551615


def u16_normalized_float(x: int) -> float:
    """Converts a u16 int to a float"""
    return float(x) / float(U16_MAX)


def u64_normalized_float(x: int) -> float:
    """Converts a u64 int to a float"""
    return float(x) / float(U64_MAX)


def float_to_u64(value: float) -> int:
    """Converts a float to a u64 int"""
    # Ensure the input is within the expected range
    if not (0 <= value < 1):
        raise ValueError("Input value must be between 0 and 1")

    # Convert the float to a u64 value
    return int(value * (2**64 - 1))


def u64_to_float(value: int) -> float:
    u64_max = 2**64 - 1
    # Allow for a small margin of error (e.g., 1) to account for potential rounding issues
    if not (0 <= value <= u64_max + 1):
        raise ValueError(
            f"Input value ({value}) must be between 0 and {u64_max} (2^64 - 1)"
        )
    return min(value / u64_max, 1.0)  # Ensure the result is never greater than 1.0


def float_to_u16(value: float) -> int:
    # Ensure the input is within the expected range
    if not (0 <= value <= 1):
        raise ValueError("Input value must be between 0 and 1")

    # Calculate the u16 representation
    u16_max = 65535
    return int(value * u16_max)


def u16_to_float(value: int) -> float:
    # Ensure the input is within the expected range
    if not (0 <= value <= 65535):
        raise ValueError("Input value must be between 0 and 65535")

    # Calculate the float representation
    u16_max = 65535
    return value / u16_max


def convert_weight_uids_and_vals_to_tensor(
    n: int, uids: Collection[int], weights: Collection[int]
) -> NDArray[np.float32]:
    """
    Converts weights and uids from chain representation into a `np.array` (inverse operation from
    convert_weights_and_uids_for_emit)

    :param n: number of neurons on network.
    :param uids: Tensor of uids as destinations for passed weights.
    :param weights: Tensor of weights.

    :return: row_weights: Converted row weights.
    """
    row_weights = np.zeros([n], dtype=np.float32)
    for uid_j, wij in list(zip(uids, weights)):
        row_weights[uid_j] = float(
            wij
        )  # assumes max-upscaled values (w_max = U16_MAX).
    row_sum = row_weights.sum()
    if row_sum > 0:
        row_weights /= row_sum  # normalize
    return row_weights


def convert_bond_uids_and_vals_to_tensor(
    n: int, uids: list[int], bonds: list[int]
) -> NDArray[np.int64]:
    """Converts bond and uids from chain representation into a np.array.

    :param n: number of neurons on network.
    :param uids: Tensor of uids as destinations for passed bonds.
    :param bonds: Tensor of bonds.

    :return: Converted row bonds.
    """
    row_bonds = np.zeros([n], dtype=np.int64)

    for uid_j, bij in list(zip(uids, bonds)):
        row_bonds[uid_j] = int(bij)
    return row_bonds


def convert_root_weight_uids_and_vals_to_tensor(
    n: int, uids: list[int], weights: list[int], subnets: list[int]
) -> NDArray:
    """
    Converts root weights and uids from chain representation into a `np.array` or `torch.FloatTensor` (inverse operation
    from `convert_weights_and_uids_for_emit`)

    :param n: number of neurons on network.
    :param uids: Tensor of uids as destinations for passed weights.
    :param weights: Tensor of weights.
    :param subnets: list of subnets on the network

    :return: row_weights: Converted row weights.
    """

    row_weights = np.zeros([n], dtype=np.float32)
    for uid_j, wij in list(zip(uids, weights)):
        if uid_j in subnets:
            index_s = subnets.index(uid_j)
            row_weights[index_s] = float(
                wij
            )  # assumes max-upscaled values (w_max = U16_MAX).
        else:
            # TODO standardise logging
            # logging.warning(
            #     f"Incorrect Subnet uid {uid_j} in Subnets {subnets}. The subnet is unavailable at the moment."
            # )
            continue
    row_sum = row_weights.sum()
    if row_sum > 0:
        row_weights /= row_sum  # normalize
    return row_weights


def get_hotkey_wallets_for_wallet(
    wallet: Wallet, show_nulls: bool = False
) -> list[Optional[Wallet]]:
    """
    Returns wallet objects with hotkeys for a single given wallet

    :param wallet: Wallet object to use for the path
    :param show_nulls: will add `None` into the output if a hotkey is encrypted or not on the device

    :return: a list of wallets (with Nones included for cases of a hotkey being encrypted or not on the device, if
             `show_nulls` is set to `True`)
    """
    hotkey_wallets = []
    wallet_path = Path(wallet.path).expanduser()
    hotkeys_path = wallet_path / wallet.name / "hotkeys"
    try:
        hotkeys = [entry.name for entry in hotkeys_path.iterdir()]
    except FileNotFoundError:
        hotkeys = []
    for h_name in hotkeys:
        hotkey_for_name = Wallet(path=str(wallet_path), name=wallet.name, hotkey=h_name)
        try:
            if (
                hotkey_for_name.hotkey_file.exists_on_device()
                and not hotkey_for_name.hotkey_file.is_encrypted()
                # and hotkey_for_name.coldkeypub.ss58_address
                and hotkey_for_name.hotkey.ss58_address
            ):
                hotkey_wallets.append(hotkey_for_name)
            elif show_nulls:
                hotkey_wallets.append(None)
        except (
            UnicodeDecodeError,
            AttributeError,
        ):  # usually an unrelated file like .DS_Store
            continue

    return hotkey_wallets


def get_coldkey_wallets_for_path(path: str) -> list[Wallet]:
    """Gets all wallets with coldkeys from a given path"""
    wallet_path = Path(path).expanduser()
    wallets = [
        Wallet(name=directory.name, path=path)
        for directory in wallet_path.iterdir()
        if directory.is_dir()
    ]
    return wallets


def get_all_wallets_for_path(path: str) -> list[Wallet]:
    """Gets all wallets from a given path."""
    all_wallets = []
    cold_wallets = get_coldkey_wallets_for_path(path)
    for cold_wallet in cold_wallets:
        try:
            if (
                cold_wallet.coldkeypub_file.exists_on_device()
                and not cold_wallet.coldkeypub_file.is_encrypted()
            ):
                all_wallets.extend(get_hotkey_wallets_for_wallet(cold_wallet))
        except UnicodeDecodeError:  # usually an incorrect file like .DS_Store
            continue
    return all_wallets


def is_valid_wallet(wallet: Wallet) -> tuple[bool, bool]:
    """
    Verifies that the wallet with specified parameters.

    :param wallet: a Wallet instance

    :return: tuple[bool], whether wallet appears valid, whether valid hotkey in wallet
    """
    return (
        all(
            [
                os.path.exists(wp := os.path.expanduser(wallet.path)),
                os.path.exists(os.path.join(wp, wallet.name)),
            ]
        ),
        os.path.isfile(os.path.join(wp, wallet.name, "hotkeys", wallet.hotkey_str)),
    )


def is_valid_ss58_address(address: str) -> bool:
    """
    Checks if the given address is a valid ss58 address.

    :param address: The address to check.

    :return: `True` if the address is a valid ss58 address for Bittensor, `False` otherwise.
    """
    try:
        return ss58.is_valid_ss58_address(
            address, valid_ss58_format=SS58_FORMAT
        ) or ss58.is_valid_ss58_address(
            address, valid_ss58_format=42
        )  # Default substrate ss58 format (legacy)
    except IndexError:
        return False


def is_valid_ed25519_pubkey(public_key: Union[str, bytes]) -> bool:
    """
    Checks if the given public_key is a valid ed25519 key.

    :param public_key: The public_key to check.

    :return: True if the public_key is a valid ed25519 key, False otherwise.

    """
    try:
        if isinstance(public_key, str):
            if len(public_key) != 64 and len(public_key) != 66:
                raise ValueError("a public_key should be 64 or 66 characters")
        elif isinstance(public_key, bytes):
            if len(public_key) != 32:
                raise ValueError("a public_key should be 32 bytes")
        else:
            raise ValueError("public_key must be a string or bytes")

        keypair = Keypair(public_key=public_key, ss58_format=SS58_FORMAT)

        ss58_addr = keypair.ss58_address
        return ss58_addr is not None

    except (ValueError, IndexError):
        return False


def is_valid_bittensor_address_or_public_key(address: Union[str, bytes]) -> bool:
    """
    Checks if the given address is a valid destination address.

    :param address: The address to check.

    :return: True if the address is a valid destination address, False otherwise.
    """
    if isinstance(address, str):
        # Check if ed25519
        if address.startswith("0x"):
            return is_valid_ed25519_pubkey(address)
        else:
            # Assume ss58 address
            return is_valid_ss58_address(address)
    elif isinstance(address, bytes):
        # Check if ed25519
        return is_valid_ed25519_pubkey(address)
    else:
        # Invalid address type
        return False


def decode_scale_bytes(return_type, scale_bytes, custom_rpc_type_registry):
    """Decodes a ScaleBytes object using our type registry and return type"""
    rpc_runtime_config = RuntimeConfiguration()
    rpc_runtime_config.update_type_registry(load_type_registry_preset("legacy"))
    rpc_runtime_config.update_type_registry(custom_rpc_type_registry)
    obj = rpc_runtime_config.create_scale_object(return_type, scale_bytes)
    if obj.data.to_hex() == "0x0400":  # RPC returned None result
        return None
    return obj.decode()


def ss58_address_to_bytes(ss58_address: str) -> bytes:
    """Converts a ss58 address to a bytes object."""
    account_id_hex: str = scalecodec.ss58_decode(ss58_address, SS58_FORMAT)
    return bytes.fromhex(account_id_hex)


def ss58_to_vec_u8(ss58_address: str) -> list[int]:
    """
    Converts an SS58 address to a list of integers (vector of u8).

    :param ss58_address: The SS58 address to be converted.

    :return: A list of integers representing the byte values of the SS58 address.
    """
    ss58_bytes: bytes = ss58_address_to_bytes(ss58_address)
    encoded_address: list[int] = [int(byte) for byte in ss58_bytes]
    return encoded_address


def get_explorer_root_url_by_network_from_map(
    network: str, network_map: dict[str, dict[str, str]]
) -> dict[str, str]:
    """
    Returns the explorer root url for the given network name from the given network map.

    :param network: The network to get the explorer url for.
    :param network_map: The network map to get the explorer url from.

    :return: The explorer url for the given network.
    """
    explorer_urls: dict[str, str] = {}
    for entity_nm, entity_network_map in network_map.items():
        if network in entity_network_map:
            explorer_urls[entity_nm] = entity_network_map[network]

    return explorer_urls


def get_explorer_url_for_network(
    network: str, block_hash: str, network_map: dict[str, dict[str, str]]
) -> dict[str, str]:
    """
    Returns the explorer url for the given block hash and network.

    :param network: The network to get the explorer url for.
    :param block_hash: The block hash to get the explorer url for.
    :param network_map: The network maps to get the explorer urls from.

    :return: The explorer url for the given block hash and network
    """

    explorer_urls: dict[str, str] = {}
    # Will be None if the network is not known. i.e. not in network_map
    explorer_root_urls: dict[str, str] = get_explorer_root_url_by_network_from_map(
        network, network_map
    )

    if explorer_root_urls != {}:
        # We are on a known network.
        explorer_opentensor_url = "{root_url}/query/{block_hash}".format(
            root_url=explorer_root_urls.get("opentensor"), block_hash=block_hash
        )
        explorer_taostats_url = "{root_url}/extrinsic/{block_hash}".format(
            root_url=explorer_root_urls.get("taostats"), block_hash=block_hash
        )
        explorer_urls["opentensor"] = explorer_opentensor_url
        explorer_urls["taostats"] = explorer_taostats_url

    return explorer_urls


def format_error_message(error_message: dict) -> str:
    """
    Formats an error message from the Subtensor error information to using in extrinsics.

    :param error_message: A dictionary containing the error information from Subtensor.

    :return: A formatted error message string.
    """
    err_type = "UnknownType"
    err_name = "UnknownError"
    err_description = "Unknown Description"

    if isinstance(error_message, dict):
        err_type = error_message.get("type", err_type)
        err_name = error_message.get("name", err_name)
        err_docs = error_message.get("docs", [])
        err_description = err_docs[0] if len(err_docs) > 0 else err_description
    return f"Subtensor returned `{err_name} ({err_type})` error. This means: `{err_description}`"


def convert_blocks_to_time(blocks: int, block_time: int = 12) -> tuple[int, int, int]:
    """
    Converts number of blocks into number of hours, minutes, seconds.
    :param blocks: number of blocks
    :param block_time: time per block, by default this is 12
    :return: tuple containing number of hours, number of minutes, number of seconds
    """
    seconds = blocks * block_time
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    remaining_seconds = seconds % 60
    return hours, minutes, remaining_seconds


async def get_delegates_details_from_github(url: str) -> dict[str, DelegatesDetails]:
    """
    Queries GitHub to get the delegates details.

    :return: {delegate: DelegatesDetails}
    """
    all_delegates_details = {}

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(10.0)) as session:
        try:
            response = await session.get(url)
            if response.ok:
                all_delegates: dict[str, Any] = await response.json(content_type=None)
                for delegate_hotkey, delegates_details in all_delegates.items():
                    all_delegates_details[delegate_hotkey] = DelegatesDetails.from_json(
                        delegates_details
                    )
        except TimeoutError:
            err_console.print(
                "Request timed out pulling delegates details from GitHub."
            )

    return all_delegates_details


def get_human_readable(num: float, suffix="H"):
    """
    Converts a number to a human-readable string.

    :return: human-readable string representation of a number.
    """
    for unit in ["", "K", "M", "G", "T", "P", "E", "Z"]:
        if abs(num) < 1000.0:
            return f"{num:3.1f}{unit}{suffix}"
        num /= 1000.0
    return f"{num:.1f}Y{suffix}"


def millify(n: int):
    """
    Convert a large number into a more readable format with appropriate suffixes.

    This function transforms a large integer into a shorter, human-readable string with
    suffixes such as K, M, B, and T for thousands, millions, billions, and trillions,
    respectively. The number is formatted to two decimal places.

    :param n: The number to be converted.

    :return: The formatted string representing the number with a suffix.
    """
    mill_names = ["", " K", " M", " B", " T"]
    n_ = float(n)
    mill_idx = max(
        0,
        min(
            len(mill_names) - 1,
            int(math.floor(0 if n_ == 0 else math.log10(abs(n_)) / 3)),
        ),
    )

    return "{:.2f}{}".format(n_ / 10 ** (3 * mill_idx), mill_names[mill_idx])


def normalize_hyperparameters(
    subnet: "SubnetHyperparameters",
) -> list[tuple[str, str, str]]:
    """
    Normalizes the hyperparameters of a subnet.

    :param subnet: The subnet hyperparameters object.

    :return: A list of tuples containing the parameter name, value, and normalized value.
    """
    param_mappings = {
        "adjustment_alpha": u64_normalized_float,
        "min_difficulty": u64_normalized_float,
        "max_difficulty": u64_normalized_float,
        "difficulty": u64_normalized_float,
        "bonds_moving_avg": u64_normalized_float,
        "max_weight_limit": u16_normalized_float,
        "kappa": u16_normalized_float,
        "alpha_high": u16_normalized_float,
        "alpha_low": u16_normalized_float,
        "min_burn": Balance.from_rao,
        "max_burn": Balance.from_rao,
    }

    normalized_values: list[tuple[str, str, str]] = []
    subnet_dict = subnet.__dict__

    for param, value in subnet_dict.items():
        try:
            if param in param_mappings:
                norm_value = param_mappings[param](value)
                if isinstance(norm_value, float):
                    norm_value = f"{norm_value:.{10}g}"
            else:
                norm_value = value
        except Exception as e:
            # bittensor.logging.warning(f"Error normalizing parameter '{param}': {e}")
            norm_value = "-"

        normalized_values.append((param, str(value), str(norm_value)))

    return normalized_values


class DB:
    """
    For ease of interaction with the SQLite database used for --reuse-last and --html outputs of tables
    """

    def __init__(
        self,
        db_path: str = os.path.expanduser("~/.bittensor/bittensor.db"),
        row_factory=None,
    ):
        self.db_path = db_path
        self.conn: Optional[sqlite3.Connection] = None
        self.row_factory = row_factory

    def __enter__(self):
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = self.row_factory
        return self.conn, self.conn.cursor()

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.conn:
            self.conn.close()


def create_table(title: str, columns: list[tuple[str, str]], rows: list[list]) -> None:
    """
    Creates and populates the rows of a table in the SQLite database.

    :param title: title of the table
    :param columns: [(column name, column type), ...]
    :param rows: [[element, element, ...], ...]
    :return: None
    """
    blob_cols = []
    for idx, (_, col_type) in enumerate(columns):
        if col_type == "BLOB":
            blob_cols.append(idx)
    if blob_cols:
        for row in rows:
            for idx in blob_cols:
                row[idx] = row[idx].to_bytes(row[idx].bit_length() + 7, byteorder="big")
    with DB() as (conn, cursor):
        drop_query = f"DROP TABLE IF EXISTS {title}"
        cursor.execute(drop_query)
        conn.commit()
        columns_ = ", ".join([" ".join(x) for x in columns])
        creation_query = f"CREATE TABLE IF NOT EXISTS {title} ({columns_})"
        conn.commit()
        cursor.execute(creation_query)
        conn.commit()
        query = f"INSERT INTO {title} ({', '.join([x[0] for x in columns])}) VALUES ({', '.join(['?'] * len(columns))})"
        cursor.executemany(query, rows)
        conn.commit()
    return


def read_table(table_name: str, order_by: str = "") -> tuple[list, list]:
    """
    Reads a table from a SQLite database, returning back a column names and rows as a tuple
    :param table_name: the table name in the database
    :param order_by: the order of the columns in the table, optional
    :return: ([column names], [rows])
    """
    with DB() as (conn, cursor):
        cursor.execute(f"PRAGMA table_info({table_name})")
        columns_info = cursor.fetchall()
        column_names = [info[1] for info in columns_info]
        column_types = [info[2] for info in columns_info]
        cursor.execute(f"SELECT * FROM {table_name} {order_by}")
        rows = cursor.fetchall()
    blob_cols = []
    for idx, col_type in enumerate(column_types):
        if col_type == "BLOB":
            blob_cols.append(idx)
    if blob_cols:
        rows = [list(row) for row in rows]
        for row in rows:
            for idx in blob_cols:
                row[idx] = int.from_bytes(row[idx], byteorder="big")
    return column_names, rows


def update_metadata_table(table_name: str, values: dict[str, str]) -> None:
    """
    Used for updating the metadata for storing a table. This includes items like total_neurons, etc.
    :param table_name: the name of the table you're referencing inside of the metadata table (this is generally
                       going to be the same as the table for which you have rows.)
    :param values: {key: value} dict for items you wish to insert
    :return: None
    """
    with DB() as (conn, cursor):
        cursor.execute(
            "CREATE TABLE IF NOT EXISTS metadata ("
            "TableName TEXT, "
            "Key TEXT, "
            "Value TEXT"
            ")"
        )
        conn.commit()
        for key, value in values.items():
            cursor.execute(
                "UPDATE metadata SET Value = ? WHERE Key = ? AND TableName = ?",
                (value, key, table_name),
            )
            conn.commit()
            if cursor.rowcount == 0:
                cursor.execute(
                    "INSERT INTO metadata (TableName, Key, Value) VALUES (?, ?, ?)",
                    (table_name, key, value),
                )
                conn.commit()
    return


def get_metadata_table(table_name: str) -> dict[str, str]:
    """
    Retrieves the metadata dict for the specified table.
    :param table_name: Table name within the metadata table.
    :return: {key: value} dict for metadata items.
    """
    with DB() as (conn, cursor):
        cursor.execute(
            "SELECT Key, Value FROM metadata WHERE TableName = ?", (table_name,)
        )
        data = cursor.fetchall()
        return dict(data)


def render_table(table_name: str, table_info: str, columns: list[dict], show=True):
    """
    Renders the table to HTML, and displays it in the browser
    :param table_name: The table name in the database
    :param table_info: Think of this like a subtitle
    :param columns: list of dicts that conform to Tabulator's expected columns format
    :param show: whether to open a browser window with the rendered table HTML
    :return: None
    """
    db_cols, rows = read_table(table_name)
    template_dir = os.path.join(os.path.dirname(__file__), "templates")
    with open(os.path.join(template_dir, "table.j2"), "r") as f:
        template = Template(f.read())
    rendered = template.render(
        title=table_name,
        columns=Markup(columns),
        rows=Markup([{c: v for (c, v) in zip(db_cols, r)} for r in rows]),
        column_names=db_cols,
        table_info=table_info,
        tree=False,
    )
    output_file = "/tmp/bittensor_table.html"
    with open(output_file, "w+") as f:
        f.write(rendered)
    if show:
        webbrowser.open(f"file://{output_file}")


def render_tree(
    table_name: str,
    table_info: str,
    columns: list[dict],
    parent_column: int = 0,
    show=True,
):
    """
    Largely the same as render_table, but this renders the table with nested data.
    This is done by a table looking like: (FOO ANY, BAR ANY, BAZ ANY, CHILD INTEGER)
    where CHILD is 0 or 1, determining if the row should be treated as a child of another row.
    The parent and child rows should contain same value for the given parent_column

    E.g. Let's say you have rows as such:
    (COLDKEY TEXT, BALANCE REAL, STAKE REAL, CHILD INTEGER)
    ("5GTjidas", 1.0, 0.0, 0)
    ("5GTjidas", 0.0, 1.0, 1)
    ("DJIDSkod", 1.0, 0.0, 0)

    This will be rendered as:
    Coldkey   |  Balance  | Stake
    5GTjidas  |     1.0   |  0.0
        └     |     0.0   |  1.0
    DJIDSkod  |     1.0   |  0.0

    :param table_name: The table name in the database
    :param table_info: Think of this like a subtitle
    :param columns: list of dicts that conform to Tabulator's expected columns format
    :param parent_column: the index of the column to use as for parent reference
    :param show: whether to open a browser window with the rendered table HTML
    :return: None
    """
    db_cols, rows = read_table(table_name, "ORDER BY CHILD ASC")
    template_dir = os.path.join(os.path.dirname(__file__), "templates")
    result = []
    parent_dicts = {}
    for row in rows:
        row_dict = {c: v for (c, v) in zip(db_cols, row)}
        child = row_dict["CHILD"]
        del row_dict["CHILD"]
        if child == 0:
            row_dict["_children"] = []
            result.append(row_dict)
            parent_dicts[row_dict[db_cols[parent_column]]] = (
                row_dict  # Reference to row obj
            )
        elif child == 1:
            parent_key = row[parent_column]
            row_dict[db_cols[parent_column]] = None
            if parent_key in parent_dicts:
                parent_dicts[parent_key]["_children"].append(row_dict)
    with open(os.path.join(template_dir, "table.j2"), "r") as f:
        template = Template(f.read())
    rendered = template.render(
        title=table_name,
        columns=Markup(columns),
        rows=Markup(result),
        column_names=db_cols,
        table_info=table_info,
        tree=True,
    )
    output_file = "/tmp/bittensor_table.html"
    with open(output_file, "w+") as f:
        f.write(rendered)
    if show:
        webbrowser.open(f"file://{output_file}")
