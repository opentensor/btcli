import os
from typing import Union

from bittensor_wallet import Wallet
from bittensor_wallet.keyfile import Keypair
from bittensor_wallet.utils import SS58_FORMAT, ss58
from rich.console import Console

console = Console()
err_console = Console(stderr=True)


RAO_PER_TAO = 1e9
U16_MAX = 65535
U64_MAX = 18446744073709551615


def is_valid_wallet(wallet: Wallet) -> bool:
    """
    Verifies that the wallet with specified parameters.
    :param wallet: a Wallet instance
    :return: bool, whether the wallet appears valid
    """
    return all(
        [
            os.path.exists(wp := os.path.expanduser(wallet.path)),
            os.path.exists(os.path.join(wp, wallet.name)),
            os.path.isfile(os.path.join(wp, wallet.name, "hotkeys", wallet.hotkey_str)),
        ]
    )


def is_valid_ss58_address(address: str) -> bool:
    """
    Checks if the given address is a valid ss58 address.

    Args:
        address(str): The address to check.

    Returns:
        True if the address is a valid ss58 address for Bittensor, False otherwise.
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

    Args:
        public_key(Union[str, bytes]): The public_key to check.

    Returns:
        True if the public_key is a valid ed25519 key, False otherwise.

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

    Args:
        address(Union[str, bytes]): The address to check.

    Returns:
        True if the address is a valid destination address, False otherwise.
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
