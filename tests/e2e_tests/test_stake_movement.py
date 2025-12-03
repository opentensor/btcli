import asyncio
import json
import pytest

from .utils import set_storage_extrinsic


@pytest.mark.parametrize("local_chain", [False], indirect=True)
def test_stake_movement(local_chain, wallet_setup):
    """
    Exercise stake move, transfer, and swap flows across subnets using Alice and Bob.

    Steps:
        0. Initial setup: Make alice own SN 0, create SN2, SN3, SN4, start emissions on all subnets.
        1. Activation: Register Bob on subnets 2 and 3; add initial stake for V3 activation.
        2. Move: Move stake from Alice's hotkey on netuid 2 to Bob's hotkey on netuid 3.
        3. Transfer: Transfer all root (netuid 0) stake from Alice's coldkey to Bob's coldkey.
        4. Swap: Swap Alice's stake from netuid 4 to the root netuid.

    Note:
        - All movement commands executed with mev shield
        - Stake commands executed without shield to speed up tests
        - Shield for stake commands is already covered in its own test
    """
    print("Testing stake movement commands 🧪")

    wallet_path_alice = "//Alice"
    wallet_path_bob = "//Bob"

    keypair_alice, wallet_alice, wallet_path_alice, exec_command_alice = wallet_setup(
        wallet_path_alice
    )
    keypair_bob, wallet_bob, wallet_path_bob, exec_command_bob = wallet_setup(
        wallet_path_bob
    )

    # Force Alice to own SN0 by setting storage
    sn0_owner_storage_items = [
        (
            bytes.fromhex(
                "658faa385070e074c85bf6b568cf055536e3e82152c8758267395fe524fbbd160000"
            ),
            bytes.fromhex(
                "d43593c715fdd31c61141abd04a99fd6822c8558854ccde39a5684e7a56da27d"
            ),
        )
    ]
    asyncio.run(
        set_storage_extrinsic(
            local_chain,
            wallet=wallet_alice,
            items=sn0_owner_storage_items,
        )
    )

    # Create SN2, SN3, SN4 for move/transfer/swap checks
    subnets_to_create = [2, 3, 4]
    for netuid in subnets_to_create:
        create_subnet_result = exec_command_alice(
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
        create_subnet_payload = json.loads(create_subnet_result.stdout)
        assert create_subnet_payload["success"] is True
        assert create_subnet_payload["netuid"] == netuid

    # Start emission schedule for subnets (including root netuid 0)
    for netuid in [0] + subnets_to_create:
        start_emission_result = exec_command_alice(
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
            f"Successfully started subnet {netuid}'s emission schedule."
            in start_emission_result.stdout
        )

    # Alice is already registered - register Bob on the two non-root subnets
    for netuid in [2, 3]:
        register_bob_result = exec_command_bob(
            command="subnets",
            sub_command="register",
            extra_args=[
                "--netuid",
                str(netuid),
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
        assert "✅ Registered" in register_bob_result.stdout, register_bob_result.stderr
        assert "Your extrinsic has been included" in register_bob_result.stdout, (
            register_bob_result.stdout
        )

    # Add initial stake to enable V3 (1 TAO) on all created subnets
    for netuid in [2, 3, 4]:
        add_initial_stake_result = exec_command_alice(
            command="stake",
            sub_command="add",
            extra_args=[
                "--netuid",
                str(netuid),
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
                "--no-mev-protection",
            ],
        )
        assert "✅ Finalized" in add_initial_stake_result.stdout, (
            add_initial_stake_result.stderr
        )
