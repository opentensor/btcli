import asyncio
import logging
import os
import shutil
import subprocess
import sys
from typing import List

import pytest
from bittensor_wallet import Wallet
from substrateinterface import Keypair

template_path = os.getcwd() + "/neurons/"
templates_repo = "templates repository"


def setup_wallet(uri: str):
    keypair = Keypair.create_from_uri(uri)
    wallet_path = f"/tmp/btcli-e2e-wallet-{uri.strip('/')}"
    wallet = Wallet(path=wallet_path)
    wallet.set_coldkey(keypair=keypair, encrypt=False, overwrite=True)
    wallet.set_coldkeypub(keypair=keypair, encrypt=False, overwrite=True)
    wallet.set_hotkey(keypair=keypair, encrypt=False, overwrite=True)

    def exec_command(command: str, sub_command: str, extra_args: List[str] = []):
        cli_path = os.getenv("BTCLI_PATH")  
        if not (cli_path and os.path.isfile(cli_path)):
            pytest.skip("cli.py not found. Set the BTCLI_PATH environment variable")

        # Prepare the command arguments
        args = [
            sys.executable,  # This ensures the correct Python interpreter is used
            cli_path,
            command,
            sub_command,
        ] + extra_args

        # Run the command using subprocess
        result = None
        try:
            result = subprocess.run(args, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            # Handle errors in execution
            print(f"Command failed with error: {e.stderr}")
            result = e
            

        return result

    return keypair, wallet, wallet_path, exec_command


async def wait_epoch(subtensor, netuid=1):
    q_tempo = [
        v.value
        for [k, v] in subtensor.query_map_subtensor("Tempo")
        if k.value == netuid
    ]
    if len(q_tempo) == 0:
        raise Exception("could not determine tempo")
    tempo = q_tempo[0]
    logging.info(f"tempo = {tempo}")
    await wait_interval(tempo, subtensor, netuid)


async def wait_interval(tempo, subtensor, netuid=1):
    interval = tempo + 1
    current_block = subtensor.get_current_block()
    last_epoch = current_block - 1 - (current_block + netuid + 1) % interval
    next_tempo_block_start = last_epoch + interval
    last_reported = None
    while current_block < next_tempo_block_start:
        await asyncio.sleep(
            1
        )  # Wait for 1 second before checking the block number again
        current_block = subtensor.get_current_block()
        if last_reported is None or current_block - last_reported >= 10:
            last_reported = current_block
            print(
                f"Current Block: {current_block}  Next tempo for netuid {netuid} at: {next_tempo_block_start}"
            )
            logging.info(
                f"Current Block: {current_block}  Next tempo for netuid {netuid} at: {next_tempo_block_start}"
            )


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
