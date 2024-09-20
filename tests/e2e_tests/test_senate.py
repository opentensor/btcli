"""
Verify commands:

* btcli root senate
* btcli root proposals
* btcli root senate-vote
* btcli root nominate
* btcli root register
"""

import asyncio
from .utils import call_add_proposal


def test_senate(local_chain, wallet_setup):
    """
    Test the senate functionality in Bittensor
    Steps:
        1. Create a wallet for Bob
        2. Assert bob is not part of the senate
        3. Execute root register for Bob
        4. Assert Bob is now part of the senate
        5. Manually add a proposal to the chain

    Raises:
        AssertionError: If any of the checks or verifications fail
    """
    print("Testing Senate commands 🧪")

    wallet_path_bob = "//Bob"

    # Create wallet for Bob
    keypair_bob, wallet_bob, wallet_path_bob, exec_command_bob = wallet_setup(
        wallet_path_bob
    )

    # Fetch existing senate list
    root_senate = exec_command_bob(
        command="root",
        sub_command="senate",
        extra_args=[
            "--chain",
            "ws://127.0.0.1:9945",
        ]
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
        ]
    )

    # Assert Bob is now part of the senate
    assert wallet_bob.hotkey.ss58_address in root_senate_after_reg.stdout

    success = asyncio.run(call_add_proposal(local_chain, wallet_bob))
    assert success is True

    # Fetch proposals
    proposals = exec_command_bob(
        command="root",
        sub_command="proposals",
        extra_args=[
            "--chain",
            "ws://127.0.0.1:9945",
        ]
    )

    proposals_output = proposals.stdout.splitlines()[8].split()

    # Assert the hash is of correct format
    assert len(proposals_output[0]) == 66
    assert proposals_output[0][0:2] == "0x"
    
    # 0 Ayes for the proposal
    assert proposals_output[2] == '0'

    # 0 Nayes for the proposal
    assert proposals_output[3] == '0'

    # Assert initial threshold is 3
    assert proposals_output[1] == '3'

    vote_aye = exec_command_bob(
        command="root",
        sub_command="senate-vote",
        extra_args = [
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
            "--no-prompt"
        ]
    )

    assert "✅ Vote cast" in vote_aye.stdout
    
    # Fetch proposals
    proposals = exec_command_bob(
        command="root",
        sub_command="proposals",
        extra_args=[
            "--chain",
            "ws://127.0.0.1:9945",
        ]
    )

    proposals_output = proposals.stdout.splitlines()[8].split()