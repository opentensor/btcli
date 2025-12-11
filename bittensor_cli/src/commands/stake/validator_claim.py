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
