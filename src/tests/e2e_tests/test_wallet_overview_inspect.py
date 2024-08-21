from btcli.src.bittensor.balances import Balance

from .utils import (
    extract_coldkey_balance,
    setup_wallet,
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
"""


def test_wallet_overview_inspect(local_chain):
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
    netuid = 1
    wallet_path_name = "//Alice"

    # Create wallet for Alice
    keypair, wallet, wallet_path, exec_command = setup_wallet(wallet_path_name)

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
            "--network",
            "local",
        ],
    )
    assert f"✅ Registered subnetwork with netuid: {netuid}" in result.stdout

    # List all the subnets in the network
    subnets_list = exec_command(
        command="subnets",
        sub_command="list",
        extra_args=[
            "--chain",
            "ws://127.0.0.1:9945",
            "--network",
            "local",
        ],
    )

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
            "--network",
            "local",
            "--netuid",
            "1",
            "--chain",
            "ws://127.0.0.1:9945",
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
            "--network",
            "local",
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
            "--network",
            "local",
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
            "--network",
            "local",
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
