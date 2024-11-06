import asyncio
import json
import sqlite3
from textwrap import dedent
from typing import TYPE_CHECKING, Optional, cast

from bittensor_wallet import Wallet
from bittensor_wallet.errors import KeyFileError
from rich.prompt import Confirm
from rich.table import Column, Table

from bittensor_cli.src import DelegatesDetails
from bittensor_cli.src.bittensor.balances import Balance
from bittensor_cli.src.bittensor.chain_data import SubnetInfo
from bittensor_cli.src.bittensor.extrinsics.registration import register_extrinsic
from bittensor_cli.src.bittensor.minigraph import MiniGraph
from bittensor_cli.src.commands.root import burned_register_extrinsic
from bittensor_cli.src.commands.wallets import set_id, set_id_prompts
from bittensor_cli.src.bittensor.utils import (
    RAO_PER_TAO,
    console,
    create_table,
    err_console,
    print_verbose,
    print_error,
    format_error_message,
    get_metadata_table,
    millify,
    render_table,
    update_metadata_table,
)

if TYPE_CHECKING:
    from bittensor_cli.src.bittensor.subtensor_interface import SubtensorInterface


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

    async def _find_event_attributes_in_extrinsic_receipt(
        response_, event_name: str
    ) -> list:
        """
        Searches for the attributes of a specified event within an extrinsic receipt.

        :param response_: (substrateinterface.base.ExtrinsicReceipt): The receipt of the extrinsic to be searched.
        :param event_name: The name of the event to search for.

        :return: A list of attributes for the specified event. Returns [-1] if the event is not found.
        """
        for event in await response_.triggered_events:
            # Access the event details
            event_details = event["event"]
            # Check if the event_id is 'NetworkAdded'
            if event_details["event_id"] == event_name:
                # Once found, you can access the attributes of the event_name
                return event_details["attributes"]
        return [-1]

    print_verbose("Fetching balance")
    your_balance_ = await subtensor.get_balance(wallet.coldkeypub.ss58_address)
    your_balance = your_balance_[wallet.coldkeypub.ss58_address]

    print_verbose("Fetching lock_cost")
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

    try:
        wallet.unlock_coldkey()
    except KeyFileError:
        err_console.print("Error decrypting coldkey (possibly incorrect password)")
        return False

    with console.status(":satellite: Registering subnet...", spinner="earth"):
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

        await response.process_events()
        if not await response.is_success:
            err_console.print(
                f":cross_mark: [red]Failed[/red]: {format_error_message(await response.error_message, substrate)}"
            )
            await asyncio.sleep(0.5)
            return False

        # Successful registration, final check for membership
        else:
            attributes = await _find_event_attributes_in_extrinsic_receipt(
                response, "NetworkAdded"
            )
            console.print(
                f":white_heavy_check_mark: [green]Registered subnetwork with netuid: {attributes[0]}[/green]"
            )
            return True


# commands


async def subnets_list(
    subtensor: "SubtensorInterface", reuse_last: bool, html_output: bool, no_cache: bool
):
    """List all subnet netuids in the network."""

    async def _get_all_subnets_info():
        hex_bytes_result = await subtensor.query_runtime_api(
            runtime_api="SubnetInfoRuntimeApi", method="get_subnets_info", params=[]
        )
        try:
            bytes_result = bytes.fromhex(hex_bytes_result[2:])
        except ValueError:
            bytes_result = bytes.fromhex(hex_bytes_result)

        return SubnetInfo.list_from_vec_u8(bytes_result)

    if not reuse_last:
        subnets: list[SubnetInfo]
        delegate_info: dict[str, DelegatesDetails]

        print_verbose("Fetching subnet and delegate information")
        subnets, delegate_info = await asyncio.gather(
            _get_all_subnets_info(),
            subtensor.get_delegate_identities(),
        )

        if not subnets:
            err_console.print("[red]No subnets found[/red]")
            return

        rows = []
        db_rows = []
        total_neurons = 0
        max_neurons = 0

        for subnet in subnets:
            total_neurons += subnet.subnetwork_n
            max_neurons += subnet.max_n
            rows.append(
                (
                    str(subnet.netuid),
                    str(subnet.subnetwork_n),
                    str(millify(subnet.max_n)),
                    f"{subnet.emission_value / RAO_PER_TAO * 100:0.2f}%",
                    str(subnet.tempo),
                    f"{subnet.burn!s:8.8}",
                    str(millify(subnet.difficulty)),
                    str(
                        delegate_info[subnet.owner_ss58].display
                        if subnet.owner_ss58 in delegate_info
                        else subnet.owner_ss58
                    ),
                )
            )
            db_rows.append(
                [
                    int(subnet.netuid),
                    int(subnet.subnetwork_n),
                    int(subnet.max_n),  # millified in HTML table
                    float(
                        subnet.emission_value / RAO_PER_TAO * 100
                    ),  # shown as percentage in HTML table
                    int(subnet.tempo),
                    float(subnet.burn),
                    int(subnet.difficulty),  # millified in HTML table
                    str(
                        delegate_info[subnet.owner_ss58].display
                        if subnet.owner_ss58 in delegate_info
                        else subnet.owner_ss58
                    ),
                ]
            )
        metadata = {
            "network": subtensor.network,
            "netuid_count": len(subnets),
            "N": total_neurons,
            "MAX_N": max_neurons,
            "rows": json.dumps(rows),
        }
        if not no_cache:
            create_table(
                "subnetslist",
                [
                    ("NETUID", "INTEGER"),
                    ("N", "INTEGER"),
                    ("MAX_N", "BLOB"),
                    ("EMISSION", "REAL"),
                    ("TEMPO", "INTEGER"),
                    ("RECYCLE", "REAL"),
                    ("DIFFICULTY", "BLOB"),
                    ("SUDO", "TEXT"),
                ],
                db_rows,
            )
            update_metadata_table("subnetslist", values=metadata)
    else:
        try:
            metadata = get_metadata_table("subnetslist")
            rows = json.loads(metadata["rows"])
        except sqlite3.OperationalError:
            err_console.print(
                "[red]Error[/red] Unable to retrieve table data. This is usually caused by attempting to use "
                "`--reuse-last` before running the command a first time. In rare cases, this could also be due to "
                "a corrupted database. Re-run the command (do not use `--reuse-last`) and see if that resolves your "
                "issue."
            )
            return
    if not html_output:
        table = Table(
            title=f"[underline dark_orange]Subnets[/underline dark_orange]\n[dark_orange]Network: {metadata['network']}[/dark_orange]\n",
            show_footer=True,
            show_edge=False,
            header_style="bold white",
            border_style="bright_black",
            style="bold",
            title_justify="center",
            show_lines=False,
            pad_edge=True,
        )

        table.add_column(
            "[bold white]NETUID",
            footer=f"[white]{metadata['netuid_count']}[/white]",
            style="white",
            justify="center",
        )
        table.add_column(
            "[bold white]N",
            footer=f"[white]{metadata['N']}[/white]",
            style="bright_cyan",
            justify="right",
        )
        table.add_column(
            "[bold white]MAX_N",
            footer=f"[white]{metadata['MAX_N']}[/white]",
            style="bright_cyan",
            justify="right",
        )
        table.add_column(
            "[bold white]EMISSION", style="light_goldenrod2", justify="right"
        )
        table.add_column("[bold white]TEMPO", style="rgb(42,161,152)", justify="right")
        table.add_column("[bold white]RECYCLE", style="light_salmon3", justify="right")
        table.add_column("[bold white]POW", style="medium_purple", justify="right")
        table.add_column(
            "[bold white]SUDO", style="bright_magenta", justify="right", overflow="fold"
        )

        for row in rows:
            table.add_row(*row)

        console.print(table)
        console.print(
            dedent(
                """
            Description:
                The table displays the list of subnets registered in the Bittensor network.
                    - NETUID: The network identifier of the subnet.
                    - N: The current UIDs registered to the network. 
                    - MAX_N: The total UIDs allowed on the network.
                    - EMISSION: The emission accrued by this subnet in the network.
                    - TEMPO: A duration of a number of blocks. Several subnet events occur at the end of every tempo period.
                    - RECYCLE: Cost to register to the subnet.
                    - POW: Proof of work metric of the subnet.
                    - SUDO: Owner's identity.
            """
            )
        )
    else:
        render_table(
            "subnetslist",
            f"Subnets List | Network: {metadata['network']} - "
            f"Netuids: {metadata['netuid_count']} - N: {metadata['N']}",
            columns=[
                {"title": "NetUID", "field": "NETUID"},
                {"title": "N", "field": "N"},
                {"title": "MAX_N", "field": "MAX_N", "customFormatter": "millify"},
                {
                    "title": "EMISSION",
                    "field": "EMISSION",
                    "formatter": "money",
                    "formatterParams": {
                        "symbolAfter": "p",
                        "symbol": "%",
                        "precision": 2,
                    },
                },
                {"title": "Tempo", "field": "TEMPO"},
                {
                    "title": "Recycle",
                    "field": "RECYCLE",
                    "formatter": "money",
                    "formatterParams": {"symbol": "τ", "precision": 5},
                },
                {
                    "title": "Difficulty",
                    "field": "DIFFICULTY",
                    "customFormatter": "millify",
                },
                {"title": "sudo", "field": "SUDO"},
            ],
        )


async def lock_cost(subtensor: "SubtensorInterface") -> Optional[Balance]:
    """View locking cost of creating a new subnetwork"""
    with console.status(
        f":satellite:Retrieving lock cost from {subtensor.network}...",
        spinner="aesthetic",
    ):
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


async def create(wallet: Wallet, subtensor: "SubtensorInterface", prompt: bool):
    """Register a subnetwork"""

    # Call register command.
    success = await register_subnetwork_extrinsic(subtensor, wallet, prompt=prompt)
    if success and prompt:
        # Prompt for user to set identity.
        do_set_identity = Confirm.ask(
            "Subnetwork registered successfully. Would you like to set your identity?"
        )

        if do_set_identity:
            id_prompts = set_id_prompts(validator=False)
            await set_id(wallet, subtensor, *id_prompts, prompt=prompt)


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
    prompt: bool,
):
    """Register neuron."""

    await register_extrinsic(
        subtensor,
        wallet=wallet,
        netuid=netuid,
        prompt=prompt,
        tpb=threads_per_block,
        update_interval=update_interval,
        num_processes=processors,
        cuda=use_cuda,
        dev_id=dev_id,
        output_in_place=output_in_place,
        log_verbose=verbose,
    )


async def register(
    wallet: Wallet, subtensor: "SubtensorInterface", netuid: int, prompt: bool
):
    """Register neuron by recycling some TAO."""

    # Verify subnet exists
    print_verbose("Checking subnet status")
    block_hash = await subtensor.substrate.get_chain_head()
    if not await subtensor.subnet_exists(netuid=netuid, block_hash=block_hash):
        err_console.print(f"[red]Subnet {netuid} does not exist[/red]")
        return

    # Check current recycle amount
    print_verbose("Fetching recycle amount")
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

    if prompt:
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
    subtensor: Optional["SubtensorInterface"],
    netuid: Optional[int],
    reuse_last: bool,
    html_output: bool,
    no_cache: bool,
    display_cols: dict,
):
    """Prints an entire metagraph."""
    # TODO allow config to set certain columns
    if not reuse_last:
        cast("SubtensorInterface", subtensor)
        cast(int, netuid)
        with console.status(
            f":satellite: Syncing with chain: [white]{subtensor.network}[/white] ...",
            spinner="aesthetic",
        ) as status:
            block_hash = await subtensor.substrate.get_chain_head()

            if not await subtensor.subnet_exists(netuid, block_hash):
                print_error(f"Subnet with netuid: {netuid} does not exist", status)
                return False

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
        total_issuance = Balance.from_rao(total_issuance_)
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
                    else "[light_goldenrod2]none[/light_goldenrod2]"
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
            "N0": str(sum(metagraph.active.tolist())),
            "N1": str(metagraph.n.item()),
            "issuance": str(total_issuance),
            "difficulty": str(difficulty),
            "total_neurons": str(len(metagraph.uids)),
            "table_data": json.dumps(table_data),
        }
        if not no_cache:
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
        try:
            metadata_info = get_metadata_table("metagraph")
            table_data = json.loads(metadata_info["table_data"])
        except sqlite3.OperationalError:
            err_console.print(
                "[red]Error[/red] Unable to retrieve table data. This is usually caused by attempting to use "
                "`--reuse-last` before running the command a first time. In rare cases, this could also be due to "
                "a corrupted database. Re-run the command (do not use `--reuse-last`) and see if that resolves your "
                "issue."
            )
            return

    if html_output:
        try:
            render_table(
                table_name="metagraph",
                table_info=f"Metagraph | "
                f"net: {metadata_info['net']}, "
                f"block: {metadata_info['block']}, "
                f"N: {metadata_info['N']}, "
                f"stake: {metadata_info['stake']}, "
                f"issuance: {metadata_info['issuance']}, "
                f"difficulty: {metadata_info['difficulty']}",
                columns=[
                    {"title": "UID", "field": "UID"},
                    {
                        "title": "Stake",
                        "field": "STAKE",
                        "formatter": "money",
                        "formatterParams": {"symbol": "τ", "precision": 5},
                    },
                    {
                        "title": "Rank",
                        "field": "RANK",
                        "formatter": "money",
                        "formatterParams": {"precision": 5},
                    },
                    {
                        "title": "Trust",
                        "field": "TRUST",
                        "formatter": "money",
                        "formatterParams": {"precision": 5},
                    },
                    {
                        "title": "Consensus",
                        "field": "CONSENSUS",
                        "formatter": "money",
                        "formatterParams": {"precision": 5},
                    },
                    {
                        "title": "Incentive",
                        "field": "INCENTIVE",
                        "formatter": "money",
                        "formatterParams": {"precision": 5},
                    },
                    {
                        "title": "Dividends",
                        "field": "DIVIDENDS",
                        "formatter": "money",
                        "formatterParams": {"precision": 5},
                    },
                    {"title": "Emission", "field": "EMISSION"},
                    {
                        "title": "VTrust",
                        "field": "VTRUST",
                        "formatter": "money",
                        "formatterParams": {"precision": 5},
                    },
                    {"title": "Validated", "field": "VAL"},
                    {"title": "Updated", "field": "UPDATED"},
                    {"title": "Active", "field": "ACTIVE"},
                    {"title": "Axon", "field": "AXON"},
                    {"title": "Hotkey", "field": "HOTKEY"},
                    {"title": "Coldkey", "field": "COLDKEY"},
                ],
            )
        except sqlite3.OperationalError:
            err_console.print(
                "[red]Error[/red] Unable to retrieve table data. This may indicate that your database is corrupted, "
                "or was not able to load with the most recent data."
            )
            return
    else:
        cols: dict[str, tuple[int, Column]] = {
            "UID": (
                0,
                Column(
                    "[bold white]UID",
                    footer=f"[white]{metadata_info['total_neurons']}[/white]",
                    style="white",
                    justify="right",
                    ratio=0.75,
                ),
            ),
            "STAKE": (
                1,
                Column(
                    "[bold white]STAKE(\u03c4)",
                    footer=metadata_info["total_stake"],
                    style="bright_cyan",
                    justify="right",
                    no_wrap=True,
                    ratio=1.5,
                ),
            ),
            "RANK": (
                2,
                Column(
                    "[bold white]RANK",
                    footer=metadata_info["rank"],
                    style="medium_purple",
                    justify="right",
                    no_wrap=True,
                    ratio=1,
                ),
            ),
            "TRUST": (
                3,
                Column(
                    "[bold white]TRUST",
                    footer=metadata_info["trust"],
                    style="dark_sea_green",
                    justify="right",
                    no_wrap=True,
                    ratio=1,
                ),
            ),
            "CONSENSUS": (
                4,
                Column(
                    "[bold white]CONSENSUS",
                    footer=metadata_info["consensus"],
                    style="rgb(42,161,152)",
                    justify="right",
                    no_wrap=True,
                    ratio=1,
                ),
            ),
            "INCENTIVE": (
                5,
                Column(
                    "[bold white]INCENTIVE",
                    footer=metadata_info["incentive"],
                    style="#5fd7ff",
                    justify="right",
                    no_wrap=True,
                    ratio=1,
                ),
            ),
            "DIVIDENDS": (
                6,
                Column(
                    "[bold white]DIVIDENDS",
                    footer=metadata_info["dividends"],
                    style="#8787d7",
                    justify="right",
                    no_wrap=True,
                    ratio=1,
                ),
            ),
            "EMISSION": (
                7,
                Column(
                    "[bold white]EMISSION(\u03c1)",
                    footer=metadata_info["emission"],
                    style="#d7d7ff",
                    justify="right",
                    no_wrap=True,
                    ratio=1.5,
                ),
            ),
            "VTRUST": (
                8,
                Column(
                    "[bold white]VTRUST",
                    footer=metadata_info["validator_trust"],
                    style="magenta",
                    justify="right",
                    no_wrap=True,
                    ratio=1,
                ),
            ),
            "VAL": (
                9,
                Column(
                    "[bold white]VAL",
                    justify="center",
                    style="bright_white",
                    no_wrap=True,
                    ratio=0.4,
                ),
            ),
            "UPDATED": (
                10,
                Column("[bold white]UPDATED", justify="right", no_wrap=True, ratio=1),
            ),
            "ACTIVE": (
                11,
                Column(
                    "[bold white]ACTIVE",
                    justify="center",
                    style="#8787ff",
                    no_wrap=True,
                    ratio=1,
                ),
            ),
            "AXON": (
                12,
                Column(
                    "[bold white]AXON",
                    justify="left",
                    style="dark_orange",
                    overflow="fold",
                    ratio=2,
                ),
            ),
            "HOTKEY": (
                13,
                Column(
                    "[bold white]HOTKEY",
                    justify="center",
                    style="bright_magenta",
                    overflow="fold",
                    ratio=1.5,
                ),
            ),
            "COLDKEY": (
                14,
                Column(
                    "[bold white]COLDKEY",
                    justify="center",
                    style="bright_magenta",
                    overflow="fold",
                    ratio=1.5,
                ),
            ),
        }
        table_cols: list[Column] = []
        table_cols_indices: list[int] = []
        for k, (idx, v) in cols.items():
            if display_cols[k] is True:
                table_cols_indices.append(idx)
                table_cols.append(v)

        table = Table(
            *table_cols,
            show_footer=True,
            show_edge=False,
            header_style="bold white",
            border_style="bright_black",
            style="bold",
            title_style="bold white",
            title_justify="center",
            show_lines=False,
            expand=True,
            title=(
                f"[underline dark_orange]Metagraph[/underline dark_orange]\n\n"
                f"Net: [bright_cyan]{metadata_info['net']}[/bright_cyan], "
                f"Block: [bright_cyan]{metadata_info['block']}[/bright_cyan], "
                f"N: [bright_green]{metadata_info['N0']}[/bright_green]/[bright_red]{metadata_info['N1']}[/bright_red], "
                f"Stake: [dark_orange]{metadata_info['stake']}[/dark_orange], "
                f"Issuance: [bright_blue]{metadata_info['issuance']}[/bright_blue], "
                f"Difficulty: [bright_cyan]{metadata_info['difficulty']}[/bright_cyan]\n"
            ),
            pad_edge=True,
        )

        if all(x is False for x in display_cols.values()):
            console.print("You have selected no columns to display in your config.")
            table.add_row(" " * 256)  # allows title to be printed
        elif any(x is False for x in display_cols.values()):
            console.print(
                "Limiting column display output based on your config settings. Hiding columns "
                f"{', '.join([k for (k, v) in display_cols.items() if v is False])}"
            )
            for row in table_data:
                new_row = [row[idx] for idx in table_cols_indices]
                table.add_row(*new_row)
        else:
            for row in table_data:
                table.add_row(*row)

        console.print(table)
