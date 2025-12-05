import hashlib
from typing import TYPE_CHECKING, Optional

from async_substrate_interface import AsyncExtrinsicReceipt
from bittensor_drand import encrypt_mlkem768
from bittensor_cli.src.bittensor.utils import format_error_message

if TYPE_CHECKING:
    from bittensor_wallet import Keypair
    from scalecodec import GenericCall, GenericExtrinsic
    from bittensor_cli.src.bittensor.subtensor_interface import SubtensorInterface


async def encrypt_extrinsic(
    subtensor: "SubtensorInterface",
    signed_extrinsic: "GenericExtrinsic",
) -> "GenericCall":
    """
    Encrypts a signed extrinsic using MEV Shield.

    Takes a pre-signed extrinsic and returns a `MevShield.submit_encrypted` call.
    The inner extrinsic must be signed with `nonce = current_nonce + 1` because it
    executes after the wrapper.

    :param subtensor: SubtensorInterface instance for chain queries.
    :param signed_extrinsic: The pre-signed extrinsic to encrypt.

    :return: `MevShield.submit_encrypted` call to sign with the current nonce.

    :raises ValueError: If a MEV Shield `NextKey` is not available on chain.
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


async def create_mev_protected_extrinsic(
    subtensor: "SubtensorInterface",
    keypair: "Keypair",
    call: "GenericCall",
    nonce: int,
    era: Optional[int] = None,
) -> tuple["GenericExtrinsic", str]:
    """
    Creates a MEV-protected extrinsic.

    Handles MEV Shield wrapping by signing the inner call with the future nonce,
    encrypting it, and then signing the wrapper with the current nonce.

    :param subtensor: SubtensorInterface instance.
    :param keypair: Keypair to sign both inner and wrapper extrinsics.
    :param call: Call to protect (for example, `add_stake`).
    :param nonce: Current account nonce; the wrapper uses this, the inner uses `nonce + 1`.
    :param era: Optional era period for the extrinsic.

    :return: Tuple of `(signed_shield_extrinsic, inner_extrinsic_hash)`, where
        `inner_extrinsic_hash` is used to track the actual extrinsic execution.
    """

    next_nonce = await subtensor.substrate.get_account_next_index(keypair.ss58_address)

    async def create_signed(call_to_sign, n):
        kwargs = {
            "call": call_to_sign,
            "keypair": keypair,
            "nonce": n,
        }
        if era is not None:
            kwargs["era"] = {"period": era}
        return await subtensor.substrate.create_signed_extrinsic(**kwargs)

    # Actual call: Sign with future nonce (current_nonce + 1)
    inner_extrinsic = await create_signed(call, next_nonce)
    inner_hash = f"0x{inner_extrinsic.extrinsic_hash.hex()}"

    # MeV Shield wrapper: Sign with current nonce
    shield_call = await encrypt_extrinsic(subtensor, inner_extrinsic)
    shield_extrinsic = await create_signed(shield_call, nonce)

    return shield_extrinsic, inner_hash

