from enum import Enum
from typing import TYPE_CHECKING

from rich.prompt import Confirm
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


class ProxyType(str, Enum):
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
) -> None:
    success, msg, receipt = await subtensor.sign_and_send_extrinsic(
        call=call,
        wallet=wallet,
        wait_for_inclusion=wait_for_inclusion,
        wait_for_finalization=wait_for_finalization,
        era={"period": period},
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
) -> None:
    if prompt:
        if not Confirm.ask(
            f"This will create a Pure Proxy of type {proxy_type.value}. Do you want to proceed?",
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
        call_function="create_pure",
        call_params={"proxy_type": proxy_type.value, "delay": delay, "index": idx},
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
    idx: int,
    prompt: bool,
    wait_for_inclusion: bool,
    wait_for_finalization: bool,
    period: int,
    json_output: bool,
) -> None:
    if prompt:
        if not Confirm.ask(
            f"This will kill a Pure Proxy of type {proxy_type.value}. Do you want to proceed?",
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
    spawner = wallet.coldkey.ss58_address
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
    )
