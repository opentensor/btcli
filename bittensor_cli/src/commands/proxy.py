from typing import TYPE_CHECKING, Optional
import sys

from rich.prompt import Confirm, Prompt, FloatPrompt, IntPrompt
from scalecodec import GenericCall, ScaleBytes

from bittensor_cli.src import COLORS
from bittensor_cli.src.bittensor.balances import Balance
from bittensor_cli.src.bittensor.utils import (
    print_extrinsic_id,
    json_console,
    console,
    err_console,
    unlock_key,
    ProxyAddressBook,
    is_valid_ss58_address_prompt,
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


# TODO add announce with also --reject and --remove


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
        if delay > 0:
            if not Confirm.ask(
                f"By adding a non-zero delay ({delay}), all proxy calls must be announced "
                f"{delay} blocks before they will be able to be made. Continue?"
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
        msg = (
            f"Created pure '{created_pure}' "
            f"from spawner '{created_spawner}' "
            f"with proxy type '{created_proxy_type.value}' "
            f"with delay {delay}."
        )
        console.print(msg)
        if not prompt:
            console.print(
                f" You can add this to your config with {arg_start}"
                f"btcli config add-proxy "
                f"--name <PROXY_NAME> --address {created_pure} --proxy-type {created_proxy_type.value} "
                f"--delay {delay} --spawner {created_spawner}"
                f"{arg_end}"
            )
        else:
            if Confirm.ask("Would you like to add this to your address book?"):
                proxy_name = Prompt.ask("Name this proxy")
                note = Prompt.ask("[Optional] Add a note for this proxy", default="")
                with ProxyAddressBook.get_db() as (conn, cursor):
                    ProxyAddressBook.add_entry(
                        conn,
                        cursor,
                        name=proxy_name,
                        ss58_address=created_pure,
                        delay=delay,
                        proxy_type=created_proxy_type.value,
                        note=note,
                        spawner=created_spawner,
                    )
                console.print(
                    f"Added to Proxy Address Book.\n"
                    f"Show this information with [{COLORS.G.ARG}]btcli config proxies[/{COLORS.G.ARG}]"
                )
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
    # TODO add to address book
    if prompt:
        if not Confirm.ask(
            f"This will add a proxy of type {proxy_type.value} for delegate {delegate}."
            f"Do you want to proceed?"
        ):
            return None
        if delay > 0:
            if not Confirm.ask(
                f"By adding a non-zero delay ({delay}), all proxy calls must be announced "
                f"{delay} blocks before they will be able to be made. Continue?"
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
    success, msg, receipt = await subtensor.sign_and_send_extrinsic(
        call=call,
        wallet=wallet,
        wait_for_inclusion=wait_for_inclusion,
        wait_for_finalization=wait_for_finalization,
        era={"period": period},
    )
    if success:
        await print_extrinsic_id(receipt)
        delegatee = None
        delegator = None
        created_proxy_type = None
        for event in await receipt.triggered_events:
            if event["event_id"] == "PureCreated":
                attrs = event["attributes"]
                delegatee = attrs["delegatee"]
                delegator = attrs["delegator"]
                created_proxy_type = getattr(ProxyType, attrs["proxy_type"])
        arg_start = "`" if json_output else "[blue]"
        arg_end = "`" if json_output else "[/blue]"
        msg = (
            f"Added proxy delegatee '{delegatee}' "
            f"from delegator '{delegator}' "
            f"with proxy type '{created_proxy_type.value}' "
            f"with delay {delay}."
        )
        console.print(msg)
        if not prompt:
            console.print(
                f" You can add this to your config with {arg_start}"
                f"btcli config add-proxy "
                f"--name <PROXY_NAME> --address {delegatee} --proxy-type {created_proxy_type.value} --delegator "
                f"{delegator} --delay {delay}"
                f"{arg_end}"
            )
        else:
            if Confirm.ask("Would you like to add this to your address book?"):
                proxy_name = Prompt.ask("Name this proxy")
                note = Prompt.ask("[Optional] Add a note for this proxy", default="")
                with ProxyAddressBook.get_db() as (conn, cursor):
                    ProxyAddressBook.add_entry(
                        conn,
                        cursor,
                        name=proxy_name,
                        # TODO verify this is correct (it's opposite of create pure)
                        ss58_address=delegator,
                        delay=delay,
                        proxy_type=created_proxy_type.value,
                        note=note,
                        spawner=delegatee,
                    )
                console.print(
                    f"Added to Proxy Address Book.\n"
                    f"Show this information with [{COLORS.G.ARG}]btcli config proxies[/{COLORS.G.ARG}]"
                )

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
    return None


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


async def execute_announced(
    subtensor: "SubtensorInterface",
    wallet: "Wallet",
    delegate: str,
    real: str,
    period: int,
    call_hex: Optional[str],
    delay: int = 0,
    created_block: Optional[int] = None,
    prompt: bool = True,
    wait_for_inclusion: bool = False,
    wait_for_finalization: bool = False,
):
    if prompt and created_block is not None:
        current_block = await subtensor.substrate.get_block_number()
        if current_block - delay > created_block:
            if not Confirm.ask(
                f"The delay for this account is set to {delay} blocks, but the call was created"
                f" at block {created_block}. It is currently only {current_block}. The call will likely fail."
                f" Do you want to proceed?"
            ):
                return None

    if call_hex is None:
        if not prompt:
            err_console.print(
                f":cross_mark:[red]You have not provided a call, and are using"
                f" [{COLORS.G.ARG}]--no-prompt[/{COLORS.G.ARG}], so we are unable to request"
                f"the information to craft this call."
            )
            return None
        else:
            call_args = {}
            failure_ = f"Instead create the call using btcli commands with [{COLORS.G.ARG}]--announce-only[/{COLORS.G.ARG}]"
            block_hash = await subtensor.substrate.get_chain_head()
            fns = await subtensor.substrate.get_metadata_call_functions(
                block_hash=block_hash
            )
            module = Prompt.ask(
                "Enter the module name for the call",
                choices=list(fns.keys()),
                show_choices=True,
            )
            call_fn = Prompt.ask(
                "Enter the call function for the call",
                choices=list(fns[module].keys()),
                show_choices=True,
            )
            for arg in fns[module][call_fn].keys():
                type_name = fns[module][call_fn][arg]["typeName"]
                if type_name == "AccountIdLookupOf<T>":
                    value = is_valid_ss58_address_prompt(
                        f"Enter the SS58 Address for {arg}"
                    )
                elif type_name == "T::Balance":
                    value = FloatPrompt.ask(f"Enter the amount of Tao for {arg}")
                    value = Balance.from_tao(value)
                elif "RuntimeCall" in type_name:
                    err_console.print(
                        f":cross_mark:[red]Unable to craft a Call Type for arg {arg}. {failure_}"
                    )
                    return None
                elif type_name == "NetUid":
                    value = IntPrompt.ask(f"Enter the netuid for {arg}")
                elif type_name in ("u16", "u64"):
                    value = IntPrompt.ask(f"Enter the int value for {arg}")
                elif type_name == "bool":
                    value = Prompt.ask(
                        f"Enter the bool value for {arg}",
                        choices=["True", "False"],
                        show_choices=True,
                    )
                    if value == "True":
                        value = True
                    else:
                        value = False
                else:
                    err_console.print(
                        f":cross_mark:[red]Unrecogized type name {type_name}. {failure_}"
                    )
                    return None
                call_args[arg] = value
            inner_call = await subtensor.substrate.compose_call(
                module,
                call_fn,
                call_params=call_args,
                block_hash=block_hash,
            )
    else:
        runtime = await subtensor.substrate.init_runtime(block_id=created_block)
        inner_call = GenericCall(
            data=ScaleBytes(data=bytes.fromhex(call_hex)), metadata=runtime.metadata
        )
        inner_call.process()

    announced_call = await subtensor.substrate.compose_call(
        "Proxy",
        "proxy_announced",
        {
            "delegate": delegate,
            "real": real,
            "call": inner_call,
            "force_proxy_type": None,
        },
    )
    return await subtensor.sign_and_send_extrinsic(
        call=announced_call,
        wallet=wallet,
        wait_for_inclusion=wait_for_inclusion,
        wait_for_finalization=wait_for_finalization,
        era={"period": period},
    )
