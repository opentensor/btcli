from time import sleep

from bittensor_cli.src.bittensor.balances import Balance
from .utils import (
    extract_coldkey_balance,
    validate_wallet_inspect,
    validate_wallet_overview,
    verify_subnet_entry,
)

"""
Verify commands:

* btcli subnets create
* btcli subnets register
* btcli subnets list
* btcli w inspect
* btcli w overview
* btcli w balance
* btcli w transfer
* btcli w set-identity
* btcli w get-identity
* btcli w sign
"""


def test_wallet_overview_inspect(local_chain, wallet_setup):
    """
    Test the overview and inspect commands of the wallet by interaction with subnets

    Steps:
        1. Create wallet for Alice
        2. Create a subnet, execute subnet list and verify subnet creation
        3. Register Alice in the subnet and extract her balance
        4. Execute wallet overview, inspect and assert correct data is displayed

    Raises:
        AssertionError: If any of the checks or verifications fail
    """
    print("Testing wallet overview, inspect command 🧪")
    netuid = 1
    wallet_path_name = "//Alice"

    # Create wallet for Alice
    keypair, wallet, wallet_path, exec_command = wallet_setup(wallet_path_name)

    # Register a subnet with sudo as Alice
    result = exec_command(
        command="subnets",
        sub_command="create",
        extra_args=[
            "--wallet-path",
            wallet_path,
            "--chain",
            "ws://127.0.0.1:9945",
            "--wallet-name",
            wallet.name,
            "--no-prompt",
        ],
    )
    assert f"✅ Registered subnetwork with netuid: {netuid}" in result.stdout

    sleep(3)

    # List all the subnets in the network
    subnets_list = exec_command(
        command="subnets",
        sub_command="list",
        extra_args=[
            "--chain",
            "ws://127.0.0.1:9945",
        ],
    )

    sleep(3)

    # Assert using regex that the subnet is visible in subnets list
    assert verify_subnet_entry(subnets_list.stdout, netuid, keypair.ss58_address)

    # Register Alice in netuid = 1 using her hotkey
    register_subnet = exec_command(
        command="subnets",
        sub_command="register",
        extra_args=[
            "--wallet-path",
            wallet_path,
            "--wallet-name",
            wallet.name,
            "--hotkey",
            wallet.hotkey_str,
            "--netuid",
            "1",
            "--chain",
            "ws://127.0.0.1:9945",
            "--no-prompt",
        ],
    )
    assert "✅ Registered" in register_subnet.stdout

    # Check balance of Alice after registering to the subnet
    wallet_balance = exec_command(
        command="wallet",
        sub_command="balance",
        extra_args=[
            "--wallet-path",
            wallet_path,
            "--chain",
            "ws://127.0.0.1:9945",
            "--wallet-name",
            wallet.name,
        ],
    )

    # Assert correct address is displayed
    assert keypair.ss58_address in wallet_balance.stdout

    # Extract balance left after creating and registering into the subnet
    balance = extract_coldkey_balance(
        wallet_balance.stdout,
        wallet_name=wallet.name,
        coldkey_address=wallet.coldkey.ss58_address,
    )

    # Execute wallet overview command.
    wallet_overview = exec_command(
        command="wallet",
        sub_command="overview",
        extra_args=[
            "--wallet-path",
            wallet_path,
            "--wallet-name",
            wallet.name,
            "--chain",
            "ws://127.0.0.1:9945",
        ],
    )

    # Assert correct entry is present in wallet overview
    assert validate_wallet_overview(
        output=wallet_overview.stdout,
        uid=0,  # Since Alice was the first one, she has uid = 0
        coldkey=wallet.name,
        hotkey=wallet.hotkey_str,
        hotkey_ss58=keypair.ss58_address,
        axon_active=False,  # Axon is not active until we run validator/miner
    )

    # Execute wallet inspect command
    inspect = exec_command(
        command="wallet",
        sub_command="inspect",
        extra_args=[
            "--wallet-path",
            wallet_path,
            "--wallet-name",
            wallet.name,
            "--chain",
            "ws://127.0.0.1:9945",
        ],
    )

    # Assert correct entry is present in wallet inspect
    assert validate_wallet_inspect(
        inspect.stdout,
        coldkey=wallet.name,
        balance=Balance.from_tao(balance["free_balance"]),
        delegates=None,  # We have not delegated anywhere yet
        hotkeys_netuid=[
            (1, f"default-{wallet.hotkey.ss58_address}", 0, False)
        ],  # (netuid, hotkey-display, stake, check_emissions)
    )
    print("Passed wallet overview, inspect command ✅")


def test_wallet_transfer(local_chain, wallet_setup):
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
    print("Testing wallet transfer, balance command 🧪")
    wallet_path_alice = "//Alice"
    wallet_path_bob = "//Bob"

    # Create wallets for Alice and Bob
    keypair_alice, wallet_alice, wallet_path_alice, exec_command_alice = wallet_setup(
        wallet_path_alice
    )
    keypair_bob, wallet_bob, wallet_path_bob, exec_command_bob = wallet_setup(
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
            "--amount",
            "100",
            "--no-prompt",
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
        wallet_setup(wallet_path_anakin)
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
            "--amount",
            "100",
            "--no-prompt",
        ],
    )

    # This transfer is expected to fail due to low balance
    assert "❌ Not enough balance" in result.stderr
    print("✅Passed wallet transfer, balance command")


def test_wallet_identities(local_chain, wallet_setup):
    """
    Test setting ids & fetching ids in the network, and signing using wallets.

    Steps:
        1. Create a wallet for Alice
        2. Set the network identity for Alice using pre-defined values
        3. Assert id was set successfully and all values are correct
        4. Fetch the id using hotkey and assert all values are correct
        5. Sign a message using wallet's hotkey
        5. Sign a message using wallet's coldkey

    Raises:
        AssertionError: If any of the checks or verifications fail
    """
    print("Testing wallet set-id, get-id, sign command 🧪")

    wallet_path_alice = "//Alice"

    # Create wallet for Alice
    keypair_alice, wallet_alice, wallet_path_alice, exec_command_alice = wallet_setup(
        wallet_path_alice
    )

    # Register Alice to the root network (0)
    # Either root list neurons can set-id or subnet owners
    root_register = exec_command_alice(
        command="root",
        sub_command="register",
        extra_args=[
            "--wallet-path",
            wallet_path_alice,
            "--network",
            "ws://127.0.0.1:9945",
            "--wallet-name",
            wallet_alice.name,
            "--hotkey",
            wallet_alice.hotkey_str,
            "--no-prompt",
        ],
    )
    assert "✅ Registered" in root_register.stdout

    # Define values for Alice's identity
    alice_identity = {
        "display_name": "Alice",
        "legal_name": "Alice OTF",
        "web_url": "https://bittensor.com/",
        "riot": "MyRiotID",
        "email": "alice@opentensor.dev",
        "pgp": "D2A1 F4A3 B1D3 5A74 63F0 678E 35E7 041A 22C1 A4FE",
        "image_url": "https://bittensor.com/img/dark-Bittensor.svg",
        "info": "I am a tester for OTF",
        "twitter": "https://x.com/opentensor",
    }

    # Execute btcli set-identity command
    set_id = exec_command_alice(
        command="wallet",
        sub_command="set-identity",
        extra_args=[
            "--wallet-path",
            wallet_path_alice,
            "--chain",
            "ws://127.0.0.1:9945",
            "--wallet-name",
            wallet_alice.name,
            "--wallet-hotkey",
            wallet_alice.hotkey_str,
            "--display-name",
            alice_identity["display_name"],
            "--legal-name",
            alice_identity["legal_name"],
            "--web-url",
            alice_identity["web_url"],
            "--riot",
            alice_identity["riot"],
            "--email",
            alice_identity["email"],
            "--pgp",
            alice_identity["pgp"],
            "--image-url",
            alice_identity["image_url"],
            "--info",
            alice_identity["info"],
            "-x",
            alice_identity["twitter"],
            "--validator",
            "--no-prompt",
        ],
    )

    # Assert all correct values are being set
    assert "✅ Success!" in set_id.stdout
    set_id_output = set_id.stdout.splitlines()

    assert alice_identity["display_name"] in set_id_output[7]
    assert alice_identity["legal_name"] in set_id_output[8]
    assert alice_identity["web_url"] in set_id_output[9]
    assert alice_identity["riot"] in set_id_output[10]
    assert alice_identity["email"] in set_id_output[11]
    assert alice_identity["pgp"] in set_id_output[12]
    assert alice_identity["image_url"] in set_id_output[13]
    assert alice_identity["twitter"] in set_id_output[14]

    # TODO: Currently coldkey + hotkey are the same for test wallets.
    # Maybe we can add a new key to help in distinguishing
    assert wallet_alice.hotkey.ss58_address in set_id_output[5]

    # Execute btcli get-identity using hotkey
    get_identity = exec_command_alice(
        command="wallet",
        sub_command="get-identity",
        extra_args=[
            "--chain",
            "ws://127.0.0.1:9945",
            "--key",
            wallet_alice.hotkey.ss58_address,
        ],
    )
    # print(get_identity.stdout)

    # Assert all correct values are being fetched for the ID we just set
    get_identity_output = get_identity.stdout.splitlines()
    assert alice_identity["display_name"] in get_identity_output[6]
    assert alice_identity["legal_name"] in get_identity_output[7]
    assert alice_identity["web_url"] in get_identity_output[8]
    assert alice_identity["riot"] in get_identity_output[9]
    assert alice_identity["email"] in get_identity_output[10]
    assert alice_identity["pgp"] in get_identity_output[11]
    assert alice_identity["image_url"] in get_identity_output[12]
    assert alice_identity["twitter"] in get_identity_output[13]

    # Sign a message using hotkey
    sign_using_hotkey = exec_command_alice(
        command="wallet",
        sub_command="sign",
        extra_args=[
            "--wallet-path",
            wallet_path_alice,
            "--wallet-name",
            wallet_alice.name,
            "--wallet-hotkey",
            wallet_alice.hotkey_str,
            "--use-hotkey",
            "--message",
            "Bittensor is evolving to be the world's greatest decentralized AI network",
        ],
    )

    assert "Message signed successfully" in sign_using_hotkey.stdout

    # Sign a message using coldkey
    sign_using_coldkey = exec_command_alice(
        command="wallet",
        sub_command="sign",
        extra_args=[
            "--wallet-path",
            wallet_path_alice,
            "--wallet-name",
            wallet_alice.name,
            "--wallet-hotkey",
            wallet_alice.hotkey_str,
            "--use-hotkey",
            "--message",
            "Bittensor is evolving to be the world's greatest decentralized AI network",
        ],
    )

    assert "Message signed successfully" in sign_using_coldkey.stdout

    print("✅ Passed wallet set-id, get-id, sign command")
