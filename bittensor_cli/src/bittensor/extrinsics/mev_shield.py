import asyncio
import hashlib
from typing import TYPE_CHECKING, Optional

from async_substrate_interface import AsyncExtrinsicReceipt
from bittensor_drand import encrypt_mlkem768, mlkem_kdf_id
from bittensor_cli.src.bittensor.utils import encode_account_id, format_error_message

if TYPE_CHECKING:
    from bittensor_wallet import Wallet
    from scalecodec import GenericCall
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

    next_key_result, genesis_hash = await asyncio.gather(
        subtensor.get_mev_shield_next_key(),
        subtensor.substrate.get_block_hash(0),
    )
    if next_key_result is None:
        raise ValueError("MEV Shield NextKey not available on chain")

    ml_kem_768_public_key = next_key_result

    # Create payload_core: signer (32B) + next_key (32B) + SCALE(call)
    signer_bytes = encode_account_id(wallet.coldkey.ss58_address)
    scale_call_bytes = bytes(call.data.data)
    next_key = hashlib.blake2b(next_key_result, digest_size=32).digest()

    payload_core = signer_bytes + next_key + scale_call_bytes

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
    submit_block_hash: str,
    timeout_blocks: int = 4,
    status=None,
) -> tuple[bool, Optional[str], Optional[AsyncExtrinsicReceipt]]:
    """
    Wait for MEV Shield inner call execution.

    After submit_encrypted succeeds, the block author will decrypt and execute
    the inner call via execute_revealed. This function polls for the
    DecryptedExecuted or DecryptedRejected event.

    Args:
        subtensor: SubtensorInterface instance.
        wrapper_id: The ID from EncryptedSubmitted event.
        submit_block_number: Block number where submit_encrypted was included.
        timeout_blocks: Max blocks to wait (default 4).
        status: Optional rich.Status object for progress updates.

    Returns:
        Tuple of (success: bool, error: Optional[str], receipt: Optional[AsyncExtrinsicReceipt]).
        - (True, None, receipt) if DecryptedExecuted was found.
        - (False, error_message, None) if the call failed or timeout.
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

        # Find executeRevealed extrinsic & match ids
        execute_revealed_index = None
        for idx, extrinsic in enumerate(extrinsics):
            call = extrinsic.value.get("call", {})
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

        if execute_revealed_index is None:
            current_block += 1
            continue

        receipt = AsyncExtrinsicReceipt(
            substrate=subtensor.substrate,
            block_hash=block_hash,
            extrinsic_idx=execute_revealed_index,
        )

        # TODO: Activate this when we update up-stream
        # if not await receipt.is_success:
        #     error_msg = format_error_message(await receipt.error_message)
        #     return False, error_msg, None

        error = await check_mev_shield_error(receipt, subtensor, wrapper_id)
        if error:
            error_msg = format_error_message(error)
            return False, error_msg, None

        return True, None, receipt

    return False, "Timeout waiting for MEV Shield execution", None


async def check_mev_shield_error(
    receipt: AsyncExtrinsicReceipt,
    subtensor: "SubtensorInterface",
    wrapper_id: str,
) -> Optional[dict]:
    """
    Handles & extracts error messages in the MEV Shield extrinsics.
    This is a temporary implementation until we update up-stream code.

    Args:
        receipt: AsyncExtrinsicReceipt for the execute_revealed extrinsic.
        subtensor: SubtensorInterface instance.
        wrapper_id: The wrapper ID to verify we're checking the correct event.

    Returns:
        Error dict to be used with format_error_message(), or None if no error.
    """
    if not await receipt.is_success:
        return await receipt.error_message

    for event in await receipt.triggered_events:
        event_details = event.get("event", {})

        if (
            event_details.get("module_id") == "MevShield"
            and event_details.get("event_id") == "DecryptedRejected"
        ):
            attributes = event_details.get("attributes", {})
            event_wrapper_id = attributes.get("id")

            if event_wrapper_id != wrapper_id:
                continue

            reason = attributes.get("reason", {})
            dispatch_error = reason.get("error", {})

            try:
                if "Module" in dispatch_error:
                    module_index = dispatch_error["Module"]["index"]
                    error_index = dispatch_error["Module"]["error"]

                    if isinstance(error_index, str) and error_index.startswith("0x"):
                        error_index = int(error_index[2:4], 16)

                    runtime = await subtensor.substrate.init_runtime(
                        block_hash=receipt.block_hash
                    )
                    module_error = runtime.metadata.get_module_error(
                        module_index=module_index,
                        error_index=error_index,
                    )

                    return {
                        "type": "Module",
                        "name": module_error.name,
                        "docs": module_error.docs,
                    }
            except Exception:
                return dispatch_error

            return dispatch_error

    return None
