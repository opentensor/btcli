import os
import re
import subprocess
import sys
import time
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

import psutil
import typer
import yaml
from bittensor_cli.cli import CLIManager
from bittensor_wallet import Wallet
from rich.console import Console
from rich.table import Table
from typer.testing import CliRunner

from .config import (
    BTQS_DIRECTORY,
    BTQS_WALLETS_DIRECTORY,
    CONFIG_FILE_PATH,
)

console = Console()

def load_config(
    error_message: Optional[str] = None, exit_if_missing: bool = True
) -> dict[str, Any]:
    """
    Loads the configuration file.

    Args:
        error_message (Optional[str]): Custom error message to display if config file is not found.
        exit_if_missing (bool): If True, exits the program if the config file is missing.

    Returns:
        Dict[str, Any]: Configuration data.

    Raises:
        typer.Exit: If the config file is not found and exit_if_missing is True.
    """
    if not os.path.exists(CONFIG_FILE_PATH):
        if exit_if_missing:
            if error_message:
                console.print(f"[red]{error_message}")
            else:
                console.print("[red]Configuration file not found.")
            raise typer.Exit()
        else:
            return {}
    with open(CONFIG_FILE_PATH, "r") as config_file:
        config_data = yaml.safe_load(config_file) or {}
    return config_data

def remove_ansi_escape_sequences(text: str) -> str:
    """
    Removes ANSI escape sequences from the given text.

    Args:
        text (str): The text from which to remove ANSI sequences.

    Returns:
        str: The cleaned text.
    """
    ansi_escape = re.compile(
        r"""
        \x1B    # ESC character
        (?:     # Non-capturing group
            [@-Z\\-_]  # 7-bit C1 control codes
            |          # or
            \[         # ESC[
            [0-?]*     # Parameter bytes
            [ -/]*     # Intermediate bytes
            [@-~]      # Final byte
        )
    """,
        re.VERBOSE,
    )
    return ansi_escape.sub("", text)

def exec_command(
    command: str,
    sub_command: str,
    extra_args: Optional[list[str]] = None,
    inputs: Optional[list[str]] = None,
    internal_command: bool = False,
) -> typer.testing.Result:
    """
    Executes a command using the CLIManager and returns the result.

    Args:
        command (str): The main command to execute.
        sub_command (str): The sub-command to execute.
        extra_args (List[str], optional): Additional arguments for the command.
        inputs (List[str], optional): Inputs for interactive prompts.

    Returns:
        typer.testing.Result: The result of the command execution.
    """
    extra_args = extra_args or []
    cli_manager = CLIManager()
    runner = CliRunner()

    args = [command, sub_command] + extra_args
    command_for_printing = ["btcli"] + [str(arg) for arg in args]

    if not internal_command:
        console.print(
            f"Executing command: [dark_orange]{' '.join(command_for_printing)}\n"
        )

    input_text = "\n".join(inputs) + "\n" if inputs else None
    result = runner.invoke(
        cli_manager.app,
        args,
        input=input_text,
        env={"COLUMNS": "700"},
        catch_exceptions=False,
        color=False,
    )
    return result

def is_chain_running(config_file_path: str) -> bool:
    """
    Checks if the local chain is running by verifying the PID in the config file.

    Args:
        config_file_path (str): Path to the configuration file.

    Returns:
        bool: True if the chain is running, False otherwise.
    """
    if not os.path.exists(config_file_path):
        return False
    with open(config_file_path, "r") as config_file:
        config_data = yaml.safe_load(config_file) or {}
    pid = config_data.get("pid")
    if not pid:
        return False
    try:
        process = psutil.Process(pid)
        return process.is_running()
    except psutil.NoSuchProcess:
        return False

def subnet_owner_exists(config_file_path: str) -> Tuple[bool, dict]:
    """
    Checks if a subnet owner exists in the config file.

    Args:
        config_file_path (str): Path to the configuration file.

    Returns:
        Tuple[bool, dict]: (True, owner data) if exists, else (False, {}).
    """
    if not os.path.exists(config_file_path):
        return False, {}
    with open(config_file_path, "r") as config_file:
        config_data = yaml.safe_load(config_file) or {}

    owner_data = config_data.get("Owner")
    pid = config_data.get("pid")

    if owner_data and pid:
        if owner_data.get("subtensor_pid") == pid:
            return True, owner_data

    return False, {}

def subnet_exists(ss58_address: str, netuid: int) -> bool:
    """
    Checks if a subnet exists by verifying the subnet list output.
    """
    subnets_list = exec_command(
        command="subnets",
        sub_command="list",
        extra_args=[
            "--chain",
            "ws://127.0.0.1:9945",
        ],
        internal_command=True,
    )
    exists = verify_subnet_entry(
        remove_ansi_escape_sequences(subnets_list.stdout), netuid, ss58_address
    )
    return exists

def verify_subnet_entry(output_text: str, netuid: int, ss58_address: str) -> bool:
    """
    Verifies the presence of a specific subnet entry in the subnets list output.

    Args:
        output_text (str): Output of execution command.
        netuid (str): The netuid to look for.
        ss58_address (str): The SS58 address of the subnet owner.

    Returns:
        bool: True if the entry is found, False otherwise.
    """
    output_text = remove_ansi_escape_sequences(output_text)
    lines = output_text.split("\n")

    data_started = False

    for line in lines:
        line = line.strip()
        if not line:
            continue

        if "NETUID" in line:
            data_started = True
            continue

        if not data_started:
            continue

        if set(line) <= {"━", "╇", "┼", "─", "╈", "═", "║", "╬", "╣", "╠"}:
            continue

        columns = re.split(r"│|\|", line)
        columns = [col.strip() for col in columns]

        if len(columns) < 8:
            continue

        netuid_col = columns[0]
        ss58_address_col = columns[-1]

        if netuid_col == str(netuid) and ss58_address_col == ss58_address:
            return True

    return False

def get_btcli_version() -> str:
    """
    Gets the version of btcli.
    """
    try:
        result = subprocess.run(["btcli", "--version"], capture_output=True, text=True)
        return result.stdout.strip()
    except Exception:
        return "Not installed or not found"

def get_bittensor_wallet_version() -> str:
    """
    Gets the version of bittensor-wallet.
    """
    try:
        result = subprocess.run(
            ["pip", "show", "bittensor-wallet"], capture_output=True, text=True
        )
        for line in result.stdout.split("\n"):
            if line.startswith("Version:"):
                return line.split(":")[1].strip()
    except Exception:
        return "Not installed or not found"

def get_python_version() -> str:
    """
    Gets the Python version.
    """
    return sys.version.split()[0]

def get_python_path() -> str:
    """
    Gets the Python executable path.
    """
    return sys.executable

def get_process_info(pid: int) -> Tuple[str, str, str, str, float, float]:
    """
    Retrieves process information.
    """
    if pid and psutil.pid_exists(pid):
        try:
            process = psutil.Process(pid)
            status = "Running"
            cpu_percent = process.cpu_percent(interval=0.1)
            memory_percent = process.memory_percent()
            cpu_usage = f"{cpu_percent:.1f}%"
            memory_usage = f"{memory_percent:.1f}%"
            create_time = datetime.fromtimestamp(process.create_time())
            uptime = datetime.now() - create_time
            uptime_str = str(uptime).split(".")[0]
            return (
                status,
                cpu_usage,
                memory_usage,
                uptime_str,
                cpu_percent,
                memory_percent,
            )
        except Exception as e:
            console.print(f"[red]Error retrieving process info: {e}")
    status = "Not Running"
    cpu_usage = "N/A"
    memory_usage = "N/A"
    uptime_str = "N/A"
    cpu_percent = 0.0
    memory_percent = 0.0
    pid = "N/A"
    return status, cpu_usage, memory_usage, uptime_str, cpu_percent, memory_percent

def get_process_entries(
    config_data: Dict[str, Any],
) -> Tuple[list[Dict[str, str]], list[float], list[float]]:
    """
    Gets process entries for display.
    """
    cpu_usage_list = []
    memory_usage_list = []
    process_entries = []

    # Check Subtensor status
    pid = config_data.get("pid")
    subtensor_path = config_data.get("subtensor_path", "N/A")
    status, cpu_usage, memory_usage, uptime_str, cpu_percent, memory_percent = (
        get_process_info(pid)
    )

    status_style = "green" if status == "Running" else "red"

    if status == "Running":
        cpu_usage_list.append(cpu_percent)
        memory_usage_list.append(memory_percent)

    process_entries.append(
        {
            "process": "Subtensor",
            "status": status,
            "status_style": status_style,
            "pid": str(pid),
            "cpu_usage": cpu_usage,
            "memory_usage": memory_usage,
            "uptime_str": uptime_str,
            "location": subtensor_path,
        }
    )

    # Check status of Subtensor nodes (substrate_pids)
    substrate_pids = config_data.get("substrate_pid", [])
    for index, sub_pid in enumerate(substrate_pids, start=1):
        status, cpu_usage, memory_usage, uptime_str, cpu_percent, memory_percent = (
            get_process_info(sub_pid)
        )
        status_style = "green" if status == "Running" else "red"

        if status == "Running":
            cpu_usage_list.append(cpu_percent)
            memory_usage_list.append(memory_percent)

        process_entries.append(
            {
                "process": f"Subtensor Node {index}",
                "status": status,
                "status_style": status_style,
                "pid": str(sub_pid),
                "cpu_usage": cpu_usage,
                "memory_usage": memory_usage,
                "uptime_str": uptime_str,
                "location": subtensor_path,
            }
        )

    # Check status of Miners
    miners = config_data.get("Miners", {})
    for wallet_name, wallet_info in miners.items():
        pid = wallet_info.get("pid")
        location = wallet_info.get("path")
        status, cpu_usage, memory_usage, uptime_str, cpu_percent, memory_percent = (
            get_process_info(pid)
        )

        status_style = "green" if status == "Running" else "red"

        if status == "Running":
            cpu_usage_list.append(cpu_percent)
            memory_usage_list.append(memory_percent)

        process_entries.append(
            {
                "process": f"Miner: {wallet_name}",
                "status": status,
                "status_style": status_style,
                "pid": str(pid),
                "cpu_usage": cpu_usage,
                "memory_usage": memory_usage,
                "uptime_str": uptime_str,
                "location": location,
            }
        )

    # Check status of Validator
    owner_data = config_data.get("Owner")
    if owner_data:
        pid = owner_data.get("pid")
        location = owner_data.get("path")
        status, cpu_usage, memory_usage, uptime_str, cpu_percent, memory_percent = (
            get_process_info(pid)
        )

        status_style = "green" if status == "Running" else "red"

        if status == "Running":
            cpu_usage_list.append(cpu_percent)
            memory_usage_list.append(memory_percent)

        process_entries.append(
            {
                "process": "Validator",
                "status": status,
                "status_style": status_style,
                "pid": str(pid),
                "cpu_usage": cpu_usage,
                "memory_usage": memory_usage,
                "uptime_str": uptime_str,
                "location": location,
            }
        )

    return process_entries, cpu_usage_list, memory_usage_list

def display_process_status_table(
    process_entries: list[Dict[str, str]],
    cpu_usage_list: list[float],
    memory_usage_list: list[float],
) -> None:
    """
    Displays the process status table.
    """
    table = Table(
        title="[underline dark_orange]BTQS Process Manager[/underline dark_orange]\n",
        show_footer=True,
        show_edge=False,
        header_style="bold white",
        border_style="bright_black",
        style="bold",
        title_justify="center",
        show_lines=False,
        pad_edge=True,
    )

    table.add_column(
        "[bold white]Process",
        style="white",
        no_wrap=True,
        footer_style="bold white",
    )

    table.add_column(
        "[bold white]Status",
        style="bright_cyan",
        justify="center",
        footer_style="bold white",
    )

    table.add_column(
        "[bold white]PID",
        style="bright_magenta",
        justify="right",
        footer_style="bold white",
    )

    table.add_column(
        "[bold white]CPU %",
        style="light_goldenrod2",
        justify="right",
        footer_style="bold white",
    )

    table.add_column(
        "[bold white]Memory %",
        style="light_goldenrod2",
        justify="right",
        footer_style="bold white",
    )

    table.add_column(
        "[bold white]Uptime",
        style="dark_sea_green",
        justify="right",
        footer_style="bold white",
    )

    table.add_column(
        "[bold white]Location",
        style="white",
        overflow="fold",
        footer_style="bold white",
    )

    for entry in process_entries:
        if entry["process"].startswith("Subtensor"):
            process_style = "cyan"
        elif entry["process"].startswith("Miner"):
            process_style = "magenta"
        elif entry["process"].startswith("Validator"):
            process_style = "yellow"
        else:
            process_style = "white"

        table.add_row(
            f"[{process_style}]{entry['process']}[/{process_style}]",
            f"[{entry['status_style']}]{entry['status']}[/{entry['status_style']}]",
            entry["pid"],
            entry["cpu_usage"],
            entry["memory_usage"],
            entry["uptime_str"],
            entry["location"],
        )

    # Compute total CPU and Memory usage
    total_cpu = sum(cpu_usage_list)
    total_memory = sum(memory_usage_list)

    # Set footers for columns
    table.columns[0].footer = f"[white]{len(process_entries)} Processes[/white]"
    table.columns[3].footer = f"[white]{total_cpu:.1f}%[/white]"
    table.columns[4].footer = f"[white]{total_memory:.1f}%[/white]"

    # Display the table
    console.print(table)

def start_miner(
    wallet_name: str,
    wallet_info: Dict[str, Any],
    subnet_template_path: str,
    config_data: Dict[str, Any],
) -> bool:
    """
    Starts a single miner and displays logs until user presses Ctrl+C.
    """
    wallet = Wallet(
        path=wallet_info["path"],
        name=wallet_name,
        hotkey=wallet_info["hotkey"],
    )
    console.print(f"[green]Starting miner {wallet_name}...")

    env_variables = os.environ.copy()
    env_variables["BT_AXON_PORT"] = str(wallet_info["port"])
    env_variables["PYTHONUNBUFFERED"] = "1"

    cmd = [
        sys.executable,
        "-u",
        "./neurons/miner.py",
        "--wallet.name",
        wallet.name,
        "--wallet.hotkey",
        wallet.hotkey_str,
        "--wallet.path",
        BTQS_WALLETS_DIRECTORY,
        "--subtensor.chain_endpoint",
        "ws://127.0.0.1:9945",
        "--logging.trace",
    ]

    # Create log file paths
    logs_dir = os.path.join(config_data["base_path"], "logs")
    os.makedirs(logs_dir, exist_ok=True)
    log_file_path = os.path.join(logs_dir, f"miner_{wallet_name}.log")

    with open(log_file_path, "a") as log_file:
        try:
            # Start the subprocess, redirecting stdout and stderr to the log file
            process = subprocess.Popen(
                cmd,
                cwd=subnet_template_path,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                env=env_variables,
                start_new_session=True,
            )
            wallet_info["pid"] = process.pid
            wallet_info["log_file"] = log_file_path

            # Update config_data
            config_data["Miners"][wallet_name] = wallet_info

            console.print(f"[green]Miner {wallet_name} started. Press Ctrl+C to proceed.")
            attach_to_process_logs(log_file_path, f"Miner {wallet_name}", process.pid)
            return True
        except Exception as e:
            console.print(f"[red]Error starting miner {wallet_name}: {e}")
            return False
def start_validator(
    owner_info: Dict[str, Any],
    subnet_template_path: str,
    config_data: Dict[str, Any],
) -> bool:
    """
    Starts the validator process and displays logs until user presses Ctrl+C.
    """
    wallet = Wallet(
        path=owner_info["path"],
        name=owner_info["wallet_name"],
        hotkey=owner_info["hotkey"],
    )
    console.print("[green]Starting validator...")

    env_variables = os.environ.copy()
    env_variables["PYTHONUNBUFFERED"] = "1"
    env_variables["BT_AXON_PORT"] = str(8100)

    cmd = [
        sys.executable,
        "-u",
        "./neurons/validator.py",
        "--wallet.name",
        wallet.name,
        "--wallet.hotkey",
        wallet.hotkey_str,
        "--wallet.path",
        BTQS_WALLETS_DIRECTORY,
        "--subtensor.chain_endpoint",
        "ws://127.0.0.1:9945",
        "--netuid",
        "1",
        "--logging.trace",
    ]

    # Create log file paths
    logs_dir = os.path.join(config_data["base_path"], "logs")
    os.makedirs(logs_dir, exist_ok=True)
    log_file_path = os.path.join(logs_dir, "validator.log")

    with open(log_file_path, "a") as log_file:
        try:
            # Start the subprocess, redirecting stdout and stderr to the log file
            process = subprocess.Popen(
                cmd,
                cwd=subnet_template_path,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                env=env_variables,
                start_new_session=True,
            )
            owner_info["pid"] = process.pid
            owner_info["log_file"] = log_file_path

            # Update config_data
            config_data["Owner"] = owner_info

            console.print("[green]Validator started. Press Ctrl+C to proceed.")
            attach_to_process_logs(log_file_path, "Validator", process.pid)
            return True
        except Exception as e:
            console.print(f"[red]Error starting validator: {e}")
            return False
def attach_to_process_logs(log_file_path: str, process_name: str, pid: int = None):
    """
    Attaches to the log file of a process and prints logs until user presses Ctrl+C or the process terminates.
    """
    try:
        with open(log_file_path, "r") as log_file:
            # Move to the end of the file
            log_file.seek(0, os.SEEK_END)
            console.print(
                f"[green]Attached to {process_name}. Press Ctrl+C to move to the next process."
            )
            while True:
                line = log_file.readline()
                if not line:
                    # Check if the process is still running
                    if pid and not psutil.pid_exists(pid):
                        console.print(f"\n[red]{process_name} process has terminated.")
                        break
                    time.sleep(0.1)
                    continue
                print(line, end="")
    except KeyboardInterrupt:
        console.print(f"\n[green]Detached from {process_name}.")
    except Exception as e:
        console.print(f"[red]Error attaching to {process_name}: {e}")
