import json
from typing import Optional

from async_substrate_interface.types import Runtime
from rich.prompt import Prompt

from bittensor_cli.src.bittensor.subtensor_interface import SubtensorInterface
from bittensor_cli.src.bittensor.utils import console, json_console, print_error


async def prompt_custom_call_params(
    subtensor: SubtensorInterface,
    json_output: bool = False,
) -> tuple[bool, Optional[str], Optional[str], Optional[str], Optional[str]]:
    """
    Prompt user for custom call parameters (pallet, method, and JSON args)
    and validate that the call can be composed.

    Args:
        subtensor: SubtensorInterface instance for call validation
        json_output: Whether to output errors as JSON

    Returns:
        Tuple of (success, pallet_name, method_name, args_json, error_msg)
        On success: (True, pallet, method, args, None)
        On failure: (False, None, None, None, error_msg)
    """
    if not json_output:
        console.print(
            "\n[bold cyan]Custom Call Parameters[/bold cyan]\n"
            "[dim]You'll need to provide a pallet (module) name, method name, and optional JSON arguments.\n\n"
            "[yellow]Examples:[/yellow]\n"
            "  • Pallet: [cyan]SubtensorModule[/cyan], [cyan]Balances[/cyan], [cyan]System[/cyan]\n"
            "  • Method: [cyan]transfer_allow_death[/cyan], [cyan]transfer_keep_alive[/cyan], [cyan]transfer_all[/cyan]\n"
            '  • Args: [cyan]{"dest": "5D...", "value": 1000000000}[/cyan] or [cyan]{}[/cyan] for empty\n'
        )

    pallet = Prompt.ask("Enter pallet name")
    if not pallet.strip():
        if json_output:
            json_console.print(
                json.dumps({"success": False, "error": "Pallet name cannot be empty."})
            )
        else:
            print_error("[red]Pallet name cannot be empty.[/red]")
        return await prompt_custom_call_params(subtensor, json_output)

    method = Prompt.ask("Enter method name")
    if not method.strip():
        if json_output:
            json_console.print(
                json.dumps({"success": False, "error": "Method name cannot be empty."})
            )
        else:
            print_error("[red]Method name cannot be empty.[/red]")
        return await prompt_custom_call_params(subtensor, json_output)

    args_input = Prompt.ask(
        "Enter custom call arguments as JSON [dim](or press Enter for empty: {})[/dim]",
        default="{}",
    )

    try:
        call_params = json.loads(args_input)
    except json.JSONDecodeError as e:
        error_msg = f"Invalid JSON: {e}"
        if json_output:
            json_console.print(json.dumps({"success": False, "error": error_msg}))
        else:
            print_error(f"[red]{error_msg}[/red]")
            print_error(
                '[yellow]Please try again. Example: {"param1": "value", "param2": 123}[/yellow]'
            )
        return await prompt_custom_call_params(subtensor, json_output)

    call, error_msg = await subtensor.compose_custom_crowdloan_call(
        pallet_name=pallet,
        method_name=method,
        call_params=call_params,
    )
    if call is None:
        if json_output:
            json_console.print(json.dumps({"success": False, "error": error_msg}))
        else:
            print_error(f"[red]Failed to compose call: {error_msg}[/red]")
            console.print(
                "[yellow]Please check:\n"
                "  • Pallet name exists in runtime\n"
                "  • Method name exists in the pallet\n"
                "  • Arguments match the method's expected parameters[/yellow]\n"
            )
        return await prompt_custom_call_params(subtensor, json_output)

    return True, pallet, method, args_input, None


async def get_constant(
    subtensor: SubtensorInterface,
    constant_name: str,
    runtime: Optional[Runtime] = None,
    block_hash: Optional[str] = None,
) -> int:
    """
    Get a constant from the Crowdloan pallet.

    Args:
        subtensor: SubtensorInterface object for chain interaction
        constant_name: Name of the constant to get
        runtime: Runtime object
        block_hash: Block hash

    Returns:
        The value of the constant
    """

    runtime = runtime or await subtensor.substrate.init_runtime(block_hash=block_hash)

    result = await subtensor.substrate.get_constant(
        module_name="Crowdloan",
        constant_name=constant_name,
        block_hash=block_hash,
        runtime=runtime,
    )
    return getattr(result, "value", result)
