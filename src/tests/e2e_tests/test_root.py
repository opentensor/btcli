import logging
import time

from btcli.src.bittensor.balances import Balance

from .utils import setup_wallet

"""
Verify commands:

* btcli root register
* btcli root list
* btcli root list-delegates
* btcli root set-take
* btcli root delegate-stake
* btcli root my-delegates
* btcli root undelegate-stake
"""


def test_root_commands(local_chain):
    """
    Test the root commands and inspects their output

    Steps:
        1. Create wallets for Alice and Bob
        2. Register Bob in the root network -> this makes him a delegate and senator
        3. Execute root list and verify information
        4. Execute list delegates and verify information
        5. Execute set-take command, change the take to 12%, verify
        6. Execute delegate-stake command, stake from Alice to Bob

    Raises:
        AssertionError: If any of the checks or verifications fail
    """
    logging.info("Testing Root commands 🧪")

    wallet_path_alice = "//Alice"
    wallet_path_bob = "//Bob"

    # Create wallet for Alice
    keypair_alice, wallet_alice, wallet_path_alice, exec_command_alice = setup_wallet(
        wallet_path_alice
    )
    keypair_bob, wallet_bob, wallet_path_bob, exec_command_bob = setup_wallet(
        wallet_path_bob
    )

    # Register Bob to the root network (0)
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
        ],
    )
    assert "✅ Registered" in root_register.stdout

    # List all neurons in the root network
    check_root_list = exec_command_alice(
        command="root",
        sub_command="list",
        extra_args=[
            "--chain",
            "ws://127.0.0.1:9945",
            "--network",
            "local",
        ],
    )

    # Capture root information and assert correct values
    # First two rows are labels, entries start from the third row
    bob_root_info = check_root_list.stdout.splitlines()[2].split()

    # UID: First uid is always 0
    assert bob_root_info[0] == "0"

    # ADDRESS: Assert correct hotkey is registered
    assert bob_root_info[1] == wallet_bob.hotkey.ss58_address

    # SENATOR: Since there are senator slots empty, Bob is assigned senator status
    assert bob_root_info[3] == "Yes"

    # List all root delegates in the network
    check_delegates = exec_command_alice(
        command="root",
        sub_command="list-delegates",
        extra_args=[
            "--chain",
            "ws://127.0.0.1:9945",
            "--network",
            "local",
        ],
    )

    # Capture delegate information and assert correct values
    # First row are labels, entries start from the second row
    bob_delegate_info = check_delegates.stdout.splitlines()[1].split()

    # INDEX: First uid is always 0
    assert bob_delegate_info[0] == "0"

    # SS58: Assert correct hotkey for Bob
    assert wallet_bob.hotkey.ss58_address.startswith(
        bob_delegate_info[1].replace("...", "")
    )

    # NOMINATORS: This should be 0
    assert bob_delegate_info[2] == "0"

    # TAKE: (percentage) This should be 18% by default
    take_percentage = float(bob_delegate_info[7].strip("%")) / 100
    assert take_percentage == 0.18

    # DELEGATE STAKE(τ): This should be 0 as no delegation yet
    delegate_stake = Balance.from_tao(float(bob_delegate_info[3].strip("τ")))
    assert delegate_stake == Balance.from_tao(0)

    # TOTAL STAKE(τ): This should be 0 as no stake yet
    total_stake = Balance.from_tao(float(bob_delegate_info[4].strip("τ")))
    assert total_stake == Balance.from_tao(0)

    # Setting 12% as the new take
    new_take = "0.12"
    set_take = exec_command_bob(
        command="root",
        sub_command="set-take",
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
            "--take",
            new_take,
        ],
    )

    assert "✅ Finalized" in set_take.stdout
    assert "Successfully set the take" in set_take.stdout

    # List all root delegates in the network to verify take
    check_delegates = exec_command_alice(
        command="root",
        sub_command="list-delegates",
        extra_args=[
            "--chain",
            "ws://127.0.0.1:9945",
            "--network",
            "local",
        ],
    )
    # Capture delegate information after setting take
    bob_delegate_info = check_delegates.stdout.splitlines()[1].split()

    # Take percentage: This should be 18% by default
    take_percentage = float(bob_delegate_info[7].strip("%")) / 100
    assert take_percentage == float(new_take)

    # Stake to delegate Bob from Alice
    stake_delegate = exec_command_alice(
        command="root",
        sub_command="delegate-stake",
        extra_args=[
            "--wallet-path",
            wallet_path_alice,
            "--chain",
            "ws://127.0.0.1:9945",
            "--wallet-name",
            wallet_alice.name,
            "--delegate-ss58key",
            wallet_bob.hotkey.ss58_address,
            "--network",
            "local",
            "--amount",
            "10",
        ],
    )
    assert "✅ Finalized" in stake_delegate.stdout

    # List all delegates of Alice (where she has staked)
    alice_delegates = exec_command_alice(
        command="root",
        sub_command="my-delegates",
        extra_args=[
            "--wallet-path",
            wallet_path_alice,
            "--chain",
            "ws://127.0.0.1:9945",
            "--wallet-name",
            wallet_alice.name,
            "--network",
            "local",
        ],
    )
    # First row are headers, records start from second row
    alice_delegates_info = alice_delegates.stdout.splitlines()[1].split()

    # WALLET: Wallet name of Alice
    assert alice_delegates_info[0] == wallet_alice.name

    # SS58: address of the Bob's hotkey (Alice has staked to Bob)
    assert wallet_bob.hotkey.ss58_address.startswith(
        alice_delegates_info[1].replace("...", "")
    )

    # Delegation: This should be 10 as Alice delegated 10 TAO to Bob
    delegate_stake = Balance.from_tao(float(alice_delegates_info[2].strip("τ")))
    assert delegate_stake == Balance.from_tao(10)

    # TOTAL STAKE(τ): This should be 10 as only Alice has delegated to Bob
    total_stake = Balance.from_tao(float(alice_delegates_info[6].strip("τ")))
    assert total_stake == Balance.from_tao(10)

    # Total delegated Tao: This is listed at the bottom of the information
    # Since Alice has only delegated to Bob, total should be 10 TAO
    total_delegated_tao = Balance.from_tao(
        float(alice_delegates.stdout.splitlines()[3].split()[3].strip("τ"))
    )
    assert total_delegated_tao == Balance.from_tao(10)

    # TODO: Ask nucleus the rate limit and wait epoch
    # Sleep 120 seconds for rate limiting when unstaking
    print("Waiting for interval for 2 minutes")
    time.sleep(120)

    # Unstake from Bob Delegate
    undelegate_alice = exec_command_alice(
        command="root",
        sub_command="undelegate-stake",
        extra_args=[
            "--wallet-path",
            wallet_path_alice,
            "--chain",
            "ws://127.0.0.1:9945",
            "--wallet-name",
            wallet_alice.name,
            "--delegate-ss58key",
            wallet_bob.hotkey.ss58_address,
            "--network",
            "local",
            "--amount",
            "10",
        ],
    )
    print(undelegate_alice)
