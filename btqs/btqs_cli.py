import os
import platform
import subprocess
import time
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
    subnet_exists,
    subnet_owner_exists,
)


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

        # Setup commands
        self.subnet_app.command(name="setup")(self.setup_subnet)

        # Neuron commands
        self.neurons_app.command(name="setup")(self.setup_neurons)
        self.neurons_app.command(name="run")(self.run_neurons)
        self.neurons_app.command(name="stop")(self.stop_neurons)
        self.neurons_app.command(name="reattach")(self.reattach_neurons)
        self.neurons_app.command(name="status")(self.status_neurons)
        self.neurons_app.command(name="start")(self.start_neurons)

        self.app.command(name="run-all", help="Create entire setup")(self.run_all)

    def run_all(self):
        """
        Runs all commands in sequence to set up and start the local chain, subnet, and neurons.

        This command automates the entire setup process, including starting the local Subtensor chain,
        setting up a subnet, creating and registering miner wallets, and running the miners.

        USAGE

        Run this command to perform all steps necessary to start the local chain and miners:

        [green]$[/green] btqs run-all

        [bold]Note[/bold]: This command is useful for quickly setting up the entire environment.
        It will prompt for inputs as needed.
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

        console.print("\nNext command will: 1. Start all miners processes")
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

    def start_neurons(self):
        """
        Starts selected neurons.

        This command allows you to start specific miners that are not currently running.

        USAGE

        [green]$[/green] btqs neurons start

        [bold]Note[/bold]: You can select which miners to start or start all that are not running.
        """
        config_data = load_config(
            "A running Subtensor not found. Please run [dark_orange]`btqs chain start`[/dark_orange] first."
        )
        if not config_data.get("Miners"):
            console.print(
                "[red]Miners not found. Please run `btqs neurons setup` first."
            )
            return

        # Get process entries
        process_entries, _, _ = get_process_entries(config_data)
        display_process_status_table(process_entries, [], [])

        # Filter miners that are not running
        miners_not_running = []
        for entry in process_entries:
            if entry["process"].startswith("Miner") and entry["status"] != "Running":
                miners_not_running.append(entry)

        if not miners_not_running:
            console.print("[green]All miners are already running.")
            return

        # Display the list of miners not running
        console.print("\nMiners not running:")
        for idx, miner in enumerate(miners_not_running, start=1):
            console.print(f"{idx}. {miner['process']}")

        # Prompt user to select miners to start
        selection = typer.prompt(
            "Enter miner numbers to start (comma-separated), or 'all' to start all",
            default="all",
        )

        if selection.lower() == "all":
            selected_miners = miners_not_running
        else:
            selected_indices = [
                int(i.strip()) for i in selection.split(",") if i.strip().isdigit()
            ]
            selected_miners = [
                miners_not_running[i - 1]
                for i in selected_indices
                if 1 <= i <= len(miners_not_running)
            ]

        if not selected_miners:
            console.print("[red]No valid miners selected.")
            return

        # TODO: Make this configurable
        # Subnet template setup
        subnet_template_path = os.path.join(BTQS_DIRECTORY, "subnet-template")
        if not os.path.exists(subnet_template_path):
            console.print("[green]Cloning subnet-template repository...")
            repo = Repo.clone_from(
                SUBNET_TEMPLATE_REPO_URL,
                subnet_template_path,
            )
            repo.git.checkout(SUBNET_TEMPLATE_BRANCH)
        else:
            console.print("[green]Using existing subnet-template repository.")
            repo = Repo(subnet_template_path)
            current_branch = repo.active_branch.name
            if current_branch != SUBNET_TEMPLATE_BRANCH:
                repo.git.checkout(SUBNET_TEMPLATE_BRANCH)

        # TODO: Add ability for users to define their own flags, entry point etc
        # Start selected miners
        for miner in selected_miners:
            wallet_name = miner["process"].split("Miner: ")[-1]
            wallet_info = config_data["Miners"][wallet_name]
            success = start_miner(
                wallet_name, wallet_info, subnet_template_path, config_data
            )
            if success:
                console.print(f"[green]Miner {wallet_name} started.")
            else:
                console.print(f"[red]Failed to start miner {wallet_name}.")

        # Update the config file
        with open(CONFIG_FILE_PATH, "w") as config_file:
            yaml.safe_dump(config_data, config_file)

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

        config_data = load_config(exit_if_missing=False)
        if config_data:
            console.print("[green] Refreshing config file")
            config_data = {}

        directory = typer.prompt(
            "Enter the directory to clone the subtensor repository",
            default=os.path.expanduser("~/Desktop/Bittensor_quick_start"),
            show_default=True,
        )
        os.makedirs(directory, exist_ok=True)

        subtensor_path = os.path.join(directory, "subtensor")
        repo_url = "https://github.com/opentensor/subtensor.git"

        # Clone or update the repository
        if os.path.exists(subtensor_path) and os.listdir(subtensor_path):
            update = typer.confirm(
                "Subtensor is already cloned. Do you want to update it?"
            )
            if update:
                try:
                    repo = Repo(subtensor_path)
                    origin = repo.remotes.origin
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
                Repo.clone_from(repo_url, subtensor_path)
                console.print("[green]Repository cloned successfully.")
            except GitCommandError as e:
                console.print(f"[red]Error cloning repository: {e}")
                return

        localnet_path = os.path.join(subtensor_path, "scripts", "localnet.sh")

        # Running localnet.sh
        process = subprocess.Popen(
            ["bash", localnet_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
            cwd=subtensor_path,
            start_new_session=True,
        )

        console.print("[green]Starting local chain. This may take a few minutes...")

        # Paths to subtensor log files
        log_dir = os.path.join(subtensor_path, "logs")
        alice_log = os.path.join(log_dir, "alice.log")

        # Waiting for chain compilation
        timeout = 360  # 6 minutes
        start_time = time.time()
        while not os.path.exists(alice_log):
            if time.time() - start_time > timeout:
                console.print("[red]Timeout: Log files were not created.")
                return
            time.sleep(1)

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
            return

        if chain_ready:
            text = Text(
                "Local chain is running. You can now use it for development and testing.\n",
                style="bold light_goldenrod2",
            )
            sign = Text("\n⚙️ ", style="bold yellow")
            console.print(sign, text)

            try:
                # Fetch PIDs of 2 substrate nodes spawned
                result = subprocess.run(
                    ["pgrep", "-f", "node-subtensor"], capture_output=True, text=True
                )
                substrate_pids = [int(pid) for pid in result.stdout.strip().split()]

                config_data.update(
                    {
                        "pid": process.pid,
                        "substrate_pid": substrate_pids,
                        "subtensor_path": subtensor_path,
                        "base_path": directory,
                    }
                )
            except ValueError:
                console.print("[red]Failed to get the PID of the Subtensor process.")
                return

            config_data.update(
                {
                    "pid": process.pid,
                    "subtensor_path": subtensor_path,
                    "base_path": directory,
                }
            )

            # Save config data
            try:
                os.makedirs(os.path.dirname(CONFIG_FILE_PATH), exist_ok=True)
                with open(CONFIG_FILE_PATH, "w") as config_file:
                    yaml.safe_dump(config_data, config_file)
                console.print(
                    "[green]Local chain started successfully and config file updated."
                )
            except Exception as e:
                console.print(f"[red]Failed to write to the config file: {e}")
        else:
            console.print("[red]Failed to start local chain.")

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

        # Check for running miners
        process_entries, _, _ = get_process_entries(config_data)

        # Filter running miners
        running_miners = []
        for entry in process_entries:
            if entry["process"].startswith("Miner") and entry["status"] == "Running":
                running_miners.append(entry)

        if running_miners:
            console.print(
                "[yellow]\nSome miners are still running. Terminating them..."
            )

            for miner in running_miners:
                pid = int(miner["pid"])
                wallet_name = miner["process"].split("Miner: ")[-1]
                try:
                    miner_process = psutil.Process(pid)
                    miner_process.terminate()
                    miner_process.wait(timeout=10)
                    console.print(f"[green]Miner {wallet_name} stopped.")

                except psutil.NoSuchProcess:
                    console.print(f"[yellow]Miner {wallet_name} process not found.")

                except psutil.TimeoutExpired:
                    console.print(
                        f"[red]Timeout stopping miner {wallet_name}. Forcing stop."
                    )
                    miner_process.kill()

                config_data["Miners"][wallet_name]["pid"] = None

            with open(CONFIG_FILE_PATH, "w") as config_file:
                yaml.safe_dump(config_data, config_file)
        else:
            console.print("[green]No miners were running.")

        # Refresh data
        refresh_config = typer.confirm(
            "\nConfig data is outdated. Press Y to refresh it?"
        )
        if refresh_config:
            if os.path.exists(CONFIG_FILE_PATH):
                os.remove(CONFIG_FILE_PATH)
                console.print("[green]Configuration file removed.")

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

        pid = config_data.get("pid")
        subtensor_path = config_data.get("subtensor_path")
        if not pid or not subtensor_path:
            console.print("[red]No running chain found.")
            return

        # Check if the process is still running
        try:
            process = psutil.Process(pid)
            if not process.is_running():
                console.print(
                    "[red]Process not running. The chain may have been stopped."
                )
                return
        except psutil.NoSuchProcess:
            console.print("[red]Process not found. The chain may have been stopped.")
            return

        # Log file setup for Subtensor chain
        log_dir = os.path.join(subtensor_path, "logs")
        alice_log = os.path.join(log_dir, "alice.log")

        if not os.path.exists(alice_log):
            console.print("[red]Log files not found.")
            return

        try:
            console.print("[green]Reattaching to the local chain...")
            console.print("[green]Press Ctrl+C to detach.")
            with open(alice_log, "r") as alice_file:
                alice_file.seek(0, os.SEEK_END)
                while True:
                    alice_line = alice_file.readline()
                    if not alice_line:
                        time.sleep(0.1)
                        continue
                    if alice_line:
                        print(f"[Alice] {alice_line}", end="")
        except KeyboardInterrupt:
            console.print("\n[green]Detached from the local chain.")

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
            text = Text(
                "Creating subnet owner wallet.\n", style="bold light_goldenrod2"
            )
            sign = Text("👑 ", style="bold yellow")
            console.print(sign, text)

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

            with open(CONFIG_FILE_PATH, "r") as config_file:
                config_data = yaml.safe_load(config_file)
            config_data["Owner"] = {
                "wallet_name": owner_wallet_name,
                "path": BTQS_WALLETS_DIRECTORY,
                "hotkey": owner_hotkey_name,
                "subtensor_pid": config_data["pid"],
            }
            with open(CONFIG_FILE_PATH, "w") as config_file:
                yaml.safe_dump(config_data, config_file)

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
            text = Text(
                "Creating a subnet with Netuid 1.\n", style="bold light_goldenrod2"
            )
            sign = Text("\n💻 ", style="bold yellow")
            console.print(sign, text)

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

            text = Text(
                f"Registering Owner ({owner_wallet.name}) to Netuid 1\n",
                style="bold light_goldenrod2",
            )
            sign = Text("\n📝 ", style="bold yellow")
            console.print(sign, text)

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

        This command creates miner wallets and registers them to the subnet.

        USAGE

        [green]$[/green] btqs neurons setup

        [bold]Note[/bold]: This command will prompt for wallet names and hotkey names for each miner.
        """
        if not is_chain_running(CONFIG_FILE_PATH):
            console.print(
                "[red]Local chain is not running. Please start the chain first."
            )
            return

        config_data = load_config(
            "A running Subtensor not found. Please run [dark_orange]`btqs chain start`[/dark_orange] first."
        )
        subnet_owner, owner_data = subnet_owner_exists(CONFIG_FILE_PATH)
        if subnet_owner:
            owner_wallet = Wallet(
                name=owner_data.get("wallet_name"),
                path=owner_data.get("path"),
                hotkey=owner_data.get("hotkey"),
            )
        else:
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
            uris = [
                "//Bob",
                "//Charlie",
            ]
            ports = [8100, 8101, 8102, 8103]
            for i, uri in enumerate(uris, start=0):
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

        for wallet_name, wallet_info in config_data["Miners"].items():
            wallet = Wallet(
                path=wallet_info["path"],
                name=wallet_name,
                hotkey=wallet_info["hotkey"],
            )

            text = Text(
                f"Registering Miner ({wallet_name}) to Netuid 1\n",
                style="bold light_goldenrod2",
            )
            sign = Text("\n📝 ", style="bold yellow")
            console.print(sign, text)

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
                text = Text(
                    f"Registered miner ({wallet.name}) to Netuid 1\n",
                    style="bold light_goldenrod2",
                )
                sign = Text("🏆 ", style="bold yellow")
                console.print(sign, text)
            else:
                print(clean_stdout)
                console.print(
                    f"[red]Failed to register miner ({wallet.name}). Please register the miner manually using the following command:"
                )
                command = f"btcli subnets register --wallet-path {wallet.path} --wallet-name {wallet.name} --hotkey {wallet.hotkey_str} --netuid 1 --chain ws://127.0.0.1:9945 --no-prompt"
                console.print(f"[bold yellow]{command}\n")

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

    def run_neurons(self):
        """
        Runs all neurons (miners).

        This command starts the miner processes for all configured miners, attaching to running miners if they are already running.

        USAGE

        [green]$[/green] btqs neurons run

        [bold]Note[/bold]: The command will attach to running miners or start new ones as necessary. Press Ctrl+C to detach from a miner and move to the next.
        """
        if not os.path.exists(CONFIG_FILE_PATH):
            console.print(
                "[red]Config file not found. Please run `btqs chain start` first."
            )
            return

        with open(CONFIG_FILE_PATH, "r") as config_file:
            config_data = yaml.safe_load(config_file) or {}

        if not config_data.get("Miners"):
            console.print(
                "[red]Miners not found. Please run `btqs neurons setup` first."
            )
            return

        # Subnet template setup
        subnet_template_path = os.path.join(BTQS_DIRECTORY, "subnet-template")
        if not os.path.exists(subnet_template_path):
            console.print("[green]Cloning subnet-template repository...")
            repo = Repo.clone_from(
                SUBNET_TEMPLATE_REPO_URL,
                subnet_template_path,
            )
            repo.git.checkout(SUBNET_TEMPLATE_BRANCH)
        else:
            console.print("[green]Using existing subnet-template repository.")
            repo = Repo(subnet_template_path)
            current_branch = repo.active_branch.name
            if current_branch != SUBNET_TEMPLATE_BRANCH:
                repo.git.checkout(SUBNET_TEMPLATE_BRANCH)

        chain_pid = config_data.get("pid")
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
                    try:
                        with open(log_file_path, "r") as log_file:
                            # Move to the end of the file
                            log_file.seek(0, os.SEEK_END)
                            console.print(
                                f"[green]Attached to miner {wallet_name}. Press Ctrl+C to move to the next miner."
                            )
                            while True:
                                line = log_file.readline()
                                if not line:
                                    # Check if the process is still running
                                    if not psutil.pid_exists(miner_pid):
                                        console.print(
                                            f"\n[red]Miner process {wallet_name} has terminated."
                                        )
                                        break
                                    time.sleep(0.1)
                                    continue
                                print(line, end="")
                    except KeyboardInterrupt:
                        console.print(f"\n[green]Detached from miner {wallet_name}.")
                    except Exception as e:
                        console.print(
                            f"[red]Error attaching to miner {wallet_name}: {e}"
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

        with open(CONFIG_FILE_PATH, "w") as config_file:
            yaml.safe_dump(config_data, config_file)

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

        with open(CONFIG_FILE_PATH, "r") as config_file:
            config_data = yaml.safe_load(config_file) or {}

        # Get process entries
        process_entries, _, _ = get_process_entries(config_data)
        display_process_status_table(process_entries, [], [])

        # Filter running miners
        running_miners = []
        for entry in process_entries:
            if entry["process"].startswith("Miner") and entry["status"] == "Running":
                running_miners.append(entry)

        if not running_miners:
            console.print("[red]No running miners to stop.")
            return

        console.print("\nSelect miners to stop:")
        for idx, miner in enumerate(running_miners, start=1):
            console.print(f"{idx}. {miner['process']} (PID: {miner['pid']})")

        selection = typer.prompt(
            "Enter miner numbers to stop (comma-separated), or 'all' to stop all",
            default="all",
        )

        if selection.lower() == "all":
            selected_miners = running_miners
        else:
            selected_indices = [
                int(i.strip()) for i in selection.split(",") if i.strip().isdigit()
            ]
            selected_miners = [
                running_miners[i - 1]
                for i in selected_indices
                if 1 <= i <= len(running_miners)
            ]

        if not selected_miners:
            console.print("[red]No valid miners selected.")
            return

        # Stop selected miners
        for miner in selected_miners:
            pid = int(miner["pid"])
            wallet_name = miner["process"].split("Miner: ")[-1]
            try:
                process = psutil.Process(pid)
                process.terminate()
                process.wait(timeout=10)
                console.print(f"[green]Miner {wallet_name} stopped.")

            except psutil.NoSuchProcess:
                console.print(f"[yellow]Miner {wallet_name} process not found.")

            except psutil.TimeoutExpired:
                console.print(
                    f"[red]Timeout stopping miner {wallet_name}. Forcing stop."
                )
                process.kill()

            config_data["Miners"][wallet_name]["pid"] = None
        with open(CONFIG_FILE_PATH, "w") as config_file:
            yaml.safe_dump(config_data, config_file)

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

        with open(CONFIG_FILE_PATH, "r") as config_file:
            config_data = yaml.safe_load(config_file) or {}

        # Choose which neuron to reattach to
        all_neurons = {
            **config_data.get("Validators", {}),
            **config_data.get("Miners", {}),
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

        try:
            with open(log_file_path, "r") as log_file:
                # Move to the end of the file
                log_file.seek(0, os.SEEK_END)
                while True:
                    line = log_file.readline()
                    if not line:
                        if not psutil.pid_exists(pid):
                            console.print(
                                f"\n[red]Neuron process {neuron_choice} has terminated."
                            )
                            break
                        time.sleep(0.1)
                        continue
                    print(line, end="")

        except KeyboardInterrupt:
            console.print("\n[green]Detached from neuron logs.")

        except Exception as e:
            console.print(f"[red]Error reattaching to neuron: {e}")

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

    def run(self):
        self.app()


def main():
    manager = BTQSManager()
    manager.run()


if __name__ == "__main__":
    main()
