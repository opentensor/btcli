"""
End-to-end tests for axon commands.

Verify commands:
* btcli axon reset
* btcli axon set
"""

import pytest
import re


@pytest.mark.parametrize("local_chain", [None], indirect=True)
def test_axon_reset_and_set(local_chain, wallet_setup):
    """
    Test axon reset and set commands end-to-end.

    This test:
    1. Creates a subnet
    2. Registers a neuron
    3. Sets the axon information
    4. Verifies the axon is set correctly
    5. Resets the axon
    6. Verifies the axon is reset (0.0.0.0:1 - not serving)
    """
    wallet_path_alice = "//Alice"
    netuid = 1

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
            "Test Axon Subnet",
            "--repo",
            "https://github.com/test/axon-subnet",
            "--contact",
            "test@opentensor.dev",
            "--url",
            "https://testaxon.com",
            "--discord",
            "test#1234",
            "--description",
            "Test subnet for axon e2e testing",
            "--logo-url",
            "https://testaxon.com/logo.png",
            "--additional-info",
            "Axon test subnet",
            "--no-prompt",
        ],
    )
    assert result.exit_code == 0, f"Subnet creation failed: {result.stdout}"

    # Register neuron on the subnet
    result = exec_command_alice(
        command="subnets",
        sub_command="register",
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
            str(netuid),
            "--no-prompt",
        ],
    )
    assert result.exit_code == 0, f"Neuron registration failed: {result.stdout}"
    
    # Set serving rate limit to 0 to allow immediate axon updates
    result = exec_command_alice(
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
            str(netuid),
            "--param",
            "serving_rate_limit",
            "--value",
            "0",
            "--no-prompt",
        ],
    )
    assert result.exit_code == 0, f"Setting serving_rate_limit failed: {result.stdout}"
    
    # Set axon information
    test_ip = "192.168.1.100"
    test_port = 8091

    result = exec_command_alice(
        command="axon",
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
            str(netuid),
            "--ip",
            test_ip,
            "--port",
            str(test_port),
            "--no-prompt",
        ],
    )

    assert result.exit_code == 0, f"Axon set failed: {result.stdout}"
    assert (
        "successfully" in result.stdout.lower() or "success" in result.stdout.lower()
    ), f"Success message not found in output: {result.stdout}"

    # Verify axon is set by checking wallet overview
    result = exec_command_alice(
        command="wallet",
        sub_command="overview",
        extra_args=[
            "--wallet-path",
            wallet_path_alice,
            "--chain",
            "ws://127.0.0.1:9945",
            "--wallet-name",
            wallet_alice.name,
            "--netuid",
            str(netuid),
        ],
    )

    assert result.exit_code == 0, f"Wallet overview failed: {result.stdout}"

    # Check that axon column shows an IP (not "none")
    # The overview should show the axon info in the AXON column
    lines = result.stdout.split("\n")
    axon_found = False
    for line in lines:
        # Look for a line with the neuron info that has an IP address in the AXON column
        if wallet_alice.hotkey_str[:8] in line and "none" not in line.lower():
            # Check if there's an IP-like pattern in the line
            if re.search(r"\d+\.\d+\.\d+\.\d+:\d+", line):
                axon_found = True
                break

    assert axon_found, f"Axon not set correctly in overview: {result.stdout}"

    # Reset axon
    result = exec_command_alice(
        command="axon",
        sub_command="reset",
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
            str(netuid),
            "--no-prompt",
        ],
    )

    assert result.exit_code == 0, f"Axon reset failed: {result.stdout}"
    assert (
        "successfully" in result.stdout.lower() or "success" in result.stdout.lower()
    ), f"Success message not found in output: {result.stdout}"

    # Verify axon is reset by checking wallet overview
    result = exec_command_alice(
        command="wallet",
        sub_command="overview",
        extra_args=[
            "--wallet-path",
            wallet_path_alice,
            "--chain",
            "ws://127.0.0.1:9945",
            "--wallet-name",
            wallet_alice.name,
            "--netuid",
            str(netuid),
        ],
    )

    assert result.exit_code == 0, f"Wallet overview failed: {result.stdout}"

    # Check that axon column shows "none" after reset
    lines = result.stdout.split("\n")
    axon_reset = False
    for line in lines:
        if wallet_alice.hotkey_str[:8] in line and "none" in line.lower():
            axon_reset = True
            break

    assert axon_reset, f"Axon not reset correctly in overview: {result.stdout}"


@pytest.mark.parametrize("local_chain", [None], indirect=True)
def test_axon_set_with_ipv6(local_chain, wallet_setup):
    """
    Test setting axon with IPv6 address.
    """
    wallet_path_bob = "//Bob"
    netuid = 1

    # Create wallet for Bob
    keypair_bob, wallet_bob, wallet_path_bob, exec_command_bob = wallet_setup(
        wallet_path_bob
    )

    # Register a subnet with sudo as Bob
    result = exec_command_bob(
        command="subnets",
        sub_command="create",
        extra_args=[
            "--wallet-path",
            wallet_path_bob,
            "--chain",
            "ws://127.0.0.1:9945",
            "--wallet-name",
            wallet_bob.name,
            "--wallet-hotkey",
            wallet_bob.hotkey_str,
            "--subnet-name",
            "Test IPv6 Subnet",
            "--repo",
            "https://github.com/test/ipv6-subnet",
            "--contact",
            "ipv6@opentensor.dev",
            "--url",
            "https://testipv6.com",
            "--discord",
            "ipv6#5678",
            "--description",
            "Test subnet for IPv6 axon testing",
            "--logo-url",
            "https://testipv6.com/logo.png",
            "--additional-info",
            "IPv6 test subnet",
            "--no-prompt",
        ],
    )
    assert result.exit_code == 0, f"Subnet creation failed: {result.stdout}"

    # Register neuron on the subnet
    result = exec_command_bob(
        command="subnets",
        sub_command="register",
        extra_args=[
            "--wallet-path",
            wallet_path_bob,
            "--chain",
            "ws://127.0.0.1:9945",
            "--wallet-name",
            wallet_bob.name,
            "--wallet-hotkey",
            wallet_bob.hotkey_str,
            "--netuid",
            str(netuid),
            "--no-prompt",
        ],
    )
    assert result.exit_code == 0, f"Neuron registration failed: {result.stdout}"
    
    # Set serving rate limit to 0 to allow immediate axon updates
    result = exec_command_bob(
        command="sudo",
        sub_command="set",
        extra_args=[
            "--wallet-path",
            wallet_path_bob,
            "--chain",
            "ws://127.0.0.1:9945",
            "--wallet-name",
            wallet_bob.name,
            "--wallet-hotkey",
            wallet_bob.hotkey_str,
            "--netuid",
            str(netuid),
            "--param",
            "serving_rate_limit",
            "--value",
            "0",
            "--no-prompt",
        ],
    )
    assert result.exit_code == 0, f"Setting serving_rate_limit failed: {result.stdout}"
    
    # Set axon with IPv6 address
    test_ipv6 = "2001:db8::1"
    test_port = 8092

    result = exec_command_bob(
        command="axon",
        sub_command="set",
        extra_args=[
            "--wallet-path",
            wallet_path_bob,
            "--chain",
            "ws://127.0.0.1:9945",
            "--wallet-name",
            wallet_bob.name,
            "--wallet-hotkey",
            wallet_bob.hotkey_str,
            "--netuid",
            str(netuid),
            "--ip",
            test_ipv6,
            "--port",
            str(test_port),
            "--ip-type",
            "6",  # IPv6
            "--no-prompt",
        ],
    )

    assert result.exit_code == 0, f"Axon set with IPv6 failed: {result.stdout}"
    assert (
        "successfully" in result.stdout.lower() or "success" in result.stdout.lower()
    ), f"Success message not found in output: {result.stdout}"


@pytest.mark.parametrize("local_chain", [None], indirect=True)
def test_axon_set_invalid_inputs(local_chain, wallet_setup):
    """
    Test axon set with invalid inputs to ensure proper error handling.
    """
    wallet_path_charlie = "//Charlie"
    netuid = 1

    # Create wallet for Charlie
    keypair_charlie, wallet_charlie, wallet_path_charlie, exec_command_charlie = (
        wallet_setup(wallet_path_charlie)
    )

    # Register a subnet
    result = exec_command_charlie(
        command="subnets",
        sub_command="create",
        extra_args=[
            "--wallet-path",
            wallet_path_charlie,
            "--chain",
            "ws://127.0.0.1:9945",
            "--wallet-name",
            wallet_charlie.name,
            "--wallet-hotkey",
            wallet_charlie.hotkey_str,
            "--subnet-name",
            "Test Invalid Inputs Subnet",
            "--repo",
            "https://github.com/test/invalid-subnet",
            "--contact",
            "invalid@opentensor.dev",
            "--url",
            "https://testinvalid.com",
            "--discord",
            "invalid#9999",
            "--description",
            "Test subnet for invalid inputs testing",
            "--logo-url",
            "https://testinvalid.com/logo.png",
            "--additional-info",
            "Invalid inputs test subnet",
            "--no-prompt",
        ],
    )
    assert result.exit_code == 0

    # Register neuron
    result = exec_command_charlie(
        command="subnets",
        sub_command="register",
        extra_args=[
            "--wallet-path",
            wallet_path_charlie,
            "--chain",
            "ws://127.0.0.1:9945",
            "--wallet-name",
            wallet_charlie.name,
            "--wallet-hotkey",
            wallet_charlie.hotkey_str,
            "--netuid",
            str(netuid),
            "--no-prompt",
        ],
    )
    assert result.exit_code == 0
    
    # Set serving rate limit to 0 to allow immediate axon updates
    result = exec_command_charlie(
        command="sudo",
        sub_command="set",
        extra_args=[
            "--wallet-path",
            wallet_path_charlie,
            "--chain",
            "ws://127.0.0.1:9945",
            "--wallet-name",
            wallet_charlie.name,
            "--wallet-hotkey",
            wallet_charlie.hotkey_str,
            "--netuid",
            str(netuid),
            "--param",
            "serving_rate_limit",
            "--value",
            "0",
            "--no-prompt",
        ],
    )
    assert result.exit_code == 0, f"Setting serving_rate_limit failed: {result.stdout}"
    
    # Test with invalid port (too high)
    result = exec_command_charlie(
        command="axon",
        sub_command="set",
        extra_args=[
            "--wallet-path",
            wallet_path_charlie,
            "--chain",
            "ws://127.0.0.1:9945",
            "--wallet-name",
            wallet_charlie.name,
            "--wallet-hotkey",
            wallet_charlie.hotkey_str,
            "--netuid",
            str(netuid),
            "--ip",
            "192.168.1.1",
            "--port",
            "70000",  # Invalid port
            "--no-prompt",
        ],
    )

    # Should fail with invalid port
    assert (
        result.exit_code != 0
        or "invalid port" in result.stdout.lower()
        or "failed" in result.stdout.lower()
    ), f"Expected error for invalid port, got: {result.stdout}"

    # Test with invalid IP
    result = exec_command_charlie(
        command="axon",
        sub_command="set",
        extra_args=[
            "--wallet-path",
            wallet_path_charlie,
            "--chain",
            "ws://127.0.0.1:9945",
            "--wallet-name",
            wallet_charlie.name,
            "--wallet-hotkey",
            wallet_charlie.hotkey_str,
            "--netuid",
            str(netuid),
            "--ip",
            "invalid.ip.address",  # Invalid IP
            "--port",
            "8091",
            "--no-prompt",
        ],
    )

    # Should fail with invalid IP
    assert (
        result.exit_code != 0
        or "invalid ip" in result.stdout.lower()
        or "failed" in result.stdout.lower()
    ), f"Expected error for invalid IP, got: {result.stdout}"
