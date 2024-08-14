from typing import TYPE_CHECKING

from rich.table import Table, Column

from src.utils import console, normalize_hyperparameters

if TYPE_CHECKING:
    from src.subtensor_interface import SubtensorInterface


async def hyperparameters(subtensor: "SubtensorInterface", netuid: int):
    """View hyperparameters of a subnetwork."""
    subnet = await subtensor.get_subnet_hyperparameters(
        netuid
    )

    table = Table(
        Column("[overline white]HYPERPARAMETER", style="white"),
        Column("[overline white]VALUE", style="green"),
        Column("[overline white]NORMALIZED", style="cyan"),
        title=f"[white]Subnet Hyperparameters - NETUID: {netuid} - {subtensor}",
        show_footer=True,
        width=None,
        pad_edge=True,
        box=None,
        show_edge=True,
    )

    normalized_values = normalize_hyperparameters(subnet)

    for param, value, norm_value in normalized_values:
        table.add_row("  " + param, value, norm_value)

    console.print(table)
