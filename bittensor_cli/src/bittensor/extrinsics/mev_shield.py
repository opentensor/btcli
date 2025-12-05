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


async def extract_mev_shield_id(response: "AsyncExtrinsicReceipt") -> Optional[str]:
    """
    Extracts the MEV Shield wrapper ID from an extrinsic response.

    After submitting a MEV Shield encrypted call, the `EncryptedSubmitted` event
    contains the wrapper ID needed to track execution.

    :param response: Extrinsic receipt from `submit_extrinsic`.

    :return: Wrapper ID (hex string) or `None` if not found.
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
    Waits for the result of a MEV Shield encrypted extrinsic.

    After `submit_encrypted` succeeds, the block author decrypts and submits the
    inner extrinsic directly. This polls subsequent blocks for either the inner
    extrinsic hash (success) or a `mark_decryption_failed` extrinsic for the
    matching shield ID (failure).

    :param subtensor: SubtensorInterface instance.
    :param extrinsic_hash: Hash of the inner extrinsic to find.
    :param shield_id: Wrapper ID from the `EncryptedSubmitted` event (used to detect decryption failures).
    :param submit_block_hash: Block hash where `submit_encrypted` was included.
    :param timeout_blocks: Maximum blocks to wait before timing out (default 2).
    :param status: Optional `rich.Status` object for progress updates.

    :return: Tuple `(success, error_message, receipt)` where:
        - `success` is True if the extrinsic was found and succeeded.
        - `error_message` contains the formatted failure reason, if any.
        - `receipt` is the AsyncExtrinsicReceipt when available.
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
            if (
                extrinsic.extrinsic_hash
                and f"0x{extrinsic.extrinsic_hash.hex()}" == extrinsic_hash
            ):
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
