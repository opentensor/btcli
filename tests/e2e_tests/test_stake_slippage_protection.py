import asyncio
import json
import pytest

from .utils import find_stake_entries, set_storage_extrinsic


@pytest.mark.parametrize("local_chain", [False], indirect=True)
def test_stake_slippage_protection(local_chain, wallet_setup):
    """
    Test slippage protection options for swap and transfer commands.

    Steps:
        0. Initial setup: Make alice own SN 0, create SN2, SN3, SN4, start emissions on all subnets.
        1. Activation: Register Bob on subnets 2 and 3; add initial stake for V3 activation.
        2. Test Swap with slippage protection (--safe --tolerance)
        3. Test Swap without slippage protection (--unsafe)
        4. Test Transfer with slippage protection (--safe --tolerance)
        5. Test Transfer without slippage protection (--unsafe)
        6. Test Swap with slippage protection and partial stake (--safe --tolerance --partial)
        7. Test Transfer with slippage protection and partial stake (--safe --tolerance --partial)

    Note:
        - All movement commands executed with mev shield
        - Stake commands executed without shield to speed up tests
        - Shield for stake commands is already covered in its own test
    """
    print("Testing slippage protection for swap and transfer commands 🧪")

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

    # Create SN2, SN3, SN4 for swap/transfer checks
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

    ################################
    # TEST 1: Swap with slippage protection (--safe --tolerance)
    ################################

    # Add stake for swap test with slippage protection
    swap_safe_seed_stake_result = exec_command_alice(
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
            "25",
            "--no-prompt",
            "--era",
            "144",
            "--unsafe",
            "--no-mev-protection",
        ],
    )
    assert "✅ Finalized" in swap_safe_seed_stake_result.stdout, (
        swap_safe_seed_stake_result.stderr
    )

    print("✅ Swap with slippage protection seed stake finalized")

    # Verify stake was added
    alice_stake_before_swap_safe = exec_command_alice(
        command="stake",
        sub_command="list",
        extra_args=[
            "--wallet-path",
            wallet_path_alice,
            "--wallet-name",
            wallet_alice.name,
            "--chain",
            "ws://127.0.0.1:9945",
            "--no-prompt",
            "--verbose",
            "--json-output",
        ],
    )
    alice_stake_list_before_swap_safe = json.loads(alice_stake_before_swap_safe.stdout)
    alice_stakes_before_swap_safe = find_stake_entries(
        alice_stake_list_before_swap_safe,
        netuid=2,
        hotkey_ss58=wallet_alice.hotkey.ss58_address,
    )
    assert len(alice_stakes_before_swap_safe) > 0
    assert any(stake["stake_value"] >= 20 for stake in alice_stakes_before_swap_safe)

    # Swap stake with slippage protection (--safe --tolerance)
    # Swap to root netuid (0) which has more liquidity
    swap_safe_amount = 20
    swap_safe_result = exec_command_alice(
        command="stake",
        sub_command="swap",
        extra_args=[
            "--origin-netuid",
            "2",
            "--wallet-path",
            wallet_path_alice,
            "--wallet-name",
            wallet_alice.name,
            "--wallet-hotkey",
            wallet_alice.hotkey_str,
            "--dest-netuid",
            "0",  # Root netuid has more liquidity
            "--amount",
            str(swap_safe_amount),
            "--chain",
            "ws://127.0.0.1:9945",
            "--no-prompt",
            "--safe",
            "--tolerance",
            "0.1",  # 10% tolerance
        ],
    )
    assert "✅ Sent" in swap_safe_result.stdout, swap_safe_result.stderr

    # Verify stake was swapped
    alice_stake_after_swap_safe = exec_command_alice(
        command="stake",
        sub_command="list",
        extra_args=[
            "--wallet-path",
            wallet_path_alice,
            "--wallet-name",
            wallet_alice.name,
            "--chain",
            "ws://127.0.0.1:9945",
            "--no-prompt",
            "--verbose",
            "--json-output",
        ],
    )
    alice_stake_list_after_swap_safe = json.loads(alice_stake_after_swap_safe.stdout)
    alice_stakes_after_swap_safe = find_stake_entries(
        alice_stake_list_after_swap_safe,
        netuid=0,  # Root netuid
        hotkey_ss58=wallet_alice.hotkey.ss58_address,
    )
    assert len(alice_stakes_after_swap_safe) > 0
    assert any(
        stake["stake_value"] >= swap_safe_amount
        for stake in alice_stakes_after_swap_safe
    )
    print("✅ TEST 1: Swap with slippage protection completed successfully")

    ################################
    # TEST 2: Swap without slippage protection (--unsafe)
    ################################

    # Add stake for swap test without slippage protection
    # Use netuid 4 as origin since we already have stake in netuid 0 from previous swap
    swap_unsafe_seed_stake_result = exec_command_alice(
        command="stake",
        sub_command="add",
        extra_args=[
            "--netuid",
            "4",
            "--wallet-path",
            wallet_path_alice,
            "--wallet-name",
            wallet_alice.name,
            "--hotkey",
            wallet_alice.hotkey_str,
            "--chain",
            "ws://127.0.0.1:9945",
            "--amount",
            "25",
            "--no-prompt",
            "--era",
            "144",
            "--unsafe",
            "--no-mev-protection",
        ],
    )
    assert "✅ Finalized" in swap_unsafe_seed_stake_result.stdout, (
        swap_unsafe_seed_stake_result.stderr
    )
    print("✅ Swap without slippage protection seed stake finalized")

    # Verify stake was added
    alice_stake_before_swap_unsafe = exec_command_alice(
        command="stake",
        sub_command="list",
        extra_args=[
            "--wallet-path",
            wallet_path_alice,
            "--wallet-name",
            wallet_alice.name,
            "--chain",
            "ws://127.0.0.1:9945",
            "--no-prompt",
            "--verbose",
            "--json-output",
        ],
    )
    alice_stake_list_before_swap_unsafe = json.loads(
        alice_stake_before_swap_unsafe.stdout
    )
    alice_stakes_before_swap_unsafe = find_stake_entries(
        alice_stake_list_before_swap_unsafe,
        netuid=4,
        hotkey_ss58=wallet_alice.hotkey.ss58_address,
    )
    assert len(alice_stakes_before_swap_unsafe) > 0
    assert any(stake["stake_value"] >= 20 for stake in alice_stakes_before_swap_unsafe)

    # Swap stake without slippage protection (--unsafe)
    # Swap to root netuid (0) which has more liquidity
    swap_unsafe_amount = 20
    swap_unsafe_result = exec_command_alice(
        command="stake",
        sub_command="swap",
        extra_args=[
            "--origin-netuid",
            "4",
            "--wallet-path",
            wallet_path_alice,
            "--wallet-name",
            wallet_alice.name,
            "--wallet-hotkey",
            wallet_alice.hotkey_str,
            "--dest-netuid",
            "0",  # Root netuid has more liquidity
            "--amount",
            str(swap_unsafe_amount),
            "--chain",
            "ws://127.0.0.1:9945",
            "--no-prompt",
            "--unsafe",
        ],
    )
    assert "✅ Sent" in swap_unsafe_result.stdout, swap_unsafe_result.stderr

    # Verify stake was swapped
    alice_stake_after_swap_unsafe = exec_command_alice(
        command="stake",
        sub_command="list",
        extra_args=[
            "--wallet-path",
            wallet_path_alice,
            "--wallet-name",
            wallet_alice.name,
            "--chain",
            "ws://127.0.0.1:9945",
            "--no-prompt",
            "--verbose",
            "--json-output",
        ],
    )
    alice_stake_list_after_swap_unsafe = json.loads(
        alice_stake_after_swap_unsafe.stdout
    )
    alice_stakes_after_swap_unsafe = find_stake_entries(
        alice_stake_list_after_swap_unsafe,
        netuid=0,  # Root netuid
        hotkey_ss58=wallet_alice.hotkey.ss58_address,
    )
    assert len(alice_stakes_after_swap_unsafe) > 0
    assert any(
        stake["stake_value"] >= swap_unsafe_amount
        for stake in alice_stakes_after_swap_unsafe
    )
    print("✅ TEST 2: Swap without slippage protection completed successfully")

    ################################
    # TEST 3: Transfer with slippage protection (--safe --tolerance)
    ################################

    # Add stake for transfer test with slippage protection
    transfer_safe_seed_stake_result = exec_command_alice(
        command="stake",
        sub_command="add",
        extra_args=[
            "--netuid",
            "0",
            "--wallet-path",
            wallet_path_alice,
            "--wallet-name",
            wallet_alice.name,
            "--hotkey",
            wallet_alice.hotkey_str,
            "--chain",
            "ws://127.0.0.1:9945",
            "--amount",
            "25",
            "--no-prompt",
            "--era",
            "144",
            "--unsafe",
            "--no-mev-protection",
        ],
    )
    assert "✅ Finalized" in transfer_safe_seed_stake_result.stdout, (
        transfer_safe_seed_stake_result.stderr
    )
    print("✅ Transfer with slippage protection seed stake finalized")

    # Verify stake was added
    alice_stake_before_transfer_safe = exec_command_alice(
        command="stake",
        sub_command="list",
        extra_args=[
            "--wallet-path",
            wallet_path_alice,
            "--wallet-name",
            wallet_alice.name,
            "--chain",
            "ws://127.0.0.1:9945",
            "--no-prompt",
            "--verbose",
            "--json-output",
        ],
    )
    alice_stake_list_before_transfer_safe = json.loads(
        alice_stake_before_transfer_safe.stdout
    )
    alice_stakes_before_transfer_safe = find_stake_entries(
        alice_stake_list_before_transfer_safe,
        netuid=0,
        hotkey_ss58=wallet_alice.hotkey.ss58_address,
    )
    assert len(alice_stakes_before_transfer_safe) > 0
    assert any(
        stake["stake_value"] >= 20 for stake in alice_stakes_before_transfer_safe
    )

    # Transfer stake with slippage protection (--safe --tolerance)
    transfer_safe_amount = 20
    transfer_safe_result = exec_command_alice(
        command="stake",
        sub_command="transfer",
        extra_args=[
            "--origin-netuid",
            "0",
            "--wallet-path",
            wallet_path_alice,
            "--wallet-name",
            wallet_alice.name,
            "--wallet-hotkey",
            wallet_alice.hotkey_str,
            "--dest-netuid",
            "0",
            "--dest",
            wallet_bob.coldkeypub.ss58_address,
            "--amount",
            str(transfer_safe_amount),
            "--chain",
            "ws://127.0.0.1:9945",
            "--no-prompt",
            "--safe",
            "--tolerance",
            "0.1",  # 10% tolerance
        ],
    )
    assert "✅ Sent" in transfer_safe_result.stdout, transfer_safe_result.stderr

    # Verify stake was transferred
    bob_stake_after_transfer_safe = exec_command_bob(
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
            "--json-output",
        ],
    )
    bob_stake_list_after_transfer_safe = json.loads(
        bob_stake_after_transfer_safe.stdout
    )
    bob_stakes_after_transfer_safe = find_stake_entries(
        bob_stake_list_after_transfer_safe,
        netuid=0,
    )
    assert len(bob_stakes_after_transfer_safe) > 0
    assert any(
        stake["stake_value"] >= transfer_safe_amount
        for stake in bob_stakes_after_transfer_safe
    )
    print("✅ TEST 3: Transfer with slippage protection completed successfully")

    ################################
    # TEST 4: Transfer without slippage protection (--unsafe)
    ################################

    # Add stake for transfer test without slippage protection
    transfer_unsafe_seed_stake_result = exec_command_alice(
        command="stake",
        sub_command="add",
        extra_args=[
            "--netuid",
            "0",
            "--wallet-path",
            wallet_path_alice,
            "--wallet-name",
            wallet_alice.name,
            "--hotkey",
            wallet_alice.hotkey_str,
            "--chain",
            "ws://127.0.0.1:9945",
            "--amount",
            "25",
            "--no-prompt",
            "--era",
            "144",
            "--unsafe",
            "--no-mev-protection",
        ],
    )
    assert "✅ Finalized" in transfer_unsafe_seed_stake_result.stdout, (
        transfer_unsafe_seed_stake_result.stderr
    )
    print("✅ Transfer without slippage protection seed stake finalized")

    # Verify stake was added
    alice_stake_before_transfer_unsafe = exec_command_alice(
        command="stake",
        sub_command="list",
        extra_args=[
            "--wallet-path",
            wallet_path_alice,
            "--wallet-name",
            wallet_alice.name,
            "--chain",
            "ws://127.0.0.1:9945",
            "--no-prompt",
            "--verbose",
            "--json-output",
        ],
    )
    alice_stake_list_before_transfer_unsafe = json.loads(
        alice_stake_before_transfer_unsafe.stdout
    )
    alice_stakes_before_transfer_unsafe = find_stake_entries(
        alice_stake_list_before_transfer_unsafe,
        netuid=0,
        hotkey_ss58=wallet_alice.hotkey.ss58_address,
    )
    assert len(alice_stakes_before_transfer_unsafe) > 0
    assert any(
        stake["stake_value"] >= 20 for stake in alice_stakes_before_transfer_unsafe
    )

    # Transfer stake without slippage protection (--unsafe)
    transfer_unsafe_amount = 20
    transfer_unsafe_result = exec_command_alice(
        command="stake",
        sub_command="transfer",
        extra_args=[
            "--origin-netuid",
            "0",
            "--wallet-path",
            wallet_path_alice,
            "--wallet-name",
            wallet_alice.name,
            "--wallet-hotkey",
            wallet_alice.hotkey_str,
            "--dest-netuid",
            "0",
            "--dest",
            wallet_bob.coldkeypub.ss58_address,
            "--amount",
            str(transfer_unsafe_amount),
            "--chain",
            "ws://127.0.0.1:9945",
            "--no-prompt",
            "--unsafe",
        ],
    )
    assert "✅ Sent" in transfer_unsafe_result.stdout, transfer_unsafe_result.stderr

    # Verify stake was transferred
    bob_stake_after_transfer_unsafe = exec_command_bob(
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
            "--json-output",
        ],
    )
    bob_stake_list_after_transfer_unsafe = json.loads(
        bob_stake_after_transfer_unsafe.stdout
    )
    bob_stakes_after_transfer_unsafe = find_stake_entries(
        bob_stake_list_after_transfer_unsafe,
        netuid=0,
    )
    assert len(bob_stakes_after_transfer_unsafe) > 0
    assert any(
        stake["stake_value"] >= transfer_unsafe_amount
        for stake in bob_stakes_after_transfer_unsafe
    )
    print("✅ TEST 4: Transfer without slippage protection completed successfully")

    ################################
    # TEST 5: Swap with slippage protection and partial stake (--safe --tolerance --partial)
    ################################

    # Add stake for swap test with partial stake option
    swap_partial_seed_stake_result = exec_command_alice(
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
            "25",
            "--no-prompt",
            "--era",
            "144",
            "--unsafe",
            "--no-mev-protection",
        ],
    )
    assert "✅ Finalized" in swap_partial_seed_stake_result.stdout, (
        swap_partial_seed_stake_result.stderr
    )
    print("✅ Swap with partial stake seed stake finalized")

    # Verify stake was added
    alice_stake_before_swap_partial = exec_command_alice(
        command="stake",
        sub_command="list",
        extra_args=[
            "--wallet-path",
            wallet_path_alice,
            "--wallet-name",
            wallet_alice.name,
            "--chain",
            "ws://127.0.0.1:9945",
            "--no-prompt",
            "--verbose",
            "--json-output",
        ],
    )
    alice_stake_list_before_swap_partial = json.loads(
        alice_stake_before_swap_partial.stdout
    )
    alice_stakes_before_swap_partial = find_stake_entries(
        alice_stake_list_before_swap_partial,
        netuid=2,
        hotkey_ss58=wallet_alice.hotkey.ss58_address,
    )
    assert len(alice_stakes_before_swap_partial) > 0
    assert any(stake["stake_value"] >= 20 for stake in alice_stakes_before_swap_partial)

    # Swap stake with slippage protection and partial stake (--safe --tolerance --partial)
    swap_partial_amount = 20
    swap_partial_result = exec_command_alice(
        command="stake",
        sub_command="swap",
        extra_args=[
            "--origin-netuid",
            "2",
            "--wallet-path",
            wallet_path_alice,
            "--wallet-name",
            wallet_alice.name,
            "--wallet-hotkey",
            wallet_alice.hotkey_str,
            "--dest-netuid",
            "0",  # Root netuid has more liquidity
            "--amount",
            str(swap_partial_amount),
            "--chain",
            "ws://127.0.0.1:9945",
            "--no-prompt",
            "--safe",
            "--tolerance",
            "0.1",  # 10% tolerance
            "--partial",  # Allow partial stake if rates change
        ],
    )
    assert "✅ Sent" in swap_partial_result.stdout, swap_partial_result.stderr

    # Verify stake was swapped (may be partial)
    alice_stake_after_swap_partial = exec_command_alice(
        command="stake",
        sub_command="list",
        extra_args=[
            "--wallet-path",
            wallet_path_alice,
            "--wallet-name",
            wallet_alice.name,
            "--chain",
            "ws://127.0.0.1:9945",
            "--no-prompt",
            "--verbose",
            "--json-output",
        ],
    )
    alice_stake_list_after_swap_partial = json.loads(
        alice_stake_after_swap_partial.stdout
    )
    alice_stakes_after_swap_partial = find_stake_entries(
        alice_stake_list_after_swap_partial,
        netuid=0,  # Root netuid
        hotkey_ss58=wallet_alice.hotkey.ss58_address,
    )
    # With partial stake, we expect at least some stake to be swapped
    assert len(alice_stakes_after_swap_partial) > 0
    print(
        "✅ TEST 5: Swap with slippage protection and partial stake completed successfully"
    )

    ################################
    # TEST 6: Transfer with slippage protection and partial stake (--safe --tolerance --partial)
    ################################

    # Add stake for transfer test with partial stake option
    transfer_partial_seed_stake_result = exec_command_alice(
        command="stake",
        sub_command="add",
        extra_args=[
            "--netuid",
            "0",
            "--wallet-path",
            wallet_path_alice,
            "--wallet-name",
            wallet_alice.name,
            "--hotkey",
            wallet_alice.hotkey_str,
            "--chain",
            "ws://127.0.0.1:9945",
            "--amount",
            "25",
            "--no-prompt",
            "--era",
            "144",
            "--unsafe",
            "--no-mev-protection",
        ],
    )
    assert "✅ Finalized" in transfer_partial_seed_stake_result.stdout, (
        transfer_partial_seed_stake_result.stderr
    )
    print("✅ Transfer with partial stake seed stake finalized")

    # Verify stake was added
    alice_stake_before_transfer_partial = exec_command_alice(
        command="stake",
        sub_command="list",
        extra_args=[
            "--wallet-path",
            wallet_path_alice,
            "--wallet-name",
            wallet_alice.name,
            "--chain",
            "ws://127.0.0.1:9945",
            "--no-prompt",
            "--verbose",
            "--json-output",
        ],
    )
    alice_stake_list_before_transfer_partial = json.loads(
        alice_stake_before_transfer_partial.stdout
    )
    alice_stakes_before_transfer_partial = find_stake_entries(
        alice_stake_list_before_transfer_partial,
        netuid=0,
        hotkey_ss58=wallet_alice.hotkey.ss58_address,
    )
    assert len(alice_stakes_before_transfer_partial) > 0
    assert any(
        stake["stake_value"] >= 20 for stake in alice_stakes_before_transfer_partial
    )

    # Transfer stake with slippage protection and partial stake (--safe --tolerance --partial)
    transfer_partial_amount = 20
    transfer_partial_result = exec_command_alice(
        command="stake",
        sub_command="transfer",
        extra_args=[
            "--origin-netuid",
            "0",
            "--wallet-path",
            wallet_path_alice,
            "--wallet-name",
            wallet_alice.name,
            "--wallet-hotkey",
            wallet_alice.hotkey_str,
            "--dest-netuid",
            "0",
            "--dest",
            wallet_bob.coldkeypub.ss58_address,
            "--amount",
            str(transfer_partial_amount),
            "--chain",
            "ws://127.0.0.1:9945",
            "--no-prompt",
            "--safe",
            "--tolerance",
            "0.1",  # 10% tolerance
            "--partial",  # Allow partial stake if rates change
        ],
    )
    assert "✅ Sent" in transfer_partial_result.stdout, transfer_partial_result.stderr

    # Verify stake was transferred (may be partial)
    bob_stake_after_transfer_partial = exec_command_bob(
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
            "--json-output",
        ],
    )
    bob_stake_list_after_transfer_partial = json.loads(
        bob_stake_after_transfer_partial.stdout
    )
    bob_stakes_after_transfer_partial = find_stake_entries(
        bob_stake_list_after_transfer_partial,
        netuid=0,
    )
    # With partial stake, we expect at least some stake to be transferred
    assert len(bob_stakes_after_transfer_partial) > 0
    print(
        "✅ TEST 6: Transfer with slippage protection and partial stake completed successfully"
    )

    print("✅ Passed all slippage protection tests for swap and transfer commands")
