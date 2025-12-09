"""
Proxy List Command - List all proxies for an account.

This command queries and displays all proxy relationships for a given account.
"""

import asyncio
from typing import TYPE_CHECKING, Optional

from rich.table import Table
from async_substrate_interface.errors import SubstrateRequestException

from bittensor_cli.src.bittensor.utils import (
    console,
    err_console,
    format_error_message,
    is_valid_ss58_address,
)
from bittensor_wallet import Wallet

if TYPE_CHECKING:
    from bittensor_cli.src.bittensor.subtensor_interface import SubtensorInterface


async def proxy_list(
    subtensor: "SubtensorInterface",
    address: str,
) -> bool:
    """
    List all proxies for a given account.

    Args:
        subtensor: SubtensorInterface object
        address: SS58 address to query proxies for

    Returns:
        bool: True if query was successful, False otherwise
    """

    # Validate address
    if not is_valid_ss58_address(address):
        err_console.print(
            f":cross_mark: [red]Invalid SS58 address[/red]:[bold white]\n  {address}[/bold white]"
        )
        return False

    console.print(f"[dark_orange]Querying proxies on network: {subtensor.network}")

    try:
        with console.status("[bold green]Fetching proxies..."):
            # Query the Proxy.Proxies storage
            result = await subtensor.substrate.query(
                module="Proxy",
                storage_function="Proxies",
                params=[address],
            )

        if result is None:
            console.print(f"\n[yellow]No proxies found for account:[/yellow] {address}")
            return True

        # Parse the result - it returns a tuple of (Vec<ProxyDefinition>, Balance)
        proxies_data = result.value if hasattr(result, 'value') else result

        # Handle different response formats
        proxies = []
        deposit = 0

        if isinstance(proxies_data, (list, tuple)):
            if len(proxies_data) >= 1:
                # First element should be the list of proxies
                if isinstance(proxies_data[0], list):
                    proxies = proxies_data[0]
                elif isinstance(proxies_data[0], dict):
                    # Single proxy as dict
                    proxies = [proxies_data[0]]
                # Second element is deposit if present
                if len(proxies_data) > 1 and isinstance(proxies_data[1], int):
                    deposit = proxies_data[1]
        elif isinstance(proxies_data, dict):
            # Single proxy returned as dict
            proxies = [proxies_data]

        if not proxies:
            console.print(f"\n[yellow]No proxies found for account:[/yellow] {address}")
            return True

        # Create table for display
        table = Table(
            title=f"Proxies for {address[:8]}...{address[-8:]}",
            show_header=True,
            header_style="bold magenta",
        )
        table.add_column("Delegate", style="cyan")
        table.add_column("Proxy Type", style="yellow")
        table.add_column("Delay (blocks)", style="green", justify="right")

        for proxy in proxies:
            if isinstance(proxy, dict):
                delegate = proxy.get("delegate", "Unknown")
                proxy_type = proxy.get("proxy_type", proxy.get("proxyType", "Unknown"))
                delay = proxy.get("delay", 0)
            else:
                # Handle tuple format
                delegate = proxy[0] if len(proxy) > 0 else "Unknown"
                proxy_type = proxy[1] if len(proxy) > 1 else "Unknown"
                delay = proxy[2] if len(proxy) > 2 else 0

            # Convert proxy_type if it's a dict/enum
            if isinstance(proxy_type, dict):
                proxy_type = list(proxy_type.keys())[0] if proxy_type else "Unknown"

            table.add_row(
                str(delegate),
                str(proxy_type),
                str(delay),
            )

        console.print()
        console.print(table)

        # Show deposit if available
        if deposit and deposit > 0:
            from bittensor_cli.src.bittensor.balances import Balance
            deposit_balance = Balance.from_rao(deposit)
            console.print(f"\n[dim]Reserved deposit: {deposit_balance}[/dim]")

        return True

    except SubstrateRequestException as e:
        err_console.print(
            f":cross_mark: [red]Failed to query proxies[/red]:\n  {format_error_message(e)}"
        )
        return False
    except Exception as e:
        err_console.print(
            f":cross_mark: [red]Error querying proxies[/red]:\n  {str(e)}"
        )
        return False


async def proxy_list_for_wallet(
    wallet: Wallet,
    subtensor: "SubtensorInterface",
) -> bool:
    """
    List all proxies for the wallet's coldkey account.

    Args:
        wallet: The wallet object
        subtensor: SubtensorInterface object

    Returns:
        bool: True if query was successful, False otherwise
    """
    return await proxy_list(subtensor, wallet.coldkeypub.ss58_address)
