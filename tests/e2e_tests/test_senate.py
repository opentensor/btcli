"""
Verify commands:

* btcli root senate
* btcli root proposals
* btcli root senate-vote
* btcli root nominate
* btcli root register
"""

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

    # success = asyncio.run(call_add_proposal(local_chain, wallet_bob))
