import json
import time

import pytest

from .utils import extract_coldkey_balance


@pytest.mark.parametrize("local_chain", [False], indirect=True)
def test_subnet_buyback(local_chain, wallet_setup):
    """
    Test subnet buyback
    1. Create a subnet
    2. Start the subnet's emission schedule
    3. Buyback the subnet
    3. Check the balance before and after the buyback upon success
    4. Try to buyback again and expect it to fail due to rate limit
    """

    _, wallet_alice, wallet_path_alice, exec_command_alice = wallet_setup("//Alice")
    time.sleep(2)
    netuid = 2
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
            "test@opentensor.dev",
            "--url",
            "https://testsubnet.com",
            "--discord",
            "test#1234",
            "--description",
            "A test subnet for e2e testing",
            "--logo-url",
            "https://testsubnet.com/logo.png",
            "--additional-info",
            "Test subnet",
            "--no-prompt",
            "--no-mev-protection",
        ],
    )
    assert "✅ Registered subnetwork with netuid: 2" in result.stdout

    # Start the subnet's emission schedule
    start_call_netuid_2 = exec_command_alice(
        command="subnets",
        sub_command="start",
        extra_args=[
            "--netuid",
            str(netuid),
            "--wallet-name",
            wallet_alice.name,
            "--no-prompt",
            "--chain",
            "ws://127.0.0.1:9945",
            "--wallet-path",
            wallet_path_alice,
        ],
    )
    assert (
        "Successfully started subnet 2's emission schedule."
        in start_call_netuid_2.stdout
    )
    assert "Your extrinsic has been included" in start_call_netuid_2.stdout
    time.sleep(2)

    # Balance before buyback
    _balance_before = exec_command_alice(
        "wallet",
        "balance",
        extra_args=[
            "--wallet-path",
            wallet_path_alice,
            "--wallet-name",
            wallet_alice.name,
            "--network",
            "ws://127.0.0.1:9945",
        ],
    )
    balance_before = extract_coldkey_balance(
        _balance_before.stdout, wallet_alice.name, wallet_alice.coldkey.ss58_address
    )["free_balance"]

    # First buyback
    amount_tao = 5.0
    buyback_result = exec_command_alice(
        "sudo",
        "buyback",
        extra_args=[
            "--wallet-path",
            wallet_path_alice,
            "--wallet-name",
            wallet_alice.name,
            "--wallet-hotkey",
            wallet_alice.hotkey_str,
            "--network",
            "ws://127.0.0.1:9945",
            "--netuid",
            str(netuid),
            "--amount",
            str(amount_tao),
            "--no-prompt",
            "--json-output",
        ],
    )
    buyback_ok_out = json.loads(buyback_result.stdout)
    assert buyback_ok_out["success"] is True, buyback_result.stdout
