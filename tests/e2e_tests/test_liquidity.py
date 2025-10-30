import asyncio
import json
import re
import time

from bittensor_cli.src.bittensor.balances import Balance
from .utils import turn_off_hyperparam_freeze_window

"""
Verify commands:

* btcli liquidity add
* btcli liquidity list
* btcli liquidity modify
* btcli liquidity remove
"""


def test_liquidity(local_chain, wallet_setup):
    wallet_path_alice = "//Alice"
    netuid = 2

    # Create wallet for Alice
    keypair_alice, wallet_alice, wallet_path_alice, exec_command_alice = wallet_setup(
        wallet_path_alice
    )
    try:
        asyncio.run(turn_off_hyperparam_freeze_window(local_chain, wallet_alice))
    except ValueError:
        print(
            "Skipping turning off hyperparams freeze window. This indicates the call does not exist on the chain you are testing."
        )
    time.sleep(10)

    # Register a subnet with sudo as Alice
    result = exec_command_alice(
        command="subnets",
        sub_command="create",
        extra_args=[
            "--wallet-path",
            wallet_path_alice,
            "--chain",
            "ws://127.0.0.1:9945",
            "--wallet-name",
            wallet_alice.name,
            "--wallet-hotkey",
            wallet_alice.hotkey_str,
            "--subnet-name",
            "Test Subnet",
            "--repo",
            "https://github.com/username/repo",
            "--contact",
            "alice@opentensor.dev",
            "--url",
            "https://testsubnet.com",
            "--discord",
            "alice#1234",
            "--description",
            "A test subnet for e2e testing",
            "--additional-info",
            "Created by Alice",
            "--logo-url",
            "https://testsubnet.com/logo.png",
            "--no-prompt",
            "--json-output",
        ],
    )
    result_output = json.loads(result.stdout)
    assert result_output["success"] is True
    assert result_output["netuid"] == netuid
    assert isinstance(result_output["extrinsic_identifier"], str)

    # verify no results for list thus far (subnet not yet started)
    liquidity_list_result = exec_command_alice(
        command="liquidity",
        sub_command="list",
        extra_args=[
            "--wallet-path",
            wallet_path_alice,
            "--chain",
            "ws://127.0.0.1:9945",
            "--wallet-name",
            wallet_alice.name,
            "--wallet-hotkey",
            wallet_alice.hotkey_str,
            "--netuid",
            netuid,
            "--json-output",
        ],
    )
    result_output = json.loads(liquidity_list_result.stdout)
    assert result_output["success"] is False
    assert f"Subnet with netuid: {netuid} is not active" in result_output["err_msg"]
    assert result_output["positions"] == []

    # start emissions schedule
    start_subnet_emissions = exec_command_alice(
        command="subnets",
        sub_command="start",
        extra_args=[
            "--netuid",
            netuid,
            "--wallet-path",
            wallet_path_alice,
            "--wallet-name",
            wallet_alice.name,
            "--hotkey",
            wallet_alice.hotkey_str,
            "--network",
            "ws://127.0.0.1:9945",
            "--no-prompt",
        ],
    )
    assert (
        f"Successfully started subnet {netuid}'s emission schedule"
        in start_subnet_emissions.stdout
    ), start_subnet_emissions.stderr
    assert "Your extrinsic has been included " in start_subnet_emissions.stdout

    stake_to_enable_v3 = exec_command_alice(
        command="stake",
        sub_command="add",
        extra_args=[
            "--netuid",
            "2",
            "--wallet-path",
            wallet_path_alice,
            "--wallet-name",
            wallet_alice.name,
            "--hotkey",
            wallet_alice.hotkey_str,
            "--chain",
            "ws://127.0.0.1:9945",
            "--amount",
            "1",
            "--unsafe",
            "--no-prompt",
            "--era",
            "144",
        ],
    )
    assert "✅ Finalized" in stake_to_enable_v3.stdout, stake_to_enable_v3.stderr
    time.sleep(10)
    liquidity_list_result = exec_command_alice(
        command="liquidity",
        sub_command="list",
        extra_args=[
            "--wallet-path",
            wallet_path_alice,
            "--chain",
            "ws://127.0.0.1:9945",
            "--wallet-name",
            wallet_alice.name,
            "--wallet-hotkey",
            wallet_alice.hotkey_str,
            "--netuid",
            netuid,
            "--json-output",
        ],
    )
    print(">>>", liquidity_list_result.stdout, liquidity_list_result.stderr)
    result_output = json.loads(liquidity_list_result.stdout)
    assert result_output["success"] is False
    assert result_output["err_msg"] == "No liquidity positions found."
    assert result_output["positions"] == []

    enable_user_liquidity = exec_command_alice(
        command="sudo",
        sub_command="set",
        extra_args=[
            "--wallet-path",
            wallet_path_alice,
            "--chain",
            "ws://127.0.0.1:9945",
            "--wallet-name",
            wallet_alice.name,
            "--wallet-hotkey",
            wallet_alice.hotkey_str,
            "--netuid",
            netuid,
            "--param",
            "user_liquidity_enabled",
            "--value",
            "1",
            "--json-output",
            "--no-prompt",
        ],
    )
    enable_user_liquidity_result = json.loads(enable_user_liquidity.stdout)
    assert enable_user_liquidity_result["success"] is True
    assert isinstance(enable_user_liquidity_result["extrinsic_identifier"], str)

    add_liquidity = exec_command_alice(
        command="liquidity",
        sub_command="add",
        extra_args=[
            "--wallet-path",
            wallet_path_alice,
            "--chain",
            "ws://127.0.0.1:9945",
            "--wallet-name",
            wallet_alice.name,
            "--wallet-hotkey",
            wallet_alice.hotkey_str,
            "--netuid",
            netuid,
            "--liquidity",
            "1.0",
            "--price-low",
            "1.7",
            "--price-high",
            "1.8",
            "--no-prompt",
            "--json-output",
        ],
    )
    add_liquidity_result = json.loads(add_liquidity.stdout)
    assert add_liquidity_result["success"] is True
    assert add_liquidity_result["message"] == ""
    assert isinstance(add_liquidity_result["extrinsic_identifier"], str)

    liquidity_list_result = exec_command_alice(
        command="liquidity",
        sub_command="list",
        extra_args=[
            "--wallet-path",
            wallet_path_alice,
            "--chain",
            "ws://127.0.0.1:9945",
            "--wallet-name",
            wallet_alice.name,
            "--wallet-hotkey",
            wallet_alice.hotkey_str,
            "--netuid",
            netuid,
            "--json-output",
        ],
    )
    print(">>>", liquidity_list_result.stdout, liquidity_list_result.stderr)
    liquidity_list_result = json.loads(liquidity_list_result.stdout)
    assert liquidity_list_result["success"] is True
    assert len(liquidity_list_result["positions"]) == 1
    liquidity_position = liquidity_list_result["positions"][0]
    assert liquidity_position["liquidity"] == 1.0
    assert liquidity_position["fees_tao"] == 0.0
    assert liquidity_position["fees_alpha"] == 0.0
    assert liquidity_position["netuid"] == netuid
    assert abs(liquidity_position["price_high"] - 1.8) < 0.0001
    assert abs(liquidity_position["price_low"] - 1.7) < 0.0001

    modify_liquidity = exec_command_alice(
        command="liquidity",
        sub_command="modify",
        extra_args=[
            "--wallet-path",
            wallet_path_alice,
            "--chain",
            "ws://127.0.0.1:9945",
            "--wallet-name",
            wallet_alice.name,
            "--wallet-hotkey",
            wallet_alice.hotkey_str,
            "--netuid",
            netuid,
            "--position-id",
            str(liquidity_position["id"]),
            "--liquidity-delta",
            "20.0",
            "--json-output",
            "--no-prompt",
        ],
    )
    modify_liquidity_result = json.loads(modify_liquidity.stdout)
    assert modify_liquidity_result["success"] is True
    assert isinstance(modify_liquidity_result["extrinsic_identifier"], str)

    llr = exec_command_alice(
        command="liquidity",
        sub_command="list",
        extra_args=[
            "--wallet-path",
            wallet_path_alice,
            "--chain",
            "ws://127.0.0.1:9945",
            "--wallet-name",
            wallet_alice.name,
            "--wallet-hotkey",
            wallet_alice.hotkey_str,
            "--netuid",
            netuid,
            "--json-output",
        ],
    )
    print(">>>", llr.stdout, llr.stderr)
    liquidity_list_result = json.loads(llr.stdout)
    assert len(liquidity_list_result["positions"]) == 1
    liquidity_position = liquidity_list_result["positions"][0]
    assert liquidity_position["liquidity"] == 21.0

    removal = exec_command_alice(
        command="liquidity",
        sub_command="remove",
        extra_args=[
            "--wallet-path",
            wallet_path_alice,
            "--chain",
            "ws://127.0.0.1:9945",
            "--wallet-name",
            wallet_alice.name,
            "--wallet-hotkey",
            wallet_alice.hotkey_str,
            "--netuid",
            netuid,
            "--all",
            "--no-prompt",
            "--json-output",
        ],
    )
    removal_result = json.loads(removal.stdout)
    assert removal_result[str(liquidity_position["id"])]["success"] is True
    assert isinstance(
        removal_result[str(liquidity_position["id"])]["extrinsic_identifier"], str
    )

    liquidity_list_result = exec_command_alice(
        command="liquidity",
        sub_command="list",
        extra_args=[
            "--wallet-path",
            wallet_path_alice,
            "--chain",
            "ws://127.0.0.1:9945",
            "--wallet-name",
            wallet_alice.name,
            "--wallet-hotkey",
            wallet_alice.hotkey_str,
            "--netuid",
            netuid,
            "--json-output",
        ],
    )
    print(">>>", liquidity_list_result.stdout, liquidity_list_result.stderr)
    liquidity_list_result = json.loads(liquidity_list_result.stdout)
    assert liquidity_list_result["success"] is False
    assert result_output["err_msg"] == "No liquidity positions found."
    assert liquidity_list_result["positions"] == []
