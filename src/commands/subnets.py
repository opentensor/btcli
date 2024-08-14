import asyncio
from typing import TYPE_CHECKING

from rich.table import Table, Column

from src import Constants, DelegatesDetails
from src.bittensor.chain_data import SubnetInfo
from src.utils import (
    console,
    err_console,
    get_delegates_details_from_github,
    millify,
    RAO_PER_TAO,
)

if TYPE_CHECKING:
    from src.subtensor_interface import SubtensorInterface


async def subnets_list(subtensor: "SubtensorInterface"):
    """List all subnet netuids in the network."""

    async def _get_all_subnets_info():
        json_body = await subtensor.substrate.rpc_request(
            method="subnetInfo_getSubnetsInfo",  # custom rpc method
            params=[],
        )

        return (
            SubnetInfo.list_from_vec_u8(result)
            if (result := json_body.get("result"))
            else []
        )

    subnets: list[SubnetInfo]
    delegate_info: dict[str, DelegatesDetails]

    subnets, delegate_info = await asyncio.gather(
        _get_all_subnets_info(),
        get_delegates_details_from_github(url=Constants.delegates_detail_url),
    )

    if not subnets:
        err_console.print("[red]No subnets found[/red]")
        return

    rows = []
    total_neurons = 0

    for subnet in subnets:
        total_neurons += subnet.max_n
        rows.append(
            (
                str(subnet.netuid),
                str(subnet.subnetwork_n),
                str(millify(subnet.max_n)),
                f"{subnet.emission_value / RAO_PER_TAO * 100:0.2f}%",
                str(subnet.tempo),
                f"{subnet.burn!s:8.8}",
                str(millify(subnet.difficulty)),
                f"{delegate_info[subnet.owner_ss58].name if subnet.owner_ss58 in delegate_info else subnet.owner_ss58}",
            )
        )
    table = Table(
        Column(
            "[overline white]NETUID",
            str(len(subnets)),
            footer_style="overline white",
            style="bold green",
            justify="center",
        ),
        Column(
            "[overline white]N",
            str(total_neurons),
            footer_style="overline white",
            style="green",
            justify="center",
        ),
        Column("[overline white]MAX_N", style="white", justify="center"),
        Column("[overline white]EMISSION", style="white", justify="center"),
        Column("[overline white]TEMPO", style="white", justify="center"),
        Column("[overline white]RECYCLE", style="white", justify="center"),
        Column("[overline white]POW", style="white", justify="center"),
        Column("[overline white]SUDO", style="white"),
        title=f"[white]Subnets - {subtensor.network}",
        show_footer=True,
        width=None,
        pad_edge=True,
        box=None,
        show_edge=True,
    )
    for row in rows:
        table.add_row(*row)
    console.print(table)
