"""Request an API key for an entity miner."""
import getpass
import json

from rich.panel import Panel
from rich.text import Text
from rich.table import Table

from bittensor_wallet import Wallet
from bittensor_cli.src.bittensor.utils import console

from vanta_cli.src.config import VANTA_API_BASE_URL_MAINNET, VANTA_API_BASE_URL_TESTNET
from vanta_cli.src.utils.api import make_api_request


async def apikey(
    wallet: Wallet,
    network: str,
    quiet: bool = False,
    verbose: bool = False,
    json_output: bool = False,
):
    """
    Request or retrieve an API key for a registered entity miner.

    The API key grants tier-200 WebSocket access, allowing the entity miner
    to receive real-time subaccount dashboard updates. The key is idempotent —
    calling this command again returns the same key if one has already been
    issued for the entity.
    """
    if not json_output:
        title = Text("VANTA NETWORK", style="bold blue")
        subtitle = Text("Entity API Key Request", style="italic cyan")
        panel = Panel.fit(
            f"{title}\n{subtitle}",
            style="bold blue",
            border_style="bright_blue"
        )
        console.print(panel)

    base_url = VANTA_API_BASE_URL_TESTNET if network == "test" else VANTA_API_BASE_URL_MAINNET

    password = getpass.getpass(prompt="Enter your wallet password: ")

    try:
        coldkey = wallet.get_coldkey(password=password)
        hotkey = wallet.hotkey
    except Exception as e:
        console.print(f"[red]Failed to unlock wallet: {e}[/red]")
        return False

    if not json_output:
        console.print("\n[cyan]Signing API key request...[/cyan]")

    request_data = {
        "entity_coldkey": coldkey.ss58_address,
        "entity_hotkey": hotkey.ss58_address,
    }
    message = json.dumps(request_data, sort_keys=True)
    signature = coldkey.sign(message.encode("utf-8")).hex()

    payload = {
        "entity_coldkey": coldkey.ss58_address,
        "entity_hotkey": hotkey.ss58_address,
        "signature": signature,
    }

    try:
        response = make_api_request("/request-api-key", payload, base_url=base_url, dev_mode=verbose)

        if response is None:
            console.print("[red]API key request failed - no response from validator[/red]")
            return False

        api_key = response.get("api_key")
        if api_key:
            if json_output:
                import json as _json
                console.print(_json.dumps({"api_key": api_key}))
            else:
                result_table = Table(title="Entity API Key", show_header=True, header_style="bold cyan")
                result_table.add_column("Field", style="cyan")
                result_table.add_column("Value", style="green")
                result_table.add_row("Entity Hotkey", hotkey.ss58_address)
                result_table.add_row("API Key", api_key)
                console.print(result_table)

                console.print(Panel.fit(
                    "Store this API key as 'validator_api_key' in your entity miner secrets file.\n"
                    "It grants tier-200 WebSocket access to your subaccount dashboards.",
                    style="bold green",
                    border_style="green"
                ))
            return True
        else:
            error_message = response.get("error") or "Unknown error occurred"
            console.print(f"[red]API key request failed: {error_message}[/red]")
            return False

    except Exception as e:
        console.print(f"[red]Error requesting API key: {e}[/red]")
        return False
