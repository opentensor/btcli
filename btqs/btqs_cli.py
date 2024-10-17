import os
import platform
import time
from time import sleep
from typing import Optional


import psutil
from rich.prompt import Confirm
import typer
from btqs.commands import chain, neurons, subnet
from rich.table import Table
from rich.text import Text

from .config import (
    CONFIG_FILE_PATH,
    EPILOG,
    LOCALNET_ENDPOINT,
    DEFAULT_WORKSPACE_DIRECTORY,
    DEFAULT_SUBTENSOR_BRANCH,
)
from .utils import (
    console,
    display_process_status_table,
    exec_command,
    get_bittensor_wallet_version,
    get_btcli_version,
    get_process_entries,
    is_chain_running,
    load_config,
    get_bittensor_version,
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

        # Core commands
        self.app.command(name="run-all", help="Create entire setup")(self.run_all)
        self.app.command(name="status", help="Current status of bittensor quick start")(
            self.status_neurons
        )
        self.app.command(name="steps", help="Display steps for subnet setup")(
            self.setup_steps
        )
        self.app.command(name="live")(self.display_live_metagraph)

        # Chain commands
        self.chain_app.command(name="start")(self.start_chain)
        self.chain_app.command(name="stop")(self.stop_chain)
        self.chain_app.command(name="reattach")(self.reattach_chain)
        self.chain_app.command(name="status")(self.status_neurons)

        # Subnet commands
        self.subnet_app.command(name="setup")(self.setup_subnet)
        self.subnet_app.command(name="live")(self.display_live_metagraph)
        self.subnet_app.command(name="stake")(self.add_stake)
        self.subnet_app.command(name="add-weights")(self.add_weights)

        # Neuron commands
        self.neurons_app.command(name="setup")(self.setup_neurons)
        self.neurons_app.command(name="run")(self.run_neurons)
        self.neurons_app.command(name="stop")(self.stop_neurons)
        self.neurons_app.command(name="reattach")(self.reattach_neurons)
        self.neurons_app.command(name="status")(self.status_neurons)
        self.neurons_app.command(name="start")(self.start_neurons)

    def start_chain(
        self,
        workspace_path: Optional[str] = typer.Option(
            None,
            "--path",
            "--workspace",
            help="Path to Bittensor's quick start workspace",
        ),
        branch: Optional[str] = typer.Option(
            None, "--subtensor_branch", help="Subtensor branch to checkout"
        ),
    ):
        """
        Starts the local Subtensor chain.
        """
        config_data = load_config(exit_if_missing=False)
        if is_chain_running():
            console.print(
                f"[red]The local chain is already running. Endpoint: {LOCALNET_ENDPOINT}"
            )
            return
        if not workspace_path:
            if config_data.get("workspace_path"):
                reuse_config_path = Confirm.ask(
                    f"[blue]Previously saved workspace_path found: [green]({config_data.get('workspace_path')}) \n[blue]Do you want to re-use it?",
                    default=True,
                    show_default=True,
                )
                if reuse_config_path:
                    workspace_path = config_data.get("workspace_path")
            else:
                workspace_path = typer.prompt(
                    typer.style(
                        "Enter path to create Bittensor development workspace",
                        fg="blue",
                    ),
                    default=DEFAULT_WORKSPACE_DIRECTORY,
                )

        if not branch:
            branch = typer.prompt(
                typer.style("Enter Subtensor branch", fg="blue"),
                default=DEFAULT_SUBTENSOR_BRANCH,
            )

        console.print("[dark_orange]Starting the local chain...")
        chain.start(config_data, workspace_path, branch)

    def stop_chain(self):
        """
        Stops the local Subtensor chain and any running miners.

        This command terminates the local Subtensor chain process, miner and validator processes, and optionally cleans up configuration data.

        USAGE

        [green]$[/green] btqs chain stop

        [bold]Note[/bold]: Use this command to gracefully shut down the local chain. It will also stop any running miner processes.
        """
        config_data = load_config(
            "No running chain found. Please run [dark_orange]`btqs chain start`[/dark_orange] first."
        )
        chain.stop(config_data)

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
        chain.reattach(config_data)

    def run_all(self):
        """
        Runs all commands in sequence to set up and start the local chain, subnet, and neurons.
        """
        text = Text("Starting Local Subtensor\n", style="bold light_goldenrod2")
        sign = Text("🔗 ", style="bold yellow")
        console.print(sign, text)
        sleep(3)

        # Start the local chain
        self.start_chain(workspace_path=None, branch=None)

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
            "\nNext command will: 1. Add stake to the validator 2. Register the validator to the root network (netuid 0)"
        )
        console.print("Press any key to continue..\n")
        input()
        text = Text("Adding stake by Validator\n", style="bold light_goldenrod2")
        sign = Text("\n🪙 ", style="bold yellow")
        console.print(sign, text)
        time.sleep(2)
        self.add_stake()

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
                LOCALNET_ENDPOINT,
            ],
        )
        print(subnets_list.stdout, end="")

        console.print(
            "\nNext command will set weights to Netuid 1 through the Validator"
        )
        console.print("Press any key to continue..\n")
        input()
        self.add_weights()

        console.print(
            "\nNext command will start a live view of the metagraph to monitor the subnet and its status\nPress Ctrl + C to exit the live view"
        )
        console.print("Press any key to continue..\n")
        input()
        self.display_live_metagraph()

    def display_live_metagraph(self):
        config_data = load_config(
            "A running Subtensor not found. Please run [dark_orange]`btqs chain start`[/dark_orange] first."
        )
        subnet.display_live_metagraph(config_data)

    def setup_steps(self):
        subnet.steps()

    def add_stake(self):
        config_data = load_config(
            "A running Subtensor not found. Please run [dark_orange]`btqs chain start`[/dark_orange] first."
        )
        subnet.add_stake(config_data)

    def add_weights(self):
        config_data = load_config(
            "A running Subtensor not found. Please run [dark_orange]`btqs chain start`[/dark_orange] first."
        )
        subnet.add_weights(config_data)

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
        subnet.setup_subnet(config_data)

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
        process_entries, cpu_usage_list, memory_usage_list = get_process_entries(
            config_data
        )
        display_process_status_table(
            process_entries, cpu_usage_list, memory_usage_list, config_data
        )
        neurons.reattach_neurons(config_data)

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
        display_process_status_table(
            process_entries, cpu_usage_list, memory_usage_list, config_data
        )

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
        version_table.add_row("bittensor version:", get_bittensor_version())

        layout = Table.grid(expand=True)
        layout.add_column(justify="left")
        layout.add_column(justify="left")
        layout.add_row(spec_table, version_table)

        console.print("\n")
        console.print(layout)
        return layout

    def run(self):
        self.app()


def main():
    manager = BTQSManager()
    manager.run()


if __name__ == "__main__":
    main()
