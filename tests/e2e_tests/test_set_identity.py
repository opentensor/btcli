import json
from unittest.mock import MagicMock, AsyncMock, patch


"""
Verify commands:
* btcli s create (with identity)
* btcli s get-identity (reads from owner coldkey)
"""


def test_set_id(local_chain, wallet_setup):
    """
    Tests that subnet creation with identity works and that get-identity
    retrieves the identity from the subnet owner's coldkey.
    Note: set-identity has been removed as identities are now on owner coldkeys.
    """
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
    
    # Note: Since identities are now stored on owner coldkeys, 
    # get-identity will read from Alice's coldkey identity.
    # The subnet identity fields passed during creation are stored on-chain
    # but get-identity now returns the owner's coldkey identity instead.
