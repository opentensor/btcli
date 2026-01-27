import asyncio
import json

from .utils import (
    find_stake_entries,
)


def _wait_until_block(substrate, target_block: int):
    async def _wait():
        while True:
            head = await substrate.get_chain_head()
            current = await substrate.get_block_number(block_hash=head)
            if current >= target_block:
                return current
            await asyncio.sleep(1)

    return asyncio.run(_wait())


def test_coldkey_swap_happy_path(local_chain, wallet_setup):
    """
    Green path coldkey swap:
        0. Bob registers on root and adds stake.
        1. Bob announces coldkey swap.
        2. Status shows pending.
        3. Wait until execution block.
        4. Execute swap.
        5. Status clear and root stake moves to new coldkey.
    """
    print("Testing coldkey swap happy path 🧪")
    wallet_path_bob = "//Bob"
    wallet_path_new = "//Charlie"

    _, wallet_bob, path_bob, exec_command_bob = wallet_setup(wallet_path_bob)
    _, wallet_new, path_new, _ = wallet_setup(wallet_path_new)
    netuid = 2

    # Create a new subnet by Bob
    create_sn = exec_command_bob(
        command="subnets",
        sub_command="create",
        extra_args=[
            "--wallet-path",
            path_bob,
            "--wallet-name",
            wallet_bob.name,
            "--wallet-hotkey",
            wallet_bob.hotkey_str,
            "--chain",
            "ws://127.0.0.1:9945",
            "--subnet-name",
            "Test Subnet CK Swap",
            "--repo",
            "https://github.com/opentensor/subnet-repo",
            "--contact",
            "bob@opentensor.dev",
            "--url",
            "https://subnet.example.com",
            "--discord",
            "bob#1234",
            "--description",
            "Subnet for coldkey swap e2e",
            "--logo-url",
            "https://subnet.example.com/logo.png",
            "--additional-info",
            "Created for e2e coldkey swap test",
            "--no-prompt",
            "--json-output",
            "--no-mev-protection",
        ],
    )
    create_payload = json.loads(create_sn.stdout)
    assert create_payload["success"] is True

    # Start emission schedule
    start_sn = exec_command_bob(
        command="subnets",
        sub_command="start",
        extra_args=[
            "--netuid",
            str(2),
            "--wallet-name",
            wallet_bob.name,
            "--wallet-path",
            path_bob,
            "--network",
            "ws://127.0.0.1:9945",
            "--no-prompt",
        ],
    )
    assert "Successfully started subnet" in start_sn.stdout, start_sn.stdout

    # Add stake to the new subnet
    stake_add = exec_command_bob(
        command="stake",
        sub_command="add",
        extra_args=[
            "--netuid",
            str(netuid),
            "--wallet-path",
            path_bob,
            "--wallet-name",
            wallet_bob.name,
            "--hotkey",
            wallet_bob.hotkey_str,
            "--chain",
            "ws://127.0.0.1:9945",
            "--amount",
            "5",
            "--unsafe",
            "--no-prompt",
            "--no-mev-protection",
        ],
    )
    assert "✅ Finalized" in stake_add.stdout, stake_add.stdout

    # Announce swap
    announce = exec_command_bob(
        command="wallet",
        sub_command="swap-coldkey",
        extra_args=[
            "announce",
            "--wallet-path",
            path_bob,
            "--wallet-name",
            wallet_bob.name,
            "--network",
            "ws://127.0.0.1:9945",
            "--new-coldkey",
            wallet_new.coldkeypub.ss58_address,
            "--no-prompt",
            "--no-mev-protection",
        ],
    )
    assert "Successfully announced coldkey swap" in announce.stdout, announce.stdout

    # Fetch announcement and wait until executable
    status_json = exec_command_bob(
        command="wallet",
        sub_command="swap-check",
        extra_args=[
            "--wallet-path",
            path_bob,
            "--wallet-name",
            wallet_bob.name,
            "--network",
            "ws://127.0.0.1:9945",
            "--json-output",
        ],
    )
    status_payload = json.loads(status_json.stdout)
    assert status_payload["announcements"], status_payload
    when = status_payload["announcements"][0]["execution_block"]
    _wait_until_block(local_chain, when)

    # Execute swap
    execute = exec_command_bob(
        command="wallet",
        sub_command="swap-coldkey",
        extra_args=[
            "execute",
            "--wallet-path",
            path_bob,
            "--wallet-name",
            wallet_bob.name,
            "--network",
            "ws://127.0.0.1:9945",
            "--new-coldkey",
            wallet_new.coldkeypub.ss58_address,
            "--no-prompt",
            "--no-mev-protection",
        ],
    )
    assert "Successfully executed coldkey swap" in execute.stdout, execute.stdout

    # Status should clear
    status = exec_command_bob(
        command="wallet",
        sub_command="swap-check",
        extra_args=[
            "--wallet-path",
            path_bob,
            "--wallet-name",
            wallet_bob.name,
            "--network",
            "ws://127.0.0.1:9945",
        ],
    )
    assert "No pending swap announcement" in status.stdout, status.stdout

    # Stake should now be on the new coldkey
    stake_new = exec_command_bob(
        command="stake",
        sub_command="list",
        extra_args=[
            "--coldkey-ss58",
            wallet_new.coldkeypub.ss58_address,
            "--network",
            "ws://127.0.0.1:9945",
            "--json-output",
            "--no-prompt",
        ],
    )
    payload_new = json.loads(stake_new.stdout)
    new_entries = find_stake_entries(
        payload_new, netuid=netuid, hotkey_ss58=wallet_bob.hotkey.ss58_address
    )
    assert len(new_entries) > 0, "Stake not found on new coldkey"
    assert float(new_entries[0].get("value", 0)) > 0

    # Old coldkey should have no stake
    stake_old = exec_command_bob(
        command="stake",
        sub_command="list",
        extra_args=[
            "--coldkey-ss58",
            wallet_bob.coldkeypub.ss58_address,
            "--network",
            "ws://127.0.0.1:9945",
            "--json-output",
            "--no-prompt",
        ],
    )
    assert not stake_old.stdout, "Old coldkey still has stake"
