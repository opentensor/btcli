import asyncio
from typing import TYPE_CHECKING, Optional

from bittensor_wallet import Wallet
from rich.prompt import Confirm
from rich.table import Table, Column

from src import Constants, DelegatesDetails
from src.bittensor.balances import Balance
from src.bittensor.chain_data import SubnetInfo
from src.commands.wallets import set_id_prompts, set_id
from src.utils import (
    console,
    err_console,
    get_delegates_details_from_github,
    millify,
    RAO_PER_TAO,
)

if TYPE_CHECKING:
    from src.subtensor_interface import SubtensorInterface


# helpers and extrinsics


async def register_subnetwork_extrinsic(
    subtensor: "SubtensorInterface",
    wallet: Wallet,
    wait_for_inclusion: bool = False,
    wait_for_finalization: bool = True,
    prompt: bool = False,
) -> bool:
    """Registers a new subnetwork.

        wallet (bittensor.wallet):
            bittensor wallet object.
        wait_for_inclusion (bool):
            If set, waits for the extrinsic to enter a block before returning ``true``, or returns ``false`` if the extrinsic fails to enter the block within the timeout.
        wait_for_finalization (bool):
            If set, waits for the extrinsic to be finalized on the chain before returning ``true``, or returns ``false`` if the extrinsic fails to be finalized within the timeout.
        prompt (bool):
            If true, the call waits for confirmation from the user before proceeding.
    Returns:
        success (bool):
            Flag is ``true`` if extrinsic was finalized or included in the block.
            If we did not wait for finalization / inclusion, the response is ``true``.
    """

    def _find_event_attributes_in_extrinsic_receipt(response_, event_name: str) -> list:
        """
        Searches for the attributes of a specified event within an extrinsic receipt.

        :param response_: (substrateinterface.base.ExtrinsicReceipt): The receipt of the extrinsic to be searched.
        :param event_name: The name of the event to search for.

        :return: A list of attributes for the specified event. Returns [-1] if the event is not found.
        """
        for event in response_.triggered_events:
            # Access the event details
            event_details = event.value["event"]
            # Check if the event_id is 'NetworkAdded'
            if event_details["event_id"] == event_name:
                # Once found, you can access the attributes of the event_name
                return event_details["attributes"]
        return [-1]

    your_balance_ = await subtensor.get_balance(wallet.coldkeypub.ss58_address)
    your_balance = your_balance_[wallet.coldkeypub.ss58_address]
    burn_cost = await lock_cost(subtensor)
    if burn_cost > your_balance:
        err_console.print(
            f"Your balance of: [green]{your_balance}[/green] is not enough to pay the subnet lock cost of: "
            f"[green]{burn_cost}[/green]"
        )
        return False

    if prompt:
        console.print(f"Your balance is: [green]{your_balance}[/green]")
        if not Confirm.ask(
            f"Do you want to register a subnet for [green]{ burn_cost }[/green]?"
        ):
            return False

    wallet.unlock_coldkey()

    with console.status(":satellite: Registering subnet..."):
        with subtensor.substrate as substrate:
            # create extrinsic call
            call = await substrate.compose_call(
                call_module="SubtensorModule",
                call_function="register_network",
                call_params={"immunity_period": 0, "reg_allowed": True},
            )
            extrinsic = await substrate.create_signed_extrinsic(
                call=call, keypair=wallet.coldkey
            )
            response = await substrate.submit_extrinsic(
                extrinsic,
                wait_for_inclusion=wait_for_inclusion,
                wait_for_finalization=wait_for_finalization,
            )

            # We only wait here if we expect finalization.
            if not wait_for_finalization and not wait_for_inclusion:
                return True

            response.process_events()
            if not response.is_success:
                err_console.print(f":cross_mark: [red]Failed[/red]: {err_msg}")
                await asyncio.sleep(0.5)
                return False

            # Successful registration, final check for membership
            else:
                attributes = _find_event_attributes_in_extrinsic_receipt(
                    response, "NetworkAdded"
                )
                console.print(
                    f":white_heavy_check_mark: [green]Registered subnetwork with netuid: {attributes[0]}[/green]"
                )
                return True


# commands


async def subnets_list(subtensor: "SubtensorInterface"):
    """List all subnet netuids in the network."""

    async def _get_all_subnets_info():
        json_body = await subtensor.substrate.rpc_request(
            method="subnetInfo_getSubnetsInfo",  # custom rpc method
            params=[],
        )

        return (
            SubnetInfo.list_from_vec_u8(result)
            if (result := json_body.get("result"))
            else []
        )

    subnets: list[SubnetInfo]
    delegate_info: dict[str, DelegatesDetails]

    subnets, delegate_info = await asyncio.gather(
        _get_all_subnets_info(),
        get_delegates_details_from_github(url=Constants.delegates_detail_url),
    )

    if not subnets:
        err_console.print("[red]No subnets found[/red]")
        return

    rows = []
    total_neurons = 0

    for subnet in subnets:
        total_neurons += subnet.max_n
        rows.append(
            (
                str(subnet.netuid),
                str(subnet.subnetwork_n),
                str(millify(subnet.max_n)),
                f"{subnet.emission_value / RAO_PER_TAO * 100:0.2f}%",
                str(subnet.tempo),
                f"{subnet.burn!s:8.8}",
                str(millify(subnet.difficulty)),
                f"{delegate_info[subnet.owner_ss58].name if subnet.owner_ss58 in delegate_info else subnet.owner_ss58}",
            )
        )
    table = Table(
        Column(
            "[overline white]NETUID",
            str(len(subnets)),
            footer_style="overline white",
            style="bold green",
            justify="center",
        ),
        Column(
            "[overline white]N",
            str(total_neurons),
            footer_style="overline white",
            style="green",
            justify="center",
        ),
        Column("[overline white]MAX_N", style="white", justify="center"),
        Column("[overline white]EMISSION", style="white", justify="center"),
        Column("[overline white]TEMPO", style="white", justify="center"),
        Column("[overline white]RECYCLE", style="white", justify="center"),
        Column("[overline white]POW", style="white", justify="center"),
        Column("[overline white]SUDO", style="white"),
        title=f"[white]Subnets - {subtensor.network}",
        show_footer=True,
        width=None,
        pad_edge=True,
        box=None,
        show_edge=True,
    )
    for row in rows:
        table.add_row(*row)
    console.print(table)


async def lock_cost(subtensor: "SubtensorInterface") -> Optional[Balance]:
    """View locking cost of creating a new subnetwork"""
    with console.status(f":satellite:Retrieving lock cost from {subtensor.network}..."):
        lc = await subtensor.query_runtime_api(
            runtime_api="SubnetRegistrationRuntimeApi",
            method="get_network_registration_cost",
            params=[],
        )
    if lc:
        lock_cost_ = Balance(lc)
        console.print(f"Subnet lock cost: [green]{lock_cost_}[/green]")
        return lock_cost_
    else:
        err_console.print("Subnet lock cost: [red]Failed to get subnet lock cost[/red]")
        return None


async def create(wallet: Wallet, subtensor: "SubtensorInterface"):
    """Register a subnetwork"""

    # Call register command.
    success = await register_subnetwork_extrinsic(subtensor, wallet)
    if success and not False:  # TODO no-prompt
        # Prompt for user to set identity.
        do_set_identity = Confirm.ask(
            "Subnetwork registered successfully. Would you like to set your identity?"
        )

        if do_set_identity:
            id_prompts = set_id_prompts()
            await set_id(wallet, subtensor, *id_prompts)
