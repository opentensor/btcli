import sys
import os
import subprocess
import time
from threading import Thread
from rich.console import Console
from rich.progress import (
    Progress,
    SpinnerColumn,
    BarColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.text import Text

import asyncio
import psutil
import yaml
from btqs.config import (
    BTQS_LOCK_CONFIG_FILE_PATH,
    SUBTENSOR_REPO_URL,
    LOCALNET_ENDPOINT,
    SUDO_URI,
)
from bittensor_wallet import Wallet, Keypair
from btqs.utils import (
    attach_to_process_logs,
    create_virtualenv,
    get_process_entries,
    install_subtensor_dependencies,
    print_info,
    print_success,
    print_error,
    print_info_box,
    messages,
    display_process_status_table,
    console,
)
from git import GitCommandError, Repo
from rich.prompt import Confirm
from bittensor_cli.src.bittensor.async_substrate_interface import (
    AsyncSubstrateInterface,
)


def update_chain_tempos(
    config_data: dict,
    netuid_tempo_list: list[tuple[int, int]],
    add_emission_tempo: bool = True,
    emission_tempo: int = 10,
):
    """
    Update tempos on the chain for given netuids and optionally update emission tempo.

    Parameters:
    - config_data: Configuration data containing paths and other settings.
    - netuid_tempo_list: List of tuples where each tuple contains (netuid, tempo).
    - add_emission_tempo: Boolean flag to indicate if emission tempo should be updated.
    - emission_tempo: The value to set for emission tempo if `add_emission_tempo` is True.
    """
    # Initialize the Rich console
    console = Console()

    keypair = Keypair.create_from_uri(SUDO_URI)
    sudo_wallet = Wallet(
        path=config_data["wallets_path"],
        name="sudo",
        hotkey="default",
    )
    sudo_wallet.set_coldkey(keypair=keypair, encrypt=False, overwrite=True)
    sudo_wallet.set_coldkeypub(keypair=keypair, encrypt=False, overwrite=True)
    sudo_wallet.set_hotkey(keypair=keypair, encrypt=False, overwrite=True)
    print_info_box(
        "**Emissions Tempo** control the frequency at which rewards (emissions) are distributed to hotkeys. On Finney (mainnet), the setting is every 7200 blocks, which equates to approximately 1 day.",
        title="Info: Emission and Subnet Tempos",
    )
    total_steps = len(netuid_tempo_list) + (1 if add_emission_tempo else 0)

    desc_width = 30
    progress = Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}", justify="left"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}", justify="right"),
        TimeElapsedColumn(),
        console=console,
    )

    console.print("\n[bold yellow]Getting the chain ready...\n")
    with progress:
        task = progress.add_task("Initializing...", total=total_steps)

        def update_description():
            i = 0
            while not progress.finished:
                message = messages[i % len(messages)]
                printable_length = len(Text.from_markup(message).plain)
                if printable_length < desc_width:
                    padded_message = message + " " * (desc_width - printable_length)
                else:
                    padded_message = message[:desc_width]
                progress.update(task, description=padded_message)
                time.sleep(3)  # Update every 3 seconds
                i += 1

        # Start the thread to update the description
        desc_thread = Thread(target=update_description)
        desc_thread.start()
        local_chain = AsyncSubstrateInterface(chain_endpoint=LOCALNET_ENDPOINT)
        try:
            if add_emission_tempo:
                local_chain = AsyncSubstrateInterface(chain_endpoint=LOCALNET_ENDPOINT)
                success = asyncio.run(
                    sudo_set_emission_tempo(local_chain, sudo_wallet, emission_tempo)
                )
                progress.advance(task)

            for netuid, tempo in netuid_tempo_list:
                local_chain = AsyncSubstrateInterface(chain_endpoint=LOCALNET_ENDPOINT)
                success = asyncio.run(
                    sudo_set_tempo(local_chain, sudo_wallet, netuid, tempo)
                )
                progress.advance(task)
        finally:
            desc_thread.join()


async def sudo_set_emission_tempo(
    substrate: "AsyncSubstrateInterface", wallet: Wallet, emission_tempo: int
) -> bool:
    async with substrate:
        emission_call = await substrate.compose_call(
            call_module="AdminUtils",
            call_function="sudo_set_hotkey_emission_tempo",
            call_params={"emission_tempo": emission_tempo},
        )
        sudo_call = await substrate.compose_call(
            call_module="Sudo",
            call_function="sudo",
            call_params={"call": emission_call},
        )
        extrinsic = await substrate.create_signed_extrinsic(
            call=sudo_call, keypair=wallet.coldkey
        )
        response = await substrate.submit_extrinsic(
            extrinsic,
            wait_for_inclusion=True,
            wait_for_finalization=True,
        )
        await response.process_events()
        return await response.is_success


async def sudo_set_target_registrations_per_interval(
    substrate: "AsyncSubstrateInterface",
    wallet: Wallet,
    netuid: int,
    target_registrations_per_interval: int,
) -> bool:
    async with substrate:
        registration_call = await substrate.compose_call(
            call_module="AdminUtils",
            call_function="sudo_set_target_registrations_per_interval",
            call_params={
                "netuid": netuid,
                "target_registrations_per_interval": target_registrations_per_interval,
            },
        )
        sudo_call = await substrate.compose_call(
            call_module="Sudo",
            call_function="sudo",
            call_params={"call": registration_call},
        )
        extrinsic = await substrate.create_signed_extrinsic(
            call=sudo_call, keypair=wallet.coldkey
        )
        response = await substrate.submit_extrinsic(
            extrinsic,
            wait_for_inclusion=True,
            wait_for_finalization=True,
        )

        await response.process_events()
        return await response.is_success


async def sudo_set_tempo(
    substrate: "AsyncSubstrateInterface", wallet: Wallet, netuid: int, tempo: int
) -> bool:
    async with substrate:
        set_tempo_call = await substrate.compose_call(
            call_module="AdminUtils",
            call_function="sudo_set_tempo",
            call_params={"netuid": netuid, "tempo": tempo},
        )
        sudo_call = await substrate.compose_call(
            call_module="Sudo",
            call_function="sudo",
            call_params={"call": set_tempo_call},
        )
        extrinsic = await substrate.create_signed_extrinsic(
            call=sudo_call, keypair=wallet.coldkey
        )
        response = await substrate.submit_extrinsic(
            extrinsic,
            wait_for_inclusion=True,
            wait_for_finalization=True,
        )
        await response.process_events()
        return await response.is_success


def start(config_data, workspace_path, branch, fast_blocks=True, verbose=False, skip_rust=False):
    os.makedirs(workspace_path, exist_ok=True)
    subtensor_path = os.path.join(workspace_path, "subtensor")

    # Clone or update the repository
    if os.path.exists(subtensor_path) and os.listdir(subtensor_path):
        update = Confirm.ask(
            "[blue]Subtensor is already cloned. Do you want to update it?",
            default=False,
            show_default=True,
        )
        if update:
            try:
                repo = Repo(subtensor_path)
                origin = repo.remotes.origin
                repo.git.checkout(branch)
                origin.pull()
                print_info("Repository updated successfully.", emoji="📦 ")
            except GitCommandError as e:
                print_error(f"Error updating repository: {e}")
                return
        else:
            print_info(
                "Using existing subtensor repository without updating.", emoji="📦 "
            )
    else:
        try:
            print_info("Cloning subtensor repository...", emoji="📦 ")
            repo = Repo.clone_from(SUBTENSOR_REPO_URL, subtensor_path)
            if branch:
                repo.git.checkout(branch)
            print_success("Repository cloned successfully.", emoji="🏷 ")
        except GitCommandError as e:
            print_error(f"Error cloning repository: {e}")
            return

    if fast_blocks:
        print_info("Fast blocks are On", emoji="🏎️ ")
    else:
        print_info("Fast blocks are Off", emoji="🐌 ")

    if skip_rust:
        venv_python = sys.executable
        print_info("Skipping Rust installation", emoji="🦘 ")
        config_data["venv_subtensor"] = "None"
        venv_subtensor_path = "None"
    else:
        venv_subtensor_path = os.path.join(workspace_path, "venv_subtensor")
        venv_python = create_virtualenv(venv_subtensor_path)
        install_subtensor_dependencies(verbose)
        print_info("Virtual environment created and dependencies installed.", emoji="🐍 ")
        config_data["venv_subtensor"] = venv_python

    # Running localnet.sh using the virtual environment's Python
    localnet_path = os.path.join(subtensor_path, "scripts", "localnet.sh")

    env_variables = os.environ.copy()
    env_variables["PATH"] = (
        os.path.dirname(venv_python) + os.pathsep + env_variables["PATH"]
    )
    process = subprocess.Popen(
        [localnet_path, str(fast_blocks)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
        cwd=subtensor_path,
        start_new_session=True,
        env=env_variables,
    )

    print_info(
        "Compiling and starting local chain. This may take a few minutes... (Timeout at 20 minutes)",
        emoji="🛠️ ",
    )

    # Paths to subtensor log files
    log_dir = os.path.join(subtensor_path, "logs")
    alice_log = os.path.join(log_dir, "alice.log")

    # Waiting for chain compilation
    timeout = 3000 
    start_time = time.time()
    while not os.path.exists(alice_log):
        if time.time() - start_time > timeout:
            print_error("Timeout: Log files were not created.")
            return
        time.sleep(1)

    chain_ready = wait_for_chain_compilation(alice_log, start_time, timeout, verbose)
    if chain_ready:
        print_info(
            "Local chain is running.\n",
            emoji="\n🔗",
        )

        # Fetch PIDs of substrate nodes
        substrate_pids = get_substrate_pids()
        if substrate_pids is None:
            return

        config_data.update(
            {
                "pid": process.pid,
                "substrate_pid": substrate_pids,
                "subtensor_path": subtensor_path,
                "workspace_path": workspace_path,
                "venv_subtensor": venv_subtensor_path,
                "wallets_path": os.path.join(workspace_path, "wallets"),
                "subnet_path": os.path.join(workspace_path, "subnet-template"),
            }
        )

        # Save config data
        try:
            print_info("Updating config file.\n", emoji="🖋️ ")
            os.makedirs(os.path.dirname(BTQS_LOCK_CONFIG_FILE_PATH), exist_ok=True)
            with open(BTQS_LOCK_CONFIG_FILE_PATH, "w") as config_file:
                yaml.safe_dump(config_data, config_file)
            print_info("Config file updated.", emoji="📝 ")
            update_chain_tempos(
                netuid_tempo_list=[(0, 9), (1, 10)],
                config_data=config_data,
                add_emission_tempo=True,
                emission_tempo=20,
            )
            print_info(
                "Local chain is now set up. You can now use it for development and testing.",
                emoji="\n🚀",
            )
            console.print(f"[dark_orange]Endpoint: {LOCALNET_ENDPOINT}\n")
            print_info_box(
                "📊 **Subtensor Nodes**: During your local Subtensor setup, two blockchain nodes are initiated. These nodes communicate and collaborate to reach consensus, ensuring the integrity and synchronization of your blockchain network.",
                title="Info: Subtensor Nodes",
            )
            process_entries, cpu_usage_list, memory_usage_list = get_process_entries(
                config_data
            )
            display_process_status_table(
                process_entries, cpu_usage_list, memory_usage_list
            )
        except Exception as e:
            print_error(f"Failed to write to the config file: {e}")
    else:
        print_error("Failed to start local chain.")


def stop(config_data):
    pid = config_data.get("pid")
    if not pid:
        console.print("[red]No running chain found.")
        return

    console.print("[red]Stopping the local chain...")

    try:
        process = psutil.Process(pid)
        process.terminate()
        process.wait(timeout=10)
        print_info("Local chain stopped successfully.", emoji="🛑 ")
    except psutil.NoSuchProcess:
        console.print(
            "[red]Process not found. The chain may have already been stopped."
        )
    except psutil.TimeoutExpired:
        console.print("[red]Timeout while stopping the chain. Forcing stop...")
        process.kill()

    # Stop running neurons
    stop_running_neurons(config_data)

    # Refresh data
    refresh_config = Confirm.ask(
        "\n[blue]Config data is outdated. Do you want to refresh it?",
        default=True,
        show_default=True,
    )
    if refresh_config:
        if os.path.exists(BTQS_LOCK_CONFIG_FILE_PATH):
            os.remove(BTQS_LOCK_CONFIG_FILE_PATH)
            print_info("Configuration file refreshed.", emoji="🔄 ")


def reattach(config_data):
    pid = config_data.get("pid")
    subtensor_path = config_data.get("subtensor_path")
    if not pid or not subtensor_path:
        console.print("[red]No running chain found.")
        return

    # Check if the process is still running
    if not is_process_running(pid):
        return

    # Paths to the log files
    log_dir = os.path.join(subtensor_path, "logs")
    alice_log = os.path.join(log_dir, "alice.log")

    # Check if log file exists
    if not os.path.exists(alice_log):
        console.print("[red]Log files not found.")
        return

    # Reattach using attach_to_process_logs
    attach_to_process_logs(alice_log, "Subtensor Chain", pid)


def wait_for_chain_compilation(alice_log, start_time, timeout, verbose):
    chain_ready = False
    try:
        with open(alice_log, "r") as log_file:
            log_file.seek(0, os.SEEK_END)
            while True:
                line = log_file.readline()
                if line:
                    if verbose:
                        console.print(line, end="")
                    if "Imported #" in line:
                        chain_ready = True
                        break
                else:
                    if time.time() - start_time > timeout:
                        console.print("[red]Timeout: Chain did not compile in time.")
                        break
                    time.sleep(0.1)
    except Exception as e:
        console.print(f"[red]Error reading log files: {e}")
    return chain_ready


def get_substrate_pids():
    try:
        result = subprocess.run(
            ["pgrep", "-f", "node-subtensor"], capture_output=True, text=True
        )
        substrate_pids = [int(pid) for pid in result.stdout.strip().split()]
        return substrate_pids
    except ValueError:
        console.print("[red]Failed to get the PID of the Subtensor process.")
        return None


def stop_running_neurons(config_data):
    """Stops any running neurons."""
    process_entries, _, _ = get_process_entries(config_data)

    # Filter running neurons
    running_neurons = [
        entry
        for entry in process_entries
        if (
            entry["process"].startswith("Miner")
            or entry["process"].startswith("Validator")
        )
        and entry["status"] == "Running"
    ]

    if running_neurons:
        print_info("Some neurons are still running. Terminating them...", emoji="\n🧨 ")

        for neuron in running_neurons:
            pid = int(neuron["pid"])
            neuron_name = neuron["process"]
            try:
                neuron_process = psutil.Process(pid)
                neuron_process.terminate()
                neuron_process.wait(timeout=10)
                print_info(f"{neuron_name} stopped.", emoji="🛑 ")
            except psutil.NoSuchProcess:
                console.print(f"[yellow]{neuron_name} process not found.")
            except psutil.TimeoutExpired:
                console.print(f"[red]Timeout stopping {neuron_name}. Forcing stop.")
                neuron_process.kill()

            if neuron["process"].startswith("Miner"):
                wallet_name = neuron["process"].split("Miner: ")[-1]
                config_data["Miners"][wallet_name]["pid"] = None
            elif neuron["process"].startswith("Validator"):
                config_data["Owner"]["pid"] = None

        with open(BTQS_LOCK_CONFIG_FILE_PATH, "w") as config_file:
            yaml.safe_dump(config_data, config_file)
    else:
        print_info("No neurons were running.", emoji="✅ ")


def is_process_running(pid):
    try:
        process = psutil.Process(pid)
        if not process.is_running():
            console.print("[red]Process not running. The chain may have been stopped.")
            return False
        return True
    except psutil.NoSuchProcess:
        console.print("[red]Process not found. The chain may have been stopped.")
        return False
