import getpass
import json
from typing import Any

from rich.table import Table
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn

from bittensor_wallet import Wallet
from bittensor_cli.src.bittensor.utils import console

from vanta_cli.src.config import COLLATERAL_DEST_ADDRESS_MAINNET, COLLATERAL_DEST_ADDRESS_TESTNET, VANTA_API_BASE_URL_MAINNET, VANTA_API_BASE_URL_TESTNET
from vanta_cli.src.utils.api import make_api_request

async def deposit(
    wallet: Wallet,
    network: str,
    amount: float,
    quiet: bool = False,
    verbose: bool = False,
    json_output: bool = False
):
    from collateral_sdk import CollateralManager, Network # importing on compile time causes help menu to break
    console.print("[blue]Adding collateral to Vanta Network[/blue]")

    manager = CollateralManager(Network.TESTNET if network == 'test' else Network.MAINNET)

    password = getpass.getpass(prompt='Enter your password: ')

    coldkey = wallet.get_coldkey(password)
    hotkey = wallet.hotkey

    # Set netuid based on network
    netuid = 116 if network == 'test' else 8

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Fetching stake information...", total=None)
        source_stake: Any = manager.subtensor_api.staking.get_stake_for_coldkey(coldkey.ss58_address)

        progress.update(task, description="Checking Wallet Information...")
        balance: Any = manager.balance_of(hotkey.ss58_address) / 10 ** 9
        progress.stop()

    # Create wallet info table
    table_title = "Current Collateral Balance"
    if network == 'test':
        table_title += " (testnet)"

    table = Table(title=table_title, show_header=True, header_style="bold magenta")
    table.add_column("Property", style="cyan", no_wrap=True)
    table.add_column("Value", style="green")

    # Handle Balance object formatting
    try:
        if hasattr(balance, 'value'):
            balance_str = str(balance.value)
        elif hasattr(balance, 'free'):
            balance_str = str(balance.free)
        else:
            balance_str = repr(balance)
    except Exception:
        balance_str = repr(balance)

    # Add wallet information rows
    table.add_row("Coldkey Address", coldkey.ss58_address)
    table.add_row("Hotkey Address", hotkey.ss58_address)
    table.add_row("Balance (Theta)", balance_str)

    console.print(table)

    # Display all stake information in a single table
    matching_stake = None
    if source_stake:
        # Create unified stake table
        stake_table = Table(title="Stake Information", show_header=True, header_style="bold cyan")
        stake_table.add_column("Hotkey", style="cyan", no_wrap=True)
        stake_table.add_column("Netuid", style="magenta", no_wrap=True)
        stake_table.add_column("Stake Amount", style="green", justify="right")
        stake_table.add_column("Locked", style="yellow", justify="right")
        stake_table.add_column("Registered", style="bold", justify="center")

        for stake_info in source_stake:
            if stake_info.netuid != netuid:
                continue

            # Format the hotkey address to show first 8 and last 6 characters
            formatted_hotkey = f"{stake_info.hotkey_ss58[:8]}...{stake_info.hotkey_ss58[-6:]}"

            # Highlight the target netuid row
            netuid_style = "bold green" if stake_info.netuid == netuid else "magenta"

            stake_table.add_row(
                formatted_hotkey,
                f"[{netuid_style}]{stake_info.netuid}[/{netuid_style}]",
                f"{float(stake_info.stake):.4f}",
                f"{float(stake_info.locked):.4f}",
                "✅" if stake_info.is_registered else "❌"
            )
        console.print(stake_table)

        # Set matching_stake
        matching_stake = next(
            (stake for stake in source_stake if (stake.hotkey_ss58 == hotkey.ss58_address and stake.netuid == netuid)),
            None
        )
    else:
        console.print("[yellow]No stake information available[/yellow]")


      # Check if source_stake is empty to avoid index error
    if not source_stake:
        console.print("[red]❌ No source stake found for this coldkey[/red]")
        return None

    if not matching_stake:
        console.print(f"[red]❌ No stake found for hotkey {hotkey} on netuid {netuid}[/red]")
        return None

    if verbose:
      console.print("[yellow]🔄 Creating stake transfer extrinsic...[/yellow]")

    # Use configured dest address
    dest_address = COLLATERAL_DEST_ADDRESS_TESTNET if network == 'test' else COLLATERAL_DEST_ADDRESS_MAINNET


    # Create an extrinsic for a stake transfer.
    extrinsic = manager.create_stake_transfer_extrinsic(
        amount=int(amount * 10**9),     # convert theta to rao_theta
        dest=dest_address,
        source_stake=matching_stake.hotkey_ss58,
        source_wallet=wallet,
        wallet_password=password
    )

    if verbose:
      console.print(f"extrinsic: {extrinsic}")
      console.print(json.dumps(str(extrinsic), indent=2))

    encoded = manager.encode_extrinsic(extrinsic)
    decoded = manager.decode_extrinsic(encoded)

    if verbose:
      console.print("[cyan]Encoded extrinsic:[/cyan]")
      console.print(json.dumps(str(encoded), indent=2))

      console.print("[cyan]Decoded extrinsic:[/cyan]")
      console.print(json.dumps(str(decoded), indent=2))

    result = {
        "encoded": encoded.hex(),
        "amount": amount,
        "coldkey": coldkey.ss58_address,
    }

    if verbose:
      console.print("[cyan]Request:[/cyan]")
      console.print(json.dumps(result, indent=2, default=str))

    if json_output:
        console.print("json")

    try:
        if verbose:
            print(result)

        if result is None:
            console.print("[red]❌ Collateral setup failed[/red]")
            return False

        if verbose:
            console.print("[green]✅ Extrinsic Created successfully[/green]")
            console.print("sending extrinsic")

        try:
            # Convert bytearray to hex string for JSON serialization
            encoded_data = result["encoded"]
            if isinstance(encoded_data, bytearray):
                encoded_data = encoded_data.hex()

            payload = {
                "extrinsic": encoded_data,
            }

            # Determine the base URL based on network
            base_url = VANTA_API_BASE_URL_TESTNET if network == "test" else VANTA_API_BASE_URL_MAINNET

            # Use the new API utility
            response = make_api_request("/collateral/deposit", payload, base_url=base_url)

            if response is None:
                console.print("[yellow]⚠️ API call failed[/yellow]")
                return False
            else:
                if response.get("successfully_processed"):
                    console.print("[green]✅ Collateral added successfully![/green]")
                    return True
                else:
                    error_message = (
                        response.get("error_message") or
                        response.get("error") or
                        "An unknown error occurred."
                    )
                    console.print(f"[red]❌ Deposit failed: {error_message}[/red]")
                    return False

        except Exception as api_error:
            console.print(f"[yellow]⚠️ API call failed: {api_error}[/yellow]")
            return False

    except Exception as e:
        console.print(f"[red]❌ Error adding collateral: {e}[/red]")
        return False
