import asyncio
import json
from typing import TYPE_CHECKING, Optional

from bittensor_wallet import Wallet
from rich.prompt import Confirm
from rich.table import Table, Column

from src import Constants, DelegatesDetails
from src.bittensor.balances import Balance
from src.bittensor.chain_data import SubnetInfo
from src.bittensor.minigraph import MiniGraph
from src.bittensor.extrinsics.registration import register_extrinsic
from src.commands.root import burned_register_extrinsic
from src.commands.wallets import set_id_prompts, set_id
from src.utils import (
    console,
    err_console,
    get_delegates_details_from_github,
    millify,
    RAO_PER_TAO,
    format_error_message,
    render_table,
    create_table,
    update_metadata_table,
    get_metadata_table,
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
            f"Do you want to register a subnet for [green]{burn_cost}[/green]?"
        ):
            return False

    wallet.unlock_coldkey()

    with console.status(":satellite: Registering subnet..."):
        substrate = subtensor.substrate
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
            err_console.print(
                f":cross_mark: [red]Failed[/red]: {format_error_message(response.error_message)}"
            )
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

    table_width = console.width - 20

    table = Table(
        title=f"[bold magenta]Subnets - {subtensor.network}[/bold magenta]",
        show_footer=True,
        show_edge=False,
        header_style="bold white",
        border_style="bright_black",
        style="bold",
        title_style="bold white",
        title_justify="center",
        show_lines=False,
        expand=True,
        width=table_width,
        pad_edge=True,
    )

    table.add_column(
        "[bold white]NETUID",
        footer=f"[white]{len(subnets)}[/white]",
        style="white",
        justify="center",
    )
    table.add_column(
        "[bold white]N",
        footer=f"[white]{total_neurons}[/white]",
        style="bright_cyan",
        justify="center",
    )
    table.add_column("[bold white]MAX_N", style="bright_yellow", justify="center")
    table.add_column("[bold white]EMISSION", style="bright_yellow", justify="center")
    table.add_column("[bold white]TEMPO", style="magenta", justify="center")
    table.add_column("[bold white]RECYCLE", style="bright_red", justify="center")
    table.add_column("[bold white]POW", style="medium_purple", justify="center")
    table.add_column("[bold white]SUDO", style="bright_magenta", justify="center")

    for row in rows:
        table.add_row(*row)

    console.print(table)
    console.print(
        """
Description:
    The table displays the list of subnets registered in the Bittensor network.
        - NETIUID: The network identifier of the subnet.
        - N: The current UIDs registered to the network. 
        - MAX_N: The total UIDs allowed on the network.
        - EMISSION: The emission accrued by this subnet in the network.
        - TEMPO: A duration of a number of blocks. Several subnet events occur at the end of every tempo period.
        - RECYCLE: Cost to register to the subnet.
        - POW: Proof of work metric of the subnet.
        - SUDO: Owner's identity.
"""
    )


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


async def pow_register(
    wallet: Wallet,
    subtensor: "SubtensorInterface",
    netuid,
    processors,
    update_interval,
    output_in_place,
    verbose,
    use_cuda,
    dev_id,
    threads_per_block,
):
    """Register neuron."""

    # Verify subnet exists
    if not await subtensor.subnet_exists(netuid=netuid):
        err_console.print(f"[red]Subnet {netuid} does not exist[/red]")
        return

    await register_extrinsic(
        subtensor,
        wallet=wallet,
        netuid=netuid,
        prompt=True,
        tpb=threads_per_block,
        update_interval=update_interval,
        num_processes=processors,
        cuda=use_cuda,
        dev_id=dev_id,
        output_in_place=output_in_place,
        log_verbose=verbose,
    )


async def register(wallet: Wallet, subtensor: "SubtensorInterface", netuid: int):
    """Register neuron by recycling some TAO."""

    # Verify subnet exists
    block_hash = await subtensor.substrate.get_chain_head()
    if not await subtensor.subnet_exists(netuid=netuid, block_hash=block_hash):
        err_console.print(f"[red]Subnet {netuid} does not exist[/red]")
        return

    # Check current recycle amount
    current_recycle_, balance_ = await asyncio.gather(
        subtensor.get_hyperparameter(
            param_name="Burn", netuid=netuid, block_hash=block_hash
        ),
        subtensor.get_balance(wallet.coldkeypub.ss58_address, block_hash=block_hash),
    )
    current_recycle = (
        Balance.from_rao(int(current_recycle_)) if current_recycle_ else Balance(0)
    )
    balance = balance_[wallet.coldkeypub.ss58_address]

    # Check balance is sufficient
    if balance < current_recycle:
        err_console.print(
            f"[red]Insufficient balance {balance} to register neuron. Current recycle is {current_recycle} TAO[/red]"
        )
        return

    if not False:  # TODO no-prompt
        if not (
            Confirm.ask(
                f"Your balance is: [bold green]{balance}[/bold green]\nThe cost to register by recycle is "
                f"[bold red]{current_recycle}[/bold red]\nDo you want to continue?",
                default=False,
            )
        ):
            return

    await burned_register_extrinsic(
        subtensor,
        wallet=wallet,
        netuid=netuid,
        prompt=False,
        recycle_amount=current_recycle,
        old_balance=balance,
    )


async def metagraph_cmd(
    subtensor: "SubtensorInterface",
    netuid: Optional[int],
    reuse_last: bool,
    html_output: bool,
):
    """Prints an entire metagraph."""
    # TODO allow config to set certain columns
    if not reuse_last:
        with console.status(
            f":satellite: Syncing with chain: [white]{subtensor.network}[/white] ..."
        ):
            block_hash = await subtensor.substrate.get_chain_head()
            neurons, difficulty_, total_issuance_, block = await asyncio.gather(
                subtensor.neurons(netuid, block_hash=block_hash),
                subtensor.get_hyperparameter(
                    param_name="Difficulty", netuid=netuid, block_hash=block_hash
                ),
                subtensor.substrate.query(
                    module="SubtensorModule",
                    storage_function="TotalIssuance",
                    params=[],
                    block_hash=block_hash,
                ),
                subtensor.substrate.get_block_number(block_hash=block_hash),
            )

        difficulty = int(difficulty_)
        total_issuance = Balance.from_rao(total_issuance_.value)
        metagraph = MiniGraph(
            netuid=netuid, neurons=neurons, subtensor=subtensor, block=block
        )
        table_data = []
        db_table = []
        total_stake = 0.0
        total_rank = 0.0
        total_validator_trust = 0.0
        total_trust = 0.0
        total_consensus = 0.0
        total_incentive = 0.0
        total_dividends = 0.0
        total_emission = 0
        for uid in metagraph.uids:
            neuron = metagraph.neurons[uid]
            ep = metagraph.axons[uid]
            row = [
                str(neuron.uid),
                "{:.5f}".format(metagraph.total_stake[uid]),
                "{:.5f}".format(metagraph.ranks[uid]),
                "{:.5f}".format(metagraph.trust[uid]),
                "{:.5f}".format(metagraph.consensus[uid]),
                "{:.5f}".format(metagraph.incentive[uid]),
                "{:.5f}".format(metagraph.dividends[uid]),
                "{}".format(int(metagraph.emission[uid] * 1000000000)),
                "{:.5f}".format(metagraph.validator_trust[uid]),
                "*" if metagraph.validator_permit[uid] else "",
                str(metagraph.block.item() - metagraph.last_update[uid].item()),
                str(metagraph.active[uid].item()),
                (
                    ep.ip + ":" + str(ep.port)
                    if ep.is_serving
                    else "[yellow]none[/yellow]"
                ),
                ep.hotkey[:10],
                ep.coldkey[:10],
            ]
            db_row = [
                neuron.uid,
                float(metagraph.total_stake[uid]),
                float(metagraph.ranks[uid]),
                float(metagraph.trust[uid]),
                float(metagraph.consensus[uid]),
                float(metagraph.incentive[uid]),
                float(metagraph.dividends[uid]),
                int(metagraph.emission[uid] * 1000000000),
                float(metagraph.validator_trust[uid]),
                bool(metagraph.validator_permit[uid]),
                metagraph.block.item() - metagraph.last_update[uid].item(),
                metagraph.active[uid].item(),
                (ep.ip + ":" + str(ep.port) if ep.is_serving else "ERROR"),
                ep.hotkey[:10],
                ep.coldkey[:10],
            ]
            db_table.append(db_row)
            total_stake += metagraph.total_stake[uid]
            total_rank += metagraph.ranks[uid]
            total_validator_trust += metagraph.validator_trust[uid]
            total_trust += metagraph.trust[uid]
            total_consensus += metagraph.consensus[uid]
            total_incentive += metagraph.incentive[uid]
            total_dividends += metagraph.dividends[uid]
            total_emission += int(metagraph.emission[uid] * 1000000000)
            table_data.append(row)
        metadata_info = {
            "stake": str(Balance.from_tao(total_stake)),
            "total_stake": "\u03c4{:.5f}".format(total_stake),
            "rank": "{:.5f}".format(total_rank),
            "validator_trust": "{:.5f}".format(total_validator_trust),
            "trust": "{:.5f}".format(total_trust),
            "consensus": "{:.5f}".format(total_consensus),
            "incentive": "{:.5f}".format(total_incentive),
            "dividends": "{:.5f}".format(total_dividends),
            "emission": "\u03c1{}".format(int(total_emission)),
            "net": f"{subtensor.network}:{metagraph.netuid}",
            "block": str(metagraph.block.item()),
            "N": f"{sum(metagraph.active.tolist())}/{metagraph.n.item()}",
            "issuance": str(total_issuance),
            "difficulty": str(difficulty),
            "total_neurons": str(len(metagraph.uids)),
            "table_data": json.dumps(table_data),
        }
        update_metadata_table("metagraph", metadata_info)
        create_table(
            "metagraph",
            columns=[
                ("UID", "INTEGER"),
                ("STAKE", "REAL"),
                ("RANK", "REAL"),
                ("TRUST", "REAL"),
                ("CONSENSUS", "REAL"),
                ("INCENTIVE", "REAL"),
                ("DIVIDENDS", "REAL"),
                ("EMISSION", "INTEGER"),
                ("VTRUST", "REAL"),
                ("VAL", "INTEGER"),
                ("UPDATED", "INTEGER"),
                ("ACTIVE", "INTEGER"),
                ("AXON", "TEXT"),
                ("HOTKEY", "TEXT"),
                ("COLDKEY", "TEXT"),
            ],
            rows=db_table,
        )
    else:
        metadata_info = get_metadata_table("metagraph")
        table_data = json.loads(metadata_info["table_data"])

    if html_output:
        # TODO add the metadata_info to the table
        render_table("metagraph")
    else:
        table = Table(show_footer=False, box=None, pad_edge=False, width=None)

        table.title = (
            f"[white]Metagraph: "
            f"net: {metadata_info['net']}, "
            f"block: {metadata_info['block']},"
            f"N: {metadata_info['N']}, "
            f"stake: {metadata_info['stake']}, "
            f"issuance: {metadata_info['issuance']}, "
            f"difficulty: {metadata_info['difficulty']}"
        )
        table.add_column(
            "[overline white]UID",
            metadata_info["total_neurons"],
            footer_style="overline white",
            style="yellow",
        )
        table.add_column(
            "[overline white]STAKE(\u03c4)",
            metadata_info["total_stake"],
            footer_style="overline white",
            justify="right",
            style="green",
            no_wrap=True,
        )
        table.add_column(
            "[overline white]RANK",
            metadata_info["rank"],
            footer_style="overline white",
            justify="right",
            style="green",
            no_wrap=True,
        )
        table.add_column(
            "[overline white]TRUST",
            metadata_info["trust"],
            footer_style="overline white",
            justify="right",
            style="green",
            no_wrap=True,
        )
        table.add_column(
            "[overline white]CONSENSUS",
            metadata_info["consensus"],
            footer_style="overline white",
            justify="right",
            style="green",
            no_wrap=True,
        )
        table.add_column(
            "[overline white]INCENTIVE",
            metadata_info["incentive"],
            footer_style="overline white",
            justify="right",
            style="green",
            no_wrap=True,
        )
        table.add_column(
            "[overline white]DIVIDENDS",
            metadata_info["dividends"],
            footer_style="overline white",
            justify="right",
            style="green",
            no_wrap=True,
        )
        table.add_column(
            "[overline white]EMISSION(\u03c1)",
            metadata_info["emission"],
            footer_style="overline white",
            justify="right",
            style="green",
            no_wrap=True,
        )
        table.add_column(
            "[overline white]VTRUST",
            metadata_info["validator_trust"],
            footer_style="overline white",
            justify="right",
            style="green",
            no_wrap=True,
        )
        table.add_column(
            "[overline white]VAL", justify="right", style="green", no_wrap=True
        )
        table.add_column("[overline white]UPDATED", justify="right", no_wrap=True)
        table.add_column(
            "[overline white]ACTIVE", justify="right", style="green", no_wrap=True
        )
        table.add_column(
            "[overline white]AXON", justify="left", style="dim blue", no_wrap=True
        )
        table.add_column("[overline white]HOTKEY", style="dim blue", no_wrap=False)
        table.add_column("[overline white]COLDKEY", style="dim purple", no_wrap=False)
        table.show_footer = True

        for row in table_data:
            table.add_row(*row)

        console.print(table)
