"""
Proxy Add Command - Add a proxy delegate to an account.

This command allows adding a proxy account that can execute permitted
calls on behalf of the real account.
"""

import asyncio
from typing import TYPE_CHECKING, Optional

from rich.prompt import Confirm
from async_substrate_interface.errors import SubstrateRequestException

from bittensor_cli.src.bittensor.balances import Balance
from bittensor_cli.src.bittensor.utils import (
    console,
    err_console,
    format_error_message,
    is_valid_ss58_address,
    print_error,
    print_verbose,
    unlock_key,
)
from bittensor_wallet import Wallet

if TYPE_CHECKING:
    from bittensor_cli.src.bittensor.subtensor_interface import SubtensorInterface


# Proxy types supported by the Bittensor chain
PROXY_TYPES = [
    "Any",
    "NonTransfer",
    "Governance",
    "Staking",
    "Registration",
    "SenateVoting",
    "Transfer",
    "SmallTransfer",
    "RootWeights",
    "ChildKeys",
    "SudoUncheckedSetCode",
]


async def proxy_add(
    wallet: Wallet,
    subtensor: "SubtensorInterface",
    delegate: str,
    proxy_type: str,
    delay: int = 0,
    prompt: bool = True,
    era: int = 64,
) -> bool:
    """
    Add a proxy delegate to the wallet's account.

    Args:
        wallet: The wallet object (will be the 'real' account)
        subtensor: SubtensorInterface object
        delegate: SS58 address of the delegate account
        proxy_type: Type of proxy permissions to grant
        delay: Block delay before proxy can execute (0 for immediate)
        prompt: Whether to prompt for confirmation
        era: Blocks for which the transaction should be valid

    Returns:
        bool: True if proxy was added successfully, False otherwise
    """

    async def get_add_proxy_fee() -> Balance:
        """Calculate the transaction fee for adding a proxy."""
        call = await subtensor.substrate.compose_call(
            call_module="Proxy",
            call_function="add_proxy",
            call_params={
                "delegate": delegate,
                "proxy_type": proxy_type,
                "delay": delay,
            },
        )
        try:
            payment_info = await subtensor.substrate.get_payment_info(
                call=call, keypair=wallet.coldkeypub
            )
        except SubstrateRequestException as e:
            payment_info = {"partial_fee": int(2e7)}  # assume 0.02 Tao
            err_console.print(
                f":cross_mark: [red]Failed to get payment info[/red]:[bold white]\n"
                f"  {format_error_message(e)}[/bold white]\n"
                f"  Defaulting to default fee: {Balance.from_rao(payment_info['partial_fee'])}"
            )
        return Balance.from_rao(payment_info["partial_fee"])

    async def do_add_proxy() -> tuple[bool, str, str]:
        """Execute the add_proxy extrinsic."""
        call = await subtensor.substrate.compose_call(
            call_module="Proxy",
            call_function="add_proxy",
            call_params={
                "delegate": delegate,
                "proxy_type": proxy_type,
                "delay": delay,
            },
        )
        extrinsic = await subtensor.substrate.create_signed_extrinsic(
            call=call, keypair=wallet.coldkey, era={"period": era}
        )
        response = await subtensor.substrate.submit_extrinsic(
            extrinsic,
            wait_for_inclusion=True,
            wait_for_finalization=False,
        )

        if await response.is_success:
            return True, response.block_hash, ""
        else:
            return False, "", format_error_message(await response.error_message)

    # Validate delegate address
    if not is_valid_ss58_address(delegate):
        err_console.print(
            f":cross_mark: [red]Invalid delegate SS58 address[/red]:[bold white]\n  {delegate}[/bold white]"
        )
        return False

    # Validate proxy type
    if proxy_type not in PROXY_TYPES:
        err_console.print(
            f":cross_mark: [red]Invalid proxy type[/red]: {proxy_type}\n"
            f"  Valid types: {', '.join(PROXY_TYPES)}"
        )
        return False

    console.print(f"[dark_orange]Adding proxy on network: {subtensor.network}")

    # Unlock wallet coldkey
    if not unlock_key(wallet).success:
        return False

    # Get and display fee
    with console.status("[bold green]Calculating transaction fee..."):
        fee = await get_add_proxy_fee()

    console.print(
        f"\n[bold]Add Proxy Details:[/bold]\n"
        f"  Real Account: [cyan]{wallet.coldkeypub.ss58_address}[/cyan]\n"
        f"  Delegate: [cyan]{delegate}[/cyan]\n"
        f"  Proxy Type: [yellow]{proxy_type}[/yellow]\n"
        f"  Delay: [yellow]{delay}[/yellow] blocks\n"
        f"  Estimated Fee: [green]{fee}[/green]\n"
    )

    if prompt:
        if not Confirm.ask("Do you want to proceed?"):
            console.print("[yellow]Cancelled.[/yellow]")
            return False

    with console.status("[bold green]Adding proxy..."):
        success, block_hash, error_msg = await do_add_proxy()

    if success:
        console.print(
            f":white_check_mark: [green]Proxy added successfully![/green]\n"
            f"  Block Hash: [cyan]{block_hash}[/cyan]"
        )
        return True
    else:
        err_console.print(
            f":cross_mark: [red]Failed to add proxy[/red]:\n  {error_msg}"
        )
        return False
