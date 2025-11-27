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

    nonce = nonce + 1  # TODO: Update once chain is updated
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


async def wait_for_mev_execution(
    subtensor: "SubtensorInterface",
    wrapper_id: str,
    timeout_blocks: int = 4,
    status=None,
) -> tuple[bool, Optional[str]]:
    """
    Wait for MEV Shield inner call execution.

    After submit_encrypted succeeds, the block author will decrypt and execute
    the inner call via execute_revealed. This function polls for the
    DecryptedExecuted or DecryptedRejected event.

    Args:
        subtensor: SubtensorInterface instance.
        wrapper_id: The ID from EncryptedSubmitted event.
        timeout_blocks: Max blocks to wait (default 4).
        status: Optional rich.Status object for progress updates.

    Returns:
        Tuple of (success: bool, error: Optional[str]).
        - (True, None) if DecryptedExecuted was found.
        - (False, error_message) if the call failed or timeout.
    """

    start_block = await subtensor.substrate.get_block_number()
    current_block = start_block

    while current_block - start_block < timeout_blocks:
        if status:
            status.update(
                f":hourglass: Waiting for MEV Shield execution "
                f"(block {current_block - start_block + 1}/{timeout_blocks})..."
            )

        block_hash = await subtensor.substrate.get_block_hash(current_block)
        events, extrinsics = await asyncio.gather(
            subtensor.substrate.get_events(block_hash),
            subtensor.substrate.get_extrinsics(block_hash),
        )

        # Look for execute_revealed extrinsic
        execute_revealed_index = None
        for idx, extrinsic in enumerate(extrinsics):
            call = extrinsic.get("call", {})
            call_module = call.get("call_module")
            call_function = call.get("call_function")

            if call_module == "MevShield" and call_function == "execute_revealed":
                call_args = call.get("call_args", [])
                for arg in call_args:
                    if arg.get("name") == "id":
                        extrinsic_wrapper_id = arg.get("value")
                        if extrinsic_wrapper_id == wrapper_id:
                            execute_revealed_index = idx
                            break

                if execute_revealed_index is not None:
                    break

        # Check for success or failure events in the extrinsic
        if execute_revealed_index is not None:
            for event in events:
                event_id = event.get("event_id", "")
                event_extrinsic_idx = event.get("extrinsic_idx")

                if event_extrinsic_idx == execute_revealed_index:
                    if event_id == "ExtrinsicSuccess":
                        return True, None
                    elif event_id == "ExtrinsicFailed":
                        dispatch_error = event.get("attributes", {}).get(
                            "dispatch_error", {}
                        )
                        error_msg = f"{dispatch_error}"
                        return False, error_msg

        current_block += 1

        async def _noop(_):
            return True

        await subtensor.substrate.wait_for_block(
            current_block,
            result_handler=_noop,
            task_return=False,
        )

    return False, "Timeout waiting for MEV Shield execution"
