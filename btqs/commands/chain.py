import os
import subprocess
import time

import psutil

import yaml
from git import GitCommandError, Repo
from rich.console import Console
from rich.text import Text

from btqs.config import CONFIG_FILE_PATH, SUBTENSOR_REPO_URL
from btqs.utils import attach_to_process_logs, get_process_entries, create_virtualenv, install_neuron_dependencies, install_subtensor_dependencies
from rich.prompt import Confirm

console = Console()


def start(config_data, workspace_path, branch):
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
                console.print("[green]Repository updated successfully.")
            except GitCommandError as e:
                console.print(f"[red]Error updating repository: {e}")
                return
        else:
            console.print(
                "[green]Using existing subtensor repository without updating."
            )
    else:
        try:
            console.print("[green]Cloning subtensor repository...")
            repo = Repo.clone_from(SUBTENSOR_REPO_URL, subtensor_path)
            if branch:
                repo.git.checkout(branch)
            console.print("[green]Repository cloned successfully.")
        except GitCommandError as e:
            console.print(f"[red]Error cloning repository: {e}")
            return
    
    venv_subtensor_path = os.path.join(workspace_path, 'venv_subtensor')
    venv_python = create_virtualenv(venv_subtensor_path)
    install_subtensor_dependencies()

    config_data['venv_subtensor'] = venv_subtensor_path

    # Running localnet.sh using the virtual environment's Python
    localnet_path = os.path.join(subtensor_path, "scripts", "localnet.sh")

    env_variables = os.environ.copy()
    env_variables["PATH"] = os.path.dirname(venv_python) + os.pathsep + env_variables["PATH"]
    process = subprocess.Popen(
        [localnet_path],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
        cwd=subtensor_path,
        start_new_session=True,
        env=env_variables,
    )

    console.print("[green]Compiling and starting local chain. This may take a few minutes... (Timeout at 20 minutes)")

    # Paths to subtensor log files
    log_dir = os.path.join(subtensor_path, "logs")
    alice_log = os.path.join(log_dir, "alice.log")

    # Waiting for chain compilation
    timeout = 1200  # 17 minutes
    start_time = time.time()
    while not os.path.exists(alice_log):
        if time.time() - start_time > timeout:
            console.print("[red]Timeout: Log files were not created.")
            return
        time.sleep(1)

    chain_ready = wait_for_chain_compilation(alice_log, start_time, timeout)
    if chain_ready:
        text = Text("Local chain is running. You can now use it for development and testing.\n", style="bold light_goldenrod2")
        sign = Text("\nℹ️ ", style="bold yellow")
        console.print(sign, text)

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
                "subnet_path": os.path.join(workspace_path, "subnet-template")
            }
        )

        # Save config data
        try:
            os.makedirs(os.path.dirname(CONFIG_FILE_PATH), exist_ok=True)
            with open(CONFIG_FILE_PATH, "w") as config_file:
                yaml.safe_dump(config_data, config_file)
            console.print(
                "[green]Config file updated."
            )
        except Exception as e:
            console.print(f"[red]Failed to write to the config file: {e}")
    else:
        console.print("[red]Failed to start local chain.")


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
        console.print("[green]Local chain stopped successfully.")
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
        if os.path.exists(CONFIG_FILE_PATH):
            os.remove(CONFIG_FILE_PATH)
            console.print("[green]Configuration file refreshed.")


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
    attach_to_process_logs(alice_log, "Subtensor Chain (Alice)", pid)


def wait_for_chain_compilation(alice_log, start_time, timeout):
    chain_ready = False
    try:
        with open(alice_log, "r") as log_file:
            log_file.seek(0, os.SEEK_END)
            while True:
                line = log_file.readline()
                if line:
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
        console.print("[yellow]\nSome neurons are still running. Terminating them...")

        for neuron in running_neurons:
            pid = int(neuron["pid"])
            neuron_name = neuron["process"]
            try:
                neuron_process = psutil.Process(pid)
                neuron_process.terminate()
                neuron_process.wait(timeout=10)
                console.print(f"[green]{neuron_name} stopped.")
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

        with open(CONFIG_FILE_PATH, "w") as config_file:
            yaml.safe_dump(config_data, config_file)
    else:
        console.print("[green]No neurons were running.")


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
