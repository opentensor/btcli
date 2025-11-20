from datetime import datetime, timezone
import getpass
import json
import secrets

from rich.panel import Panel

from bittensor_wallet import Wallet
from rich.text import Text
import typer
from bittensor_cli.src.bittensor.utils import console

from ptn_cli.src.config import PTN_API_BASE_URL_MAINNET, PTN_API_BASE_URL_TESTNET
from ptn_cli.src.utils.api import make_api_request

async def withdraw(
    wallet: Wallet,
    network: str,
    amount: float,
    prompt: bool,
    quiet: bool = False,
    verbose: bool = False,
    json_output: bool = False
):
    # Display the main title with Rich Panel
    title = Text("🔗 PROPRIETARY TRADING NETWORK 🔗", style="bold blue")
    subtitle = Text("Collateral Withdrawal", style="italic cyan")

    panel = Panel.fit(
        f"{title}\n{subtitle}",
        style="bold blue",
        border_style="bright_blue"
    )

    console.print(panel)
    console.print("[blue]Withdrawing collateral from PTN[/blue]")

    # Load wallet and get keys
    password = getpass.getpass(prompt='Enter your password: ')

    coldkey = wallet.get_coldkey(password=password)
    hotkey = wallet.hotkey

    # Show withdrawal details
    console.print(f"[cyan]Amount to withdraw:[/cyan] {amount}")
    console.print(f"[cyan]Wallet:[/cyan] {wallet.name}")
    console.print(f"[cyan]Miner coldkey:[/cyan] {coldkey.ss58_address}")
    console.print(f"[cyan]Miner hotkey:[/cyan] {hotkey.ss58_address}")

    if prompt:
        confirm = typer.confirm(f"Are you sure you want to withdraw {amount} Theta collateral for miner {hotkey.ss58_address}?")
        if not confirm:
            console.print("[yellow]Withdrawal cancelled[/yellow]")
            return False

    # Determine which API base URL to use based on network
    base_url = PTN_API_BASE_URL_TESTNET if network == "test" else PTN_API_BASE_URL_MAINNET

    # Step 1: Query the withdrawal to get the slashed amount
    console.print("\n[cyan]Querying withdrawal details...[/cyan]")

    query_payload = {
        "amount": amount,
        "miner_hotkey": hotkey.ss58_address
    }

    try:
        query_response = make_api_request("/collateral/query-withdraw", query_payload, base_url=base_url)

        if query_response is None:
            console.print("[red]❌ Failed to query withdrawal details[/red]")
            return False

        if query_response.get("successfully_processed"):
            # Display the detailed withdrawal information
            drawdown = query_response.get("drawdown", 0)
            slashed_amount = query_response.get("slashed_amount", 0)
            withdrawal_amount = query_response.get("withdrawal_amount", amount)
            new_balance = query_response.get("new_balance", 0)

            console.print(f"\n[yellow]⚠️  Withdrawal Impact:[/yellow]")
            console.print(f"\n[yellow]Values are approximate and may change depending on current drawdown.[/yellow]")
            console.print(f"[cyan]Requested withdrawal:[/cyan] {amount} Theta")
            console.print(f"[cyan]Current drawdown:[/cyan] {(1.0 - drawdown) * 100:.2f}%")
            console.print(f"[cyan]Amount to be slashed:[/cyan] {slashed_amount} Theta")
            console.print(f"[cyan]Net withdrawal amount:[/cyan] {withdrawal_amount} Theta")
            console.print(f"[cyan]New balance after withdrawal:[/cyan] {new_balance} Theta")

        else:
            error_message = (
                    query_response.get("error_message") or
                    query_response.get("error") or
                    "An unknown error occurred."
            )
            console.print(f"[red]❌ Query failed: {error_message}[/red]")
            return False

        # Step 2: Confirm with the user about the slashed amount
        if prompt:
            if slashed_amount > 0:
                confirm_slash = typer.confirm(f"\nThis withdrawal will result in approximately {slashed_amount} Theta being slashed. Do you want to continue?")
            else:
                confirm_slash = typer.confirm(f"\nProceed with withdrawal of {withdrawal_amount} Theta?")

            if not confirm_slash:
                console.print("[yellow]Withdrawal cancelled[/yellow]")
                return False

    except Exception as e:
        console.print(f"[red]❌ Error querying withdrawal: {e}[/red]")
        return False

    # Step 3: Proceed with the actual withdrawal
    nonce = secrets.token_urlsafe()
    timestamp = int(datetime.now(timezone.utc).timestamp() * 1000)

    # Prepare withdrawal data for signing
    withdrawal_data = {
        "amount": amount,
        "miner_coldkey": coldkey.ss58_address,
        "miner_hotkey": hotkey.ss58_address,
        "nonce": nonce,
        "timestamp": timestamp,
    }

    # Create message to sign (sorted JSON)
    message = json.dumps(withdrawal_data, sort_keys=True)

    # Sign the message with coldkey
    signature = coldkey.sign(message.encode('utf-8')).hex()

    # Prepare payload for withdrawal (include signature)
    payload = {
        "amount": amount,
        "miner_coldkey": coldkey.ss58_address,
        "miner_hotkey": hotkey.ss58_address,
        "nonce": nonce,
        "timestamp": timestamp,
        "signature": signature
    }

    # Make the API request
    console.print("\n[cyan]Sending withdrawal request...[/cyan]")
    console.print(f"[dim]Using network: {network}[/dim]")

    try:
        response = make_api_request("/collateral/withdraw", payload, base_url=base_url)

        if response is None:
            console.print("[red]❌ Withdrawal request failed[/red]")
            return False

        # Check if withdrawal was successful
        if response.get("successfully_processed"):
            console.print("[green]✅ Collateral withdrawal successful![/green]")

            # Show success panel
            returned_amount = response.get("returned_amount")
            success_panel = Panel.fit(
                f"🎉 Withdrawal completed!\nAmount: {returned_amount}\nMiner: {coldkey.ss58_address}",
                style="bold green",
                border_style="green"
            )
            console.print(success_panel)
            return True
        else:
            error_message = (
                response.get("error_message") or
                response.get("error") or
                "An unknown error occurred."
            )
            console.print(f"[red]❌ Withdrawal failed: {error_message}[/red]")
            return False
    except Exception as e:
        console.print(f"[red]❌ Error during withdrawal: {e}[/red]")

