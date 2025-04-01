import re

from bittensor_cli.src.bittensor.balances import Balance


def test_unstaking(local_chain, wallet_setup):
    """
    Test various unstaking scenarios including partial unstake, unstake all alpha, and unstake all.

    Steps:
        1. Create wallets for Alice and Bob
        2. Create 2 subnets with Alice
        3. Register Bob in one subnet
        4. Add stake from Bob to all subnets (except 1)
        5. Remove partial stake from one subnet and verify
        6. Remove all alpha stake and verify
        7. Add stake again to both subnets
        8. Remove all stake and verify
    """
    print("Testing unstaking scenarios 🧪")

    # Create wallets for Alice and Bob
    wallet_path_alice = "//Alice"
    wallet_path_bob = "//Bob"

    # Setup Alice's wallet
    keypair_alice, wallet_alice, wallet_path_alice, exec_command_alice = wallet_setup(
        wallet_path_alice
    )

    # Setup Bob's wallet
    keypair_bob, wallet_bob, wallet_path_bob, exec_command_bob = wallet_setup(
        wallet_path_bob
    )

    # Create first subnet (netuid = 2)
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
            "Test Subnet 2",
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
            "--additional-info",
            "Test subnet",
            "--no-prompt",
        ],
    )
    assert "✅ Registered subnetwork with netuid: 2" in result.stdout

    # Create second subnet (netuid = 3)
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
            "Test Subnet 3",
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
            "--additional-info",
            "Test subnet",
            "--no-prompt",
        ],
    )
    assert "✅ Registered subnetwork with netuid: 3" in result.stdout

    # Register Bob in one subnet
    register_result = exec_command_bob(
        command="subnets",
        sub_command="register",
        extra_args=[
            "--netuid",
            "2",
            "--wallet-path",
            wallet_path_bob,
            "--wallet-name",
            wallet_bob.name,
            "--hotkey",
            wallet_bob.hotkey_str,
            "--chain",
            "ws://127.0.0.1:9945",
            "--no-prompt",
        ],
    )
    assert "✅ Registered" in register_result.stdout

    # Add stake to subnets
    for netuid in [0, 2, 3]:
        stake_result = exec_command_bob(
            command="stake",
            sub_command="add",
            extra_args=[
                "--netuid",
                netuid,
                "--wallet-path",
                wallet_path_bob,
                "--wallet-name",
                wallet_bob.name,
                "--hotkey",
                wallet_bob.hotkey_str,
                "--amount",
                "700",
                "--chain",
                "ws://127.0.0.1:9945",
                "--no-prompt",
                "--partial",
                "--tolerance",
                "0.5",
                "--era",
                "144",
            ],
        )
        assert "✅ Finalized" in stake_result.stdout

    stake_list = exec_command_bob(
        command="stake",
        sub_command="list",
        extra_args=[
            "--wallet-path",
            wallet_path_bob,
            "--wallet-name",
            wallet_bob.name,
            "--chain",
            "ws://127.0.0.1:9945",
            "--no-prompt",
            "--verbose",
        ],
    )

    cleaned_stake = [
        re.sub(r"\s+", " ", line) for line in stake_list.stdout.splitlines()
    ]
    inital_stake_netuid_2 = cleaned_stake[9].split("│")[3].strip().split()[0]

    # Remove partial stake from netuid 2
    partial_unstake_netuid_2 = exec_command_bob(
        command="stake",
        sub_command="remove",
        extra_args=[
            "--netuid",
            "2",
            "--wallet-path",
            wallet_path_bob,
            "--wallet-name",
            wallet_bob.name,
            "--hotkey",
            wallet_bob.hotkey_str,
            "--amount",
            "100",
            "--chain",
            "ws://127.0.0.1:9945",
            "--no-prompt",
            "--partial",
            "--tolerance",
            "0.5",
            "--era",
            "144",
        ],
    )
    assert "✅ Finalized" in partial_unstake_netuid_2.stdout

    # Verify partial unstake
    stake_list = exec_command_bob(
        command="stake",
        sub_command="list",
        extra_args=[
            "--wallet-path",
            wallet_path_bob,
            "--wallet-name",
            wallet_bob.name,
            "--chain",
            "ws://127.0.0.1:9945",
            "--no-prompt",
            "--verbose",
        ],
    )

    # Verify stake amounts after partial unstake
    cleaned_stake = [
        re.sub(r"\s+", " ", line) for line in stake_list.stdout.splitlines()
    ]
    stake_after_unstaking_netuid_2 = cleaned_stake[10].split("│")[3].strip().split()[0]
    assert Balance.from_tao(float(stake_after_unstaking_netuid_2)) <= Balance.from_tao(
        float(inital_stake_netuid_2)
    )

    # Remove all alpha stakes
    unstake_alpha = exec_command_bob(
        command="stake",
        sub_command="remove",
        extra_args=[
            "--wallet-path",
            wallet_path_bob,
            "--wallet-name",
            wallet_bob.name,
            "--wallet-hotkey",
            wallet_bob.hotkey_str,
            "--chain",
            "ws://127.0.0.1:9945",
            "--all-alpha",
            "--no-prompt",
            "--verbose",
            "--era",
            "144",
        ],
    )

    assert (
        "✅ Finalized: Successfully unstaked all Alpha stakes" in unstake_alpha.stdout
    )

    # Add stake again to subnets
    for netuid in [0, 2, 3]:
        stake_result = exec_command_bob(
            command="stake",
            sub_command="add",
            extra_args=[
                "--netuid",
                netuid,
                "--wallet-path",
                wallet_path_bob,
                "--wallet-name",
                wallet_bob.name,
                "--hotkey",
                wallet_bob.hotkey_str,
                "--amount",
                "300",
                "--chain",
                "ws://127.0.0.1:9945",
                "--no-prompt",
                "--partial",
                "--tolerance",
                "0.5",
                "--era",
                "144",
            ],
        )
        assert "✅ Finalized" in stake_result.stdout

    # Remove all stakes
    unstake_all = exec_command_bob(
        command="stake",
        sub_command="remove",
        extra_args=[
            "--wallet-path",
            wallet_path_bob,
            "--wallet-name",
            wallet_bob.name,
            "--hotkey",
            wallet_bob.hotkey_str,
            "--chain",
            "ws://127.0.0.1:9945",
            "--all",
            "--no-prompt",
            "--era",
            "144",
        ],
    )
    assert "✅ Finalized: Successfully unstaked all stakes from" in unstake_all.stdout
    print("Passed unstaking tests 🎉")
