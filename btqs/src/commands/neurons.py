import os
import psutil
import typer
import yaml
from rich.console import Console
from bittensor_wallet import Wallet, Keypair
from git import Repo, GitCommandError

from btqs.config import (
    CONFIG_FILE_PATH,
    BTQS_WALLETS_DIRECTORY,
    SUBNET_TEMPLATE_REPO_URL,
    SUBNET_TEMPLATE_BRANCH,
)
from btqs.utils import (
    console,
    exec_command,
    remove_ansi_escape_sequences,
    get_process_entries,
    display_process_status_table,
    start_validator,
    start_miner,
    attach_to_process_logs,
    subnet_owner_exists,
)

def setup_neurons(config_data):
    subnet_owner, owner_data = subnet_owner_exists(CONFIG_FILE_PATH)
    if not subnet_owner:
        console.print(
            "[red]Subnet netuid 1 registered to the owner not found. Run `btqs subnet setup` first"
        )
        return

    config_data.setdefault("Miners", {})
    miners = config_data.get("Miners", {})

    if miners and all(
        miner_info.get("subtensor_pid") == config_data.get("pid")
        for miner_info in miners.values()
    ):
        console.print(
            "[green]Miner wallets associated with this subtensor instance already present. Proceeding..."
        )
    else:
        _create_miner_wallets(config_data)

    _register_miners(config_data)

    console.print("[dark_green]\nViewing Metagraph for Subnet 1")
    subnets_list = exec_command(
        command="subnets",
        sub_command="metagraph",
        extra_args=[
            "--netuid",
            "1",
            "--chain",
            "ws://127.0.0.1:9945",
        ],
    )
    print(subnets_list.stdout, end="")

def run_neurons(config_data):
    # Ensure subnet-template is available
    subnet_template_path = _ensure_subnet_template(config_data)

    chain_pid = config_data.get("pid")
    config_data["subnet_path"] = subnet_template_path

    # Handle Validator
    if config_data.get("Owner"):
        _handle_validator(config_data, subnet_template_path, chain_pid)

    # Handle Miners
    _handle_miners(config_data, subnet_template_path, chain_pid)

    with open(CONFIG_FILE_PATH, "w") as config_file:
        yaml.safe_dump(config_data, config_file)

def stop_neurons(config_data):
    # Get process entries
    process_entries, _, _ = get_process_entries(config_data)
    display_process_status_table(process_entries, [], [])

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

    if not running_neurons:
        console.print("[red]No running neurons to stop.")
        return

    console.print("\nSelect neurons to stop:")
    for idx, neuron in enumerate(running_neurons, start=1):
        console.print(f"{idx}. {neuron['process']} (PID: {neuron['pid']})")

    selection = typer.prompt(
        "Enter neuron numbers to stop (comma-separated), or 'all' to stop all",
        default="all",
    )

    if selection.lower() == "all":
        selected_neurons = running_neurons
    else:
        selected_indices = [
            int(i.strip()) for i in selection.split(",") if i.strip().isdigit()
        ]
        selected_neurons = [
            running_neurons[i - 1]
            for i in selected_indices
            if 1 <= i <= len(running_neurons)
        ]

    if not selected_neurons:
        console.print("[red]No valid neurons selected.")
        return

    # Stop selected neurons
    _stop_selected_neurons(config_data, selected_neurons)

    with open(CONFIG_FILE_PATH, "w") as config_file:
        yaml.safe_dump(config_data, config_file)

def start_neurons(config_data):
    # Get process entries
    process_entries, _, _ = get_process_entries(config_data)
    display_process_status_table(process_entries, [], [])

    # Filter stopped neurons
    stopped_neurons = [
        entry
        for entry in process_entries
        if (
            entry["process"].startswith("Miner")
            or entry["process"].startswith("Validator")
        )
        and entry["status"] == "Not Running"
    ]

    if not stopped_neurons:
        console.print("[green]All neurons are already running.")
        return

    console.print("\nSelect neurons to start:")
    for idx, neuron in enumerate(stopped_neurons, start=1):
        console.print(f"{idx}. {neuron['process']}")

    selection = typer.prompt(
        "Enter neuron numbers to start (comma-separated), or 'all' to start all",
        default="all",
    )

    if selection.lower() == "all":
        selected_neurons = stopped_neurons
    else:
        selected_indices = [
            int(i.strip()) for i in selection.split(",") if i.strip().isdigit()
        ]
        selected_neurons = [
            stopped_neurons[i - 1]
            for i in selected_indices
            if 1 <= i <= len(stopped_neurons)
        ]

    if not selected_neurons:
        console.print("[red]No valid neurons selected.")
        return

    # Start selected neurons
    _start_selected_neurons(config_data, selected_neurons)

    with open(CONFIG_FILE_PATH, "w") as config_file:
        yaml.safe_dump(config_data, config_file)

# Helper functions

def _create_miner_wallets(config_data):
    uris = ["//Bob", "//Charlie"]
    ports = [8101, 8102, 8103]
    for i, uri in enumerate(uris):
        console.print(f"Miner {i+1}:")
        wallet_name = typer.prompt(
            f"Enter wallet name for miner {i+1}", default=f"{uri.strip('//')}"
        )
        hotkey_name = typer.prompt(
            f"Enter hotkey name for miner {i+1}", default="default"
        )

        keypair = Keypair.create_from_uri(uri)
        wallet = Wallet(
            path=BTQS_WALLETS_DIRECTORY, name=wallet_name, hotkey=hotkey_name
        )
        wallet.set_coldkey(keypair=keypair, encrypt=False, overwrite=True)
        wallet.set_coldkeypub(keypair=keypair, encrypt=False, overwrite=True)
        wallet.set_hotkey(keypair=keypair, encrypt=False, overwrite=True)

        config_data["Miners"][wallet_name] = {
            "path": BTQS_WALLETS_DIRECTORY,
            "hotkey": hotkey_name,
            "uri": uri,
            "pid": None,
            "subtensor_pid": config_data["pid"],
            "port": ports[i],
        }

    with open(CONFIG_FILE_PATH, "w") as config_file:
        yaml.safe_dump(config_data, config_file)

    console.print("[green]All wallets are created.")

def _register_miners(config_data):
    for wallet_name, wallet_info in config_data["Miners"].items():
        wallet = Wallet(
            path=wallet_info["path"],
            name=wallet_name,
            hotkey=wallet_info["hotkey"],
        )

        console.print(
            f"Registering Miner ({wallet_name}) to Netuid 1\n",
            style="bold light_goldenrod2",
        )

        miner_registered = exec_command(
            command="subnets",
            sub_command="register",
            extra_args=[
                "--wallet-path",
                wallet.path,
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
        clean_stdout = remove_ansi_escape_sequences(miner_registered.stdout)

        if "✅ Registered" in clean_stdout:
            console.print(f"[green]Registered miner ({wallet.name}) to Netuid 1")
        else:
            console.print(
                f"[red]Failed to register miner ({wallet.name}). Please register the miner manually."
            )
            command = (
                f"btcli subnets register --wallet-path {wallet.path} --wallet-name "
                f"{wallet.name} --hotkey {wallet.hotkey_str} --netuid 1 --chain "
                f"ws://127.0.0.1:9945 --no-prompt"
            )
            console.print(f"[bold yellow]{command}\n")

def _ensure_subnet_template(config_data):
    base_path = config_data.get("base_path")
    if not base_path:
        console.print("[red]Base path not found in the configuration file.")
        return

    subnet_template_path = os.path.join(base_path, "subnet-template")

    if not os.path.exists(subnet_template_path):
        console.print("[green]Cloning subnet-template repository...")
        try:
            repo = Repo.clone_from(
                SUBNET_TEMPLATE_REPO_URL,
                subnet_template_path,
            )
            repo.git.checkout(SUBNET_TEMPLATE_BRANCH)
            console.print("[green]Cloned subnet-template repository successfully.")
        except GitCommandError as e:
            console.print(f"[red]Error cloning subnet-template repository: {e}")
    else:
        console.print("[green]Using existing subnet-template repository.")
        repo = Repo(subnet_template_path)
        current_branch = repo.active_branch.name
        if current_branch != SUBNET_TEMPLATE_BRANCH:
            try:
                repo.git.checkout(SUBNET_TEMPLATE_BRANCH)
                console.print(
                    f"[green]Switched to branch '{SUBNET_TEMPLATE_BRANCH}'."
                )
            except GitCommandError as e:
                console.print(
                    f"[red]Error switching to branch '{SUBNET_TEMPLATE_BRANCH}': {e}"
                )

    return subnet_template_path

def _handle_validator(config_data, subnet_template_path, chain_pid):
    owner_info = config_data["Owner"]
    validator_pid = owner_info.get("pid")
    validator_subtensor_pid = owner_info.get("subtensor_pid")

    if (
        validator_pid
        and psutil.pid_exists(validator_pid)
        and validator_subtensor_pid == chain_pid
    ):
        console.print(
            "[green]Validator is already running. Attaching to the process..."
        )
        log_file_path = owner_info.get("log_file")
        if log_file_path and os.path.exists(log_file_path):
            attach_to_process_logs(log_file_path, "Validator", validator_pid)
        else:
            console.print("[red]Log file not found for validator. Cannot attach.")
    else:
        # Validator is not running, start it
        success = start_validator(owner_info, subnet_template_path, config_data)
        if not success:
            console.print("[red]Failed to start validator.")

def _handle_miners(config_data, subnet_template_path, chain_pid):
    for wallet_name, wallet_info in config_data.get("Miners", {}).items():
        miner_pid = wallet_info.get("pid")
        miner_subtensor_pid = wallet_info.get("subtensor_pid")
        # Check if miner process is running and associated with the current chain
        if (
            miner_pid
            and psutil.pid_exists(miner_pid)
            and miner_subtensor_pid == chain_pid
        ):
            console.print(
                f"[green]Miner {wallet_name} is already running. Attaching to the process..."
            )
            log_file_path = wallet_info.get("log_file")
            if log_file_path and os.path.exists(log_file_path):
                attach_to_process_logs(
                    log_file_path, f"Miner {wallet_name}", miner_pid
                )
            else:
                console.print(
                    f"[red]Log file not found for miner {wallet_name}. Cannot attach."
                )
        else:
            # Miner is not running, start it
            success = start_miner(
                wallet_name, wallet_info, subnet_template_path, config_data
            )
            if not success:
                console.print(f"[red]Failed to start miner {wallet_name}.")

def _stop_selected_neurons(config_data, selected_neurons):
    for neuron in selected_neurons:
        pid = int(neuron["pid"])
        neuron_name = neuron["process"]
        try:
            process = psutil.Process(pid)
            process.terminate()
            process.wait(timeout=10)
            console.print(f"[green]{neuron_name} stopped.")
        except psutil.NoSuchProcess:
            console.print(f"[yellow]{neuron_name} process not found.")
        except psutil.TimeoutExpired:
            console.print(f"[red]Timeout stopping {neuron_name}. Forcing stop.")
            process.kill()

        if neuron["process"].startswith("Miner"):
            wallet_name = neuron["process"].split("Miner: ")[-1]
            config_data["Miners"][wallet_name]["pid"] = None
        elif neuron["process"].startswith("Validator"):
            config_data["Owner"]["pid"] = None

def _start_selected_neurons(config_data, selected_neurons):
    subnet_template_path = _ensure_subnet_template(config_data)

    for neuron in selected_neurons:
        neuron_name = neuron["process"]
        if neuron_name.startswith("Validator"):
            success = start_validator(
                config_data["Owner"], subnet_template_path, config_data
            )
        elif neuron_name.startswith("Miner"):
            wallet_name = neuron_name.split("Miner: ")[-1]
            wallet_info = config_data["Miners"][wallet_name]
            success = start_miner(
                wallet_name, wallet_info, subnet_template_path, config_data
            )

        if success:
            console.print(f"[green]{neuron_name} started successfully.")
        else:
            console.print(f"[red]Failed to start {neuron_name}.")

    # Update the process entries after starting neurons
    process_entries, _, _ = get_process_entries(config_data)
    display_process_status_table(process_entries, [], [])