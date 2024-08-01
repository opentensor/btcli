import os
import math
from pathlib import Path
from typing import Union, Any

import aiohttp
import scalecodec
from bittensor_wallet import Wallet
from bittensor_wallet.keyfile import Keypair
from bittensor_wallet.utils import SS58_FORMAT, ss58
from rich.console import Console
from scalecodec.base import RuntimeConfiguration
from scalecodec.type_registry import load_type_registry_preset

from src import DelegatesDetails

console = Console()
err_console = Console(stderr=True)


RAO_PER_TAO = 1e9
U16_MAX = 65535
U64_MAX = 18446744073709551615


def get_hotkey_wallets_for_wallet(
    wallet: Wallet, show_nulls: bool = False
) -> list[Wallet]:
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
    wallet_path = Path(path).expanduser()
    wallets = [
        Wallet(name=directory.name, path=path)
        for directory in wallet_path.iterdir()
        if directory.is_dir()
    ]
    return wallets


def get_all_wallets_for_path(path: str) -> list[Wallet]:
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


def u16_normalized_float(x: int) -> float:
    return float(x) / float(U16_MAX)


def decode_scale_bytes(return_type, scale_bytes, custom_rpc_type_registry):
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
    r"""
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
    network: str, block_hash: str, network_map: dict[str, str]
) -> dict[str, str]:
    r"""
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


async def get_delegates_details_from_github(url: str) -> dict[str, DelegatesDetails]:
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


def get_human_readable(num, suffix="H"):
    for unit in ["", "K", "M", "G", "T", "P", "E", "Z"]:
        if abs(num) < 1000.0:
            return f"{num:3.1f}{unit}{suffix}"
        num /= 1000.0
    return f"{num:.1f}Y{suffix}"


def millify(n: int):
    mill_names = ["", " K", " M", " B", " T"]
    n = float(n)
    mill_idx = max(
        0,
        min(
            len(mill_names) - 1,
            int(math.floor(0 if n == 0 else math.log10(abs(n)) / 3)),
        ),
    )

    return "{:.2f}{}".format(n / 10 ** (3 * mill_idx), mill_names[mill_idx])
