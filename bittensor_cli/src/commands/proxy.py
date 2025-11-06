import asyncio
from enum import Enum
from typing import TYPE_CHECKING

from rich.prompt import Confirm

from bittensor_cli.src.bittensor.utils import (
    print_extrinsic_id,
    json_console,
    console,
    err_console,
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
            return
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
