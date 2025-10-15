from typing import Optional

from async_substrate_interface.utils.cache import asyncio
from bittensor_wallet import Wallet
from rich import box
from rich.prompt import Confirm, FloatPrompt
from rich.table import Column, Table

from bittensor_cli.src import COLORS
from bittensor_cli.src.bittensor.balances import Balance
from bittensor_cli.src.bittensor.subtensor_interface import SubtensorInterface
from bittensor_cli.src.bittensor.utils import (
    console,
    err_console,
    print_extrinsic_id,
    unlock_key,
)
from bittensor_cli.src.commands.crowd.view import show_crowdloan_details
from bittensor_cli.src.bittensor.chain_data import CrowdloanData


def validate_for_contribution(
    crowdloan: CrowdloanData,
    crowdloan_id: int,
    current_block: int,
) -> tuple[bool, Optional[str]]:
    """Validate if a crowdloan can accept contributions.

    Args:
        crowdloan: The crowdloan data object
        crowdloan_id: The ID of the crowdloan
        current_block: Current blockchain block number

    Returns:
        tuple[bool, Optional[str]]: (is_valid, error_message)
            - If valid: (True, None)
            - If invalid: (False, error_message)
    """
    if crowdloan.finalized:
        return False, f"Crowdloan #{crowdloan_id} is already finalized."

    if current_block >= crowdloan.end:
        return False, f"Crowdloan #{crowdloan_id} has ended."

    if crowdloan.raised >= crowdloan.cap:
        return False, f"Crowdloan #{crowdloan_id} has reached its cap."

    return True, None


async def contribute_to_crowdloan(
    subtensor: SubtensorInterface,
    wallet: Wallet,
    crowdloan_id: int,
    amount: Optional[float],
    prompt: bool,
    wait_for_inclusion: bool,
    wait_for_finalization: bool,
) -> tuple[bool, str]:
    """Contribute TAO to an active crowdloan.

    Args:
        subtensor: SubtensorInterface object for chain interaction
        wallet: Wallet object containing coldkey for contribution
        crowdloan_id: ID of the crowdloan to contribute to
        amount: Amount to contribute in TAO (None to prompt)
        prompt: Whether to prompt for confirmation
        wait_for_inclusion: Wait for transaction inclusion
        wait_for_finalization: Wait for transaction finalization

    Returns:
        tuple[bool, str]: Success status and message
    """
    crowdloan, current_block = await asyncio.gather(
        subtensor.get_single_crowdloan(crowdloan_id),
        subtensor.substrate.get_block_number(None),
    )
    if not crowdloan:
        err_console.print(f"[red]Crowdloan #{crowdloan_id} not found.[/red]")
        return False, f"Crowdloan #{crowdloan_id} not found."

    is_valid, error_message = validate_for_contribution(
        crowdloan, crowdloan_id, current_block
    )
    if not is_valid:
        err_console.print(f"[red]{error_message}[/red]")
        return False, error_message
