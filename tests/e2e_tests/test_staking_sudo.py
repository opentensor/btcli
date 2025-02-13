import re
import time

from bittensor_cli.src.bittensor.balances import Balance

"""
Verify commands:

* btcli subnets create
* btcli subnets register
* btcli stake add
* btcli stake remove
* btcli stake show
* btcli sudo set
* btcli sudo get
"""


def test_staking(local_chain, wallet_setup):
    """
    Test staking & sudo commands and inspect their output

    Steps:
        1. Create wallets for Alice and create a subnet & register
        2. Add 100 TAO stake to Alice's hotkey and verify
        3. Execute stake show and assert stake is present
        4. Execute stake remove and assert removal
        5. Fetch current subnet hyperparameters
        6. Change the max_burn hyperparameter and assert it changed.

    Raises:
        AssertionError: If any of the checks or verifications fail
    """
    print("Testing staking and sudo commands🧪")
    netuid = 2
    wallet_path_alice = "//Alice"

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
            "--name",
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
            "--no-prompt",
        ],
    )
    assert f"✅ Registered subnetwork with netuid: {netuid}" in result.stdout

    # Register Alice in netuid = 1 using her hotkey
    register_subnet = exec_command_alice(
        command="subnets",
        sub_command="register",
        extra_args=[
            "--wallet-path",
            wallet_path_alice,
            "--wallet-name",
            wallet_alice.name,
            "--hotkey",
            wallet_alice.hotkey_str,
            "--netuid",
            netuid,
            "--chain",
            "ws://127.0.0.1:9945",
            "--no-prompt",
        ],
    )
    assert "✅ Already Registered" in register_subnet.stdout

    # Add stake to Alice's hotkey
    add_stake = exec_command_alice(
        command="stake",
        sub_command="add",
        extra_args=[
            "--netuid",
            netuid,
            "--wallet-path",
            wallet_path_alice,
            "--wallet-name",
            wallet_alice.name,
            "--hotkey",
            wallet_alice.hotkey_str,
            "--chain",
            "ws://127.0.0.1:9945",
            "--amount",
            "100",
            "--tolerance",
            "0.1",
            "--partial",
            "--no-prompt",
        ],
    )
    assert "✅ Finalized" in add_stake.stdout

    # Execute stake show for Alice's wallet
    show_stake = exec_command_alice(
        command="stake",
        sub_command="list",
        extra_args=[
            "--wallet-path",
            wallet_path_alice,
            "--wallet-name",
            wallet_alice.name,
            "--chain",
            "ws://127.0.0.1:9945",
        ],
    )
    # Assert correct stake is added
    cleaned_stake = [
        re.sub(r"\s+", " ", line) for line in show_stake.stdout.splitlines()
    ]
    stake_added = cleaned_stake[8].split("│")[3].strip().split()[0]
    assert Balance.from_tao(float(stake_added)) >= Balance.from_tao(100)

    # Execute remove_stake command and remove all 100 TAO from Alice
    remove_stake = exec_command_alice(
        command="stake",
        sub_command="remove",
        extra_args=[
            "--netuid",
            netuid,
            "--wallet-path",
            wallet_path_alice,
            "--wallet-name",
            wallet_alice.name,
            "--hotkey",
            wallet_alice.hotkey_str,
            "--chain",
            "ws://127.0.0.1:9945",
            "--amount",
            "100",
            "--tolerance",
            "0.1",
            "--partial",
            "--no-prompt",
        ],
    )
    assert "✅ Finalized" in remove_stake.stdout

    # Fetch the hyperparameters of the subnet
    hyperparams = exec_command_alice(
        command="sudo",
        sub_command="get",
        extra_args=[
            "--chain",
            "ws://127.0.0.1:9945",
            "--netuid",
            netuid,
        ],
    )

    # Parse all hyperparameters and single out max_burn in TAO
    all_hyperparams = hyperparams.stdout.splitlines()
    max_burn_tao = all_hyperparams[22].split()[3]

    # Assert max_burn is 100 TAO from default
    assert Balance.from_tao(float(max_burn_tao)) == Balance.from_tao(100)

    # Change max_burn hyperparameter to 10 TAO
    change_hyperparams = exec_command_alice(
        command="sudo",
        sub_command="set",
        extra_args=[
            "--wallet-path",
            wallet_path_alice,
            "--wallet-name",
            wallet_alice.name,
            "--hotkey",
            wallet_alice.hotkey_str,
            "--chain",
            "ws://127.0.0.1:9945",
            "--netuid",
            netuid,
            "--param",
            "max_burn",
            "--value",
            "10000000000",  # In RAO, TAO = 10
        ],
    )
    assert (
        "✅ Hyperparameter max_burn changed to 10000000000" in change_hyperparams.stdout
    )

    # Fetch the hyperparameters again to verify
    updated_hyperparams = exec_command_alice(
        command="sudo",
        sub_command="get",
        extra_args=[
            "--chain",
            "ws://127.0.0.1:9945",
            "--netuid",
            netuid,
        ],
    )

    # Parse updated hyperparameters
    all_updated_hyperparams = updated_hyperparams.stdout.splitlines()
    updated_max_burn_tao = all_updated_hyperparams[22].split()[3]

    # Assert max_burn is now 10 TAO
    assert Balance.from_tao(float(updated_max_burn_tao)) == Balance.from_tao(10)
    print("✅ Passed staking and sudo commands")
