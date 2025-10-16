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
    print_error,
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
        print_error(f"[red]Crowdloan #{crowdloan_id} not found.[/red]")
        return False, f"Crowdloan #{crowdloan_id} not found."

    is_valid, error_message = validate_for_contribution(
        crowdloan, crowdloan_id, current_block
    )
    if not is_valid:
        print_error(f"[red]{error_message}[/red]")
        return False, error_message

    contributor_address = wallet.coldkeypub.ss58_address
    current_contribution, user_balance, _ = await asyncio.gather(
        subtensor.get_crowdloan_contribution(crowdloan_id, contributor_address),
        subtensor.get_balance(contributor_address),
        show_crowdloan_details(
            subtensor=subtensor,
            crowdloan_id=crowdloan_id,
            wallet=wallet,
            verbose=False,
            crowdloan=crowdloan,
            current_block=current_block,
        ),
    )

    if amount is None:
        left_to_raise = crowdloan.cap - crowdloan.raised
        max_contribution = min(user_balance, left_to_raise)

        console.print(
            f"\n[bold cyan]Contribution Options:[/bold cyan]\n"
            f"  Your Balance: {user_balance}\n"
            f"  Maximum You Can Contribute: [{COLORS.S.AMOUNT}]{max_contribution}[/{COLORS.S.AMOUNT}]"
        )
        amount = FloatPrompt.ask(
            f"\nEnter contribution amount in {Balance.unit}",
            default=float(crowdloan.min_contribution.tao),
        )

    contribution_amount = Balance.from_tao(amount)
    if contribution_amount < crowdloan.min_contribution:
        print_error(
            f"[red]Contribution amount ({contribution_amount}) is below minimum ({crowdloan.min_contribution}).[/red]"
        )
        return False, "Contribution below minimum requirement."

    if contribution_amount > user_balance:
        print_error(
            f"[red]Insufficient balance. You have {user_balance} but trying to contribute {contribution_amount}.[/red]"
        )
        return False, "Insufficient balance."

    # Auto-adjustment
    left_to_raise = crowdloan.cap - crowdloan.raised
    actual_contribution = contribution_amount
    will_be_adjusted = False

    if contribution_amount > left_to_raise:
        actual_contribution = left_to_raise
        will_be_adjusted = True

    # Extrinsic fee
    call = await subtensor.substrate.compose_call(
        call_module="Crowdloan",
        call_function="contribute",
        call_params={
            "crowdloan_id": crowdloan_id,
            "amount": contribution_amount.rao,
        },
    )
    extrinsic_fee = await subtensor.get_extrinsic_fee(call, wallet.coldkeypub)
    updated_balance = user_balance - actual_contribution - extrinsic_fee

    table = Table(
        Column("[bold white]Field", style=COLORS.G.SUBHEAD),
        Column("[bold white]Value", style=COLORS.G.TEMPO),
        title="\n[bold cyan]Contribution Summary[/bold cyan]",
        show_footer=False,
        width=None,
        pad_edge=False,
        box=box.SIMPLE,
        show_edge=True,
        border_style="bright_black",
    )

    table.add_row("Crowdloan ID", str(crowdloan_id))
    table.add_row("Creator", crowdloan.creator)
    table.add_row(
        "Current Progress",
        f"{crowdloan.raised} / {crowdloan.cap} ({(crowdloan.raised.tao / crowdloan.cap.tao * 100):.2f}%)",
    )

    if current_contribution:
        table.add_row("Your Current Contribution", str(current_contribution))
        table.add_row("New Contribution", str(actual_contribution))
        table.add_row(
            "Total After Contribution",
            f"[{COLORS.S.AMOUNT}]{Balance.from_rao(current_contribution.rao + actual_contribution.rao)}[/{COLORS.S.AMOUNT}]",
        )
    else:
        table.add_row(
            "Contribution Amount",
            f"[{COLORS.S.AMOUNT}]{actual_contribution}[/{COLORS.S.AMOUNT}]",
        )

    if will_be_adjusted:
        table.add_row(
            "Note",
            f"[yellow]Amount adjusted from {contribution_amount} to {actual_contribution} (cap limit)[/yellow]",
        )

    table.add_row("Transaction Fee", str(extrinsic_fee))
    table.add_row(
        "Balance After",
        f"[blue]{user_balance}[/blue] → [{COLORS.S.AMOUNT}]{updated_balance}[/{COLORS.S.AMOUNT}]",
    )
    console.print(table)

    if will_be_adjusted:
        console.print(
            f"\n[yellow] Your contribution will be automatically adjusted to {actual_contribution} "
            f"because the crowdloan only needs {left_to_raise} more to reach its cap.[/yellow]"
        )

    if prompt:
        if not Confirm.ask("\nProceed with contribution?"):
            console.print("[yellow]Contribution cancelled.[/yellow]")
            return False, "Contribution cancelled by user."

    unlock_status = unlock_key(wallet)
    if not unlock_status.success:
        print_error(f"[red]{unlock_status.message}[/red]")
        return False, unlock_status.message

    with console.status(f"\n:satellite: Contributing to crowdloan #{crowdloan_id}..."):
        (
            success,
            error_message,
            extrinsic_receipt,
        ) = await subtensor.sign_and_send_extrinsic(
            call=call,
            wallet=wallet,
            wait_for_inclusion=wait_for_inclusion,
            wait_for_finalization=wait_for_finalization,
        )

    if not success:
        print_error(f"[red]Failed to contribute: {error_message}[/red]")
        return False, error_message or "Failed to contribute."

    new_balance, new_contribution, updated_crowdloan = await asyncio.gather(
        subtensor.get_balance(contributor_address),
        subtensor.get_crowdloan_contribution(crowdloan_id, contributor_address),
        subtensor.get_single_crowdloan(crowdloan_id),
    )

    console.print(
        f"\n[dark_sea_green3]Successfully contributed to crowdloan #{crowdloan_id}![/dark_sea_green3]"
    )

    console.print(
        f"Balance:\n  [blue]{user_balance}[/blue] → "
        f"[{COLORS.S.AMOUNT}]{new_balance}[/{COLORS.S.AMOUNT}]"
    )

    if new_contribution:
        if current_contribution:
            console.print(
                f"Your Contribution:\n  [blue]{current_contribution}[/blue] → "
                f"[{COLORS.S.AMOUNT}]{new_contribution}[/{COLORS.S.AMOUNT}]"
            )
        else:
            console.print(
                f"Your Contribution: [{COLORS.S.AMOUNT}]{new_contribution}[/{COLORS.S.AMOUNT}]"
            )

    if updated_crowdloan:
        console.print(
            f"Crowdloan Progress:\n  [blue]{crowdloan.raised}[/blue] → "
            f"[{COLORS.S.AMOUNT}]{updated_crowdloan.raised}[/{COLORS.S.AMOUNT}] / {updated_crowdloan.cap}"
        )

        if updated_crowdloan.raised >= updated_crowdloan.cap:
            console.print(
                "\n[bold green]🎉 Crowdloan has reached its funding cap![/bold green]"
            )

    if extrinsic_receipt:
        await print_extrinsic_id(extrinsic_receipt)

    return True, "Successfully contributed to crowdloan."


async def withdraw_from_crowdloan(
    subtensor: SubtensorInterface,
    wallet: Wallet,
    crowdloan_id: int,
    wait_for_inclusion: bool,
    wait_for_finalization: bool,
    prompt: bool,
) -> tuple[bool, str]:
    """
    Withdraw contributions from a non-finalized crowdloan.

    Non-creators can withdraw their full contribution.
    Creators can only withdraw amounts above their initial deposit.

    Args:
        subtensor: SubtensorInterface instance for blockchain interaction
        wallet: Wallet instance containing the user's keys
        crowdloan_id: The ID of the crowdloan to withdraw from
        wait_for_inclusion: Whether to wait for transaction inclusion
        wait_for_finalization: Whether to wait for transaction finalization
        prompt: Whether to prompt for user confirmation

    Returns:
        Tuple of (success, message) indicating the result
    """

    crowdloan, current_block = await asyncio.gather(
        subtensor.get_single_crowdloan(crowdloan_id),
        subtensor.substrate.get_block_number(None),
    )

    if not crowdloan:
        print_error(f"[red]Crowdloan #{crowdloan_id} does not exist.[/red]")
        return False, f"Crowdloan #{crowdloan_id} does not exist."

    if crowdloan.finalized:
        print_error(
            f"[red]Crowdloan #{crowdloan_id} is already finalized. Withdrawals are not allowed.[/red]"
        )
        return False, "Cannot withdraw from finalized crowdloan."

    user_contribution, user_balance = await asyncio.gather(
        subtensor.get_crowdloan_contribution(
            crowdloan_id, wallet.coldkeypub.ss58_address
        ),
        subtensor.get_balance(wallet.coldkeypub.ss58_address),
    )

    if user_contribution == Balance.from_tao(0):
        print_error(
            f"[red]You have no contribution to withdraw from crowdloan #{crowdloan_id}.[/red]"
        )
        return False, "No contribution to withdraw."

    is_creator = wallet.coldkeypub.ss58_address == crowdloan.creator
    if is_creator:
        withdrawable = user_contribution - crowdloan.deposit
        if withdrawable <= 0:
            print_error(
                f"[red]As the creator, you cannot withdraw your deposit of {crowdloan.deposit}. "
                f"Only contributions above the deposit can be withdrawn.[/red]"
            )
            return False, "Creator cannot withdraw deposit amount."
        remaining_contribution = crowdloan.deposit
    else:
        withdrawable = user_contribution
        remaining_contribution = Balance.from_tao(0)

    call = await subtensor.substrate.compose_call(
        call_module="Crowdloan",
        call_function="withdraw",
        call_params={
            "crowdloan_id": crowdloan_id,
        },
    )
    extrinsic_fee = await subtensor.get_extrinsic_fee(call, wallet.coldkeypub)
    await show_crowdloan_details(
        subtensor=subtensor,
        crowdloan_id=crowdloan_id,
        wallet=wallet,
        verbose=False,
        crowdloan=crowdloan,
        current_block=current_block,
    )

    if prompt:
        new_balance = user_balance + withdrawable - extrinsic_fee
        new_raised = crowdloan.raised - withdrawable
        table = Table(
            Column("[bold white]Field", style=COLORS.G.SUBHEAD),
            Column("[bold white]Value", style=COLORS.G.TEMPO),
            title="\n[bold cyan]Withdrawal Summary[/bold cyan]",
            show_footer=False,
            show_header=False,
            width=None,
            pad_edge=False,
            box=box.SIMPLE,
            show_edge=True,
            border_style="bright_black",
        )

        table.add_row("Crowdloan ID", str(crowdloan_id))

        if is_creator:
            table.add_row("Role", "[yellow]Creator[/yellow]")
            table.add_row("Current Contribution", str(user_contribution))
            table.add_row("Deposit (Locked)", f"[yellow]{crowdloan.deposit}[/yellow]")
            table.add_row(
                "Withdrawable Amount",
                f"[{COLORS.S.AMOUNT}]{withdrawable}[/{COLORS.S.AMOUNT}]",
            )
            table.add_row(
                "Remaining After Withdrawal",
                f"[yellow]{remaining_contribution}[/yellow] (deposit)",
            )
        else:
            table.add_row("Current Contribution", str(user_contribution))
            table.add_row(
                "Withdrawal Amount",
                f"[{COLORS.S.AMOUNT}]{withdrawable}[/{COLORS.S.AMOUNT}]",
            )

        table.add_row("Transaction Fee", str(extrinsic_fee))
        table.add_row(
            "Balance After",
            f"[blue]{user_balance}[/blue] → [{COLORS.S.AMOUNT}]{new_balance}[/{COLORS.S.AMOUNT}]",
        )

        table.add_row(
            "Crowdloan Total After",
            f"[blue]{crowdloan.raised}[/blue] → [{COLORS.S.AMOUNT}]{new_raised}[/{COLORS.S.AMOUNT}]",
        )

        console.print(table)

        if not Confirm.ask("\nProceed with withdrawal?"):
            console.print("[yellow]Withdrawal cancelled.[/yellow]")
            return False, "Withdrawal cancelled by user."

    unlock_status = unlock_key(wallet)
    if not unlock_status.success:
        print_error(f"[red]{unlock_status.message}[/red]")
        return False, unlock_status.message

    with console.status(f"\n:satellite: Withdrawing from crowdloan #{crowdloan_id}..."):
        (
            success,
            error_message,
            extrinsic_receipt,
        ) = await subtensor.sign_and_send_extrinsic(
            call=call,
            wallet=wallet,
            wait_for_inclusion=wait_for_inclusion,
            wait_for_finalization=wait_for_finalization,
        )

    if not success:
        print_error(
            f"[red]Failed to withdraw: {error_message or 'Unknown error'}[/red]"
        )
        return False, error_message or "Failed to withdraw from crowdloan."

    console.print(
        f"\n✅ [green]Successfully withdrew from crowdloan #{crowdloan_id}![/green]\n"
    )

    new_balance, updated_contribution = await asyncio.gather(
        subtensor.get_balance(wallet.coldkeypub.ss58_address),
        subtensor.get_crowdloan_contribution(
            crowdloan_id, wallet.coldkeypub.ss58_address
        ),
    )

    console.print(
        f"Amount Withdrawn: [{COLORS.S.AMOUNT}]{withdrawable}[/{COLORS.S.AMOUNT}]\n"
        f"Balance:\n  [blue]{user_balance}[/blue] → [{COLORS.S.AMOUNT}]{new_balance}[/{COLORS.S.AMOUNT}]"
    )

    if is_creator and updated_contribution:
        console.print(
            f"Remaining Contribution: [{COLORS.S.AMOUNT}]{updated_contribution}[/{COLORS.S.AMOUNT}] (deposit locked)"
        )

    if extrinsic_receipt:
        await print_extrinsic_id(extrinsic_receipt)

    return True, "Successfully withdrew from crowdloan."
