from typing import TYPE_CHECKING, Optional
import sys

from rich.prompt import Confirm, Prompt
from scalecodec import GenericCall

from bittensor_cli.src.bittensor.utils import (
    print_extrinsic_id,
    json_console,
    console,
    err_console,
    unlock_key,
)

if TYPE_CHECKING:
    from bittensor_cli.src.bittensor.subtensor_interface import SubtensorInterface
    from bittensor_wallet.bittensor_wallet import Wallet


# TODO when 3.10 support is dropped in Oct 2026, remove this
if sys.version_info >= (3, 11):
    from enum import StrEnum
else:
    from enum import Enum
    class StrEnum(str, Enum):
        pass


class ProxyType(StrEnum):
    Any = "Any"
    Owner = "Owner"
    NonCritical = "NonCritical"
    NonTransfer = "NonTransfer"
    Senate = "Senate"
    NonFungible = "NonFungible"
    Triumvirate = "Triumvirate"
    Governance = "Governance"
    Staking = "Staking"
    Registration = "Registration"
    Transfer = "Transfer"
    SmallTransfer = "SmallTransfer"
    RootWeights = "RootWeights"
    ChildKeys = "ChildKeys"
    SudoUncheckedSetCode = "SudoUncheckedSetCode"
    SwapHotkey = "SwapHotkey"
    SubnetLeaseBeneficiary = "SubnetLeaseBeneficiary"
    RootClaim = "RootClaim"


async def submit_proxy(
    subtensor: "SubtensorInterface",
    wallet: "Wallet",
    call: GenericCall,
    wait_for_inclusion: bool,
    wait_for_finalization: bool,
    period: int,
    json_output: bool,
    proxy: Optional[str] = None,
) -> None:
    success, msg, receipt = await subtensor.sign_and_send_extrinsic(
        call=call,
        wallet=wallet,
        wait_for_inclusion=wait_for_inclusion,
        wait_for_finalization=wait_for_finalization,
        era={"period": period},
        proxy=proxy,
    )
    if success:
        await print_extrinsic_id(receipt)
        if json_output:
            json_console.print_json(
                data={
                    "success": success,
                    "message": msg,
                    "extrinsic_id": await receipt.get_extrinsic_identifier(),
                }
            )
        else:
            console.print("Success!")  # TODO add more shit here

    else:
        if json_output:
            json_console.print_json(
                data={
                    "success": success,
                    "message": msg,
                    "extrinsic_id": None,
                }
            )
        else:
            err_console.print(f"Failure: {msg}")  # TODO add more shit here


async def create_proxy(
    subtensor: "SubtensorInterface",
    wallet: "Wallet",
    proxy_type: ProxyType,
    delay: int,
    idx: int,
    prompt: bool,
    wait_for_inclusion: bool,
    wait_for_finalization: bool,
    period: int,
    json_output: bool,
) -> tuple[bool, str, str, str]:
    """

    Args:
        subtensor:
        wallet:
        proxy_type:
        delay:
        idx:
        prompt:
        wait_for_inclusion:
        wait_for_finalization:
        period:
        json_output:

    Returns:
        tuple containing the following:
            should_update: True if the address book should be updated, False otherwise
            name: name of the new pure proxy for the address book
            address: SS58 address of the new pure proxy
            proxy_type: proxy type of the new pure proxy

    """
    if prompt:
        if not Confirm.ask(
            f"This will create a Pure Proxy of type {proxy_type.value}. Do you want to proceed?",
        ):
            return False, "", "", ""
    if not (ulw := unlock_key(wallet, print_out=not json_output)).success:
        if not json_output:
            err_console.print(ulw.message)
        else:
            json_console.print_json(
                data={
                    "success": ulw.success,
                    "message": ulw.message,
                    "extrinsic_id": None,
                }
            )
        return False, "", "", ""
    call = await subtensor.substrate.compose_call(
        call_module="Proxy",
        call_function="create_pure",
        call_params={"proxy_type": proxy_type.value, "delay": delay, "index": idx},
    )
    success, msg, receipt = await subtensor.sign_and_send_extrinsic(
        call=call,
        wallet=wallet,
        wait_for_inclusion=wait_for_inclusion,
        wait_for_finalization=wait_for_finalization,
        era={"period": period},
    )
    if success:
        await print_extrinsic_id(receipt)
        created_pure = None
        created_spawner = None
        created_proxy_type = None
        for event in await receipt.triggered_events:
            if event["event_id"] == "PureCreated":
                attrs = event["attributes"]
                created_pure = attrs["pure"]
                created_spawner = attrs["who"]
                created_proxy_type = getattr(ProxyType, attrs["proxy_type"])
        arg_start = "`" if json_output else "[blue]"
        arg_end = "`" if json_output else "[/blue]"
        msg = f"Created pure '{created_pure}' from spawner '{created_spawner}' with proxy type '{created_proxy_type.value}'."
        console.print(msg)
        if not prompt:
            console.print(
                f" You can add this to your config with {arg_start}"
                f"btcli config add-proxy "
                f"--name <PROXY_NAME> --address {created_pure} --proxy-type {created_proxy_type.value}"
                f"{arg_end}"
            )
        else:
            if Confirm.ask("Would you like to add this to your address book?"):
                proxy_name = Prompt.ask("Name this proxy")
                return True, proxy_name, created_pure, created_proxy_type

        if json_output:
            json_console.print_json(
                data={
                    "success": success,
                    "message": msg,
                    "extrinsic_id": await receipt.get_extrinsic_identifier(),
                }
            )

    else:
        if json_output:
            json_console.print_json(
                data={
                    "success": success,
                    "message": msg,
                    "extrinsic_id": None,
                }
            )
        else:
            err_console.print(f"Failure: {msg}")  # TODO add more shit here
    return False, "", "", ""


async def remove_proxy(
    subtensor: "SubtensorInterface",
    wallet: "Wallet",
    proxy_type: ProxyType,
    delegate: str,
    delay: int,
    prompt: bool,
    wait_for_inclusion: bool,
    wait_for_finalization: bool,
    period: int,
    json_output: bool,
) -> None:
    if prompt:
        if not Confirm.ask(
            f"This will remove a proxy of type {proxy_type.value} for delegate {delegate}."
            f"Do you want to proceed?"
        ):
            return None
    if not (ulw := unlock_key(wallet, print_out=not json_output)).success:
        if not json_output:
            err_console.print(ulw.message)
        else:
            json_console.print_json(
                data={
                    "success": ulw.success,
                    "message": ulw.message,
                    "extrinsic_id": None,
                }
            )
        return None
    call = await subtensor.substrate.compose_call(
        call_module="Proxy",
        call_function="remove_proxy",
        call_params={
            "proxy_type": proxy_type.value,
            "delay": delay,
            "delegate": delegate,
        },
    )
    return await submit_proxy(
        subtensor=subtensor,
        wallet=wallet,
        call=call,
        wait_for_inclusion=wait_for_inclusion,
        wait_for_finalization=wait_for_finalization,
        period=period,
        json_output=json_output,
    )


async def add_proxy(
    subtensor: "SubtensorInterface",
    wallet: "Wallet",
    proxy_type: ProxyType,
    delegate: str,
    delay: int,
    prompt: bool,
    wait_for_inclusion: bool,
    wait_for_finalization: bool,
    period: int,
    json_output: bool,
):
    if prompt:
        if not Confirm.ask(
            f"This will add a proxy of type {proxy_type.value} for delegate {delegate}."
            f"Do you want to proceed?"
        ):
            return None
    if not (ulw := unlock_key(wallet, print_out=not json_output)).success:
        if not json_output:
            err_console.print(ulw.message)
        else:
            json_console.print_json(
                data={
                    "success": ulw.success,
                    "message": ulw.message,
                    "extrinsic_id": None,
                }
            )
        return None
    call = await subtensor.substrate.compose_call(
        call_module="Proxy",
        call_function="add_proxy",
        call_params={
            "proxy_type": proxy_type.value,
            "delay": delay,
            "delegate": delegate,
        },
    )
    return await submit_proxy(
        subtensor=subtensor,
        wallet=wallet,
        call=call,
        wait_for_inclusion=wait_for_inclusion,
        wait_for_finalization=wait_for_finalization,
        period=period,
        json_output=json_output,
    )


async def kill_proxy(
    subtensor: "SubtensorInterface",
    wallet: "Wallet",
    proxy_type: ProxyType,
    height: int,
    ext_index: int,
    spawner: Optional[str],
    idx: int,
    proxy: Optional[str],
    prompt: bool,
    wait_for_inclusion: bool,
    wait_for_finalization: bool,
    period: int,
    json_output: bool,
) -> None:
    if prompt:
        confirmation = Prompt.ask(
            f"This will kill a Pure Proxy account of type {proxy_type.value}.\n"
            f"[red]All access to this account will be lost. Any funds held in it will be inaccessible.[/red]"
            f"To proceed, enter [red]KILL[/red]"
        )
        if confirmation != "KILL":
            err_console.print("Invalid input. Exiting.")
            return None
    if not (ulw := unlock_key(wallet, print_out=not json_output)).success:
        if not json_output:
            err_console.print(ulw.message)
        else:
            json_console.print_json(
                data={
                    "success": ulw.success,
                    "message": ulw.message,
                    "extrinsic_id": None,
                }
            )
        return None
    spawner = spawner or wallet.coldkeypub.ss58_address
    call = await subtensor.substrate.compose_call(
        call_module="Proxy",
        call_function="kill_pure",
        call_params={
            "proxy_type": proxy_type.value,
            "index": idx,
            "height": height,
            "ext_index": ext_index,
            "spawner": spawner,
        },
    )

    return await submit_proxy(
        subtensor=subtensor,
        wallet=wallet,
        call=call,
        wait_for_inclusion=wait_for_inclusion,
        wait_for_finalization=wait_for_finalization,
        period=period,
        json_output=json_output,
        proxy=proxy,
    )
