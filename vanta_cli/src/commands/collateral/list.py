from bittensor_wallet import Wallet
from rich.text import Text
from rich.panel import Panel
from rich.table import Table
from bittensor_cli.src.bittensor.utils import console

from vanta_cli.src.config import VANTA_API_BASE_URL_MAINNET, VANTA_API_BASE_URL_TESTNET
from vanta_cli.src.utils.api import make_api_request

async def collateral_list(
    wallet: Wallet,
    network: str = "finney",
    quiet: bool = False,
    verbose: bool = False,
    json_output: bool = False
):
    if not json_output:
        # Display the main title with Rich Panel
        title = Text("🔗 VANTA NETWORK 🔗", style="bold blue")
        subtitle = Text("Collateral Balance", style="italic cyan")

        panel = Panel.fit(
            f"{title}\n{subtitle}",
            style="bold blue",
            border_style="bright_blue"
        )

        console.print(panel)
        console.print("[blue]Checking collateral balance[/blue]")

    # Determine the base URL based on network
    base_url = VANTA_API_BASE_URL_TESTNET if network == "test" else VANTA_API_BASE_URL_MAINNET

    # Make the API request
    miner_address = wallet.hotkey.ss58_address
    endpoint = f"/collateral/balance/{miner_address}"

    try:
        response = make_api_request(endpoint, method="GET", base_url=base_url, dev_mode=verbose)

        if response is None:
            if json_output:
                console.print('{"error": "API request failed", "success": false}')
            else:
                console.print("[red]❌ Failed to retrieve collateral balance[/red]")
            return False

        # Handle successful response
        if json_output:
            import json
            console.print(json.dumps(response))
            return True

        # Display results in a nice table format
        balance_theta = response.get("balance_theta", 0.0)

        # Create a table for the results
        table = Table(title="Collateral Balance Information", show_header=True, header_style="bold magenta")
        table.add_column("Field", style="cyan", no_wrap=True)
        table.add_column("Value", style="green")

        if wallet.name:
            table.add_row("Wallet Name", wallet.name)

        table.add_row("Miner Address", miner_address)
        table.add_row("Collateral Balance (THETA)", str(balance_theta))

        console.print(table)

        # Show success message (only in dev mode)
        if response is None:
            console.print("[yellow]⚠️ API call failed[/yellow]")
        else:
            if response.get("balance_theta") is not None:
                if verbose:
                    console.print("[green]✅ Collateral balance retrieved successfully![/green]")
                return True
            else:
                error_message = (
                    response.get("error") or
                    "An unknown error occurred."
                )
                console.print(f"[red]❌ Error: {error_message}[/red]")
                return False

    except Exception as e:
        if json_output:
            console.print(f'{{"error": "Exception occurred: {e}", "success": false}}')
        else:
            console.print(f"[red]❌ Error retrieving collateral balance: {e}[/red]")
        return False
    return
