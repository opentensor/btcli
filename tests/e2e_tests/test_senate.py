"""
Verify commands:

* btcli root senate
* btcli root proposals
* btcli root senate-vote
* btcli root register
"""

import asyncio
import json
import pytest

from .utils import call_add_proposal


@pytest.mark.skip(
    reason="See: https://github.com/opentensor/bittensor/pull/3102. Skipping until new governance is set up."
)
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
        command="sudo",
        sub_command="senate",
        extra_args=[
            "--network",
            "ws://127.0.0.1:9945",
        ],
    )

    # Assert Bob is not part of the senate yet
    assert wallet_bob.hotkey.ss58_address not in root_senate.stdout

    # Register Bob to the root network (0)
    # Registering to root automatically makes you a senator if eligible
    root_register = exec_command_bob(
        command="subnets",
        sub_command="register",
        extra_args=[
            "--netuid",
            "0",
            "--wallet-path",
            wallet_path_bob,
            "--network",
            "ws://127.0.0.1:9945",
            "--wallet-name",
            wallet_bob.name,
            "--hotkey",
            wallet_bob.hotkey_str,
            "--no-prompt",
        ],
    )
    assert "✅ Registered" in root_register.stdout, root_register.stderr
    assert "Your extrinsic has been included " in root_register.stdout, (
        root_register.stderr
    )

    # Fetch the senate members after registering to root
    root_senate_after_reg = exec_command_bob(
        command="sudo",
        sub_command="senate",
        extra_args=[
            "--chain",
            "ws://127.0.0.1:9945",
        ],
    )

    # Assert Bob is now part of the senate
    assert wallet_bob.hotkey.ss58_address in root_senate_after_reg.stdout, (
        root_senate_after_reg.stderr
    )

    # Manually add a proposal on the chain & assert
    success = asyncio.run(call_add_proposal(local_chain, wallet_bob))
    assert success is True

    # Fetch proposals after adding one
    proposals = exec_command_bob(
        command="sudo",
        sub_command="proposals",
        extra_args=[
            "--chain",
            "ws://127.0.0.1:9945",
            "--verbose",
        ],
    )
    proposals_output = proposals.stdout.splitlines()[9].split()

    # Assert the hash is of correct format
    assert len(proposals_output[0]) == 66
    assert proposals_output[0][0:2] == "0x"

    # 0 Ayes for the proposal
    assert proposals_output[2] == "0"

    # 0 Nays for the proposal
    assert proposals_output[4] == "0"

    # Assert initial threshold is 3
    assert proposals_output[1] == "3"

    json_proposals = exec_command_bob(
        command="sudo",
        sub_command="proposals",
        extra_args=["--chain", "ws://127.0.0.1:9945", "--json-output"],
    )
    json_proposals_output = json.loads(json_proposals.stdout)

    assert len(json_proposals_output) == 1
    assert json_proposals_output[0]["threshold"] == 3
    assert json_proposals_output[0]["ayes"] == 0
    assert json_proposals_output[0]["nays"] == 0
    assert json_proposals_output[0]["votes"] == {}
    assert json_proposals_output[0]["call_data"] == "System.remark(remark: (0,))"

    # Vote on the proposal by Bob (vote aye)
    vote_aye = exec_command_bob(
        command="sudo",
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
    assert "Your extrinsic has been included " in vote_aye.stdout

    # Fetch proposals after voting aye
    proposals_after_aye = exec_command_bob(
        command="sudo",
        sub_command="proposals",
        extra_args=[
            "--chain",
            "ws://127.0.0.1:9945",
            "--verbose",
        ],
    )
    proposals_after_aye_output = proposals_after_aye.stdout.splitlines()[9].split()

    # Assert Bob's vote is shown as aye
    assert proposals_after_aye_output[6].strip(":") == wallet_bob.hotkey.ss58_address
    assert proposals_after_aye_output[7] == "Aye"

    # Aye votes increased to 1
    assert proposals_after_aye_output[2] == "1"

    # Nay votes remain 0
    assert proposals_after_aye_output[4] == "0"

    proposals_after_aye_json = exec_command_bob(
        command="sudo",
        sub_command="proposals",
        extra_args=[
            "--chain",
            "ws://127.0.0.1:9945",
            "--json-output",
        ],
    )
    proposals_after_aye_json_output = json.loads(proposals_after_aye_json.stdout)
    assert len(proposals_after_aye_json_output) == 1
    assert proposals_after_aye_json_output[0]["threshold"] == 3
    assert proposals_after_aye_json_output[0]["ayes"] == 1
    assert proposals_after_aye_json_output[0]["nays"] == 0
    assert len(proposals_after_aye_json_output[0]["votes"]) == 1
    assert proposals_after_aye_json_output[0]["votes"][keypair_bob.ss58_address] is True
    assert (
        proposals_after_aye_json_output[0]["call_data"] == "System.remark(remark: (0,))"
    )

    # Register Alice to the root network (0)
    # Registering to root automatically makes you a senator if eligible
    root_register = exec_command_alice(
        command="subnets",
        sub_command="register",
        extra_args=[
            "--netuid",
            "0",
            "--wallet-path",
            wallet_path_alice,
            "--chain",
            "ws://127.0.0.1:9945",
            "--wallet-name",
            wallet_alice.name,
            "--hotkey",
            wallet_alice.hotkey_str,
            "--no-prompt",
        ],
    )
    assert "✅ Registered" in root_register.stdout
    assert "Your extrinsic has been included " in root_register.stdout

    # Vote on the proposal by Alice (vote nay)
    vote_nay = exec_command_alice(
        command="sudo",
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
    assert "Your extrinsic has been included " in vote_nay.stdout

    # Fetch proposals after voting
    proposals_after_nay = exec_command_bob(
        command="sudo",
        sub_command="proposals",
        extra_args=[
            "--chain",
            "ws://127.0.0.1:9945",
            "--verbose",
        ],
    )
    proposals_after_nay_output = proposals_after_nay.stdout.splitlines()

    # Total Ayes to remain 1
    assert proposals_after_nay_output[9].split()[2] == "1"

    # Total Nays increased to 1
    assert proposals_after_nay_output[9].split()[4] == "1"

    # Assert Alice has voted Nay
    assert (
        proposals_after_nay_output[10].split()[0].strip(":")
        == wallet_alice.hotkey.ss58_address
    )

    # Assert vote casted as Nay
    assert proposals_after_nay_output[10].split()[1] == "Nay"

    proposals_after_nay_json = exec_command_bob(
        command="sudo",
        sub_command="proposals",
        extra_args=[
            "--chain",
            "ws://127.0.0.1:9945",
            "--json-output",
        ],
    )
    proposals_after_nay_json_output = json.loads(proposals_after_nay_json.stdout)
    assert len(proposals_after_nay_json_output) == 1
    assert proposals_after_nay_json_output[0]["nays"] == 1
    assert (
        proposals_after_nay_json_output[0]["votes"][keypair_alice.ss58_address] is False
    )

    print("✅ Passed senate commands")
