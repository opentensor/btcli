import time

from bittensor_cli.src.bittensor.balances import Balance
from .utils import extract_coldkey_balance

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


def test_root_commands(local_chain, wallet_setup):
    """
    Test the root commands and inspects their output

    Steps:
        1. Create wallets for Alice and Bob
        2. Register Bob in the root network -> this makes him a delegate and senator
        3. Execute root list and verify information
        4. Execute list delegates and verify information
        5. Execute set-take command, change the take to 12%, verify
        6. Execute delegate-stake command, stake from Alice to Bob
        7. Execute undelegate-stake command, unstake from Bob to Alice
        8. Execute delegate-stake command, stake all from Alice to Bob
        9. Execute undelegate-stake command, unstake all from Bob to Alice

    Raises:
        AssertionError: If any of the checks or verifications fail
    """
    print("Testing Root commands 🧪")

    wallet_path_alice = "//Alice"
    wallet_path_bob = "//Bob"

    # Create wallet for Alice
    keypair_alice, wallet_alice, wallet_path_alice, exec_command_alice = wallet_setup(
        wallet_path_alice
    )
    keypair_bob, wallet_bob, wallet_path_bob, exec_command_bob = wallet_setup(
        wallet_path_bob
    )

    # Register Bob to the root network (0)
    root_register = exec_command_bob(
        command="root",
        sub_command="register",
        extra_args=[
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
    assert "✅ Registered" in root_register.stdout

    # List all neurons in the root network
    check_root_list = exec_command_alice(
        command="root",
        sub_command="list",
        extra_args=[
            "--network",
            "ws://127.0.0.1:9945",
        ],
    )

    # Capture root information and assert correct values
    # First two rows are labels, entries start from the third row
    bob_root_info = check_root_list.stdout.splitlines()[4].split()

    # UID: First uid is always 0
    assert bob_root_info[0] == "0"

    # ADDRESS: Assert correct hotkey is registered
    assert bob_root_info[4] == wallet_bob.hotkey.ss58_address

    # SENATOR: Since there are senator slots empty, Bob is assigned senator status
    assert bob_root_info[8] == "Yes"

    # List all root delegates in the network
    check_delegates = exec_command_alice(
        command="root",
        sub_command="list-delegates",
        extra_args=[
            "--network",
            "ws://127.0.0.1:9945",
        ],
    )

    # Capture delegate information and assert correct values
    # First row are labels, entries start from the second row
    bob_delegate_info = check_delegates.stdout.splitlines()[6].split()

    # INDEX: First uid is always 0
    assert bob_delegate_info[0] == "0"

    # SS58: Assert correct hotkey for Bob
    assert wallet_bob.hotkey.ss58_address == bob_delegate_info[2]

    # NOMINATORS: This should be 0
    assert bob_delegate_info[3] == "0"

    # TAKE: (percentage) This should be 18% by default
    take_percentage = float(bob_delegate_info[7].strip("%")) / 100
    assert take_percentage == 0.18

    # DELEGATE STAKE(τ): This should be 0 as no delegation yet
    delegate_stake = Balance.from_tao(string_tao_to_float(bob_delegate_info[4]))
    assert delegate_stake == Balance.from_tao(0)

    # TOTAL STAKE(τ): This should be 0 as no stake yet
    total_stake = Balance.from_tao(string_tao_to_float(bob_delegate_info[5]))
    assert total_stake == Balance.from_tao(0)

    # Setting 12% as the new take
    new_take = "0.12"
    set_take = exec_command_bob(
        command="root",
        sub_command="set-take",
        extra_args=[
            "--wallet-path",
            wallet_path_bob,
            "--network",
            "ws://127.0.0.1:9945",
            "--wallet-name",
            wallet_bob.name,
            "--hotkey",
            wallet_bob.hotkey_str,
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
            "--network",
            "ws://127.0.0.1:9945",
        ],
    )
    # Capture delegate information after setting take
    bob_delegate_info = check_delegates.stdout.splitlines()[6].split()

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
            "--network",
            "ws://127.0.0.1:9945",
            "--wallet-name",
            wallet_alice.name,
            "--delegate-ss58key",
            wallet_bob.hotkey.ss58_address,
            "--amount",
            "10",
            "--no-prompt",
        ],
    )
    assert "✅ Finalized" in stake_delegate.stdout

    check_my_delegates(
        exec_command=exec_command_alice,
        wallet=wallet_alice,
        delegate_ss58key=wallet_bob.hotkey.ss58_address,
        delegate_amount=10,
    )

    check_balance(
        exec_command=exec_command_alice,
        wallet=wallet_alice,
        expected_balance={
            "free_balance": 999990.0,
            "staked_balance": 10.0,
            "total_balance": 1000000.0,
        },
    )

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
            "--network",
            "ws://127.0.0.1:9945",
            "--wallet-name",
            wallet_alice.name,
            "--delegate-ss58key",
            wallet_bob.hotkey.ss58_address,
            "--amount",
            "10",
            "--no-prompt",
        ],
    )
    time.sleep(10)
    assert "✅ Finalized" in undelegate_alice.stdout

    check_balance(
        exec_command=exec_command_alice,
        wallet=wallet_alice,
        expected_balance={
            "free_balance": 1000000.0,
            "staked_balance": 0.0,
            "total_balance": 1000000.0,
        },
    )

    # TODO: Ask nucleus the rate limit and wait epoch
    # Sleep 120 seconds for rate limiting when unstaking
    print("Waiting for interval for 2 minutes")
    time.sleep(120)

    # Stake to delegate Bob from Alice
    stake_delegate = exec_command_alice(
        command="root",
        sub_command="delegate-stake",
        extra_args=[
            "--wallet-path",
            wallet_path_alice,
            "--network",
            "ws://127.0.0.1:9945",
            "--wallet-name",
            wallet_alice.name,
            "--delegate-ss58key",
            wallet_bob.hotkey.ss58_address,
            "--all",
            "--no-prompt",
        ],
    )
    assert "✅ Finalized" in stake_delegate.stdout

    # check_my_delegates(
    #     exec_command=exec_command_alice,
    #     wallet=wallet_alice,
    #     delegate_ss58key=wallet_bob.hotkey.ss58_address,
    #     delegate_amount=999999.9999995
    # )

    check_balance(
        exec_command=exec_command_alice,
        wallet=wallet_alice,
        expected_balance={
            "free_balance": 0.0000005,
            "staked_balance": 999999.9999995,
            "total_balance": 1000000.0,
        },
    )

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
            "--network",
            "ws://127.0.0.1:9945",
            "--wallet-name",
            wallet_alice.name,
            "--delegate-ss58key",
            wallet_bob.hotkey.ss58_address,
            "--all",
            "--no-prompt",
        ],
    )
    assert "✅ Finalized" in undelegate_alice.stdout

    check_balance(
        exec_command=exec_command_alice,
        wallet=wallet_alice,
        expected_balance={
            "free_balance": 1000000.0,
            "staked_balance": 0.0,
            "total_balance": 1000000.0,
        },
    )

    print("✅ Passed Root commands")


def check_my_delegates(exec_command, wallet, delegate_ss58key, delegate_amount):
    # List all delegates of Alice (where she has staked)
    delegates = exec_command(
        command="root",
        sub_command="my-delegates",
        extra_args=[
            "--wallet-path",
            wallet.path,
            "--network",
            "ws://127.0.0.1:9945",
            "--wallet-name",
            wallet.name,
        ],
    )
    # First row are headers, records start from second row
    delegates_info = delegates.stdout.splitlines()[5].split()
    # WALLET: Wallet name of Alice
    assert delegates_info[0] == wallet.name
    # SS58: address of the Bob's hotkey (Alice has staked to Bob)
    assert delegate_ss58key == delegates_info[2]
    # Delegation: This should be `delegate_amount` as Alice delegated `delegate_amount` TAO to Bob
    delegate_stake = Balance.from_tao(string_tao_to_float(delegates_info[3]))
    assert delegate_stake == Balance.from_tao(delegate_amount)
    # TOTAL STAKE(τ): This should be `delegate_amount` as only Alice has delegated to Bob
    total_stake = Balance.from_tao(string_tao_to_float(delegates_info[7]))
    assert total_stake == Balance.from_tao(delegate_amount)
    # Total delegated Tao: This is listed at the bottom of the information
    # Since Alice has only delegated to Bob, total should be `delegate_amount` TAO
    total_delegated_tao = Balance.from_tao(
        string_tao_to_float(delegates.stdout.splitlines()[8].split()[3])
    )
    assert total_delegated_tao == Balance.from_tao(delegate_amount)


def check_balance(exec_command, wallet, expected_balance):
    # Check balance of Alice after registering to the subnet
    wallet_balance = exec_command(
        command="wallet",
        sub_command="balance",
        extra_args=[
            "--wallet-path",
            wallet.path,
            "--network",
            "ws://127.0.0.1:9945",
            "--wallet-name",
            wallet.name,
        ],
    )

    # Extract balance left after creating and registering into the subnet
    balance = extract_coldkey_balance(
        wallet_balance.stdout,
        wallet_name=wallet.name,
        coldkey_address=wallet.coldkey.ss58_address,
    )

    assert balance == expected_balance


def string_tao_to_float(alice_delegates_info: str) -> float:
    return float(alice_delegates_info.replace(",", "").strip("τ"))
