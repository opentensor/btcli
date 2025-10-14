import asyncio
from typing import Optional

from bittensor_wallet import Wallet
from rich.prompt import Confirm, IntPrompt, Prompt, FloatPrompt

from bittensor_cli.src import COLORS
from bittensor_cli.src.bittensor.balances import Balance
from bittensor_cli.src.bittensor.subtensor_interface import SubtensorInterface
from bittensor_cli.src.bittensor.utils import (
    blocks_to_duration,
    console,
    err_console,
    is_valid_ss58_address,
    print_extrinsic_id,
    unlock_key,
)


async def create_crowdloan(
    subtensor: SubtensorInterface,
    wallet: Wallet,
    deposit_tao: Optional[int],
    min_contribution_tao: Optional[int],
    cap_tao: Optional[int],
    duration_blocks: Optional[int],
    target_address: Optional[str],
    wait_for_inclusion: bool,
    wait_for_finalization: bool,
    prompt: bool,
    json_output: bool,
) -> tuple[bool, str]:
    """
    Create a new crowdloan with the given parameters.
    Prompts for missing parameters if not provided.
    """

    unlock_status = unlock_key(wallet)
    if not unlock_status.success:
        err_console.print(f"[red]{unlock_status.message}[/red]")
        return False, unlock_status.message

    async def _get_constant(constant_name: str) -> int:
        result = await subtensor.substrate.get_constant(
            module_name="Crowdloan",
            constant_name=constant_name,
        )
        return getattr(result, "value", result)

    (
        minimum_deposit_raw,
        min_contribution_raw,
        min_duration,
        max_duration,
    ) = await asyncio.gather(
        _get_constant("MinimumDeposit"),
        _get_constant("AbsoluteMinimumContribution"),
        _get_constant("MinimumBlockDuration"),
        _get_constant("MaximumBlockDuration"),
    )

    minimum_deposit = Balance.from_rao(minimum_deposit_raw)
    min_contribution = Balance.from_rao(min_contribution_raw)

    if not prompt:
        missing_fields = []
        if deposit_tao is None:
            missing_fields.append("--deposit")
        if min_contribution_tao is None:
            missing_fields.append("--min-contribution")
        if cap_tao is None:
            missing_fields.append("--cap")
        if duration_blocks is None:
            missing_fields.append("--duration")
        if missing_fields:
            err_console.print(
                "[red]The following options must be provided when prompts are disabled:[/red] "
                + ", ".join(missing_fields)
            )
            return False, "Missing required options when prompts are disabled."

    deposit_value = deposit_tao
    while True:
        if deposit_value is None:
            deposit_value = FloatPrompt.ask(
                f"Enter the deposit amount in TAO "
                f"[blue](>= {minimum_deposit.tao:,.4f})[/blue]"
            )
        deposit = Balance.from_tao(deposit_value)
        if deposit < minimum_deposit:
            if prompt:
                err_console.print(
                    f"[red]Deposit must be at least {minimum_deposit.tao:,.4f} TAO.[/red]"
                )
                deposit_value = None
                continue
            err_console.print(
                f"[red]Deposit is below the minimum required deposit "
                f"({minimum_deposit.tao:,.4f} TAO).[/red]"
            )
            return False, "Deposit is below the minimum required deposit."
        break

    min_contribution_value = min_contribution_tao
    while True:
        if min_contribution_value is None:
            min_contribution_value = FloatPrompt.ask(
                f"Enter the minimum contribution amount in TAO "
                f"[blue](>= {min_contribution.tao:,.4f})[/blue]"
            )
        min_contribution = Balance.from_tao(min_contribution_value)
        if min_contribution < min_contribution:
            if prompt:
                err_console.print(
                    f"[red]Minimum contribution must be at least "
                    f"{min_contribution.tao:,.4f} TAO.[/red]"
                )
                min_contribution_value = None
                continue
            err_console.print(
                "[red]Minimum contribution is below the chain's absolute minimum.[/red]"
            )
            return False, "Minimum contribution is below the chain's absolute minimum."
        break

    cap_value = cap_tao
    while True:
        if cap_value is None:
            cap_value = FloatPrompt.ask(
                f"Enter the cap amount in TAO [blue](> deposit of {deposit.tao:,.4f})[/blue]"
            )
        cap = Balance.from_tao(cap_value)
        if cap <= deposit:
            if prompt:
                err_console.print(
                    f"[red]Cap must be greater than the deposit ({deposit.tao:,.4f} TAO).[/red]"
                )
                cap_value = None
                continue
            err_console.print(
                "[red]Cap must be greater than the initial deposit.[/red]"
            )
            return False, "Cap must be greater than the initial deposit."
        break

    duration_value = duration_blocks
    while True:
        if duration_value is None:
            duration_value = IntPrompt.ask(
                f"Enter the crowdloan duration in blocks "
                f"[blue]({min_duration} - {max_duration})[/blue]"
            )
        if duration_value < min_duration or duration_value > max_duration:
            if prompt:
                err_console.print(
                    f"[red]Duration must be between {min_duration} and "
                    f"{max_duration} blocks.[/red]"
                )
                duration_value = None
                continue
            err_console.print(
                "[red]Crowdloan duration is outside the allowed range.[/red]"
            )
            return False, "Crowdloan duration is outside the allowed range."
        duration = duration_value
        break

    if target_address and target_address.strip():
        target_address = target_address.strip()
        if not is_valid_ss58_address(target_address):
            err_console.print(
                f"[red]Invalid target SS58 address provided: {target_address}[/red]"
            )
            return False, "Invalid target SS58 address provided."
    elif prompt:
        target_input = Prompt.ask(
            "Enter a target SS58 address (leave blank for none)",
            default="",
            show_default=False,
        )
        target_address = target_input.strip() or None

    if target_address and not is_valid_ss58_address(target_address):
        err_console.print(
            f"[red]Invalid target SS58 address provided: {target_address}[/red]"
        )
        return False, "Invalid target SS58 address provided."

    creator_balance = await subtensor.get_balance(wallet.coldkeypub.ss58_address)
    if deposit > creator_balance:
        err_console.print(
            f"[red]Insufficient balance to cover the deposit. "
            f"Available: {creator_balance}, required: {deposit}[/red]"
        )
        return False, "Insufficient balance to cover the deposit."

    current_block = await subtensor.substrate.get_block_number(None)
    end_block = current_block + duration

    call = await subtensor.substrate.compose_call(
        call_module="Crowdloan",
        call_function="create",
        call_params={
            "deposit": deposit.rao,
            "min_contribution": min_contribution.rao,
            "cap": cap.rao,
            "end": end_block,
            "call": None,
            "target_address": target_address,
        },
    )

    extrinsic_fee = await subtensor.get_extrinsic_fee(call, wallet.coldkeypub)

    if prompt:
        duration_text = blocks_to_duration(duration)
        target_text = (
            target_address
            if target_address
            else f"[{COLORS.G.SUBHEAD_MAIN}]Not specified[/{COLORS.G.SUBHEAD_MAIN}]"
        )

        console.print(
            f"You are about to create a crowdloan on "
            f"[{COLORS.G.SUBHEAD_MAIN}]{subtensor.network}[/{COLORS.G.SUBHEAD_MAIN}]\n"
            f"  Deposit: [{COLORS.P.TAO}]{deposit}[/{COLORS.P.TAO}]\n"
            f"  Min contribution: [{COLORS.P.TAO}]{min_contribution}[/{COLORS.P.TAO}]\n"
            f"  Cap: [{COLORS.P.TAO}]{cap}[/{COLORS.P.TAO}]\n"
            f"  Duration: [bold]{duration}[/bold] blocks (~{duration_text})\n"
            f"  Ends at block: [bold]{end_block}[/bold]\n"
            f"  Target address: {target_text}\n"
            f"  Estimated fee: [{COLORS.P.TAO}]{extrinsic_fee}[/{COLORS.P.TAO}]"
        )

        if not Confirm.ask("Proceed with creating the crowdloan?"):
            console.print("[yellow]Cancelled crowdloan creation.[/yellow]")
            return False, "Cancelled crowdloan creation."

    success, error_message, extrinsic_receipt = await subtensor.sign_and_send_extrinsic(
        call=call,
        wallet=wallet,
        wait_for_inclusion=wait_for_inclusion,
        wait_for_finalization=wait_for_finalization,
    )

    extrinsic_id = None
    if extrinsic_receipt:
        await print_extrinsic_id(extrinsic_receipt)
        extrinsic_id = await extrinsic_receipt.get_extrinsic_identifier()

    if not success:
        err_console.print(
            f"[red]{error_message or 'Failed to create crowdloan.'}[/red]"
        )
        return False, error_message or "Failed to create crowdloan."

    message = "Crowdloan created successfully."
    console.print(
        f"\n:white_check_mark: [green]{message}[/green]\n"
        f"  Deposit: [{COLORS.P.TAO}]{deposit}[/{COLORS.P.TAO}]\n"
        f"  Min contribution: [{COLORS.P.TAO}]{min_contribution}[/{COLORS.P.TAO}]\n"
        f"  Cap: [{COLORS.P.TAO}]{cap}[/{COLORS.P.TAO}]\n"
        f"  Ends at block: [bold]{end_block}[/bold]"
    )
    if target_address:
        console.print(f"  Target address: {target_address}")
    if extrinsic_id:
        console.print(f"  Extrinsic ID: [bold]{extrinsic_id}[/bold]")

    return True, message
