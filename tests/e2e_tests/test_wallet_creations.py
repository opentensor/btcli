import json
import os
import re
import time
from typing import Dict, Optional, Tuple

from bittensor_wallet import Wallet

"""
Verify commands:

* btcli w list
* btcli w create
* btcli w new_coldkey
* btcli w new_hotkey
* btcli w regen_coldkey
* btcli w regen_coldkeypub
* btcli w regen_hotkey
* btcli w regen_hotkeypub
"""


def verify_wallet_dir(
    base_path: str,
    wallet_name: str,
    hotkey_name: Optional[str] = None,
    coldkeypub_name: Optional[str] = None,
) -> Tuple[bool, str]:
    """
    Verifies the existence of wallet directory, coldkey, and optionally the hotkey.

    Args:
        base_path (str): The base directory path where wallets are stored.
        wallet_name (str): The name of the wallet directory to verify.
        hotkey_name (str, optional): The name of the hotkey file to verify. If None,
                                     only the wallet and coldkey file are checked.
        coldkeypub_name (str, optional): The name of the coldkeypub file to verify. If None
                                         only the wallet and coldkey is checked

    Returns:
        tuple: Returns a tuple containing a boolean and a message. The boolean is True if
               all checks pass, otherwise False.
    """
    wallet_path = os.path.join(base_path, wallet_name)

    # Check if wallet directory exists
    if not os.path.isdir(wallet_path):
        return False, f"Wallet directory {wallet_name} not found in {base_path}"

    # Check if coldkey file exists
    coldkey_path = os.path.join(wallet_path, "coldkey")
    if not os.path.isfile(coldkey_path):
        return False, f"Coldkey file not found in {wallet_name}"

    # Check if coldkeypub exists
    if coldkeypub_name:
        coldkeypub_path = os.path.join(wallet_path, coldkeypub_name)
        if not os.path.isfile(coldkeypub_path):
            return False, f"Coldkeypub file not found in {wallet_name}"

    # Check if hotkey directory and file exists
    if hotkey_name:
        hotkeys_path = os.path.join(wallet_path, "hotkeys")
        if not os.path.isdir(hotkeys_path):
            return False, f"Hotkeys directory not found in {wallet_name}"

        hotkey_file_path = os.path.join(hotkeys_path, hotkey_name)
        if not os.path.isfile(hotkey_file_path):
            return (
                False,
                f"Hotkey file {hotkey_name} not found in {wallet_name}/hotkeys",
            )

    return True, f"Wallet {wallet_name} verified successfully"


def verify_key_pattern(output: str, wallet_name: str) -> Optional[str]:
    """
    Verifies that a specific wallet key pattern exists in the output text.

    Args:
        output (str): The string output where the wallet key should be verified.
        wallet_name (str): The name of the wallet to search for in the output.

    Raises:
        AssertionError: If the wallet key pattern is not found, or if the key does not
                        start with '5', or if the key is not exactly 48 characters long.
    """
    split_output = output.splitlines()
    pattern = rf"{wallet_name}\s+ss58_address\s+(5[A-Za-z0-9]{{47}})"
    found = False

    # Traverse each line to find instance of the pattern
    for line in split_output:
        match = re.search(pattern, line)
        if match:
            # Assert key starts with '5'
            assert match.group(1).startswith("5"), (
                f"{wallet_name} should start with '5'"
            )
            # Assert length of key is 48 characters
            assert len(match.group(1)) == 48, (
                f"Key for {wallet_name} should be 48 characters long"
            )
            found = True
            return match.group(1)

    # If no match is found in any line, raise an assertion error
    assert found, f"{wallet_name} not found in wallet list"
    return None


def extract_ss58_address(output: str, wallet_name: str) -> str:
    """
    Extracts the ss58 address from the given output for a specified wallet.

    Args:
        output (str): The captured output.
        wallet_name (str): The name of the wallet.

    Returns:
        str: ss58 address.
    """
    pattern = rf"{wallet_name}\s+ss58_address\s+(5[A-Za-z0-9]{{47}})"
    lines = output.splitlines()
    for line in lines:
        match = re.search(pattern, line)
        if match:
            return match.group(1)  # Return the ss58 address

    raise ValueError(f"ss58 address not found for wallet {wallet_name}")


def extract_mnemonics_from_commands(output: str) -> Dict[str, Optional[str]]:
    """
    Extracts mnemonics of coldkeys & hotkeys from the given output for a specified wallet.

    Args:
        output (str): The captured output.

    Returns:
        dict: A dictionary keys 'coldkey' and 'hotkey', each containing their mnemonics.
    """
    mnemonics: Dict[str, Optional[str]] = {"coldkey": None, "hotkey": None}

    key_types = ["coldkey", "hotkey"]

    # We will assume the most recent match is the one we want
    for key_type in key_types:
        # Note: python's re needs this P before the group name
        # See: https://stackoverflow.com/questions/10059673/named-regular-expression-group-pgroup-nameregexp-what-does-p-stand-for
        pat = re.compile(rf"(?P<key_type>{key_type}).*?(?P<mnemonic>(\w+( |)){{12}})")
        matches = pat.search(output)

        groups = matches.groupdict()

        if len(groups.keys()) == 0:
            mnemonics[key_type] = None
            continue

        key_type_str = groups["key_type"]
        if key_type != key_type_str:
            continue

        mnemonic_phrase = groups["mnemonic"]
        mnemonics[key_type] = mnemonic_phrase

    return mnemonics


def test_wallet_creations(wallet_setup):
    """
    Test the creation and verification of wallet keys and directories in the Bittensor network.

    Steps:
        1. List existing wallets and verify the default setup.
        2. Create a new wallet with both coldkey and hotkey, verify their presence in the output,
           and check their physical existence.
        3. Create a new coldkey and verify both its display in the command line output and its physical file.
        4. Create a new hotkey for an existing coldkey, verify its display in the command line output,
           and check for both coldkey and hotkey files.

    Raises:
        AssertionError: If any of the checks or verifications fail
    """

    wallet_path_name = "//Alice"
    keypair, wallet, wallet_path, exec_command = wallet_setup(wallet_path_name)

    result = exec_command(
        command="wallet", sub_command="list", extra_args=["--wallet-path", wallet_path]
    )

    # Assert default keys are present before proceeding
    assert f"default  ss58_address {wallet.coldkeypub.ss58_address}" in result.stdout
    assert f"default  ss58_address {wallet.hotkey.ss58_address}" in result.stdout
    wallet_status, message = verify_wallet_dir(
        wallet_path, "default", hotkey_name="default"
    )
    assert wallet_status, message

    json_result = exec_command(
        command="wallet",
        sub_command="list",
        extra_args=["--wallet-path", wallet_path, "--json-output"],
    )
    json_wallet = json.loads(json_result.stdout)["wallets"][0]
    assert json_wallet["ss58_address"] == wallet.coldkey.ss58_address
    assert json_wallet["hotkeys"][0]["ss58_address"] == wallet.hotkey.ss58_address

    # -----------------------------
    # Command 1: <btcli w create>
    # -----------------------------

    print("Testing wallet create command 🧪")
    # Create a new wallet (coldkey + hotkey)
    exec_command(
        command="wallet",
        sub_command="create",
        extra_args=[
            "--wallet-path",
            wallet_path,
            "--wallet-name",
            "new_wallet",
            "--hotkey",
            "new_hotkey",
            "--no-use-password",
            "--n-words",
            "12",
        ],
    )

    # List the wallets
    result = exec_command(
        command="wallet", sub_command="list", extra_args=["--wallet-path", wallet_path]
    )

    # Verify coldkey "new_wallet" is displayed with key
    verify_key_pattern(result.stdout, "new_wallet")

    # Verify hotkey "new_hotkey" is displayed with key
    verify_key_pattern(result.stdout, "new_hotkey")

    # Physically verify "new_wallet" and "new_hotkey" are present
    wallet_status, message = verify_wallet_dir(
        wallet_path, "new_wallet", hotkey_name="new_hotkey"
    )
    assert wallet_status, message

    # -----------------------------
    # Command 2: <btcli w new_coldkey>
    # -----------------------------

    print("Testing wallet new_coldkey command 🧪")

    # Create a new wallet (coldkey)
    exec_command(
        "wallet",
        sub_command="new-coldkey",
        extra_args=[
            "--wallet-name",
            "new_coldkey",
            "--wallet-path",
            wallet_path,
            "--n-words",
            "12",
            "--no-use-password",
        ],
    )

    # List the wallets
    result = exec_command(
        command="wallet", sub_command="list", extra_args=["--wallet-path", wallet_path]
    )

    # Verify coldkey "new_coldkey" is displayed with key
    verify_key_pattern(result.stdout, "new_coldkey")

    # Physically verify "new_coldkey" is present
    wallet_status, message = verify_wallet_dir(wallet_path, "new_coldkey")
    assert wallet_status, message

    json_creation = exec_command(
        "wallet",
        "new-coldkey",
        extra_args=[
            "--wallet-name",
            "new_json_coldkey",
            "--wallet-path",
            wallet_path,
            "--n-words",
            "12",
            "--no-use-password",
            "--json-output",
        ],
    )
    json_creation_output = json.loads(json_creation.stdout)
    assert json_creation_output["success"] is True
    assert json_creation_output["data"]["name"] == "new_json_coldkey"
    assert "coldkey_ss58" in json_creation_output["data"]
    assert json_creation_output["error"] == ""
    new_json_coldkey_ss58 = json_creation_output["data"]["coldkey_ss58"]

    # -----------------------------
    # Command 3: <btcli w new_hotkey>
    # -----------------------------

    print("Testing wallet new_hotkey command 🧪")
    # Create a new hotkey for new_coldkey wallet
    result = exec_command(
        "wallet",
        sub_command="new-hotkey",
        extra_args=[
            "--wallet-name",
            "new_coldkey",
            "--hotkey",
            "new_hotkey",
            "--wallet-path",
            wallet_path,
            "--n-words",
            "12",
            "--no-use-password",
        ],
    )

    # List the wallets
    result = exec_command(
        command="wallet", sub_command="list", extra_args=["--wallet-path", wallet_path]
    )

    # Verify hotkey "new_hotkey" is displayed with key
    verify_key_pattern(result.stdout, "new_hotkey")

    # Physically verify "new_coldkey" and "new_hotkey" are present
    wallet_status, message = verify_wallet_dir(
        wallet_path, "new_coldkey", hotkey_name="new_hotkey"
    )
    assert wallet_status, message

    new_hotkey_json = exec_command(
        "wallet",
        sub_command="new-hotkey",
        extra_args=[
            "--wallet-name",
            "new_json_coldkey",
            "--hotkey",
            "new_json_hotkey",
            "--wallet-path",
            wallet_path,
            "--n-words",
            "12",
            "--no-use-password",
            "--json-output",
        ],
    )
    new_hotkey_json_output = json.loads(new_hotkey_json.stdout)
    assert new_hotkey_json_output["success"] is True
    assert new_hotkey_json_output["data"]["name"] == "new_json_coldkey"
    assert new_hotkey_json_output["data"]["hotkey"] == "new_json_hotkey"
    assert new_hotkey_json_output["data"]["coldkey_ss58"] == new_json_coldkey_ss58
    assert new_hotkey_json_output["error"] == ""


def test_wallet_regen(wallet_setup, capfd):
    """
    Test the regeneration of coldkeys, hotkeys, and coldkeypub files using mnemonics or ss58 address.

    Steps:
        1. List existing wallets and verify the default setup.
        2. Regenerate the coldkey using the mnemonics and verify using mod time.
        3. Regenerate the coldkeypub using ss58 address and verify using mod time
        4. Regenerate the hotkey using mnemonics and verify using mod time.

    Raises:
        AssertionError: If any of the checks or verifications fail
    """
    wallet_path_name = "//Bob"
    keypair, wallet, wallet_path, exec_command = wallet_setup(wallet_path_name)

    # Create a new wallet (coldkey + hotkey)
    result = exec_command(
        command="wallet",
        sub_command="create",
        extra_args=[
            "--wallet-path",
            wallet_path,
            "--wallet-name",
            "new_wallet",
            "--hotkey",
            "new_hotkey",
            "--no-use-password",
            "--n-words",
            "12",
        ],
    )

    # Check for an exception first
    assert result.exception is None
    # Verify the command has output, as expected
    assert result.stdout is not None

    captured = capfd.readouterr()
    mnemonics = extract_mnemonics_from_commands(captured.out)

    wallet_status, message = verify_wallet_dir(
        wallet_path,
        "new_wallet",
        hotkey_name="new_hotkey",
        coldkeypub_name="coldkeypub.txt",
    )
    assert wallet_status, message  # Ensure wallet exists

    # -----------------------------
    # Command 1: <btcli w regen_coldkey>
    # -----------------------------
    print("Testing wallet regen_coldkey command 🧪")
    coldkey_path = os.path.join(wallet_path, "new_wallet", "coldkey")
    initial_coldkey_ss58 = Wallet(
        name="new_wallet", path=wallet_path
    ).coldkey.ss58_address
    initial_coldkey_mod_time = os.path.getmtime(coldkey_path)

    result = exec_command(
        command="wallet",
        sub_command="regen-coldkey",
        extra_args=[
            "--wallet-name",
            "new_wallet",
            "--hotkey",
            "new_hotkey",
            "--wallet-path",
            wallet_path,
            "--mnemonic",
            mnemonics["coldkey"],
            "--no-use-password",
            "--overwrite",
        ],
    )

    # Wait a bit to ensure file system updates modification time
    time.sleep(0.01)

    new_coldkey_mod_time = os.path.getmtime(coldkey_path)

    assert initial_coldkey_mod_time != new_coldkey_mod_time, (
        "Coldkey file was not regenerated as expected"
    )
    json_result = exec_command(
        command="wallet",
        sub_command="regen-coldkey",
        extra_args=[
            "--wallet-name",
            "new_wallet",
            "--hotkey",
            "new_hotkey",
            "--wallet-path",
            wallet_path,
            "--mnemonic",
            mnemonics["coldkey"],
            "--no-use-password",
            "--overwrite",
            "--json-output",
        ],
    )

    json_result_out = json.loads(json_result.stdout)
    assert json_result_out["success"] is True
    assert json_result_out["data"]["name"] == "new_wallet"
    assert json_result_out["data"]["coldkey_ss58"] == initial_coldkey_ss58

    # -----------------------------
    # Command 2: <btcli w regen_coldkeypub>
    # -----------------------------

    print("Testing wallet regen_coldkeypub command 🧪")
    coldkeypub_path = os.path.join(wallet_path, "new_wallet", "coldkeypub.txt")
    initial_coldkeypub_mod_time = os.path.getmtime(coldkeypub_path)

    result = exec_command(
        command="wallet", sub_command="list", extra_args=["--wallet-path", wallet_path]
    )

    ss58_address = extract_ss58_address(result.stdout, "new_wallet")

    result = exec_command(
        command="wallet",
        sub_command="regen-coldkeypub",
        extra_args=[
            "--wallet-name",
            "new_wallet",
            "--hotkey",
            "new_hotkey",
            "--wallet-path",
            wallet_path,
            "--ss58-address",
            ss58_address,
            "--overwrite",
        ],
    )

    # Wait a bit to ensure file system updates modification time
    time.sleep(1)

    new_coldkeypub_mod_time = os.path.getmtime(coldkeypub_path)

    assert initial_coldkeypub_mod_time != new_coldkeypub_mod_time, (
        "Coldkeypub file was not regenerated as expected"
    )
    print("Passed wallet regen_coldkeypub command ✅")

    # -----------------------------
    # Command 3: <btcli w regen_hotkey>
    # -----------------------------

    print("Testing wallet regen_hotkey command 🧪")
    hotkey_path = os.path.join(wallet_path, "new_wallet", "hotkeys", "new_hotkey")
    initial_hotkey_mod_time = os.path.getmtime(hotkey_path)

    result = exec_command(
        command="wallet",
        sub_command="regen-hotkey",
        extra_args=[
            "--wallet-name",
            "new_wallet",
            "--hotkey",
            "new_hotkey",
            "--wallet-path",
            wallet_path,
            "--mnemonic",
            mnemonics["hotkey"],
            "--no-use-password",
            "--overwrite",
        ],
    )

    # Wait a bit to ensure file system updates modification time
    time.sleep(2)

    new_hotkey_mod_time = os.path.getmtime(hotkey_path)

    assert initial_hotkey_mod_time != new_hotkey_mod_time, (
        "Hotkey file was not regenerated as expected"
    )
    print("Passed wallet regen_hotkey command ✅")

    hotkeypub_path = os.path.join(
        wallet_path, "new_wallet", "hotkeys", "new_hotkeypub.txt"
    )
    initial_hotkeypub_mod_time = os.path.getmtime(hotkeypub_path)
    result = exec_command(
        command="wallet",
        sub_command="regen-hotkeypub",
        extra_args=[
            "--wallet-name",
            "new_wallet",
            "--hotkey",
            "new_hotkey",
            "--wallet-path",
            wallet_path,
            "--ss58-address",
            ss58_address,
            "--overwrite",
        ],
    )

    # Wait a bit to ensure file system updates modification time
    time.sleep(2)

    new_hotkeypub_mod_time = os.path.getmtime(hotkeypub_path)

    assert initial_hotkeypub_mod_time != new_hotkeypub_mod_time, (
        "Hotkey file was not regenerated as expected"
    )
    print("Passed wallet regen_hotkeypub command ✅")


def test_wallet_balance_all(local_chain, wallet_setup, capfd):
    """
    Test the wallet balance --all command with a large number of wallets.

    Steps:
        1. Create 100 wallets
        2. Run wallet balance --all command
        3. Verify the output contains all wallet names and their balances

    Raises:
        AssertionError: If any of the checks or verifications fail
    """
    wallet_path_name = "//Alice"
    keypair, wallet, wallet_path, exec_command = wallet_setup(wallet_path_name)

    print("Creating 100 wallets for testing balance --all command 🧪")
    num_wallets = 100
    wallet_names = []

    for i in range(num_wallets):
        wallet_name = f"test_wallet_{i}"
        wallet_names.append(wallet_name)

        exec_command(
            command="wallet",
            sub_command="new-coldkey",
            extra_args=[
                "--wallet-name",
                wallet_name,
                "--wallet-path",
                wallet_path,
                "--n-words",
                "12",
                "--no-use-password",
            ],
        )

        wallet_status, message = verify_wallet_dir(wallet_path, wallet_name)
        assert wallet_status, message

    print("Testing wallet balance --all command 🧪")
    result = exec_command(
        command="wallet",
        sub_command="balance",
        extra_args=[
            "--wallet-path",
            wallet_path,
            "--all",
            "--chain",
            "ws://127.0.0.1:9945",
        ],
    )

    output = result.stdout

    for wallet_name in wallet_names:
        assert wallet_name in output, (
            f"Wallet {wallet_name} not found in balance --all output"
        )

    json_results = exec_command(
        "wallet",
        "balance",
        extra_args=[
            "--wallet-path",
            wallet_path,
            "--all",
            "--json-output",
            "--chain",
            "ws://127.0.0.1:9945",
        ],
    )
    json_results_output = json.loads(json_results.stdout)
    for wallet_name in wallet_names:
        assert wallet_name in json_results_output["balances"].keys()
        assert json_results_output["balances"][wallet_name]["total"] == 0.0
        assert "coldkey" in json_results_output["balances"][wallet_name]

    print("Passed wallet balance --all command with 100 wallets ✅")
