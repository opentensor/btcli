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


async def wait_for_extrinsic_by_hash(
    subtensor: "SubtensorInterface",
    extrinsic_hash: str,
    shield_id: str,
    submit_block_hash: str,
    timeout_blocks: int = 2,
    status=None,
) -> tuple[bool, Optional[str], Optional[AsyncExtrinsicReceipt]]:
    """
    Wait for the result of a MeV Shield encrypted extrinsic.

    After submit_encrypted succeeds, the block author will decrypt and submit
    the inner extrinsic directly. This function polls subsequent blocks looking
    for either:
    - an extrinsic matching the provided hash (success)
    OR
    - a markDecryptionFailed extrinsic with matching shield ID (failure)

    Args:
        subtensor: SubtensorInterface instance.
        extrinsic_hash: The hash of the inner extrinsic to find.
        shield_id: The wrapper ID from EncryptedSubmitted event (for detecting decryption failures).
        submit_block_hash: Block hash where submit_encrypted was included.
        timeout_blocks: Max blocks to wait (default 2).
        status: Optional rich.Status object for progress updates.

    Returns:
        Tuple of (success: bool, error: Optional[str], receipt: Optional[AsyncExtrinsicReceipt]).
        - (True, None, receipt) if extrinsic was found and succeeded.
        - (False, error_message, receipt) if extrinsic was found but failed.
        - (False, "Timeout...", None) if not found within timeout.
    """

    async def _noop(_):
        return True

    starting_block = await subtensor.substrate.get_block_number(submit_block_hash)
    current_block = starting_block + 1

    while current_block - starting_block <= timeout_blocks:
        if status:
            status.update(
                f"Waiting for :shield: MEV Protection "
                f"(checking block {current_block - starting_block} of {timeout_blocks})..."
            )

        await subtensor.substrate.wait_for_block(
            current_block,
            result_handler=_noop,
            task_return=False,
        )

        block_hash = await subtensor.substrate.get_block_hash(current_block)
        extrinsics = await subtensor.substrate.get_extrinsics(block_hash)

        result_idx = None
        for idx, extrinsic in enumerate(extrinsics):
            # Success: Inner extrinsic executed
            if f"0x{extrinsic.extrinsic_hash.hex()}" == extrinsic_hash:
                result_idx = idx
                break

            # Failure: Decryption failed
            call = extrinsic.value.get("call", {})
            if (
                call.get("call_module") == "MevShield"
                and call.get("call_function") == "mark_decryption_failed"
            ):
                call_args = call.get("call_args", [])
                for arg in call_args:
                    if arg.get("name") == "id" and arg.get("value") == shield_id:
                        result_idx = idx
                        break
                if result_idx is not None:
                    break

        if result_idx is not None:
            receipt = AsyncExtrinsicReceipt(
                substrate=subtensor.substrate,
                block_hash=block_hash,
                block_number=current_block,
                extrinsic_idx=result_idx,
            )

            if not await receipt.is_success:
                error_msg = format_error_message(await receipt.error_message)
                return False, error_msg, receipt

            return True, None, receipt

        current_block += 1

    return (
        False,
        "Failed to find outcome of the shield extrinsic (The protected extrinsic wasn't decrypted)",
        None,
    )
