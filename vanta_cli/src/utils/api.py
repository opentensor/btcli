import json
import requests
import importlib.metadata
from typing import Dict, Any, Optional
from rich.console import Console
from vanta_cli.src.config import VANTA_API_BASE_URL_TESTNET, VANTA_API_BASE_URL_MAINNET

console = Console()

def make_api_request(
    endpoint: str,
    payload: Optional[Dict[str, Any]] = None,
    method: str = "POST",
    base_url: str = VANTA_API_BASE_URL_MAINNET,
    dev_mode: bool = False
) -> Optional[Dict[str, Any]]:
    """
    Make an API request to the Vanta backend.

    Args:
        endpoint: API endpoint (e.g., '/collateral/deposit', '/collateral/withdraw')
        payload: Request payload as dictionary (optional for GET requests)
        method: HTTP method (default: POST)
        base_url: Base URL for the API

    Returns:
        Response JSON as dictionary, or None if request failed
    """
    url = f"{base_url}{endpoint}"

    try:
        # Inject Vanta CLI version into payload for tracking
        if payload is not None:
            try:
                vanta_cli_version = importlib.metadata.version("vanta-cli")
            except importlib.metadata.PackageNotFoundError:
                vanta_cli_version = "0.0.0"
            payload["version"] = vanta_cli_version

        if dev_mode:
            console.print(f"[cyan]Making {method} request to: {url}[/cyan]")

        if payload is not None:
            if dev_mode:
                console.print("[cyan]Payload:[/cyan]")
                console.print(json.dumps(payload, indent=2))
            response = requests.request(method, url, json=payload)
        else:
            response = requests.request(method, url)

        if dev_mode:
            console.print(f"[cyan]Response status: {response.status_code}[/cyan]")
            console.print("[cyan]Response body:[/cyan]")

        try:
            response_data = response.json()
            if dev_mode:
                console.print(json.dumps(response_data, indent=2))

            if response.status_code == 200:
                if dev_mode:
                    console.print("[green]✅ API call successful[/green]")
                return response_data
            else:
                if dev_mode:
                    console.print(f"[yellow]⚠️ API call returned status {response.status_code}[/yellow]")
                return response_data

        except json.JSONDecodeError:
            console.print(f"[red]❌ Invalid JSON response: {response.text}[/red]")
            return None

    except Exception as e:
        console.print(f"[red]❌ API request failed: {e}[/red]")
        return None
