import os
import sys
import time
import threading
from tqdm import tqdm
import typer
import yaml
from rich.text import Text
from rich.table import Table
from bittensor_wallet import Wallet, Keypair
from btqs.config  import (
    BTQS_WALLETS_DIRECTORY,
    CONFIG_FILE_PATH,
    VALIDATOR_URI,
)
from btqs.utils import (
    console,
    exec_command,
    remove_ansi_escape_sequences,
    subnet_exists,
    subnet_owner_exists,
    get_process_entries,
    display_process_status_table,
    load_config,
)

def add_stake(config_data = None):
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
    

def display_live_metagraph():
    """
    Displays a live view of the metagraph for subnet 1.

    This command shows real-time updates of the metagraph and neuron statuses.

    USAGE

    [green]$[/green] btqs subnet live

    [bold]Note[/bold]: Press Ctrl+C to exit the live view.
    """
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

def setup_subnet(config_data):
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
        create_subnet_owner_wallet(config_data)
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
        create_subnet(owner_wallet)

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

def create_subnet_owner_wallet(config_data):
    console.print(
        Text("Creating subnet owner wallet.\n", style="bold light_goldenrod2"),
    )

    owner_wallet_name = typer.prompt(
        "Enter subnet owner wallet name", default="owner", show_default=True
    )
    owner_hotkey_name = typer.prompt(
        "Enter subnet owner hotkey name", default="default", show_default=True
    )

    keypair = Keypair.create_from_uri(VALIDATOR_URI)
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

def create_subnet(owner_wallet):
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


def steps():
    steps = [
        {
            "command": "btqs chain start",
            "description": "Start and initialize a local Subtensor blockchain. It may take several minutes to complete during the Subtensor compilation process. This is the entry point of the tutorial",
        },
        {
            "command": "btqs subnet setup",
            "description": "This command creates a subnet owner's wallet, creates a new subnet, and registers the subnet owner to the subnet. Ensure the local chain is running before executing this command.",
        },
        {
            "command": "btqs neurons setup",
            "description": "This command creates miner wallets and registers them to the subnet.",
        },
        {
            "command": "btqs neurons run",
            "description": "Run all neurons (miners and validators). This command starts the processes for all configured neurons, attaching to running processes if they are already running.",
        },
        {
            "command": "btqs subnet stake",
            "description": "Add stake to the subnet. This command allows the subnet owner to stake tokens to the subnet.",
        },
        {
            "command": "btqs subnet live",
            "description": "Display the live metagraph of the subnet. This is used to monitor neuron performance and changing variables.",
        },
    ]

    table = Table(
        title="[bold dark_orange]Subnet Setup Steps",
        header_style="dark_orange",
        leading=True,
        show_edge=False,
        border_style="bright_black",
    )
    table.add_column("Step", style="cyan", width=12, justify="center")
    table.add_column("Command", justify="left", style="green")
    table.add_column("Description", justify="left", style="white")

    for index, step in enumerate(steps, start=1):
        table.add_row(str(index), step["command"], step["description"])

    console.print(table)

    console.print("\n[dark_orange] You can run an automated script covering all the steps using:\n")
    console.print("[blue]$ [green]btqs run-all")