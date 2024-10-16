import os
import platform
import subprocess
import time
import time
import threading
import sys
from tqdm import tqdm

from typing import Any, Dict, Optional
from time import sleep
import psutil
import typer
import yaml
from bittensor_wallet import Keypair, Wallet
from git import GitCommandError, Repo
from rich.table import Table
from rich.text import Text

from .config import (
    BTQS_DIRECTORY,
    BTQS_WALLETS_DIRECTORY,
    CONFIG_FILE_PATH,
    EPILOG,
    SUBNET_TEMPLATE_BRANCH,
    SUBNET_TEMPLATE_REPO_URL,
)
from .utils import (
    console,
    display_process_status_table,
    exec_command,
    get_bittensor_wallet_version,
    get_btcli_version,
    get_process_entries,
    get_python_path,
    get_python_version,
    is_chain_running,
    load_config,
    remove_ansi_escape_sequences,
    start_miner,
    start_validator,
    subnet_exists,
    subnet_owner_exists,
    attach_to_process_logs,
)

from btqs.src.commands import chain, neurons

class BTQSManager:
    """
    Bittensor Quick Start (BTQS) Manager.
    Handles CLI commands for managing the local chain and neurons.
    """

    def __init__(self):
        self.app = typer.Typer(
            rich_markup_mode="rich",
            epilog=EPILOG,
            no_args_is_help=True,
            help="BTQS CLI - Bittensor Quickstart",
            add_completion=False,
        )

        self.chain_app = typer.Typer(help="Subtensor Chain operations")
        self.subnet_app = typer.Typer(help="Subnet setup")
        self.neurons_app = typer.Typer(help="Neuron management")

        self.app.add_typer(self.chain_app, name="chain", no_args_is_help=True)
        self.app.add_typer(self.subnet_app, name="subnet", no_args_is_help=True)
        self.app.add_typer(self.neurons_app, name="neurons", no_args_is_help=True)

        # Chain commands
        self.chain_app.command(name="start")(self.start_chain)
        self.chain_app.command(name="stop")(self.stop_chain)
        self.chain_app.command(name="reattach")(self.reattach_chain)

        # Subnet commands
        self.subnet_app.command(name="setup")(self.setup_subnet)

        # Neuron commands
        self.neurons_app.command(name="setup")(self.setup_neurons)
        self.neurons_app.command(name="run")(self.run_neurons)
        self.neurons_app.command(name="stop")(self.stop_neurons)
        self.neurons_app.command(name="reattach")(self.reattach_neurons)
        self.neurons_app.command(name="status")(self.status_neurons)
        self.neurons_app.command(name="live")(self.display_live_metagraph)
        self.neurons_app.command(name="start")(self.start_neurons)
        self.neurons_app.command(name="stake")(self.add_stake)

        self.app.command(name="run-all", help="Create entire setup")(self.run_all)
        self.app.command(name="status", help="Current status of bittensor quick start")(
            self.status_neurons
        )

    def display_live_metagraph(self):
        def clear_screen():
            os.system("cls" if os.name == "nt" else "clear")

        def get_metagraph():
            result = exec_command(
                command="subnets",
                sub_command="metagraph",
                extra_args=[
                    "--netuid",
                    "1",
                    "--chain",
                    "ws://127.0.0.1:9945",
                ],
                internal_command=True
            )
            # clear_screen()
            return result.stdout

        print("Starting live metagraph view. Press 'Ctrl + C' to exit.")
        config_data = load_config(
            "A running Subtensor not found. Please run [dark_orange]`btqs chain start`[/dark_orange] first."
        )

        def input_thread():
            while True:
                if input() == "q":
                    print("Exiting live view...")
                    sys.exit(0)

        threading.Thread(target=input_thread, daemon=True).start()

        try:
            while True:
                metagraph = get_metagraph()
                process_entries, cpu_usage_list, memory_usage_list = get_process_entries(config_data)
                clear_screen()
                print(metagraph)
                display_process_status_table(process_entries, cpu_usage_list, memory_usage_list)

                # Create a progress bar for 5 seconds
                print("\n")
                for _ in tqdm(range(5), desc="Refreshing", unit="s", total=5):
                    time.sleep(1)

        except KeyboardInterrupt:
            print("Exiting live view...")

    def run_all(self):
        """
        Runs all commands in sequence to set up and start the local chain, subnet, and neurons.
        """
        text = Text("Starting Local Subtensor\n", style="bold light_goldenrod2")
        sign = Text("🔗 ", style="bold yellow")
        console.print(sign, text)
        sleep(3)

        # Start the local chain
        self.start_chain()

        text = Text("Checking chain status\n", style="bold light_goldenrod2")
        sign = Text("\n🔎 ", style="bold yellow")
        console.print(sign, text)
        sleep(3)

        self.status_neurons()

        console.print(
            "\nNext command will: 1. Create a subnet owner wallet 2. Create a Subnet 3. Register to the subnet"
        )
        console.print("Press any key to continue..\n")
        input()

        # Set up the subnet
        text = Text("Setting up subnet\n", style="bold light_goldenrod2")
        sign = Text("📡 ", style="bold yellow")
        console.print(sign, text)
        self.setup_subnet()

        console.print(
            "\nNext command will: 1. Create miner wallets 2. Register them to Netuid 1"
        )
        console.print("Press any key to continue..\n")
        input()

        text = Text("Setting up miners\n", style="bold light_goldenrod2")
        sign = Text("\n⚒️ ", style="bold yellow")
        console.print(sign, text)

        # Set up the neurons (miners)
        self.setup_neurons()

        console.print("\nNext command will: 1. Start all miner processes")
        console.print("Press any key to continue..\n")
        input()

        text = Text("Running miners\n", style="bold light_goldenrod2")
        sign = Text("🏃 ", style="bold yellow")
        console.print(sign, text)
        time.sleep(2)

        # Run the neurons
        self.run_neurons()

        # Check status after running the neurons
        self.status_neurons()
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

        self.add_stake()
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
        self.display_live_metagraph()

    def add_stake(self):
        subnet_owner, owner_data = subnet_owner_exists(CONFIG_FILE_PATH)
        if subnet_owner:
            owner_wallet = Wallet(
                name=owner_data.get("wallet_name"),
                path=owner_data.get("path"),
                hotkey=owner_data.get("hotkey"),
            )
            add_stake = exec_command(
                command="stake",
                sub_command="add",
                extra_args=[
                    "--amount",
                    1000,
                    "--wallet-path",
                    BTQS_WALLETS_DIRECTORY,
                    "--chain",
                    "ws://127.0.0.1:9945",
                    "--wallet-name",
                    owner_wallet.name,
                    "--no-prompt",
                    "--wallet-hotkey",
                    owner_wallet.hotkey_str,
                ],
            )

            clean_stdout = remove_ansi_escape_sequences(add_stake.stdout)
            if "✅ Finalized" in clean_stdout:
                text = Text(
                    f"Stake added successfully by Validator ({owner_wallet})\n",
                    style="bold light_goldenrod2",
                )
                sign = Text("📈 ", style="bold yellow")
                console.print(sign, text)
            else:
                console.print("\n[red] Failed to add stake. Command output:\n")
                print(add_stake.stdout, end="")

        else:
            console.print(
                "[red]Subnet netuid 1 registered to the owner not found. Run `btqs subnet setup` first"
            )
            return

    def start_chain(self):
        """
        Starts the local Subtensor chain.

        This command initializes and starts a local instance of the Subtensor blockchain for development and testing.

        USAGE

        [green]$[/green] btqs chain start

        [bold]Note[/bold]: This command will clone or update the Subtensor repository if necessary and start the local chain. It may take several minutes to complete.
        """
        console.print("[dark_orange]Starting the local chain...")

        if is_chain_running(CONFIG_FILE_PATH):
            console.print(
                "[red]The local chain is already running. Endpoint: ws://127.0.0.1:9945"
            )
            return

        config_data = load_config(exit_if_missing=False) or {}
        chain.start_chain(config_data)

    def stop_chain(self):
        """
        Stops the local Subtensor chain and any running miners.

        This command terminates the local Subtensor chain process and optionally cleans up configuration data.

        USAGE

        [green]$[/green] btqs chain stop

        [bold]Note[/bold]: Use this command to gracefully shut down the local chain. It will also stop any running miner processes.
        """
        config_data = load_config(
            "No running chain found. Please run [dark_orange]`btqs chain start`[/dark_orange] first."
        )
        chain.stop_chain(config_data)

    def reattach_chain(self):
        """
        Reattaches to the running local chain.

        This command allows you to view the logs of the running local Subtensor chain.

        USAGE

        [green]$[/green] btqs chain reattach

        [bold]Note[/bold]: Press Ctrl+C to detach from the chain logs.
        """
        config_data = load_config(
            "A running Subtensor not found. Please run [dark_orange]`btqs chain start`[/dark_orange] first."
        )
        chain.reattach_chain(config_data)

    def setup_subnet(self):
        """
        Sets up a subnet on the local chain.

        This command creates a subnet owner wallet, creates a subnet with netuid 1, and registers the owner to the subnet.

        USAGE

        [green]$[/green] btqs subnet setup

        [bold]Note[/bold]: Ensure the local chain is running before executing this command.
        """
        if not is_chain_running(CONFIG_FILE_PATH):
            console.print(
                "[red]Local chain is not running. Please start the chain first."
            )
            return

        config_data = load_config(
            "A running Subtensor not found. Please run [dark_orange]`btqs chain start`[/dark_orange] first."
        )

        os.makedirs(BTQS_WALLETS_DIRECTORY, exist_ok=True)
        subnet_owner, owner_data = subnet_owner_exists(CONFIG_FILE_PATH)
        if subnet_owner:
            owner_wallet = Wallet(
                name=owner_data.get("wallet_name"),
                path=owner_data.get("path"),
                hotkey=owner_data.get("hotkey"),
            )

            warning_text = Text(
                "A Subnet Owner associated with this setup already exists",
                style="bold light_goldenrod2",
            )
            wallet_info = Text(f"\t{owner_wallet}\n", style="medium_purple")
            warning_sign = Text("⚠️ ", style="bold yellow")

            console.print(warning_sign, warning_text)
            console.print(wallet_info)
        else:
            self._create_subnet_owner_wallet(config_data)
            config_data = load_config(
                "A running Subtensor not found. Please run [dark_orange]`btqs chain start`[/dark_orange] first."
            )

        owner_data = config_data["Owner"]
        owner_wallet = Wallet(
            name=owner_data.get("wallet_name"),
            path=owner_data.get("path"),
            hotkey=owner_data.get("hotkey"),
        )

        if subnet_exists(owner_wallet.coldkeypub.ss58_address, 1):
            warning_text = Text(
                "A Subnet with netuid 1 already exists and is registered with the owner's wallet:",
                style="bold light_goldenrod2",
            )
            wallet_info = Text(f"\t{owner_wallet}", style="medium_purple")
            sudo_info = Text(
                f"\tSUDO (Coldkey of Subnet 1 owner): {owner_wallet.coldkeypub.ss58_address}",
                style="medium_purple",
            )
            warning_sign = Text("⚠️ ", style="bold yellow")

            console.print(warning_sign, warning_text)
            console.print(wallet_info)
            console.print(sudo_info)
        else:
            self._create_subnet(owner_wallet)

        console.print("[dark_green]\nListing all subnets")
        subnets_list = exec_command(
            command="subnets",
            sub_command="list",
            extra_args=[
                "--chain",
                "ws://127.0.0.1:9945",
            ],
        )
        print(subnets_list.stdout, end="")

    def setup_neurons(self):
        """
        Sets up neurons (miners) for the subnet.
        """
        if not is_chain_running(CONFIG_FILE_PATH):
            console.print(
                "[red]Local chain is not running. Please start the chain first."
            )
            return

        config_data = load_config(
            "A running Subtensor not found. Please run [dark_orange]`btqs chain start`[/dark_orange] first."
        )
        neurons.setup_neurons(config_data)

    def run_neurons(self):
        """
        Runs all neurons (miners and validators).

        This command starts the processes for all configured neurons, attaching to
        running processes if they are already running.

        USAGE

        [green]$[/green] btqs neurons run

        [bold]Note[/bold]: The command will attach to running neurons or start new
        ones as necessary. Press Ctrl+C to detach from a neuron and move to the next.
        """
        config_data = load_config(
            "A running Subtensor not found. Please run [dark_orange]`btqs chain start`[/dark_orange] first."
        )

        # Ensure neurons are configured
        if not config_data.get("Miners") and not config_data.get("Owner"):
            console.print(
                "[red]No neurons found. Please run `btqs neurons setup` first."
            )
            return
        
        neurons.run_neurons(config_data)

    def stop_neurons(self):
        """
        Stops the running neurons.

        This command terminates the miner processes for the selected or all running miners.

        USAGE

        [green]$[/green] btqs neurons stop

        [bold]Note[/bold]: You can choose which miners to stop or stop all of them.
        """
        if not os.path.exists(CONFIG_FILE_PATH):
            console.print("[red]Config file not found.")
            return

        config_data = load_config()

        neurons.stop_neurons(config_data)

    def start_neurons(self):
        """
        Starts the stopped neurons.

        This command starts the miner processes for the selected or all stopped miners.

        USAGE

        [green]$[/green] btqs neurons start

        [bold]Note[/bold]: You can choose which stopped miners to start or start all of them.
        """
        if not os.path.exists(CONFIG_FILE_PATH):
            console.print("[red]Config file not found.")
            return

        config_data = load_config()

        neurons.start_neurons(config_data)

    def _start_selected_neurons(
        self, config_data: Dict[str, Any], selected_neurons: list[Dict[str, Any]]
    ):
        """Starts the selected neurons."""
        subnet_template_path = self._ensure_subnet_template(config_data)

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

    def reattach_neurons(self):
        """
        Reattaches to a running neuron.

        This command allows you to view the logs of a running miner (neuron).

        USAGE

        [green]$[/green] btqs neurons reattach

        [bold]Note[/bold]: Press Ctrl+C to detach from the miner logs.
        """
        if not os.path.exists(CONFIG_FILE_PATH):
            console.print("[red]Config file not found.")
            return

        config_data = load_config()

        # Choose which neuron to reattach to
        all_neurons = {
            **config_data.get("Miners", {}),
            "Validator": config_data.get("Owner", {}),
        }
        neuron_names = list(all_neurons.keys())
        if not neuron_names:
            console.print("[red]No neurons found.")
            return

        neuron_choice = typer.prompt(
            f"Which neuron do you want to reattach to? {neuron_names}",
            default=neuron_names[0],
        )
        if neuron_choice not in all_neurons:
            console.print("[red]Invalid neuron name.")
            return

        wallet_info = all_neurons[neuron_choice]
        pid = wallet_info.get("pid")
        log_file_path = wallet_info.get("log_file")
        if not pid or not psutil.pid_exists(pid):
            console.print("[red]Neuron process not running.")
            return

        if not log_file_path or not os.path.exists(log_file_path):
            console.print("[red]Log file not found for this neuron.")
            return

        console.print(
            f"[green]Reattaching to neuron {neuron_choice}. Press Ctrl+C to exit."
        )

        attach_to_process_logs(log_file_path, neuron_choice, pid)

    def status_neurons(self):
        """
        Shows the status of Subtensor and all neurons.

        This command displays the running status, CPU and memory usage of the local chain and all configured neurons.

        USAGE

        [green]$[/green] btqs neurons status

        [bold]Note[/bold]: Use this command to monitor the health and status of your local chain and miners.
        """
        console.print("[green]Checking status of Subtensor and neurons...")

        config_data = load_config(
            "A running Subtensor not found. Please run [dark_orange]`btqs chain start`[/dark_orange] first."
        )

        # Get process data
        process_entries, cpu_usage_list, memory_usage_list = get_process_entries(
            config_data
        )
        display_process_status_table(process_entries, cpu_usage_list, memory_usage_list)

        spec_table = Table(
            title="[underline dark_orange]Machine Specifications[/underline dark_orange]",
            show_header=False,
            border_style="bright_black",
        )
        spec_table.add_column(style="cyan", justify="left")
        spec_table.add_column(style="white")

        version_table = Table(
            title="[underline dark_orange]Version Information[/underline dark_orange]",
            show_header=False,
            border_style="bright_black",
        )
        version_table.add_column(style="cyan", justify="left")
        version_table.add_column(style="white")

        # Add specs
        spec_table.add_row(
            "Operating System:", f"{platform.system()} {platform.release()}"
        )
        spec_table.add_row("Processor:", platform.processor())
        spec_table.add_row(
            "Total RAM:",
            f"{psutil.virtual_memory().total / (1024 * 1024 * 1024):.2f} GB",
        )
        spec_table.add_row(
            "Available RAM:",
            f"{psutil.virtual_memory().available / (1024 * 1024 * 1024):.2f} GB",
        )

        # Add version
        version_table.add_row("btcli version:", get_btcli_version())
        version_table.add_row(
            "bittensor-wallet version:", get_bittensor_wallet_version()
        )
        version_table.add_row("Python version:", get_python_version())
        version_table.add_row("Python path:", get_python_path())

        layout = Table.grid(expand=True)
        layout.add_column(justify="left")
        layout.add_column(justify="left")
        layout.add_row(spec_table, version_table)

        console.print("\n")
        console.print(layout)
        return layout

    def run(self):
        self.app()

    # TODO: See if we can further streamline these. Or change location if needed
    # ------------------------ Helper Methods ------------------------

    def _wait_for_chain_ready(
        self, alice_log: str, start_time: float, timeout: int
    ) -> bool:
        """Waits for the chain to be ready by monitoring the alice.log file."""
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
                            console.print(
                                "[red]Timeout: Chain did not compile in time."
                            )
                            break
                        time.sleep(0.1)
        except Exception as e:
            console.print(f"[red]Error reading log files: {e}")
        return chain_ready

    def _get_substrate_pids(self) -> Optional[list[int]]:
        """Fetches the PIDs of the substrate nodes."""
        try:
            result = subprocess.run(
                ["pgrep", "-f", "node-subtensor"], capture_output=True, text=True
            )
            substrate_pids = [int(pid) for pid in result.stdout.strip().split()]
            return substrate_pids
        except ValueError:
            console.print("[red]Failed to get the PID of the Subtensor process.")
            return None

    def _stop_running_neurons(self, config_data: Dict[str, Any]):
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
            console.print(
                "[yellow]\nSome neurons are still running. Terminating them..."
            )

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

    def _is_process_running(self, pid: int) -> bool:
        """Checks if a process with the given PID is running."""
        try:
            process = psutil.Process(pid)
            if not process.is_running():
                console.print(
                    "[red]Process not running. The chain may have been stopped."
                )
                return False
            return True
        except psutil.NoSuchProcess:
            console.print("[red]Process not found. The chain may have been stopped.")
            return False

    def _create_subnet_owner_wallet(self, config_data: Dict[str, Any]):
        """Creates a subnet owner wallet."""
        console.print(
            Text("Creating subnet owner wallet.\n", style="bold light_goldenrod2"),
            style="bold yellow",
        )

        owner_wallet_name = typer.prompt(
            "Enter subnet owner wallet name", default="owner", show_default=True
        )
        owner_hotkey_name = typer.prompt(
            "Enter subnet owner hotkey name", default="default", show_default=True
        )

        uri = "//Alice"
        keypair = Keypair.create_from_uri(uri)
        owner_wallet = Wallet(
            path=BTQS_WALLETS_DIRECTORY,
            name=owner_wallet_name,
            hotkey=owner_hotkey_name,
        )
        owner_wallet.set_coldkey(keypair=keypair, encrypt=False, overwrite=True)
        owner_wallet.set_coldkeypub(keypair=keypair, encrypt=False, overwrite=True)
        owner_wallet.set_hotkey(keypair=keypair, encrypt=False, overwrite=True)

        console.print(
            "Executed command: [dark_orange] btcli wallet create --wallet-name",
            f"[dark_orange]{owner_hotkey_name} --wallet-hotkey {owner_wallet_name} --wallet-path {BTQS_WALLETS_DIRECTORY}",
        )

        config_data["Owner"] = {
            "wallet_name": owner_wallet_name,
            "path": BTQS_WALLETS_DIRECTORY,
            "hotkey": owner_hotkey_name,
            "subtensor_pid": config_data["pid"],
        }
        with open(CONFIG_FILE_PATH, "w") as config_file:
            yaml.safe_dump(config_data, config_file)

    def _create_subnet(self, owner_wallet: Wallet):
        """Creates a subnet with netuid 1 and registers the owner."""
        console.print(
            Text("Creating a subnet with Netuid 1.\n", style="bold light_goldenrod2"),
            style="bold yellow",
        )

        create_subnet = exec_command(
            command="subnets",
            sub_command="create",
            extra_args=[
                "--wallet-path",
                BTQS_WALLETS_DIRECTORY,
                "--chain",
                "ws://127.0.0.1:9945",
                "--wallet-name",
                owner_wallet.name,
                "--no-prompt",
                "--wallet-hotkey",
                owner_wallet.hotkey_str,
            ],
        )
        clean_stdout = remove_ansi_escape_sequences(create_subnet.stdout)
        if "✅ Registered subnetwork with netuid: 1" in clean_stdout:
            console.print("[dark_green] Subnet created successfully with netuid 1")

        console.print(
            Text(
                f"Registering Owner ({owner_wallet.name}) to Netuid 1\n",
                style="bold light_goldenrod2",
            ),
            style="bold yellow",
        )

        register_subnet = exec_command(
            command="subnets",
            sub_command="register",
            extra_args=[
                "--wallet-path",
                BTQS_WALLETS_DIRECTORY,
                "--wallet-name",
                owner_wallet.name,
                "--wallet-hotkey",
                owner_wallet.hotkey_str,
                "--netuid",
                "1",
                "--chain",
                "ws://127.0.0.1:9945",
                "--no-prompt",
            ],
        )
        clean_stdout = remove_ansi_escape_sequences(register_subnet.stdout)
        if "✅ Registered" in clean_stdout:
            console.print("[green] Registered the owner to subnet 1")

    def _create_miner_wallets(self, config_data: Dict[str, Any]):
        """Creates miner wallets."""
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

    def _register_miners(self, config_data: Dict[str, Any]):
        """Registers miners to the subnet."""
        for wallet_name, wallet_info in config_data["Miners"].items():
            wallet = Wallet(
                path=wallet_info["path"],
                name=wallet_name,
                hotkey=wallet_info["hotkey"],
            )

            console.print(
                Text(
                    f"Registering Miner ({wallet_name}) to Netuid 1\n",
                    style="bold light_goldenrod2",
                ),
                style="bold yellow",
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

    def _ensure_subnet_template(self, config_data: Dict[str, Any]):
        """Ensures that the subnet-template repository is available."""
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

    def _handle_validator(
        self, config_data: Dict[str, Any], subnet_template_path: str, chain_pid: int
    ):
        """Handles the validator process."""
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

    def _handle_miners(
        self, config_data: Dict[str, Any], subnet_template_path: str, chain_pid: int
    ):
        """Handles the miner processes."""
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

    def _stop_selected_neurons(
        self, config_data: Dict[str, Any], selected_neurons: list[Dict[str, Any]]
    ):
        """Stops the selected neurons."""
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


def main():
    manager = BTQSManager()
    manager.run()


if __name__ == "__main__":
    main()
