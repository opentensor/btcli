from btcli.src.bittensor.balances import Balance

from .utils import setup_wallet, extract_coldkey_balance

"""
Verify commands:

* btcli w balance
* btcli w transfer
"""


def test_wallet_transfer(local_chain):
    """
    Test the transfer and balance functionality in the Bittensor network.

    Steps:
        1. Create wallets for Alice and Bob with initial balance already
        2. Ensure initial balance is displayed correctly
        3. Transfer 100 TAO from Alice to Bob
        4. Assert amount was transferred along with transfer tolerance
        5. Assert transfer fails with no balance for Anakin

    Raises:
        AssertionError: If any of the checks or verifications fail
    """
    wallet_path_alice = "//Alice"
    wallet_path_bob = "//Bob"

    # Create wallets for Alice and Bob
    keypair_alice, wallet_alice, wallet_path_alice, exec_command_alice = setup_wallet(
        wallet_path_alice
    )
    keypair_bob, wallet_bob, wallet_path_bob, exec_command_bob = setup_wallet(
        wallet_path_bob
    )

    # Both Alice and Bob have initial balance through the local chain
    alice_bob_initial_balance = Balance.from_tao(1_000_000)

    # Check balance of Alice
    result = exec_command_alice(
        command="wallet",
        sub_command="balance",
        extra_args=[
            "--wallet-path",
            wallet_path_alice,
            "--chain",
            "ws://127.0.0.1:9945",
            "--wallet-name",
            "default",
            "--network",
            "local",
        ],
    )

    # Assert correct address is displayed
    assert keypair_alice.ss58_address in result.stdout

    # Assert correct initial balance is shown
    initial_balance = Balance.from_tao(
        extract_coldkey_balance(
            result.stdout,
            wallet_name=wallet_alice.name,
            coldkey_address=wallet_alice.coldkey.ss58_address,
        )["free_balance"]
    )
    assert initial_balance == alice_bob_initial_balance

    # Transfer of 100 tao for this test
    expected_transfer = Balance.from_tao(100)

    # Execute the transfer command, with Bob's address as destination
    result = exec_command_alice(
        command="wallet",
        sub_command="transfer",
        extra_args=[
            "--dest",
            keypair_bob.ss58_address,
            "--wallet-path",
            wallet_path_alice,
            "--chain",
            "ws://127.0.0.1:9945",
            "--wallet-name",
            "default",
            "--network",
            "local",
            "--amount",
            "100",
        ],
    )

    # To-do: Assert correct output once transfer is fixed

    # Check balance of Alice after transfer
    result = exec_command_alice(
        command="wallet",
        sub_command="balance",
        extra_args=[
            "--wallet-path",
            wallet_path_alice,
            "--chain",
            "ws://127.0.0.1:9945",
            "--wallet-name",
            "default",
            "--network",
            "local",
        ],
    )

    # Extract balance after the transfer
    balance_remaining = Balance.from_tao(
        extract_coldkey_balance(
            result.stdout,
            wallet_name=wallet_alice.name,
            coldkey_address=wallet_alice.coldkey.ss58_address,
        )["free_balance"]
    )

    tolerance = Balance.from_rao(200_000)  # Tolerance for transaction fee
    balance_difference = initial_balance - balance_remaining

    # Assert transfer was successful w.r.t tolerance
    assert expected_transfer <= balance_difference <= expected_transfer + tolerance

    # Check balance of Bob after transfer
    result = exec_command_bob(
        command="wallet",
        sub_command="balance",
        extra_args=[
            "--wallet-path",
            wallet_path_bob,
            "--chain",
            "ws://127.0.0.1:9945",
            "--wallet-name",
            "default",
            "--network",
            "local",
        ],
    )

    # Extract Bob's balance from output
    new_balance_bob = Balance.from_tao(
        extract_coldkey_balance(
            result.stdout,
            wallet_name=wallet_bob.name,
            coldkey_address=wallet_bob.coldkey.ss58_address,
        )["free_balance"]
    )

    # Assert correct balance was transferred from Bob
    assert alice_bob_initial_balance + expected_transfer == new_balance_bob

    wallet_path_anakin = "//Anakin"
    keypair_anakin, wallet_anakin, wallet_path_anakin, exec_command_anakin = (
        setup_wallet(wallet_path_anakin)
    )

    # Attempt transferring to Alice
    result = exec_command_anakin(
        command="wallet",
        sub_command="transfer",
        extra_args=[
            "--dest",
            keypair_alice.ss58_address,
            "--wallet-path",
            wallet_path_anakin,
            "--chain",
            "ws://127.0.0.1:9945",
            "--wallet-name",
            "default",
            "--network",
            "local",
            "--amount",
            "100",
        ],
    )

    # This transfer is expected to fail due to low balance
    assert "❌ Not enough balance" in result.stdout
