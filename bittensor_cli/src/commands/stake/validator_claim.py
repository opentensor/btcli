import asyncio
from typing import Optional, Any

from rich.table import Table
from rich import box

from bittensor_cli.src import COLOR_PALETTE
from bittensor_cli.src.bittensor.chain_data import DynamicInfo
from bittensor_cli.src.bittensor.utils import (
    console,
    err_console,
    get_subnet_name,
    millify_tao,
)


def _format_subnet_row(
    subnet: DynamicInfo,
    mechanisms: dict[int, int],
    ema_tao_inflow: dict[int, Any],
    verbose: bool,
) -> tuple[str, ...]:
    """
    Format a subnet row for display in a table.
    """
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
        f"{alpha_out_value} {symbol}" if netuid != 0 else f"{symbol} {alpha_out_value}"
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
