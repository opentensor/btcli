"""
Extrinsics for serving operations (axon management).
"""
import typing
from typing import Optional

from bittensor_wallet import Wallet
from rich.prompt import Confirm

from bittensor_cli.src.bittensor.utils import (
    console,
    err_console,
    format_error_message,
    unlock_key,
    print_extrinsic_id,
)
from bittensor_cli.src.bittensor.networking import int_to_ip

if typing.TYPE_CHECKING:
    from bittensor_cli.src.bittensor.subtensor_interface import SubtensorInterface


def ip_to_int(ip_str: str) -> int:
    """
    Converts an IP address string to its integer representation.
    
    Args:
        ip_str: IP address string (e.g., "192.168.1.1")
        
    Returns:
        Integer representation of the IP address
    """
    import netaddr
    return int(netaddr.IPAddress(ip_str))


async def reset_axon_extrinsic(
    subtensor: "SubtensorInterface",
    wallet: Wallet,
    netuid: int,
    prompt: bool = False,
    wait_for_inclusion: bool = True,
    wait_for_finalization: bool = False,
) -> tuple[bool, str]:
    """
    Resets the axon information for a neuron on the network.
    
    This effectively removes the serving endpoint by setting the IP to 0.0.0.0
    and port to 0, indicating the neuron is no longer serving.
    
    Args:
        subtensor: The subtensor interface to use for the extrinsic
        wallet: The wallet containing the hotkey to reset the axon for
        netuid: The network UID where the neuron is registered
        prompt: Whether to prompt for confirmation before submitting
        wait_for_inclusion: Whether to wait for the extrinsic to be included in a block
        wait_for_finalization: Whether to wait for the extrinsic to be finalized
        
    Returns:
        Tuple of (success: bool, message: str)
    """
    # Unlock the hotkey
    if not unlock_key(wallet, hotkey=True).success:
        return False, "Failed to unlock hotkey"
    
    # Prompt for confirmation if requested
    if prompt:
        if not Confirm.ask(
            f"Do you want to reset the axon for hotkey [bold]{wallet.hotkey.ss58_address}[/bold] "
            f"on netuid [bold]{netuid}[/bold]?"
        ):
            return False, "User cancelled the operation"
    
    with console.status(
        f":satellite: Resetting axon on [white]netuid {netuid}[/white]..."
    ):
        try:
            # Compose the serve_axon call with reset values (IP: 0.0.0.0, port: 0)
            call = await subtensor.substrate.compose_call(
                call_module="SubtensorModule",
                call_function="serve_axon",
                call_params={
                    "netuid": netuid,
                    "version": 0,
                    "ip": ip_to_int("0.0.0.0"),
                    "port": 0,
                    "ip_type": 4,  # IPv4
                    "protocol": 4,
                    "placeholder1": 0,
                    "placeholder2": 0,
                },
            )
            
            # Sign and submit the extrinsic
            success, error_msg, response = await subtensor.sign_and_send_extrinsic(
                call=call,
                wallet=wallet,
                wait_for_inclusion=wait_for_inclusion,
                wait_for_finalization=wait_for_finalization,
            )
            
            if success:
                if wait_for_inclusion or wait_for_finalization:
                    await print_extrinsic_id(response)
                console.print(":white_heavy_check_mark: [green]Axon reset successfully[/green]")
                return True, "Axon reset successfully"
            else:
                err_console.print(f":cross_mark: [red]Failed to reset axon: {error_msg}[/red]")
                return False, error_msg
                
        except Exception as e:
            error_message = format_error_message(e)
            err_console.print(f":cross_mark: [red]Failed to reset axon: {error_message}[/red]")
            return False, error_message


async def set_axon_extrinsic(
    subtensor: "SubtensorInterface",
    wallet: Wallet,
    netuid: int,
    ip: str,
    port: int,
    ip_type: int = 4,
    protocol: int = 4,
    prompt: bool = False,
    wait_for_inclusion: bool = True,
    wait_for_finalization: bool = False,
) -> tuple[bool, str]:
    """
    Sets the axon information for a neuron on the network.
    
    This configures the serving endpoint for a neuron by specifying its IP address
    and port, allowing other neurons to connect to it.
    
    Args:
        subtensor: The subtensor interface to use for the extrinsic
        wallet: The wallet containing the hotkey to set the axon for
        netuid: The network UID where the neuron is registered
        ip: The IP address to set (e.g., "192.168.1.1")
        port: The port number to set
        ip_type: IP type (4 for IPv4, 6 for IPv6)
        protocol: Protocol version (default: 4)
        prompt: Whether to prompt for confirmation before submitting
        wait_for_inclusion: Whether to wait for the extrinsic to be included in a block
        wait_for_finalization: Whether to wait for the extrinsic to be finalized
        
    Returns:
        Tuple of (success: bool, message: str)
    """
    # Validate port
    if not (0 <= port <= 65535):
        return False, f"Invalid port number: {port}. Must be between 0 and 65535."
    
    # Validate IP address
    try:
        ip_int = ip_to_int(ip)
    except Exception as e:
        return False, f"Invalid IP address: {ip}. Error: {str(e)}"
    
    # Unlock the hotkey
    if not unlock_key(wallet, hotkey=True).success:
        return False, "Failed to unlock hotkey"
    
    # Prompt for confirmation if requested
    if prompt:
        if not Confirm.ask(
            f"Do you want to set the axon for hotkey [bold]{wallet.hotkey.ss58_address}[/bold] "
            f"on netuid [bold]{netuid}[/bold] to [bold]{ip}:{port}[/bold]?"
        ):
            return False, "User cancelled the operation"
    
    with console.status(
        f":satellite: Setting axon on [white]netuid {netuid}[/white] to [white]{ip}:{port}[/white]..."
    ):
        try:
            # Compose the serve_axon call
            call = await subtensor.substrate.compose_call(
                call_module="SubtensorModule",
                call_function="serve_axon",
                call_params={
                    "netuid": netuid,
                    "version": 0,
                    "ip": ip_int,
                    "port": port,
                    "ip_type": ip_type,
                    "protocol": protocol,
                    "placeholder1": 0,
                    "placeholder2": 0,
                },
            )
            
            # Sign and submit the extrinsic
            success, error_msg, response = await subtensor.sign_and_send_extrinsic(
                call=call,
                wallet=wallet,
                wait_for_inclusion=wait_for_inclusion,
                wait_for_finalization=wait_for_finalization,
            )
            
            if success:
                if wait_for_inclusion or wait_for_finalization:
                    await print_extrinsic_id(response)
                console.print(
                    f":white_heavy_check_mark: [green]Axon set successfully to {ip}:{port}[/green]"
                )
                return True, f"Axon set successfully to {ip}:{port}"
            else:
                err_console.print(f":cross_mark: [red]Failed to set axon: {error_msg}[/red]")
                return False, error_msg
                
        except Exception as e:
            error_message = format_error_message(e)
            err_console.print(f":cross_mark: [red]Failed to set axon: {error_message}[/red]")
            return False, error_message
