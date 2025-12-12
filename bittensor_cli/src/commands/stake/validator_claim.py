import json
import asyncio
from typing import Optional, Any
from rich.prompt import Confirm, Prompt
from rich.panel import Panel
from rich.table import Table
from rich.columns import Columns
from rich.text import Text
from rich.console import Group
from rich import box

from bittensor_cli.src import COLOR_PALETTE
from bittensor_cli.src.bittensor.chain_data import DynamicInfo
from bittensor_cli.src.bittensor.utils import (
    console,
    err_console,
    get_subnet_name,
    millify_tao,
    parse_subnet_range,
    group_subnets,
    unlock_key,
    print_extrinsic_id,
    json_console,
)


async def show_validator_claims(
    subtensor,
    hotkey_ss58: Optional[str] = None,
    block_hash: Optional[str] = None,
    verbose: bool = False,
    json_output: bool = False,
) -> None:
    """
    Displays the validator claim configuration (Keep vs Swap) for a given hotkey's subnets.

    This function fetches the current claim status for all subnets where the validator has presence.

    Args:
        subtensor: The subtensor interface for chain interaction.
        hotkey_ss58: The SS58 address of the validator's hotkey.
        block_hash: Optional block hash to query state at.
        verbose: If True, displays full precision values.
        json_output: If True, prints JSON to stdout and suppresses table render.
    """

    def _format_subnet_row(
        subnet: DynamicInfo,
        mechanisms: dict[int, int],
        ema_tao_inflow: dict[int, Any],
        verbose: bool,
    ) -> tuple[str, ...]:
        symbol = f"{subnet.symbol}\u200e"
        netuid = subnet.netuid
        price_value = f"{subnet.price.tao:,.4f}"

        market_cap = (subnet.alpha_in.tao + subnet.alpha_out.tao) * subnet.price.tao
        market_cap_value = (
            f"{millify_tao(market_cap)}" if not verbose else f"{market_cap:,.4f}"
        )

        emission_tao = 0.0 if netuid == 0 else subnet.tao_in_emission.tao

        alpha_out_value = (
            f"{millify_tao(subnet.alpha_out.tao)}"
            if not verbose
            else f"{subnet.alpha_out.tao:,.4f}"
        )
        alpha_out_cell = (
            f"{alpha_out_value} {symbol}"
            if netuid != 0
            else f"{symbol} {alpha_out_value}"
        )

        ema_value = ema_tao_inflow.get(netuid).tao if netuid in ema_tao_inflow else 0.0

        return (
            str(netuid),
            f"[{COLOR_PALETTE['GENERAL']['SYMBOL']}]"
            f"{subnet.symbol if netuid != 0 else 'τ'}[/{COLOR_PALETTE['GENERAL']['SYMBOL']}] "
            f"{get_subnet_name(subnet)}",
            f"{price_value} τ/{symbol}",
            f"τ {market_cap_value}",
            f"τ {emission_tao:,.4f}",
            f"τ {ema_value:,.4f}",
            alpha_out_cell,
            str(mechanisms.get(netuid, 1)),
        )

    def _render_table(title: str, rows: list[tuple[str, ...]]) -> None:
        table = Table(
            title=f"\n[{COLOR_PALETTE['GENERAL']['HEADER']}]{title}[/]",
            show_footer=False,
            show_edge=False,
            header_style="bold white",
            border_style="bright_black",
            style="bold",
            title_justify="center",
            show_lines=False,
            pad_edge=True,
            box=box.MINIMAL_DOUBLE_HEAD,
        )

        table.add_column("[bold white]Netuid", style="grey89", justify="center")
        table.add_column("[bold white]Name", style="cyan", justify="left")
        table.add_column(
            "[bold white]Price \n(τ/α)",
            style="dark_sea_green2",
            justify="left",
        )
        table.add_column(
            "[bold white]Market Cap \n(α * Price)",
            style="steel_blue3",
            justify="left",
        )
        table.add_column(
            "[bold white]Emission (τ)",
            style=COLOR_PALETTE["POOLS"]["EMISSION"],
            justify="left",
        )
        table.add_column(
            "[bold white]Net Inflow EMA (τ)",
            style=COLOR_PALETTE["POOLS"]["ALPHA_OUT"],
            justify="left",
        )
        table.add_column(
            "[bold white]Stake (α_out)",
            style=COLOR_PALETTE["STAKE"]["STAKE_ALPHA"],
            justify="left",
        )
        table.add_column(
            "[bold white]Mechanisms",
            style=COLOR_PALETTE["GENERAL"]["SUBHEADING_EXTRA_1"],
            justify="center",
        )

        if not rows:
            table.add_row("~", "No subnets", "-", "-", "-", "-", "-", "-")
        else:
            for row in rows:
                table.add_row(*row)

        console.print(table)

    # Main function
    hotkey_value = hotkey_ss58
    if not hotkey_value:
        err_console.print("[red]Hotkey SS58 address is required.[/red]")
        return

    block_hash = block_hash or await subtensor.substrate.get_chain_head()

    validator_claims, subnets, mechanisms, ema_tao_inflow = await asyncio.gather(
        subtensor.get_all_validator_claim_types(
            hotkey_ss58=hotkey_value, block_hash=block_hash
        ),
        subtensor.all_subnets(block_hash=block_hash),
        subtensor.get_all_subnet_mechanisms(block_hash=block_hash),
        subtensor.get_all_subnet_ema_tao_inflow(block_hash=block_hash),
    )

    root_subnet = next(s for s in subnets if s.netuid == 0)
    other_subnets = sorted(
        [s for s in subnets if s.netuid != 0],
        key=lambda x: (x.alpha_in.tao + x.alpha_out.tao) * x.price.tao,
        reverse=True,
    )
    sorted_subnets = [root_subnet] + other_subnets

    keep_rows = []
    swap_rows = []
    for subnet in sorted_subnets:
        claim_type = validator_claims.get(subnet.netuid, "Keep")
        row = _format_subnet_row(subnet, mechanisms, ema_tao_inflow, verbose)
        if claim_type == "Swap":
            swap_rows.append(row)
        else:
            keep_rows.append(row)

    if json_output:
        output_data = {
            "hotkey": hotkey_value,
            "claims": {},
        }
        for subnet in sorted_subnets:
            claim_type = validator_claims.get(subnet.netuid, "Keep")
            output_data["claims"][subnet.netuid] = claim_type
        json_console.print(json.dumps(output_data))

    _render_table("Keep", keep_rows)
    _render_table("[red]Swap[/red]", swap_rows)
    return True


async def set_validator_claim_type(
    wallet,
    subtensor,
    keep: Optional[str] = None,
    swap: Optional[str] = None,
    keep_all: bool = False,
    swap_all: bool = False,
    prompt: bool = True,
    proxy: Optional[str] = None,
    json_output: bool = False,
) -> bool:
    """
    Configures the validator claim preference (Keep vs Swap) for subnets.

    Allows bulk updating of claim types for multiple subnets. Subnets set to 'Keep' will accumulate
    emissions as Alpha (subnet token), while 'Swap' will automatically convert emissions to TAO.

    Operates in two modes:
    1. CLI Mode: Updates specific ranges via `--keep` and `--swap` flags.
    2. Interactive Mode: Launches a claim selector if no range flags are provided.

    Args:
        wallet: The wallet configuration.
        subtensor: The subtensor interface.
        keep: Range info string for subnets to set to 'Keep'.
        swap: Range info string for subnets to set to 'Swap'.
        keep_all: If True, sets all valid subnets to 'Keep'.
        swap_all: If True, sets all valid subnets to 'Swap'.
        prompt: If True, requires confirmation before submitting extrinsic.
        proxy: Optional proxy address for signing.
        json_output: If True, outputs result as JSON.

    Returns:
        bool: True if the operation succeeded, False otherwise.
    """

    def _render_current_claims(
        state: dict[int, str],
        identity: dict = None,
        ss58: str = None,
    ):
        validator_name = identity.get("name", "Unknown")
        header_text = (
            f"[dim]Validator:[/dim] [bold cyan]{validator_name}[/bold cyan]\n"
            f"[dim]({ss58})[/dim]"
        )
        console.print(header_text, "\n")

        default_list = sorted([n for n, t in state.items() if t == "Default"])
        keep_list = sorted([n for n, t in state.items() if t == "Keep"])
        swap_list = sorted([n for n, t in state.items() if t == "Swap"])

        default_str = group_subnets(default_list) if default_list else "[dim]None[/dim]"
        keep_str = group_subnets(keep_list) if keep_list else "[dim]None[/dim]"
        swap_str = group_subnets(swap_list) if swap_list else "[dim]None[/dim]"

        default_panel = Panel(
            default_str,
            title="[bold blue]Default (Keep - α)[/bold blue]",
            border_style="blue",
            expand=False,
        )
        keep_panel = Panel(
            keep_str,
            title="[bold green]Keep (α)[/bold green]",
            border_style="green",
            expand=False,
        )
        swap_panel = Panel(
            swap_str,
            title="[bold red]Swap (τ)[/bold red]",
            border_style="red",
            expand=False,
        )

        top_row = Columns([keep_panel, swap_panel], expand=False, equal=True)

        total = len(state)
        default_count = len(default_list)
        keep_count = len(keep_list)
        swap_count = len(swap_list)

        if total > 0:
            effective_keep_count = keep_count + default_count

            keep_pct = effective_keep_count / total
            bar_width = 30
            keep_chars = int(bar_width * keep_pct)
            swap_chars = bar_width - keep_chars

            bar_visual = (
                f"[{'green' if effective_keep_count > 0 else 'dim'}]"
                f"{'█' * keep_chars}[/]"
                f"[{'red' if swap_count > 0 else 'dim'}]"
                f"{'█' * swap_chars}[/]"
            )

            dist_text = (
                f"\n[bold]Distribution:[/bold] {bar_visual} "
                f"[green]{effective_keep_count}[/green] vs [red]{swap_count}[/red]\n"
            )
        else:
            dist_text = ""

        console.print(Group(top_row, default_panel, Text.from_markup(dist_text)))

    def _print_changes_table(calls: list[tuple[int, str]]):
        table = Table(title="Pending Root Claim Changes", box=box.SIMPLE_HEAD, width=50)
        table.add_column("Netuid", justify="center", style="cyan")
        table.add_column("New Type", justify="center")

        for netuid, new_type in sorted(calls, key=lambda x: x[0]):
            color = "green" if new_type == "Keep" else "red"
            table.add_row(str(netuid), f"[{color}]{new_type}[/{color}]")

        console.print("\n\n", table)

    async def _execute_claim_change_calls(
        calls: list[tuple[int, str]],
    ) -> bool:
        extrinsic_calls = []
        for netuid, claim_type in calls:
            type_arg = {claim_type: None}

            call = await subtensor.substrate.compose_call(
                call_module="SubtensorModule",
                call_function="set_validator_claim_type",
                call_params={
                    "hotkey": wallet.hotkey.ss58_address,
                    "netuid": netuid,
                    "new_claim_type": type_arg,
                },
            )
            extrinsic_calls.append(call)

        with console.status(
            ":satellite: Submitting updates...",
            spinner="earth",
        ):
            if len(extrinsic_calls) == 1:
                final_call = extrinsic_calls[0]
            else:
                final_call = await subtensor.substrate.compose_call(
                    call_module="Utility",
                    call_function="batch_all",
                    call_params={"calls": extrinsic_calls},
                )

            success, err_msg, ext_receipt = await subtensor.sign_and_send_extrinsic(
                final_call, wallet, proxy=proxy
            )

            if success:
                if json_output:
                    json_console.print(
                        json.dumps(
                            {
                                "success": True,
                                "message": "Successfully updated validator claim types",
                                "extrinsic_hash": ext_receipt.extrinsic_hash,
                                "changes": [{"netuid": n, "type": t} for n, t in calls],
                            }
                        )
                    )
                else:
                    console.print(
                        "[green]:white_check_mark: Successfully updated validator claim types![/green]"
                    )
                    await print_extrinsic_id(ext_receipt)
                return True
            else:
                if json_output:
                    json_console.print(
                        json.dumps(
                            {
                                "success": False,
                                "message": f"Transaction Failed: {err_msg}",
                                "error": err_msg,
                            }
                        )
                    )
                else:
                    err_console.print(
                        f"[red]:cross_mark: Transaction Failed: {err_msg}[/red]"
                    )
                return False

    def _interactive_claim_selector(
        state: dict[int, str],
        all_netuids: list[int],
        identity: dict = None,
        ss58: str = None,
    ) -> Optional[dict[int, str]]:
        working_state = {}
        for n in all_netuids:
            working_state[n] = state.get(n, "Default")

        while True:
            console.print("\n")
            _render_current_claims(working_state, identity, ss58)
            help_table = Table(
                box=box.SIMPLE_HEAVY,
                show_header=True,
                header_style="bold white",
                expand=False,
            )
            help_table.add_column("Command", style="cyan", no_wrap=True)
            help_table.add_column("Description", style="dim")

            help_table.add_row("keep <ranges>", "Move subnets to Keep (e.g. '1,3-5')")
            help_table.add_row("swap <ranges>", "Move subnets to Swap (e.g. '2,10')")
            help_table.add_row(
                "keep-all / swap-all", "Move ALL subnets to Keep or Swap"
            )
            help_table.add_row("[green]done[/green]", "Finish and Apply changes")
            help_table.add_row("[red]q / quit[/red]", "Cancel operation")

            console.print(help_table)

            cmd = Prompt.ask("Enter command").strip().lower()

            if cmd in ("q", "quit", "exit"):
                return None

            if cmd == "done":
                return working_state

            if cmd == "keep-all":
                for n in working_state:
                    working_state[n] = "Keep"
                continue

            if cmd == "swap-all":
                for n in working_state:
                    working_state[n] = "Swap"
                continue

            parts = cmd.split(" ", 1)
            if len(parts) < 2:
                console.print("[red]Invalid command format.[/red]")
                continue

            action, ranges = parts[0], parts[1]
            try:
                selected_netuids = parse_subnet_range(
                    ranges, total_subnets=len(all_netuids)
                )
                valid = [n for n in selected_netuids if n in working_state]

                if action == "keep":
                    for n in valid:
                        working_state[n] = "Keep"
                elif action == "swap":
                    for n in valid:
                        working_state[n] = "Swap"
                else:
                    console.print(f"[red]Unknown action '{action}'[/red]")

            except ValueError as e:
                console.print(f"[red]Error parsing range: {e}[/red]")
