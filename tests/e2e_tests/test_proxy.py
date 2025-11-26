import asyncio
import json
from time import sleep

from bittensor_cli.src.bittensor.balances import Balance
from bittensor_cli.src.bittensor.utils import ProxyAnnouncements
from .utils import (
    extract_coldkey_balance,
    validate_wallet_inspect,
    validate_wallet_overview,
    verify_subnet_entry,
)

"""
Verify commands:

* btcli proxy create
* btcli proxy add
* btcli proxy remove
* btcli proxy kill
* btcli proxy execute
"""


def test_proxy_create(local_chain, wallet_setup):
    """
    Tests the pure proxy logic (create/kill)
    """
    wallet_path_alice = "//Alice"
    wallet_path_bob = "//Bob"

    # Create wallets for Alice and Bob
    keypair_alice, wallet_alice, wallet_path_alice, exec_command_alice = wallet_setup(
        wallet_path_alice
    )
    keypair_bob, wallet_bob, wallet_path_bob, exec_command_bob = wallet_setup(
        wallet_path_bob
    )
    proxy_type = "Any"
    delay = 12

    # create a pure proxy
    create_result = exec_command_alice(
        command="proxy",
        sub_command="create",
        extra_args=[
            "--wallet-path",
            wallet_path_alice,
            "--chain",
            "ws://127.0.0.1:9945",
            "--wallet-name",
            "default",
            "--proxy-type",
            proxy_type,
            "--delay",
            str(delay),
            "--period",
            "128",
            "--no-prompt",
            "--json-output"
        ]
    )
    create_result_output = json.loads(create_result.stdout)
    assert create_result_output["success"] is True
    assert create_result_output["message"] is not None
    assert create_result_output["extrinsic_id"] is not None
    created_pure = create_result_output["data"]["pure"]
    spawner = create_result_output["data"]["spawner"]
    created_proxy_type = create_result_output["data"]["proxy_type"]
    created_delay = create_result_output["data"]["delay"]
    assert isinstance(created_pure, str)
    assert isinstance(spawner, str)
    assert spawner == wallet_alice.coldkeypub.ss58_address
    assert created_proxy_type == proxy_type
    assert created_delay == delay

    # transfer some funds from alice to the pure proxy
    amount_to_transfer = 1_000
    transfer_result = exec_command_alice(
        command="wallet",
        sub_command="transfer",
        extra_args=[
            "--wallet-path",
            wallet_path_alice,
            "--chain",
            "ws://127.0.0.1:9945",
            "--wallet-name",
            "default",
            "--dest",
            created_pure,
            "--amount",
            str(amount_to_transfer),
            "--no-prompt",
            "--json-output"
        ]
    )
    transfer_result_output = json.loads(transfer_result.stdout)
    assert transfer_result_output["success"] is True

    # ensure the proxy has the transferred funds
    balance_result = exec_command_alice(
        command="wallet",
        sub_command="balance",
        extra_args=[
            "--wallet-path",
            wallet_path_alice,
            "--chain",
            "ws://127.0.0.1:9945",
            "--wallet-name",
            "default",
            "--ss58",
            created_pure,
            "--json-output"
        ]
    )
    balance_result_output = json.loads(balance_result.stdout)
    assert balance_result_output["balances"]["Provided Address 1"]["coldkey"] == created_pure
    assert balance_result_output["balances"]["Provided Address 1"]["free"] == float(amount_to_transfer)

    # transfer some of the pure proxy's funds to bob, but don't announce it
    amount_to_transfer_proxy = 100
    transfer_result_proxy = exec_command_alice(
        command="wallet",
        sub_command="transfer",
        extra_args=[
            "--wallet-path",
            wallet_path_alice,
            "--chain",
            "ws://127.0.0.1:9945",
            "--wallet-name",
            "default",
            "--proxy",
            created_pure,
            "--dest",
            keypair_bob.ss58_address,
            "--amount",
            str(amount_to_transfer_proxy),
            "--no-prompt",
            "--json-output"
        ]
    )
    transfer_result_proxy_output = json.loads(transfer_result_proxy.stdout)
    # should fail, because it wasn't announced
    assert transfer_result_proxy_output["success"] is False

    # announce the same extrinsic
    transfer_result_proxy = exec_command_alice(
        command="wallet",
        sub_command="transfer",
        extra_args=[
            "--wallet-path",
            wallet_path_alice,
            "--chain",
            "ws://127.0.0.1:9945",
            "--wallet-name",
            "default",
            "--proxy",
            created_pure,
            "--dest",
            keypair_bob.ss58_address,
            "--amount",
            str(amount_to_transfer_proxy),
            "--no-prompt",
            "--json-output",
            "--announce-only",
        ]
    )
    transfer_result_proxy_output = json.loads(transfer_result_proxy.stdout)
    assert transfer_result_proxy_output["success"] is True
    with ProxyAnnouncements.get_db() as (conn, cursor):
        rows = ProxyAnnouncements.read_rows(conn, cursor, include_header=False)
    latest_announcement = next(iter(sorted(rows, key=lambda row: row[1], reverse=True)))  # sort by epoch time
    address, epoch_time, block, call_hash, call, call_serialized = latest_announcement
    assert address == created_pure
    async def _handler(_):
        return True

    # wait for delay (probably already happened if fastblocks is on)
    asyncio.run(local_chain.wait_for_block(block+delay, _handler, False))

    announce_execution_result = exec_command_alice(
        command="proxy",
        sub_command="execute",
        extra_args=[
            "--wallet-path",
            wallet_path_alice,
            "--chain",
            "ws://127.0.0.1:9945",
            "--wallet-name",
            "default",
            "--proxy",
            created_pure,
            "--call-hash",
            call_hash,
            "--no-prompt",
            "--verbose"
            # "--json-output"
        ]
    )
    print(announce_execution_result.stdout, announce_execution_result.stderr)
    announce_execution_result_output = json.loads(announce_execution_result.stdout)
    assert announce_execution_result_output["success"] is True
    assert announce_execution_result_output["message"] == ""


    # ensure bob has the transferred funds
    balance_result = exec_command_bob(
        command="wallet",
        sub_command="balance",
        extra_args=[
            "--wallet-path",
            wallet_path_bob,
            "--chain",
            "ws://127.0.0.1:9945",
            "--wallet-name",
            "--json-output"
        ]
    )
    balance_result_output = json.loads(balance_result.stdout)
    print(balance_result_output)
    # assert balance_result_output["balances"]["Provided Address 1"]["coldkey"] == created_pure
    # assert balance_result_output["balances"]["Provided Address 1"]["free"] == float(amount_to_transfer)

