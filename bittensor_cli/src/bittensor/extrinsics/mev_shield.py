import asyncio
import hashlib
from typing import TYPE_CHECKING, Optional

from bittensor_drand import encrypt_mlkem768, mlkem_kdf_id
from bittensor_cli.src.bittensor.utils import encode_account_id

if TYPE_CHECKING:
    from bittensor_wallet import Wallet
    from scalecodec import GenericCall
    from async_substrate_interface import AsyncExtrinsicReceipt
    from bittensor_cli.src.bittensor.subtensor_interface import SubtensorInterface


async def encrypt_call(
    subtensor: "SubtensorInterface",
    wallet: "Wallet",
    call: "GenericCall",
) -> "GenericCall":
    """
    Encrypt a call using MEV Shield.

    Takes any call and returns a MevShield.submit_encrypted call
    that can be submitted like any regular extrinsic.

    Args:
        subtensor: The SubtensorInterface instance for chain queries.
        wallet: The wallet whose coldkey will sign the inner payload.
        call: The call to encrypt.

    Returns:
        A MevShield.submit_encrypted call.

    Raises:
        ValueError: If MEV Shield NextKey is not available on chain.
    """

    next_key_result, genesis_hash, nonce = await asyncio.gather(
        subtensor.get_mev_shield_next_key(),
        subtensor.substrate.get_block_hash(0),
        subtensor.substrate.get_account_nonce(wallet.coldkey.ss58_address),
    )
    if next_key_result is None:
        raise ValueError("MEV Shield NextKey not available on chain")

    nonce = nonce + 1 # TODO: Update once chain is updated
    ml_kem_768_public_key = next_key_result

    # Create payload_core: signer (32B) + nonce (u32 LE) + SCALE(call)
    signer_bytes = encode_account_id(wallet.coldkey.ss58_address)
    nonce_bytes = (nonce & 0xFFFFFFFF).to_bytes(4, byteorder="little")
    scale_call_bytes = bytes(call.data.data)

    payload_core = signer_bytes + nonce_bytes + scale_call_bytes

    mev_shield_version = mlkem_kdf_id()
    genesis_hash_clean = (
        genesis_hash[2:] if genesis_hash.startswith("0x") else genesis_hash
    )
    genesis_hash_bytes = bytes.fromhex(genesis_hash_clean)

    # Sign: coldkey.sign(b"mev-shield:v1" + genesis_hash + payload_core)
    message_to_sign = (
        b"mev-shield:" + mev_shield_version + genesis_hash_bytes + payload_core
    )
    signature = wallet.coldkey.sign(message_to_sign)

    # Plaintext: payload_core + b"\x01" + signature
    plaintext = payload_core + b"\x01" + signature

    # Encrypt using ML-KEM-768
    ciphertext = encrypt_mlkem768(ml_kem_768_public_key, plaintext)

    # Commitment: blake2_256(payload_core)
    commitment_hash = hashlib.blake2b(payload_core, digest_size=32).digest()
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


async def extract_mev_shield_id(response: "AsyncExtrinsicReceipt") -> Optional[str]:
    """
    Extract the MEV Shield wrapper ID from an extrinsic response.

    After submitting a MEV Shield encrypted call, the EncryptedSubmitted event
    contains the wrapper ID needed to track execution.

    Args:
        response: The extrinsic receipt from submit_extrinsic.

    Returns:
        The wrapper ID (hex string) or None if not found.
    """
    for event in await response.triggered_events:
        if event["event_id"] == "EncryptedSubmitted":
            return event["attributes"]["id"]
    return None
