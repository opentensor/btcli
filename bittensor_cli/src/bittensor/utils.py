import ast
from collections import namedtuple
import math
import os
import sqlite3
import platform
import webbrowser
from pathlib import Path
from typing import TYPE_CHECKING, Any, Collection, Optional, Union, Callable
from urllib.parse import urlparse
from functools import partial
import re

from bittensor_wallet import Wallet, Keypair
from bittensor_wallet.utils import SS58_FORMAT
from bittensor_wallet.errors import KeyFileError, PasswordError
from bittensor_wallet import utils
from jinja2 import Template
from markupsafe import Markup
import numpy as np
from numpy.typing import NDArray
from rich.console import Console
from rich.prompt import Prompt
from scalecodec.utils.ss58 import ss58_encode, ss58_decode
import typer


from bittensor_cli.src.bittensor.balances import Balance
from bittensor_cli.src import defaults, Constants


if TYPE_CHECKING:
    from bittensor_cli.src.bittensor.chain_data import SubnetHyperparameters

console = Console()
json_console = Console()
err_console = Console(stderr=True)
verbose_console = Console(quiet=True)

UnlockStatus = namedtuple("UnlockStatus", ["success", "message"])


class _Hotkey:
    def __init__(self, hotkey_ss58=None):
        self.ss58_address = hotkey_ss58


class _Coldkeypub:
    def __init__(self, coldkey_ss58=None):
        self.ss58_address = coldkey_ss58


class WalletLike:
    def __init__(
        self,
        name=None,
        hotkey_ss58=None,
        hotkey_str=None,
        coldkeypub_ss58=None,
    ):
        self.name = name
        self.hotkey_ss58 = hotkey_ss58
        self.hotkey_str = hotkey_str
        self._hotkey = _Hotkey(hotkey_ss58)
        self._coldkeypub = _Coldkeypub(coldkeypub_ss58)

    @property
    def hotkey(self):
        return self._hotkey

    @property
    def coldkeypub(self):
        return self._coldkeypub


def print_console(message: str, colour: str, title: str, console_: Console):
    console_.print(
        f"[bold {colour}][{title}]:[/bold {colour}] [{colour}]{message}[/{colour}]\n"
    )


def print_verbose(message: str, status=None):
    """Print verbose messages while temporarily pausing the status spinner."""
    if status:
        status.stop()
        print_console(message, "green", "Verbose", verbose_console)
        status.start()
    else:
        print_console(message, "green", "Verbose", verbose_console)


def print_error(message: str, status=None):
    """Print error messages while temporarily pausing the status spinner."""
    if status:
        status.stop()
        print_console(message, "red", "Error", err_console)
        status.start()
    else:
        print_console(message, "red", "Error", err_console)


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
    if not (0 <= value <= 1):
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
    wallet: Wallet, show_nulls: bool = False, show_encrypted: bool = False
) -> list[Optional[Wallet]]:
    """
    Returns wallet objects with hotkeys for a single given wallet

    :param wallet: Wallet object to use for the path
    :param show_nulls: will add `None` into the output if a hotkey is encrypted or not on the device
    :param show_encrypted: will add some basic info about the encrypted hotkey

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
                (exists := hotkey_for_name.hotkey_file.exists_on_device())
                and not hotkey_for_name.hotkey_file.is_encrypted()
                # and hotkey_for_name.coldkeypub.ss58_address
                and hotkey_for_name.hotkey.ss58_address
            ):
                hotkey_wallets.append(hotkey_for_name)
            elif (
                show_encrypted and exists and hotkey_for_name.hotkey_file.is_encrypted()
            ):
                hotkey_wallets.append(
                    WalletLike(str(wallet_path), "<ENCRYPTED>", h_name)
                )
            elif show_nulls:
                hotkey_wallets.append(None)
        except (
            UnicodeDecodeError,
            AttributeError,
            TypeError,
            KeyFileError,
        ):  # usually an unrelated file like .DS_Store
            continue

    return hotkey_wallets


def get_coldkey_wallets_for_path(path: str) -> list[Wallet]:
    """Gets all wallets with coldkeys from a given path"""
    wallet_path = Path(path).expanduser()
    try:
        wallets = [
            Wallet(name=directory.name, path=path)
            for directory in wallet_path.iterdir()
            if directory.is_dir()
        ]
    except FileNotFoundError:
        wallets = []
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


def validate_coldkey_presence(
    wallets: list[Wallet],
) -> tuple[list[Wallet], list[Wallet]]:
    """
    Validates the presence of coldkeypub.txt for each wallet.

    Returns:
        tuple[list[Wallet], list[Wallet]]: A tuple containing two lists:
            - The first list contains wallets with the required coldkey.
            - The second list contains wallets without the required coldkey.
    """
    valid_wallets = []
    invalid_wallets = []

    for wallet in wallets:
        if not os.path.exists(wallet.coldkeypub_file.path):
            invalid_wallets.append(wallet)
        else:
            valid_wallets.append(wallet)
    return valid_wallets, invalid_wallets


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
        return utils.is_valid_ss58_address(
            address
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


def decode_account_id(account_id_bytes: Union[tuple[int], tuple[tuple[int]]]):
    if isinstance(account_id_bytes, tuple) and isinstance(account_id_bytes[0], tuple):
        account_id_bytes = account_id_bytes[0]
    # Convert the AccountId bytes to a Base64 string
    return ss58_encode(bytes(account_id_bytes).hex(), SS58_FORMAT)


def encode_account_id(ss58_address: str) -> bytes:
    return bytes.fromhex(ss58_decode(ss58_address, SS58_FORMAT))


def ss58_to_vec_u8(ss58_address: str) -> list[int]:
    """
    Converts an SS58 address to a list of integers (vector of u8).

    :param ss58_address: The SS58 address to be converted.

    :return: A list of integers representing the byte values of the SS58 address.
    """
    ss58_bytes: bytes = encode_account_id(ss58_address)
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
        explorer_taostats_url = "{root_url}/hash/{block_hash}".format(
            root_url=explorer_root_urls.get("taostats"), block_hash=block_hash
        )
        explorer_urls["opentensor"] = explorer_opentensor_url
        explorer_urls["taostats"] = explorer_taostats_url

    return explorer_urls


def format_error_message(error_message: Union[dict, Exception]) -> str:
    """
    Formats an error message from the Subtensor error information for use in extrinsics.

    Args:
        error_message: A dictionary containing the error information from Subtensor, or a SubstrateRequestException
                       containing dictionary literal args.

    Returns:
        str: A formatted error message string.
    """
    err_name = "UnknownError"
    err_type = "UnknownType"
    err_description = "Unknown Description"

    if isinstance(error_message, Exception):
        # generally gotten through SubstrateRequestException args
        new_error_message = None
        for arg in error_message.args:
            try:
                d = ast.literal_eval(arg)
                if isinstance(d, dict):
                    if "error" in d:
                        new_error_message = d["error"]
                        break
                    elif all(x in d for x in ["code", "message", "data"]):
                        new_error_message = d
                        break
            except ValueError:
                pass
        if new_error_message is None:
            return_val = " ".join(error_message.args)
            return f"Subtensor returned: {return_val}"
        else:
            error_message = new_error_message

    if isinstance(error_message, dict):
        # subtensor error structure
        if (
            error_message.get("code")
            and error_message.get("message")
            and error_message.get("data")
        ):
            err_name = "SubstrateRequestException"
            err_type = error_message.get("message", "")
            err_data = error_message.get("data", "")

            # subtensor custom error marker
            if err_data.startswith("Custom error:"):
                err_description = (
                    f"{err_data} | Please consult "
                    f"https://docs.bittensor.com/subtensor-nodes/subtensor-error-messages"
                )
            else:
                err_description = err_data

        elif (
            error_message.get("type")
            and error_message.get("name")
            and error_message.get("docs")
        ):
            err_type = error_message.get("type", err_type)
            err_name = error_message.get("name", err_name)
            err_docs = error_message.get("docs", [err_description])
            err_description = err_docs[0] if err_docs else err_description

    return f"Subtensor returned `{err_name}({err_type})` error. This means: `{err_description}`."


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


def decode_hex_identity_dict(info_dictionary) -> dict[str, Any]:
    """
    Decodes hex-encoded strings in a dictionary.

    This function traverses the given dictionary, identifies hex-encoded strings, and decodes them into readable
        strings. It handles nested dictionaries and lists within the dictionary.

    Args:
        info_dictionary (dict): The dictionary containing hex-encoded strings to decode.

    Returns:
        dict: The dictionary with decoded strings.

    Examples:
        input_dict = {
        ...     "name": {"value": "0x6a6f686e"},
        ...     "additional": [
        ...         [{"data": "0x64617461"}]
        ...     ]
        ... }
        decode_hex_identity_dict(input_dict)
        {'name': 'john', 'additional': [('data', 'data')]}
    """

    def get_decoded(data: str) -> str:
        """Decodes a hex-encoded string."""
        try:
            return hex_to_bytes(data).decode()
        except UnicodeDecodeError:
            print(f"Could not decode: {key}: {item}")

    for key, value in info_dictionary.items():
        if isinstance(value, dict):
            item = list(value.values())[0]
            if isinstance(item, str) and item.startswith("0x"):
                try:
                    info_dictionary[key] = get_decoded(item)
                except UnicodeDecodeError:
                    print(f"Could not decode: {key}: {item}")
            else:
                info_dictionary[key] = item
        if key == "additional":
            additional = []
            for item in value:
                additional.append(
                    tuple(
                        get_decoded(data=next(iter(sub_item.values())))
                        for sub_item in item
                    )
                )
            info_dictionary[key] = additional

    return info_dictionary


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


def millify_tao(n: float, start_at: str = "K") -> str:
    """
    Dupe of millify, but for ease in converting tao values.
    Allows thresholds to be specified for different suffixes.
    """
    mill_names = ["", "k", "m", "b", "t"]
    thresholds = {"K": 1, "M": 2, "B": 3, "T": 4}

    if start_at not in thresholds:
        raise ValueError(f"start_at must be one of {list(thresholds.keys())}")

    n_ = float(n)
    if n_ == 0:
        return "0.00"

    mill_idx = int(math.floor(math.log10(abs(n_)) / 3))

    # Number's index is below our threshold, return with commas
    if mill_idx < thresholds[start_at]:
        return f"{n_:,.2f}"

    mill_idx = max(thresholds[start_at], min(len(mill_names) - 1, mill_idx))

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
        except Exception:
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


def group_subnets(registrations):
    if not registrations:
        return ""

    ranges = []
    start = registrations[0]

    for i in range(1, len(registrations)):
        if registrations[i] != registrations[i - 1] + 1:
            # Append the current range or single number
            if start == registrations[i - 1]:
                ranges.append(str(start))
            else:
                ranges.append(f"{start}-{registrations[i - 1]}")
            start = registrations[i]

    # Append the final range or single number
    if start == registrations[-1]:
        ranges.append(str(start))
    else:
        ranges.append(f"{start}-{registrations[-1]}")

    return ", ".join(ranges)


def validate_chain_endpoint(endpoint_url) -> tuple[bool, str]:
    parsed = urlparse(endpoint_url)
    if parsed.scheme not in ("ws", "wss"):
        return False, (
            f"Invalid URL or network name provided: [bright_cyan]({endpoint_url})[/bright_cyan].\n"
            "Allowed network names are [bright_cyan]finney, test, local[/bright_cyan]. "
            "Valid chain endpoints should use the scheme [bright_cyan]`ws` or `wss`[/bright_cyan].\n"
        )
    if not parsed.netloc:
        return False, "Invalid URL passed as the endpoint"
    return True, ""


def retry_prompt(
    helper_text: str,
    rejection: Callable,
    rejection_text: str,
    default="",
    show_default=False,
    prompt_type=Prompt.ask,
):
    """
    Allows for asking prompts again if they do not meet a certain criteria (as defined in `rejection`)
    Args:
        helper_text: The helper text to display for the prompt
        rejection: A function that returns True if the input should be rejected, and False if it should be accepted
        rejection_text: The text to display to the user if their input hits the rejection
        default: the default value to use for the prompt, default ""
        show_default: whether to show the default, default False
        prompt_type: the type of prompt, default `typer.prompt`

    Returns: the input value (or default)

    """
    while True:
        var = prompt_type(helper_text, default=default, show_default=show_default)
        if not rejection(var):
            return var
        else:
            err_console.print(rejection_text)


def validate_netuid(value: int) -> int:
    if value is not None and value < 0:
        raise typer.BadParameter("Negative netuid passed. Please use correct netuid.")
    return value


def validate_uri(uri: str) -> str:
    if not uri:
        return None
    clean_uri = uri.lstrip("/").lower()
    if not clean_uri.isalnum():
        raise typer.BadParameter(
            f"Invalid URI format: {uri}. URI must contain only alphanumeric characters (e.g. 'alice', 'bob')"
        )
    return f"//{clean_uri.capitalize()}"


def get_effective_network(config, network: Optional[list[str]]) -> str:
    """
    Determines the effective network to be used, considering the network parameter,
    the configuration, and the default.
    """
    if network:
        network_ = ""
        for item in network:
            if item.startswith("ws"):
                network_ = item
                break
            else:
                network_ = item
        return network_
    elif config.get("network"):
        return config["network"]
    else:
        return defaults.subtensor.network


def is_rao_network(network: str) -> bool:
    """Check if the given network is 'rao'."""
    network = network.lower()
    rao_identifiers = [
        "rao",
        Constants.rao_entrypoint,
    ]
    return (
        network == "rao"
        or network in rao_identifiers
        or "rao.chain.opentensor.ai" in network
    )


def prompt_for_identity(
    current_identity: dict,
    name: Optional[str],
    web_url: Optional[str],
    image_url: Optional[str],
    discord: Optional[str],
    description: Optional[str],
    additional: Optional[str],
    github_repo: Optional[str],
):
    """
    Prompts the user for identity fields with validation.
    Returns a dictionary with the updated fields.
    """
    identity_fields = {}

    fields = [
        ("name", "[blue]Display name[/blue]", name, 256),
        ("url", "[blue]Web URL[/blue]", web_url, 256),
        ("image", "[blue]Image URL[/blue]", image_url, 1024),
        ("discord", "[blue]Discord handle[/blue]", discord, 256),
        ("description", "[blue]Description[/blue]", description, 1024),
        ("additional", "[blue]Additional information[/blue]", additional, 1024),
        ("github_repo", "[blue]GitHub repository URL[/blue]", github_repo, 256),
    ]

    if not any(
        [name, web_url, image_url, discord, description, additional, github_repo]
    ):
        console.print(
            "\n[yellow]All fields are optional. Press Enter to skip and keep the default/existing value.[/yellow]\n"
            "[dark_sea_green3]Tip: Entering a space and pressing Enter will clear existing default value.\n"
        )

    for key, prompt, value, byte_limit in fields:
        text_rejection = partial(
            retry_prompt,
            rejection=lambda x: len(x.encode("utf-8")) > byte_limit,
            rejection_text=f"[red]Error:[/red] {key} field must be <= {byte_limit} bytes.",
        )

        if value:
            identity_fields[key] = value
        else:
            identity_fields[key] = text_rejection(
                prompt,
                default=current_identity.get(key, ""),
                show_default=True,
            )

    return identity_fields


def prompt_for_subnet_identity(
    current_identity: dict,
    subnet_name: Optional[str],
    github_repo: Optional[str],
    subnet_contact: Optional[str],
    subnet_url: Optional[str],
    discord: Optional[str],
    description: Optional[str],
    additional: Optional[str],
):
    """
    Prompts the user for required subnet identity fields with validation.
    Returns a dictionary with the updated fields.

    Args:
        subnet_name (Optional[str]): Name of the subnet
        github_repo (Optional[str]): GitHub repository URL
        subnet_contact (Optional[str]): Contact information for subnet (email)

    Returns:
        dict: Dictionary containing the subnet identity fields
    """
    identity_fields = {}

    fields = [
        (
            "subnet_name",
            "[blue]Subnet name [dim](optional)[/blue]",
            subnet_name,
            lambda x: x and len(x.encode("utf-8")) > 256,
            "[red]Error:[/red] Subnet name must be <= 256 bytes.",
        ),
        (
            "github_repo",
            "[blue]GitHub repository URL [dim](optional)[/blue]",
            github_repo,
            lambda x: x
            and (not is_valid_github_url(x) or len(x.encode("utf-8")) > 1024),
            "[red]Error:[/red] Please enter a valid GitHub repository URL (e.g., https://github.com/username/repo).",
        ),
        (
            "subnet_contact",
            "[blue]Contact email [dim](optional)[/blue]",
            subnet_contact,
            lambda x: x and (not is_valid_contact(x) or len(x.encode("utf-8")) > 1024),
            "[red]Error:[/red] Please enter a valid email address.",
        ),
        (
            "subnet_url",
            "[blue]Subnet URL [dim](optional)[/blue]",
            subnet_url,
            lambda x: x and len(x.encode("utf-8")) > 1024,
            "[red]Error:[/red] Please enter a valid URL <= 1024 bytes.",
        ),
        (
            "discord",
            "[blue]Discord handle [dim](optional)[/blue]",
            discord,
            lambda x: x and len(x.encode("utf-8")) > 256,
            "[red]Error:[/red] Please enter a valid Discord handle <= 256 bytes.",
        ),
        (
            "description",
            "[blue]Description [dim](optional)[/blue]",
            description,
            lambda x: x and len(x.encode("utf-8")) > 1024,
            "[red]Error:[/red] Description must be <= 1024 bytes.",
        ),
        (
            "additional",
            "[blue]Additional information [dim](optional)[/blue]",
            additional,
            lambda x: x and len(x.encode("utf-8")) > 1024,
            "[red]Error:[/red] Additional information must be <= 1024 bytes.",
        ),
    ]

    for key, prompt, value, rejection_func, rejection_msg in fields:
        if value:
            if rejection_func(value):
                raise ValueError(rejection_msg)
            identity_fields[key] = value
        else:
            identity_fields[key] = retry_prompt(
                prompt,
                rejection=rejection_func,
                rejection_text=rejection_msg,
                default=current_identity.get(key, ""),
                show_default=True,
            )

    return identity_fields


def is_valid_github_url(url: str) -> bool:
    """
    Validates if the provided URL is a valid GitHub repository URL.

    Args:
        url (str): URL to validate

    Returns:
        bool: True if valid GitHub repo URL, False otherwise
    """
    try:
        parsed = urlparse(url)
        if parsed.netloc != "github.com":
            return False

        # Check path follows github.com/user/repo format
        path_parts = [p for p in parsed.path.split("/") if p]
        if len(path_parts) < 2:  # Need at least username/repo
            return False

        return True
    except Exception:  # TODO figure out the exceptions that can be raised in here
        return False


def is_valid_contact(contact: str) -> bool:
    """
    Validates if the provided contact is a valid email address.

    Args:
        contact (str): Contact information to validate

    Returns:
        bool: True if valid email, False otherwise
    """
    email_pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    return bool(re.match(email_pattern, contact))


def get_subnet_name(subnet_info, max_length: int = 20) -> str:
    """Get the subnet name, prioritizing subnet_identity.subnet_name over subnet.subnet_name.
    Truncates the name if it exceeds max_length.

    Args:
        subnet_info: The subnet dynamic info
        max_length: Maximum length of the returned name. Names longer than this will be truncated with '...'

    Returns:
        str: The subnet name (truncated if necessary) or empty string if no name is found
    """
    name = (
        subnet_info.subnet_identity.subnet_name
        if hasattr(subnet_info, "subnet_identity")
        and subnet_info.subnet_identity is not None
        and subnet_info.subnet_identity.subnet_name is not None
        else (subnet_info.subnet_name if subnet_info.subnet_name is not None else "")
    )

    if len(name) > max_length:
        return name[: max_length - 3] + "..."
    return name


def print_linux_dependency_message():
    """Prints the WebKit dependency message for Linux systems."""
    console.print("[red]This command requires WebKit dependencies on Linux.[/red]")
    console.print(
        "\nPlease make sure these packages are installed on your system for PyWry to work:"
    )
    console.print("\nArch Linux / Manjaro:")
    console.print("[green]sudo pacman -S webkit2gtk[/green]")
    console.print("\nDebian / Ubuntu:")
    console.print("[green]sudo apt install libwebkit2gtk-4.0-dev[/green]")
    console.print("\nNote for Ubuntu 24.04+ & Debian 13+:")
    console.print("You may need these additional steps to install libwebkit2gtk:")
    console.print(
        "\tCreate a new source file with: [green]sudo vim /etc/apt/sources.list.d/jammy-temp.list[/green]"
    )
    console.print(
        "\tAdd this into the file and save: [green]deb http://archive.ubuntu.com/ubuntu jammy main universe[/green]"
    )
    console.print(
        "\tUpdate the repository and install the webkit dependency: [green]sudo apt update && sudo apt install "
        "libwebkit2gtk-4.0-dev[/green]"
    )
    console.print("\nFedora / CentOS / AlmaLinux:")
    console.print("[green]sudo dnf install gtk3-devel webkit2gtk3-devel[/green]\n\n")


def is_linux():
    """Returns True if the operating system is Linux."""
    return platform.system().lower() == "linux"


def validate_rate_tolerance(value: Optional[float]) -> Optional[float]:
    """Validates rate tolerance input"""
    if value is not None:
        if value < 0:
            raise typer.BadParameter(
                "Rate tolerance cannot be negative (less than 0%)."
            )
        if value > 1:
            raise typer.BadParameter("Rate tolerance cannot be greater than 1 (100%).")
        if value > 0.5:
            console.print(
                f"[yellow]Warning: High rate tolerance of {value*100}% specified. "
                "This may result in unfavorable transaction execution.[/yellow]"
            )
    return value


def unlock_key(
    wallet: Wallet, unlock_type="cold", print_out: bool = True
) -> "UnlockStatus":
    """
    Attempts to decrypt a wallet's coldkey or hotkey
    Args:
        wallet: a Wallet object
        unlock_type: the key type, 'cold' or 'hot'
        print_out:  whether to print out the error message to the err_console

    Returns: UnlockStatus for success status of unlock, with error message if unsuccessful

    """
    if unlock_type == "cold":
        unlocker = "unlock_coldkey"
    elif unlock_type == "hot":
        unlocker = "unlock_hotkey"
    else:
        raise ValueError(
            f"Invalid unlock type provided: {unlock_type}. Must be 'cold' or 'hot'."
        )
    try:
        getattr(wallet, unlocker)()
        return UnlockStatus(True, "")
    except PasswordError:
        err_msg = f"The password used to decrypt your {unlock_type.capitalize()}key Keyfile is invalid."
        if print_out:
            err_console.print(f":cross_mark: [red]{err_msg}[/red]")
        return UnlockStatus(False, err_msg)
    except KeyFileError:
        err_msg = f"{unlock_type.capitalize()}key Keyfile is corrupt, non-writable, or non-readable, or non-existent."
        if print_out:
            err_console.print(f":cross_mark: [red]{err_msg}[/red]")
        return UnlockStatus(False, err_msg)


def hex_to_bytes(hex_str: str) -> bytes:
    """
    Converts a hex-encoded string into bytes. Handles 0x-prefixed and non-prefixed hex-encoded strings.
    """
    if hex_str.startswith("0x"):
        bytes_result = bytes.fromhex(hex_str[2:])
    else:
        bytes_result = bytes.fromhex(hex_str)
    return bytes_result


def blocks_to_duration(blocks: int) -> str:
    """Convert blocks to human readable duration string using two largest units.

    Args:
        blocks (int): Number of blocks (12s per block)

    Returns:
        str: Duration string like '2d 5h', '3h 45m', '2m 10s', or '0s'
    """
    if blocks <= 0:
        return "0s"

    seconds = blocks * 12
    intervals = [
        ("d", 86400),  # 60 * 60 * 24
        ("h", 3600),  # 60 * 60
        ("m", 60),
        ("s", 1),
    ]
    results = []
    for unit, seconds_per_unit in intervals:
        unit_count = seconds // seconds_per_unit
        seconds %= seconds_per_unit
        if unit_count > 0:
            results.append(f"{unit_count}{unit}")
    # Return only the first two non-zero units
    return " ".join(results[:2]) or "0s"
