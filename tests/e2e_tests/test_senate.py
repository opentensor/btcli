"""
Verify commands:

* btcli root senate
* btcli root proposals
* btcli root senate-vote
* btcli root register
"""

import asyncio
from .utils import call_add_proposal


def test_senate(local_chain, wallet_setup):
    """
    Test the senate functionality in Bittensor
    Steps:
        1. Create a wallet for Bob & Alice
        2. Assert bob is not part of the senate, and register to senate through
        registering to root
        3. Assert Bob is now part of the senate by fetching senate list
        4. Manually add a proposal to the chain & verify
        5. Vote on the proposal by Bob (vote aye) & assert
        6. Register Alice on root (auto becomes a senator)
        7. Vote on the proposal by Alice (vote nay) & assert


    Raises:
        AssertionError: If any of the checks or verifications fail
    """
    print("Testing Senate commands 🧪")

    wallet_path_bob = "//Bob"
    wallet_path_alice = "//Alice"

    # Create wallet for Bob - he will vote aye
    keypair_bob, wallet_bob, wallet_path_bob, exec_command_bob = wallet_setup(
        wallet_path_bob
    )
    # Create wallet for Alice - she will vote nay
    keypair_alice, wallet_alice, wallet_path_alice, exec_command_alice = wallet_setup(
        wallet_path_alice
    )

    # Fetch existing senate list
    root_senate = exec_command_bob(
        command="root",
        sub_command="senate",
        extra_args=[
            "--chain",
            "ws://127.0.0.1:9945",
        ],
    )

    # Assert Bob is not part of the senate yet
    assert wallet_bob.hotkey.ss58_address not in root_senate.stdout

    # Register Bob to the root network (0)
    # Registering to root automatically makes you a senator if eligible
    root_register = exec_command_bob(
        command="root",
        sub_command="register",
        extra_args=[
            "--wallet-path",
            wallet_path_bob,
            "--chain",
            "ws://127.0.0.1:9945",
            "--wallet-name",
            wallet_bob.name,
            "--hotkey",
            wallet_bob.hotkey_str,
            "--network",
            "local",
            "--no-prompt",
        ],
    )
    assert "✅ Registered" in root_register.stdout

    # Fetch the senate members after registering to root
    root_senate_after_reg = exec_command_bob(
        command="root",
        sub_command="senate",
        extra_args=[
            "--chain",
            "ws://127.0.0.1:9945",
        ],
    )

    # Assert Bob is now part of the senate
    assert wallet_bob.hotkey.ss58_address in root_senate_after_reg.stdout
    
    # Manually add a proposal on the chain & assert
    success = asyncio.run(call_add_proposal(local_chain, wallet_bob))
    assert success is True

    # Fetch proposals after adding one
    proposals = exec_command_bob(
        command="root",
        sub_command="proposals",
        extra_args=[
            "--chain",
            "ws://127.0.0.1:9945",
        ],
    )
    proposals_output = proposals.stdout.splitlines()[8].split()

    # Assert the hash is of correct format
    assert len(proposals_output[0]) == 66
    assert proposals_output[0][0:2] == "0x"

    # 0 Ayes for the proposal
    assert proposals_output[2] == "0"

    # 0 Nayes for the proposal
    assert proposals_output[3] == "0"

    # Assert initial threshold is 3
    assert proposals_output[1] == "3"

    # Vote on the proposal by Bob (vote aye)
    vote_aye = exec_command_bob(
        command="root",
        sub_command="senate-vote",
        extra_args=[
            "--wallet-path",
            wallet_path_bob,
            "--chain",
            "ws://127.0.0.1:9945",
            "--wallet-name",
            wallet_bob.name,
            "--hotkey",
            wallet_bob.hotkey_str,
            "--proposal-hash",
            proposals_output[0],
            "--vote-aye",
            "--no-prompt",
        ],
    )
    assert "✅ Vote cast" in vote_aye.stdout

    # Fetch proposals after voting aye
    proposals_after_aye = exec_command_bob(
        command="root",
        sub_command="proposals",
        extra_args=[
            "--chain",
            "ws://127.0.0.1:9945",
        ],
    )
    proposals_after_aye_output = proposals_after_aye.stdout.splitlines()[8].split()

    # Assert Bob's vote is shown as aye
    assert proposals_after_aye_output[4].strip(":") == wallet_bob.hotkey.ss58_address
    assert proposals_after_aye_output[5] == "Aye"

    # Aye votes increased to 1
    assert proposals_after_aye_output[2] == '1'

    # Nay votes remain 0
    assert proposals_after_aye_output[3] == '0'

    # Register Alice to the root network (0)
    # Registering to root automatically makes you a senator if eligible
    root_register = exec_command_alice(
        command="root",
        sub_command="register",
        extra_args=[
            "--wallet-path",
            wallet_path_alice,
            "--chain",
            "ws://127.0.0.1:9945",
            "--wallet-name",
            wallet_alice.name,
            "--hotkey",
            wallet_alice.hotkey_str,
            "--network",
            "local",
            "--no-prompt",
        ],
    )
    assert "✅ Registered" in root_register.stdout

    # Vote on the proposal by Alice (vote nay)
    vote_nay = exec_command_alice(
        command="root",
        sub_command="senate-vote",
        extra_args=[
            "--wallet-path",
            wallet_path_alice,
            "--chain",
            "ws://127.0.0.1:9945",
            "--wallet-name",
            wallet_alice.name,
            "--hotkey",
            wallet_alice.hotkey_str,
            "--proposal-hash",
            proposals_output[0],
            "--vote-nay",
            "--no-prompt",
        ],
    )
    assert "✅ Vote cast" in vote_nay.stdout

    # Fetch proposals after voting
    proposals_after_nay = exec_command_bob(
        command="root",
        sub_command="proposals",
        extra_args=[
            "--chain",
            "ws://127.0.0.1:9945",
        ],
    )
    proposals_after_nay_output = proposals_after_nay.stdout.splitlines()

    # Total Ayes to remain 1
    proposals_after_nay_output[8].split()[2] == "1"

    # Total Nays increased to 1
    proposals_after_nay_output[8].split()[3] == "1"

    # Assert Alice has voted Nay
    proposals_after_nay_output[9].split()[0].strip(
        ":"
    ) == wallet_alice.hotkey.ss58_address

    # Assert vote casted as Nay
    proposals_after_nay_output[9].split()[1] == "Nay"

    print("✅ Passed senate commands")
