import asyncio
import json
from typing import Optional

from bittensor_wallet import Wallet
from rich.prompt import Confirm, IntPrompt, Prompt, FloatPrompt
from rich.table import Table, Column, box

from bittensor_cli.src import COLORS
from bittensor_cli.src.commands.crowd.view import show_crowdloan_details
from bittensor_cli.src.bittensor.balances import Balance
from bittensor_cli.src.bittensor.subtensor_interface import SubtensorInterface
from bittensor_cli.src.commands.crowd.utils import get_constant
from bittensor_cli.src.bittensor.utils import (
    blocks_to_duration,
    console,
    json_console,
    print_error,
    is_valid_ss58_address,
    unlock_key,
    print_extrinsic_id,
)


async def create_crowdloan(
    subtensor: SubtensorInterface,
    wallet: Wallet,
    deposit_tao: Optional[int],
    min_contribution_tao: Optional[int],
    cap_tao: Optional[int],
    duration_blocks: Optional[int],
    target_address: Optional[str],
    subnet_lease: Optional[bool],
    emissions_share: Optional[int],
    lease_end_block: Optional[int],
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
        if json_output:
            json_console.print(
                json.dumps({"success": False, "error": unlock_status.message})
            )
        else:
            print_error(f"[red]{unlock_status.message}[/red]")
        return False, unlock_status.message

    crowdloan_type = None
    if subnet_lease is not None:
        crowdloan_type = "subnet" if subnet_lease else "fundraising"
    elif prompt:
        type_choice = IntPrompt.ask(
            "\n[bold cyan]What type of crowdloan would you like to create?[/bold cyan]\n"
            "[cyan][1][/cyan] General Fundraising (funds go to address)\n"
            "[cyan][2][/cyan] Subnet Leasing (create new subnet)",
            choices=["1", "2"],
        )
        crowdloan_type = "subnet" if type_choice == 2 else "fundraising"

        if crowdloan_type == "subnet":
            current_burn_cost = await subtensor.burn_cost()
            console.print(
                "\n[magenta]Subnet Lease Crowdloan Selected[/magenta]\n"
                "  • A new subnet will be created when the crowdloan is finalized\n"
                "  • Contributors will receive emissions as dividends\n"
                "  • You will become the subnet operator\n"
                f"  • [yellow]Note: Ensure cap covers subnet registration cost (currently {current_burn_cost.tao:,.2f} TAO)[/yellow]\n"
            )
        else:
            console.print(
                "\n[cyan]General Fundraising Crowdloan Selected[/cyan]\n"
                "  • Funds will be transferred to a target address when finalized\n"
                "  • Contributors can withdraw if the cap is not reached\n"
            )
    else:
        error_msg = "Crowdloan type not specified and no prompt provided."
        if json_output:
            json_console.print(json.dumps({"success": False, "error": error_msg}))
        else:
            print_error(error_msg)
        return False, error_msg

    block_hash = await subtensor.substrate.get_chain_head()
    runtime = await subtensor.substrate.init_runtime(block_hash=block_hash)
    (
        minimum_deposit_raw,
        min_contribution_raw,
        min_duration,
        max_duration,
    ) = await asyncio.gather(
        get_constant(subtensor, "MinimumDeposit", runtime=runtime),
        get_constant(subtensor, "AbsoluteMinimumContribution", runtime=runtime),
        get_constant(subtensor, "MinimumBlockDuration", runtime=runtime),
        get_constant(subtensor, "MaximumBlockDuration", runtime=runtime),
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
            error_msg = (
                "The following options must be provided when prompts are disabled: "
                + ", ".join(missing_fields)
            )
            if json_output:
                json_console.print(json.dumps({"success": False, "error": error_msg}))
            else:
                print_error(f"[red]{error_msg}[/red]")
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
                print_error(
                    f"[red]Deposit must be at least {minimum_deposit.tao:,.4f} TAO.[/red]"
                )
                deposit_value = None
                continue
            error_msg = f"Deposit is below the minimum required deposit ({minimum_deposit.tao} TAO)."
            if json_output:
                json_console.print(json.dumps({"success": False, "error": error_msg}))
            else:
                print_error(f"[red]{error_msg}[/red]")
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
                print_error(
                    f"[red]Minimum contribution must be at least "
                    f"{min_contribution.tao:,.4f} TAO.[/red]"
                )
                min_contribution_value = None
                continue
            print_error(
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
                print_error(
                    f"[red]Cap must be greater than the deposit ({deposit.tao:,.4f} TAO).[/red]"
                )
                cap_value = None
                continue
            print_error("[red]Cap must be greater than the initial deposit.[/red]")
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
                print_error(
                    f"[red]Duration must be between {min_duration} and "
                    f"{max_duration} blocks.[/red]"
                )
                duration_value = None
                continue
            print_error("[red]Crowdloan duration is outside the allowed range.[/red]")
            return False, "Crowdloan duration is outside the allowed range."
        duration = duration_value
        break

    current_block = await subtensor.substrate.get_block_number(None)
    call_to_attach = None

    if crowdloan_type == "subnet":
        target_address = None

        if emissions_share is None:
            emissions_share = IntPrompt.ask(
                "Enter emissions share percentage for contributors [blue](0-100)[/blue]"
            )

        if not 0 <= emissions_share <= 100:
            print_error(
                f"[red]Emissions share must be between 0 and 100, got {emissions_share}[/red]"
            )
            return False, "Invalid emissions share percentage."

        if lease_end_block is None:
            lease_perpetual = Confirm.ask(
                "Should the subnet lease be perpetual?",
                default=True,
            )
            if not lease_perpetual:
                lease_end_block = IntPrompt.ask(
                    f"Enter the block number when the lease should end. Current block is [bold]{current_block}[/bold]."
                )
        register_lease_call = await subtensor.substrate.compose_call(
            call_module="SubtensorModule",
            call_function="register_leased_network",
            call_params={
                "emissions_share": emissions_share,
                "end_block": None if lease_perpetual else lease_end_block,
            },
        )
        call_to_attach = register_lease_call
    else:
        if target_address:
            target_address = target_address.strip()
            if not is_valid_ss58_address(target_address):
                print_error(
                    f"[red]Invalid target SS58 address provided: {target_address}[/red]"
                )
                return False, "Invalid target SS58 address provided."
        elif prompt:
            target_input = Prompt.ask(
                "Enter a target SS58 address",
            )
            target_address = target_input.strip() or None

        if not is_valid_ss58_address(target_address):
            print_error(
                f"[red]Invalid target SS58 address provided: {target_address}[/red]"
            )
            return False, "Invalid target SS58 address provided."

        call_to_attach = None

    creator_balance = await subtensor.get_balance(wallet.coldkeypub.ss58_address)
    if deposit > creator_balance:
        print_error(
            f"[red]Insufficient balance to cover the deposit. "
            f"Available: {creator_balance}, required: {deposit}[/red]"
        )
        return False, "Insufficient balance to cover the deposit."

    end_block = current_block + duration

    call = await subtensor.substrate.compose_call(
        call_module="Crowdloan",
        call_function="create",
        call_params={
            "deposit": deposit.rao,
            "min_contribution": min_contribution.rao,
            "cap": cap.rao,
            "end": end_block,
            "call": call_to_attach,
            "target_address": target_address,
        },
    )

    extrinsic_fee = await subtensor.get_extrinsic_fee(call, wallet.coldkeypub)

    if prompt:
        duration_text = blocks_to_duration(duration)

        table = Table(
            Column("[bold white]Field", style=COLORS.G.SUBHEAD),
            Column("[bold white]Value", style=COLORS.G.TEMPO),
            title=f"\n[bold cyan]Crowdloan Creation Summary[/bold cyan]\n"
            f"Network: [{COLORS.G.SUBHEAD_MAIN}]{subtensor.network}[/{COLORS.G.SUBHEAD_MAIN}]",
            show_footer=False,
            show_header=False,
            width=None,
            pad_edge=False,
            box=box.SIMPLE,
            show_edge=True,
            border_style="bright_black",
        )

        if crowdloan_type == "subnet":
            table.add_row("Type", "[magenta]Subnet Leasing[/magenta]")
            table.add_row(
                "Emissions Share", f"[cyan]{emissions_share}%[/cyan] for contributors"
            )
            if lease_end_block:
                table.add_row("Lease Ends", f"Block {lease_end_block}")
            else:
                table.add_row("Lease Duration", "[green]Perpetual[/green]")
        else:
            table.add_row("Type", "[cyan]General Fundraising[/cyan]")
            target_text = (
                target_address
                if target_address
                else f"[{COLORS.G.SUBHEAD_MAIN}]Not specified[/{COLORS.G.SUBHEAD_MAIN}]"
            )
            table.add_row("Target address", target_text)

        table.add_row("Deposit", f"[{COLORS.P.TAO}]{deposit}[/{COLORS.P.TAO}]")
        table.add_row(
            "Min contribution", f"[{COLORS.P.TAO}]{min_contribution}[/{COLORS.P.TAO}]"
        )
        table.add_row("Cap", f"[{COLORS.P.TAO}]{cap}[/{COLORS.P.TAO}]")
        table.add_row("Duration", f"[bold]{duration}[/bold] blocks (~{duration_text})")
        table.add_row("Ends at block", f"[bold]{end_block}[/bold]")
        table.add_row(
            "Estimated fee", f"[{COLORS.P.TAO}]{extrinsic_fee}[/{COLORS.P.TAO}]"
        )
        console.print(table)

        if not Confirm.ask("Proceed with creating the crowdloan?"):
            if json_output:
                json_console.print(
                    json.dumps(
                        {"success": False, "error": "Cancelled crowdloan creation."}
                    )
                )
            else:
                console.print("[yellow]Cancelled crowdloan creation.[/yellow]")
            return False, "Cancelled crowdloan creation."

    success, error_message, extrinsic_receipt = await subtensor.sign_and_send_extrinsic(
        call=call,
        wallet=wallet,
        wait_for_inclusion=wait_for_inclusion,
        wait_for_finalization=wait_for_finalization,
    )

    if not success:
        if json_output:
            json_console.print(
                json.dumps(
                    {
                        "success": False,
                        "error": error_message or "Failed to create crowdloan.",
                    }
                )
            )
        else:
            print_error(f"[red]{error_message or 'Failed to create crowdloan.'}[/red]")
        return False, error_message or "Failed to create crowdloan."

    if json_output:
        extrinsic_id = await extrinsic_receipt.get_extrinsic_identifier()
        output_dict = {
            "success": True,
            "error": None,
            "data": {
                "type": crowdloan_type,
                "deposit": deposit.tao,
                "min_contribution": min_contribution.tao,
                "cap": cap.tao,
                "duration": duration,
                "end_block": end_block,
                "extrinsic_id": extrinsic_id,
            },
        }

        if crowdloan_type == "subnet":
            output_dict["data"]["emissions_share"] = emissions_share
            output_dict["data"]["lease_end_block"] = lease_end_block
            output_dict["data"]["perpetual_lease"] = lease_end_block is None
        else:
            output_dict["data"]["target_address"] = target_address

        json_console.print(json.dumps(output_dict))
        message = f"{crowdloan_type.capitalize()} crowdloan created successfully."
    else:
        if crowdloan_type == "subnet":
            message = "Subnet lease crowdloan created successfully."
            console.print(
                f"\n:white_check_mark: [green]{message}[/green]\n"
                f"  Type: [magenta]Subnet Leasing[/magenta]\n"
                f"  Emissions Share: [cyan]{emissions_share}%[/cyan]\n"
                f"  Deposit: [{COLORS.P.TAO}]{deposit}[/{COLORS.P.TAO}]\n"
                f"  Min contribution: [{COLORS.P.TAO}]{min_contribution}[/{COLORS.P.TAO}]\n"
                f"  Cap: [{COLORS.P.TAO}]{cap}[/{COLORS.P.TAO}]\n"
                f"  Ends at block: [bold]{end_block}[/bold]"
            )
            if lease_end_block:
                console.print(f"  Lease ends at block: [bold]{lease_end_block}[/bold]")
            else:
                console.print("  Lease: [green]Perpetual[/green]")
        else:
            message = "Fundraising crowdloan created successfully."
            console.print(
                f"\n:white_check_mark: [green]{message}[/green]\n"
                f"  Type: [cyan]General Fundraising[/cyan]\n"
                f"  Deposit: [{COLORS.P.TAO}]{deposit}[/{COLORS.P.TAO}]\n"
                f"  Min contribution: [{COLORS.P.TAO}]{min_contribution}[/{COLORS.P.TAO}]\n"
                f"  Cap: [{COLORS.P.TAO}]{cap}[/{COLORS.P.TAO}]\n"
                f"  Ends at block: [bold]{end_block}[/bold]"
            )
            if target_address:
                console.print(f"  Target address: {target_address}")

        await print_extrinsic_id(extrinsic_receipt)

    return True, message


async def finalize_crowdloan(
    subtensor: SubtensorInterface,
    wallet: Wallet,
    crowdloan_id: int,
    wait_for_inclusion: bool,
    wait_for_finalization: bool,
    prompt: bool,
    json_output: bool = False,
) -> tuple[bool, str]:
    """
    Finalize a successful crowdloan that has reached its cap.

    Only the creator can finalize a crowdloan. Finalization will:
    - Transfer funds to the target address (if specified)
    - Execute the attached call (if any, e.g., subnet creation)
    - Mark the crowdloan as finalized

    Args:
        subtensor: SubtensorInterface instance for blockchain interaction
        wallet: Wallet instance containing the user's keys
        crowdloan_id: The ID of the crowdloan to finalize
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
        error_msg = f"Crowdloan #{crowdloan_id} does not exist."
        if json_output:
            json_console.print(json.dumps({"success": False, "error": error_msg}))
        else:
            print_error(f"[red]{error_msg}[/red]")
        return False, error_msg

    if wallet.coldkeypub.ss58_address != crowdloan.creator:
        error_msg = (
            f"Only the creator can finalize a crowdloan. Creator: {crowdloan.creator}"
        )
        if json_output:
            json_console.print(json.dumps({"success": False, "error": error_msg}))
        else:
            print_error(f"[red]{error_msg}[/red]")
        return False, "Only the creator can finalize a crowdloan."

    if crowdloan.finalized:
        error_msg = f"Crowdloan #{crowdloan_id} is already finalized."
        if json_output:
            json_console.print(json.dumps({"success": False, "error": error_msg}))
        else:
            print_error(f"[red]{error_msg}[/red]")
        return False, "Crowdloan is already finalized."

    if crowdloan.raised < crowdloan.cap:
        still_needed = crowdloan.cap - crowdloan.raised
        error_msg = (
            f"Crowdloan #{crowdloan_id} has not reached its cap. Raised: {crowdloan.raised.tao}, "
            f"Cap: {crowdloan.cap.tao}, Still needed: {still_needed.tao}"
        )
        if json_output:
            json_console.print(json.dumps({"success": False, "error": error_msg}))
        else:
            print_error(
                f"[red]Crowdloan #{crowdloan_id} has not reached its cap.\n"
                f"Raised: {crowdloan.raised}, Cap: {crowdloan.cap}\n"
                f"Still needed: {still_needed.tao}[/red]"
            )
        return False, "Crowdloan has not reached its cap."

    call = await subtensor.substrate.compose_call(
        call_module="Crowdloan",
        call_function="finalize",
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
        console.print()
        table = Table(
            Column("[bold white]Field", style=COLORS.G.SUBHEAD),
            Column("[bold white]Value", style=COLORS.G.TEMPO),
            title="\n[bold cyan]Crowdloan Finalization Summary[/bold cyan]",
            show_footer=False,
            show_header=False,
            width=None,
            pad_edge=False,
            box=box.SIMPLE,
            show_edge=True,
            border_style="bright_black",
        )

        table.add_row("Crowdloan ID", str(crowdloan_id))
        table.add_row("Status", "[green]Ready to Finalize[/green]")
        table.add_row(
            "Total Raised", f"[{COLORS.S.AMOUNT}]{crowdloan.raised}[/{COLORS.S.AMOUNT}]"
        )
        table.add_row("Contributors", str(crowdloan.contributors_count))

        if crowdloan.target_address:
            table.add_row(
                "Funds Will Go To",
                f"[{COLORS.G.SUBHEAD_EX_1}]{crowdloan.target_address}[/{COLORS.G.SUBHEAD_EX_1}]",
            )

        if crowdloan.has_call:
            table.add_row(
                "Call to Execute", "[yellow]Yes (e.g., subnet registration)[/yellow]"
            )
        else:
            table.add_row("Call to Execute", "[dim]None[/dim]")

        table.add_row("Transaction Fee", str(extrinsic_fee))

        table.add_section()
        table.add_row(
            "[bold red]WARNING[/bold red]",
            "[yellow]This action is IRREVERSIBLE![/yellow]",
        )

        console.print(table)

        console.print(
            "\n[bold yellow]Important:[/bold yellow]\n"
            "• Finalization will transfer all raised funds\n"
            "• Any attached call will be executed immediately\n"
            "• This action cannot be undone\n"
        )

        if not Confirm.ask("\nProceed with finalization?"):
            if json_output:
                json_console.print(
                    json.dumps(
                        {"success": False, "error": "Finalization cancelled by user."}
                    )
                )
            else:
                console.print("[yellow]Finalization cancelled.[/yellow]")
            return False, "Finalization cancelled by user."

    unlock_status = unlock_key(wallet)
    if not unlock_status.success:
        if json_output:
            json_console.print(
                json.dumps({"success": False, "error": unlock_status.message})
            )
        else:
            print_error(f"[red]{unlock_status.message}[/red]")
        return False, unlock_status.message

    success, error_message, extrinsic_receipt = await subtensor.sign_and_send_extrinsic(
        call=call,
        wallet=wallet,
        wait_for_inclusion=wait_for_inclusion,
        wait_for_finalization=wait_for_finalization,
    )

    if not success:
        if json_output:
            json_console.print(
                json.dumps(
                    {
                        "success": False,
                        "error": error_message or "Failed to finalize crowdloan.",
                    }
                )
            )
        else:
            print_error(
                f"[red]Failed to finalize: {error_message or 'Unknown error'}[/red]"
            )
        return False, error_message or "Failed to finalize crowdloan."

    if json_output:
        extrinsic_id = await extrinsic_receipt.get_extrinsic_identifier()
        output_dict = {
            "success": True,
            "error": None,
            "extrinsic_identifier": extrinsic_id,
            "data": {
                "crowdloan_id": crowdloan_id,
                "total_raised": crowdloan.raised.tao,
                "contributors_count": crowdloan.contributors_count,
                "target_address": crowdloan.target_address,
                "has_call": crowdloan.has_call,
                "call_executed": crowdloan.has_call,
            },
        }
        json_console.print(json.dumps(output_dict))
    else:
        console.print(
            f"\n[dark_sea_green3]Successfully finalized crowdloan #{crowdloan_id}![/dark_sea_green3]\n"
        )

        console.print(
            f"[bold]Finalization Complete:[/bold]\n"
            f"\t• Total Raised: [{COLORS.S.AMOUNT}]{crowdloan.raised}[/{COLORS.S.AMOUNT}]\n"
            f"\t• Contributors: {crowdloan.contributors_count}"
        )

        if crowdloan.target_address:
            console.print(
                f"\t• Funds transferred to: [{COLORS.G.SUBHEAD_EX_1}]{crowdloan.target_address}[/{COLORS.G.SUBHEAD_EX_1}]"
            )

        if crowdloan.has_call:
            console.print("\t• [green]Associated call has been executed[/green]")

        await print_extrinsic_id(extrinsic_receipt)

    return True, "Successfully finalized crowdloan."
