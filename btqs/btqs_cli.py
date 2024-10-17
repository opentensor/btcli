import os
import platform
from typing import Optional

import psutil
from rich.prompt import Confirm
import typer
from btqs.commands import chain, neurons, subnet
from rich.table import Table

from .config import (
    CONFIG_FILE_PATH,
    EPILOG,
    LOCALNET_ENDPOINT,
    DEFAULT_WORKSPACE_DIRECTORY,
    SUBTENSOR_BRANCH,
)
from .utils import (
    console,
    display_process_status_table,
    get_bittensor_wallet_version,
    get_btcli_version,
    get_process_entries,
    is_chain_running,
    load_config,
    get_bittensor_version,
    print_info,
    print_step,
    print_success,
    print_warning,
    print_info_box,
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

        self.steps = [
            {
                "title": "Start Local Subtensor",
                "description": "Initialize and start the local Subtensor blockchain. This may take several minutes due to the compilation process.",
                "info": "🔗 **Subtensor** is the underlying blockchain network that facilitates decentralized activities. Starting the local chain sets up your personal development environment for experimenting with Bittensor.",
                "action": lambda: self.start_chain(workspace_path=None, branch=None),
            },
            {
                "title": "Check Chain Status",
                "description": "Verify that the local chain is running correctly.",
                "info": "📊 **Chain Nodes**: During your local Subtensor setup, two blockchain nodes are initiated. These nodes communicate and collaborate to reach consensus, ensuring the integrity and synchronization of your blockchain network.",
                "action": lambda: self.status_neurons(),
            },
            {
                "title": "Set Up Subnet",
                "description": "Create a subnet owner wallet, establish a new subnet, and register the owner to the subnet.",
                "info": "🔑 **Wallets** in Bittensor are essential for managing your stake, interacting with the network, and running validators or miners. Each wallet has a unique name and associated hotkey that serves as your identity within the network.",
                "action": lambda: self.setup_subnet(),
            },
            {
                "title": "Add Stake by Validator",
                "description": "Stake Tao to the validator's hotkey and register to the root network.",
                "info": "💰 **Staking Tao** to your hotkey is the process of committing your tokens to support your role as a validator in the subnet. Your wallet can potentially earn rewards based on your performance and the subnet's incentive mechanism.",
                "action": lambda: self.add_stake(),
            },
            {
                "title": "Set Up Miners",
                "description": "Create miner wallets and register them to the subnet.",
                "info": "⚒️  **Miners** are responsible for performing computations and contributing to the subnet's tasks. Setting up miners involves creating dedicated wallets for each miner entity and registering them to the subnet.",
                "action": lambda: self.setup_neurons(),
            },
            {
                "title": "Run Miners",
                "description": "Start all miner processes.",
                "info": "🏃 This step starts and runs your miner processes so they can start contributing to the network",
                "action": lambda: self.run_neurons(),
            },
            {
                "title": "Add Weights to Netuid 1",
                "description": "Configure weights for Netuid 1 through the validator.",
                "info": "🏋️ Setting **Root weights** in Bittensor means assigning relative importance to different subnets within the network, which directly influences their share of network rewards and resources.",
                "action": lambda: self.add_weights(),
            },
        ]

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
                default=SUBTENSOR_BRANCH,
            )

        console.print("🔗 [dark_orange]Starting the local chain...")
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
        console.clear()
        print_info("Welcome to the Bittensor Quick Start Tutorial", emoji="🚀")
        console.print(
            "\nThis tutorial will guide you through setting up the local chain, subnet, and neurons (miners + validators).\n",
            style="magenta",
        )

        for idx, step in enumerate(self.steps, start=1):
            if "info" in step:
                print_info_box(step["info"], title="Info")
            print_step(step["title"], step["description"], idx)

            console.print(
                "[bold blue]Press [yellow]Enter[/yellow] to continue to the next step or [yellow]Ctrl+C[/yellow] to exit.\n"
            )
            try:
                input()
            except KeyboardInterrupt:
                print_warning("Tutorial interrupted by user. Exiting...")
                return

            # Execute the action
            step["action"]()

        print_success(
            "Your local chain, subnet, and neurons are up and running", emoji="🎉"
        )
        console.print(
            "[green]Next, execute the following command to get a live view of all the progress through the metagraph: [dark_green]$ [dark_orange]btqs live"
        )

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
        print_info("Checking status of Subtensor and neurons...", emoji="🔍 ")

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
