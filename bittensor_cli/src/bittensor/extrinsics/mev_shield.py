import hashlib
from typing import TYPE_CHECKING, Optional

from async_substrate_interface import AsyncExtrinsicReceipt
from bittensor_drand import encrypt_mlkem768
from bittensor_cli.src.bittensor.utils import format_error_message

if TYPE_CHECKING:
    from scalecodec import GenericCall, GenericExtrinsic
    from bittensor_cli.src.bittensor.subtensor_interface import SubtensorInterface


async def encrypt_extrinsic(
    subtensor: "SubtensorInterface",
    signed_extrinsic: "GenericExtrinsic",
) -> "GenericCall":
    """
    Encrypt a signed extrinsic using MEV Shield.

    Takes a pre-signed extrinsic and returns a MevShield.submit_encrypted call.
    The signed extrinsic should be created with nonce = current_nonce + 1,
    as it will execute after the shield wrapper extrinsic.

    Args:
        subtensor: The SubtensorInterface instance for chain queries.
        signed_extrinsic: The signed extrinsic to encrypt.

    Returns:
        A MevShield.submit_encrypted call to be signed with the current nonce.

    Raises:
        ValueError: If MEV Shield NextKey is not available on chain.
    """

    ml_kem_768_public_key = await subtensor.get_mev_shield_next_key()
    if ml_kem_768_public_key is None:
        raise ValueError("MEV Shield NextKey not available on chain")

    plaintext = bytes(signed_extrinsic.data.data)

    # Encrypt using ML-KEM-768
    ciphertext = encrypt_mlkem768(ml_kem_768_public_key, plaintext)

    # Commitment: blake2_256(payload_core)
    commitment_hash = hashlib.blake2b(plaintext, digest_size=32).digest()
    commitment_hex = "0x" + commitment_hash.hex()

    # Create the MevShield.submit_encrypted call
    encrypted_call = await subtensor.substrate.compose_call(
        call_module="MevShield",
        call_function="submit_encrypted",
        call_params={
            "commitment": commitment_hex,
            "ciphertext": ciphertext,
        },
    )

    return encrypted_call

