import os
import re
import shutil
import subprocess
import sys
from typing import List, Tuple

from bittensor_cli.cli import CLIManager
from bittensor_wallet import Wallet
from substrateinterface import Keypair
from typer.testing import CliRunner
from bittensor_wallet import Wallet
from bittensor_cli.src.bittensor.subtensor_interface import SubtensorInterface

template_path = os.getcwd() + "/neurons/"
templates_repo = "templates repository"


def setup_wallet(uri: str):
    keypair = Keypair.create_from_uri(uri)
    wallet_path = f"/tmp/btcli-e2e-wallet-{uri.strip('/')}"
    wallet = Wallet(path=wallet_path)
    wallet.set_coldkey(keypair=keypair, encrypt=False, overwrite=True)
    wallet.set_coldkeypub(keypair=keypair, encrypt=False, overwrite=True)
    wallet.set_hotkey(keypair=keypair, encrypt=False, overwrite=True)

    def exec_command(
        command: str,
        sub_command: str,
        extra_args: List[str] = [],
        inputs: List[str] = None,
    ):
        cli_manager = CLIManager()
        runner = CliRunner()
        # Prepare the command arguments
        args = [
            command,
            sub_command,
        ] + extra_args

        command_for_printing = ["btcli"] + [
            str(arg) if arg is not None else "None" for arg in args
        ]
        print("Executing command:", " ".join(command_for_printing))

        input_text = "\n".join(inputs) + "\n" if inputs else None
        result = runner.invoke(
            cli_manager.app, args, input=input_text, env={"COLUMNS": "700"}
        )
        return result

    return keypair, wallet, wallet_path, exec_command


def extract_coldkey_balance(text: str, wallet_name: str, coldkey_address: str) -> dict:
    """
    Extracts the free, staked, and total balances for a
    given wallet name and coldkey address from the input string.

    Args:
        text (str): The input string from wallet list command.
        wallet_name (str): The name of the wallet.
        coldkey_address (str): The coldkey address.

    Returns:
        dict: A dictionary with keys 'free_balance', 'staked_balance', and 'total_balance',
              each containing the corresponding balance as a Balance object.
              Returns a dictionary with all zeros if the wallet name or coldkey address is not found.
    """
    pattern = (
        rf"{wallet_name}\s+{coldkey_address}\s+"
        r"τ([\d,]+\.\d+)\s+"  # Free Balance
        r"τ([\d,]+\.\d+)\s+"  # Staked Balance
        r"τ([\d,]+\.\d+)"  # Total Balance
    )

    match = re.search(pattern, text)

    if not match:
        return {
            "free_balance": 0.0,
            "staked_balance": 0.0,
            "total_balance": 0.0,
        }

    # Return the balances as a dictionary
    return {
        "free_balance": float(match.group(1).replace(",", "")),
        "staked_balance": float(match.group(2).replace(",", "")),
        "total_balance": float(match.group(3).replace(",", "")),
    }


def verify_subnet_entry(output_text: str, netuid: str, ss58_address: str) -> bool:
    """
    Verifies the presence of a specific subnet entry subnets list output.

    Args:
    output_text (str): Output of execution command
    netuid (str): The netuid to look for.
    ss58_address (str): The SS58 address of the subnet owner

    Returns:
    bool: True if the entry is found, False otherwise.
    """

    pattern = (
        rf"\b{re.escape(str(netuid))}\s*\│\s*"  # NETUID
        r"\d+\s*\│\s*"  # N (any number)
        r"\d+(?:\.\d+)?\s*[KMB]*\s*\│\s*"  # MAX_N (number with optional decimal and K/M/B suffix)
        r"\d+\.\d+%\s*\│\s*"  # EMISSION (percentage)
        r"\d+\s*\│\s*"  # TEMPO (any number)
        r"τ\d+\.\d+\s*\│\s*"  # RECYCLE (τ followed by a number)
        r"\d+(?:\.\d+)?\s*[KMB]*\s*\│\s*"  # POW (number with optional decimal and K/M/B suffix)
        rf"{re.escape(ss58_address)}\b"  # SUDO (exact SS58 address)
    )

    # Normalize spaces in the output text
    normalized_output = re.sub(r"\s+", " ", output_text)

    # Search for the pattern
    match = re.search(pattern, normalized_output)

    return bool(match)


def validate_wallet_overview(
    output: str,
    uid: int,
    coldkey: str,
    hotkey: str,
    hotkey_ss58: str,
    axon_active: bool = False,
):
    """
    Validates the presence a registered neuron in wallet overview output.

    Returns:
    bool: True if the entry is found, False otherwise.
    """

    # Construct the regex pattern
    pattern = rf"{coldkey}\s+"  # COLDKEY
    pattern += rf"{hotkey}\s+"  # HOTKEY
    pattern += rf"{uid}\s+"  # UID
    pattern += r"True\s+"  # ACTIVE - Always True immediately after we register
    pattern += r"[\d.]+\s+"  # STAKE(τ)
    pattern += r"[\d.]+\s+"  # RANK
    pattern += r"[\d.]+\s+"  # TRUST
    pattern += r"[\d.]+\s+"  # CONSENSUS
    pattern += r"[\d.]+\s+"  # INCENTIVE
    pattern += r"[\d.]+\s+"  # DIVIDENDS
    pattern += r"\d+\s+"  # EMISSION(ρ)
    pattern += r"[\d.]+\s+"  # VTRUST
    pattern += r"(?:True|False)?\s*"  # VPERMIT (optional)
    pattern += r"[\d]+\s+"  # UPDATED (any number)
    pattern += (
        r"(?!none)\w+\s+" if axon_active else r"none\s+"
    )  # AXON - True if axon is active
    pattern += rf"{hotkey_ss58[:10]}\s*"  # HOTKEY_SS58

    # Search for the pattern in the wallet information
    match = re.search(pattern, output)

    return bool(match)


def validate_wallet_inspect(
    text: str,
    coldkey: str,
    balance: float,
    delegates: List[Tuple[str, float, bool]],
    hotkeys_netuid: List[Tuple[str, str, float, bool]],
):
    # TODO: Handle stake in Balance format as well
    """
    Validates the presence of specific coldkey, balance, delegates, and hotkeys/netuid in the wallet information.

    Args:
    wallet_info (str): The string output to verify.
    coldkey (str): The coldkey to check.
    balance (float): The balance to verify for the coldkey.
    delegates (list of tuple): List of delegates to check, Each tuple contains (ss58_address, stake, emission_flag).
    hotkeys_netuid (list of tuple): List of hotkeys/netuids to check, Each tuple contains (netuid, hotkey, stake, emission_flag).

    Returns:
    bool: True if all checks pass, False otherwise.
    """
    # Preprocess lines to remove the | character
    cleaned_text = text.replace("│", "").replace("|", "")
    lines = [re.sub(r"\s+", " ", line) for line in cleaned_text.splitlines()]

    def parse_value(value):
        return float(value.replace("τ", "").replace(",", ""))

    def check_stake(actual, expected):
        return expected <= actual <= expected + 2

    # Check coldkey and balance
    # This is the first row when records of a coldkey start
    coldkey_pattern = rf"{coldkey}\s+{balance}"
    for line in lines:
        match = re.search(coldkey_pattern, line.replace("|", ""))
        if match:
            break
    else:
        return False

    # This checks for presence of delegates in each row
    if delegates:
        for ss58, stake, check_emission in delegates:
            delegate_pattern = rf"{ss58}\s+τ([\d,.]+)\s+([\d.e-]+)"
            for line in lines:
                match = re.search(delegate_pattern, line)
                if match:
                    actual_stake = parse_value(match.group(1))
                    emission = float(match.group(2))
                    if not check_stake(actual_stake, stake):
                        return False
                    if check_emission and emission == 0:
                        return False
                    break
            else:
                return False

    # This checks for hotkeys that are registered to subnets
    if hotkeys_netuid:
        for netuid, hotkey, stake, check_emission in hotkeys_netuid:
            hotkey_pattern = rf"{netuid}\s+{hotkey}\s+τ([\d,.]+)\s+τ([\d,.]+)"
            for line in lines:
                match = re.search(hotkey_pattern, line)
                if match:
                    actual_stake = parse_value(match.group(1))
                    emission = parse_value(match.group(2))
                    if not check_stake(actual_stake, stake):
                        return False
                    if check_emission and emission == 0:
                        return False
                    break
            else:
                return False

    return True


def clone_or_update_templates(specific_commit=None):
    install_dir = template_path
    repo_mapping = {
        templates_repo: "https://github.com/opentensor/bittensor-subnet-template.git",
    }
    os.makedirs(install_dir, exist_ok=True)
    os.chdir(install_dir)

    for repo, git_link in repo_mapping.items():
        if not os.path.exists(repo):
            print(f"\033[94mCloning {repo}...\033[0m")
            subprocess.run(["git", "clone", git_link, repo], check=True)
        else:
            print(f"\033[94mUpdating {repo}...\033[0m")
            os.chdir(repo)
            subprocess.run(["git", "pull"], check=True)
            os.chdir("..")

    # Here for pulling specific commit versions of repo
    if specific_commit:
        os.chdir(templates_repo)
        print(
            f"\033[94mChecking out commit {specific_commit} in {templates_repo}...\033[0m"
        )
        subprocess.run(["git", "checkout", specific_commit], check=True)
        os.chdir("..")

    return install_dir + templates_repo + "/"


def install_templates(install_dir):
    subprocess.check_call([sys.executable, "-m", "pip", "install", install_dir])


def uninstall_templates(install_dir):
    # Uninstall templates
    subprocess.check_call(
        [sys.executable, "-m", "pip", "uninstall", "bittensor_subnet_template", "-y"]
    )
    # Delete everything in directory
    shutil.rmtree(install_dir)


async def call_add_proposal(subtensor: SubtensorInterface, wallet: Wallet) -> bool:
    proposal_call = await subtensor.compose_call(
        call_module="System",
        call_function="remark",
        call_params={"remark": [0]},
    )
    call = await subtensor.compose_call(
        call_module="Triumvirate",
        call_function="propose",
        call_params={
            "proposal": proposal_call,
            "length_bound": 100_000,
            "duration": 100_000_000,
        },
    )

    success, err_msg = await subtensor.sign_and_send_extrinsic(call, wallet, True, True)
    return success
