import json
import re

from bittensor_cli.src.bittensor.balances import Balance

"""
Verify commands:

* btcli liquidity add
* btcli liquidity list
* btcli liquidity modify
* btcli liquidity remove
"""


def test_liquidity(local_chain, wallet_setup):
    def liquidity_list():
        return exec_command_alice(
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

    wallet_path_alice = "//Alice"
    netuid = 2

    # Create wallet for Alice
    keypair_alice, wallet_alice, wallet_path_alice, exec_command_alice = wallet_setup(
        wallet_path_alice
    )

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

    # verify no results for list thus far (subnet not yet started)
    liquidity_list_result = liquidity_list()
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

    liquidity_list_result = liquidity_list()
    result_output = json.loads(liquidity_list_result.stdout)
    assert result_output["success"] is True
    assert result_output["err_msg"] == ""
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

    liquidity_list_result = liquidity_list()
    liquidity_list_result = json.loads(liquidity_list_result.stdout)
    assert liquidity_list_result["success"] is True
    assert len(liquidity_list_result["positions"]) == 1
    liquidity_position = liquidity_list_result["positions"][0]
    assert liquidity_position["alpha_liquidity"] == 1.0
    assert liquidity_position["id"] == 2
    assert liquidity_position["fees_tao"] == 0.0
    assert liquidity_position["fees_alpha"] == 0.0
    assert liquidity_position["netuid"] == netuid
    assert abs(liquidity_position["price_high"] - 1.8) < 0.1
    assert abs(liquidity_position["price_low"] - 1.7) < 0.1
