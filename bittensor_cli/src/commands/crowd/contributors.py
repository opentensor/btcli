from typing import Optional
import asyncio
import json
from rich.table import Table

from bittensor_cli.src import COLORS
from bittensor_cli.src.bittensor.balances import Balance
from bittensor_cli.src.bittensor.subtensor_interface import SubtensorInterface
from bittensor_cli.src.bittensor.utils import (
    console,
    json_console,
    print_error,
    millify_tao,
    decode_account_id,
)


def _shorten(account: Optional[str]) -> str:
    """Shorten an account address for display."""
    if not account:
        return "-"
    return f"{account[:6]}…{account[-6:]}"




async def list_contributors(
    subtensor: SubtensorInterface,
    crowdloan_id: int,
    verbose: bool = False,
    json_output: bool = False,
) -> bool:
    """List all contributors to a specific crowdloan.

    Args:
        subtensor: SubtensorInterface object for chain interaction
        crowdloan_id: ID of the crowdloan to list contributors for
        verbose: Show full addresses and precise amounts
        json_output: Output as JSON

    Returns:
        bool: True if successful, False otherwise
    """
    # First verify the crowdloan exists
    crowdloan = await subtensor.get_single_crowdloan(crowdloan_id)
    if not crowdloan:
        error_msg = f"Crowdloan #{crowdloan_id} not found."
        if json_output:
            json_console.print(json.dumps({"success": False, "error": error_msg}))
        else:
            print_error(f"[red]{error_msg}[/red]")
        return False

    # Query contributors from Contributions storage (double map)
    # Query map with first key fixed to crowdloan_id to get all contributors
    contributors_data = await subtensor.substrate.query_map(
        module="Crowdloan",
        storage_function="Contributions",
        params=[crowdloan_id],
        fully_exhaust=True,
    )

    # Extract contributors and their contributions from the map
    contributor_contributions = {}
    async for contributor_key, contribution_amount in contributors_data:
        # Extract contributor address from the storage key
        # For double maps queried with first key fixed, the key is a tuple: ((account_bytes_tuple,),)
        # where account_bytes_tuple is a tuple of integers representing the account ID
        try:
            # The key structure is: ((account_bytes_tuple,),)
            # where account_bytes_tuple is a tuple of integers (32 bytes = 32 ints)
            if isinstance(contributor_key, tuple) and len(contributor_key) > 0:
                inner_tuple = contributor_key[0]
                if isinstance(inner_tuple, tuple):
                    # Decode the account ID from the tuple of integers
                    # decode_account_id handles both tuple[int] and tuple[tuple[int]] formats
                    contributor_address = decode_account_id(contributor_key)
                else:
                    # Fallback: try to decode directly
                    contributor_address = decode_account_id(contributor_key)
            else:
                # Fallback: try to decode the key directly
                contributor_address = decode_account_id(contributor_key)

            # Store contribution amount
            # The value is a BittensorScaleType object, access .value to get the integer
            contribution_value = (
                contribution_amount.value
                if hasattr(contribution_amount, "value")
                else contribution_amount
            )
            contribution_balance = (
                Balance.from_rao(int(contribution_value))
                if contribution_value
                else Balance.from_tao(0)
            )
            contributor_contributions[contributor_address] = contribution_balance
        except Exception as e:
            # Skip invalid entries - uncomment for debugging
            # print(f"Error processing contributor: {e}, key: {contributor_key}")
            continue

    if not contributor_contributions:
        if json_output:
            json_console.print(
                json.dumps(
                    {
                        "success": True,
                        "error": None,
                        "data": {
                            "crowdloan_id": crowdloan_id,
                            "contributors": [],
                            "total_count": 0,
                            "total_contributed": 0,
                        },
                    }
                )
            )
        else:
            console.print(
                f"[yellow]No contributors found for crowdloan #{crowdloan_id}.[/yellow]"
            )
        return True

    all_identities = await subtensor.query_all_identities()

    # Build contributor data list
    contributors_list = list(contributor_contributions.keys())
    contributor_data = []
    total_contributed = Balance.from_tao(0)

    for contributor_address in contributors_list:
        contribution_amount = contributor_contributions[contributor_address]
        total_contributed += contribution_amount
        identity = all_identities.get(contributor_address)
        identity_name = None
        if identity:
            identity_name = identity.get("name") or identity.get("display")

        contributor_data.append(
            {
                "address": contributor_address,
                "identity": identity_name,
                "contribution": contribution_amount,
            }
        )

    # Sort by contribution amount (descending)
    contributor_data.sort(key=lambda x: x["contribution"].rao, reverse=True)

    # Calculate percentages
    for data in contributor_data:
        if total_contributed.rao > 0:
            percentage = (data["contribution"].rao / total_contributed.rao) * 100
        else:
            percentage = 0.0
        data["percentage"] = percentage

    if json_output:
        contributors_json = []
        for rank, data in enumerate(contributor_data, start=1):
            contributors_json.append(
                {
                    "rank": rank,
                    "address": data["address"],
                    "identity": data["identity"],
                    "contribution_tao": data["contribution"].tao,
                    "contribution_rao": data["contribution"].rao,
                    "percentage": data["percentage"],
                }
            )

        output_dict = {
            "success": True,
            "error": None,
            "data": {
                "crowdloan_id": crowdloan_id,
                "contributors": contributors_json,
                "total_count": len(contributor_data),
                "total_contributed_tao": total_contributed.tao,
                "total_contributed_rao": total_contributed.rao,
                "network": subtensor.network,
            },
        }
        json_console.print(json.dumps(output_dict))
        return True

    # Display table
    table = Table(
        title=f"\n[{COLORS.G.HEADER}]Contributors for Crowdloan #{crowdloan_id}"
        f"\nNetwork: [{COLORS.G.SUBHEAD}]{subtensor.network}\n\n",
        show_footer=True,
        show_edge=False,
        header_style="bold white",
        border_style="bright_black",
        style="bold",
        title_justify="center",
        show_lines=False,
        pad_edge=True,
    )

    table.add_column(
        "[bold white]Rank",
        style="grey89",
        justify="center",
        footer=str(len(contributor_data)),
    )
    table.add_column(
        "[bold white]Contributor Address",
        style=COLORS.G.TEMPO,
        justify="left",
        overflow="fold",
    )
    table.add_column(
        "[bold white]Identity Name",
        style=COLORS.G.SUBHEAD,
        justify="left",
        overflow="fold",
    )
    table.add_column(
        f"[bold white]Contribution\n({Balance.get_unit(0)})",
        style="dark_sea_green2",
        justify="right",
        footer=f"τ {millify_tao(total_contributed.tao)}"
        if not verbose
        else f"τ {total_contributed.tao:,.4f}",
    )
    table.add_column(
        "[bold white]Percentage",
        style=COLORS.P.EMISSION,
        justify="right",
        footer="100.00%",
    )

    for rank, data in enumerate(contributor_data, start=1):
        address_cell = data["address"] if verbose else _shorten(data["address"])
        identity_cell = data["identity"] if data["identity"] != "-" else "[dim]-[/dim]"

        if verbose:
            contribution_cell = f"τ {data['contribution'].tao:,.4f}"
        else:
            contribution_cell = f"τ {millify_tao(data['contribution'].tao)}"

        percentage_cell = f"{data['percentage']:.2f}%"

        table.add_row(
            str(rank),
            address_cell,
            identity_cell,
            contribution_cell,
            percentage_cell,
        )

    console.print(table)
    return True
