"""Entity registration command."""
import getpass
import json
import typer
from rich.panel import Panel
from rich.text import Text
from rich.table import Table

from bittensor_wallet import Wallet
from bittensor_cli.src.bittensor.utils import console

from vanta_cli.src.config import VANTA_API_BASE_URL_MAINNET, VANTA_API_BASE_URL_TESTNET
from vanta_cli.src.utils.api import make_api_request


async def register(
    wallet: Wallet,
    network: str,
    prompt: bool,
    quiet: bool = False,
    verbose: bool = False,
    json_output: bool = False
):
    """
    Register a new entity on the Vanta Network.

    This command:
    1. Fetches entity registration fee from validator
    2. Checks miner's collateral balance
    3. Prompts for deposit if insufficient collateral
    4. Registers entity with signature-based authentication
    """
    # Display header
    if not json_output:
        title = Text("🔗 VANTA NETWORK 🔗", style="bold blue")
        subtitle = Text("Entity Registration", style="italic cyan")
        panel = Panel.fit(
            f"{title}\n{subtitle}",
            style="bold blue",
            border_style="bright_blue"
        )
        console.print(panel)
        console.print("[blue]Registering entity on Vanta Network[/blue]")

    # Determine base URL
    base_url = VANTA_API_BASE_URL_TESTNET if network == "test" else VANTA_API_BASE_URL_MAINNET

    registration_fee = 1000 # Theta

    # Display configuration
    if not json_output:
        config_table = Table(title="Entity Registration Configuration", show_header=True, header_style="bold cyan")
        config_table.add_column("Parameter", style="cyan")
        config_table.add_column("Value", style="green")

        config_table.add_row("Network", "Testnet" if network == "test" else "Mainnet")
        config_table.add_row("Registration Fee", f"{registration_fee} Theta")

        console.print(config_table)

    # Step 2: Get password
    password = getpass.getpass(prompt='Enter your wallet password: ')

    try:
        coldkey = wallet.get_coldkey(password=password)
        hotkey = wallet.hotkey
    except Exception as e:
        console.print(f"[red]Failed to unlock wallet: {e}[/red]")
        return False

    # Step 3: Confirm registration
    if prompt:
        confirm = typer.confirm(
            f"Register entity {hotkey.ss58_address} "
            f"(costs {registration_fee} Theta)?"
        )
        if not confirm:
            console.print("[yellow]Entity registration cancelled[/yellow]")
            return False

    # Step 4: Ensure sufficient collateral
    response = make_api_request(f"/collateral/balance/{hotkey.ss58_address}", method="GET", base_url=base_url, dev_mode=verbose)
    if not response or response.get("balance_theta") < registration_fee:
        console.print(f"[red]Insufficient collateral for entity registration: {response.get('balance_theta')}[/red]")
        return False


    # collateral_success, collateral_msg = ensure_sufficient_collateral(
    #     wallet=wallet,
    #     network=network,
    #     required_theta=registration_fee,
    #     purpose="entity registration",
    #     password=password,
    #     base_url=base_url,
    #     verbose=verbose
    # )
    #
    # if not collateral_success:
    #     console.print(f"[red]Collateral check failed: {collateral_msg}[/red]")
    #     return False

    # Step 5: Prepare and sign registration request
    console.print("\n[cyan]Signing entity registration request...[/cyan]")

    registration_data = {
        "entity_coldkey": coldkey.ss58_address,
        "entity_hotkey": hotkey.ss58_address
    }

    # Create message to sign (sorted JSON)
    message = json.dumps(registration_data, sort_keys=True)

    # Sign the message with coldkey
    signature = coldkey.sign(message.encode('utf-8')).hex()

    # Prepare payload
    payload = {
        "entity_coldkey": coldkey.ss58_address,
        "entity_hotkey": hotkey.ss58_address,
        "signature": signature
    }

    # Step 6: Send registration request
    console.print("\n[cyan]Sending entity registration request...[/cyan]")

    try:
        response = make_api_request("/entity/register", payload, base_url=base_url, dev_mode=verbose)

        if response is None:
            console.print("[red]Entity registration failed - no response[/red]")
            return False

        # Check success
        if response.get("status") == "success":
            console.print(f"[green]{response.get('message')}[/green]")

            # Display success info
            success_table = Table(title="Entity Registered Successfully", show_header=True, header_style="bold green")
            success_table.add_column("Field", style="cyan")
            success_table.add_column("Value", style="green")

            success_table.add_row("Entity Hotkey", response.get('entity_hotkey'))
            success_table.add_row("Fee Charged", f"{registration_fee} Theta")

            console.print(success_table)

            success_panel = Panel.fit(
                f"🎉 Entity registration completed!\nYou can now create subaccounts using 'vanta entity create-subaccount'",
                style="bold green",
                border_style="green"
            )
            console.print(success_panel)
            return True
        else:
            error_message = response.get("error") or "Unknown error occurred"
            console.print(f"[red]Entity registration failed: {error_message}[/red]")
            return False

    except Exception as e:
        console.print(f"[red]Error during entity registration: {e}[/red]")
        return False
