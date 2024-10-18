import os
import time
from tqdm import tqdm
import typer
import yaml
from rich.text import Text
from rich.table import Table
from bittensor_wallet import Wallet, Keypair
from btqs.config import BTQS_LOCK_CONFIG_FILE_PATH, VALIDATOR_URI, LOCALNET_ENDPOINT
from btqs.utils import (
    console,
    exec_command,
    remove_ansi_escape_sequences,
    subnet_exists,
    subnet_owner_exists,
    get_process_entries,
    display_process_status_table,
    load_config,
    print_info,
    print_error,
    print_info_box,
)


def add_stake(config_data):
    print_info_box(
        "💰 You stake **TAO** to your hotkey to become a validator in a subnet. Your hotkey can potentially earn rewards based on your validating performance.",
        title="Info: Staking to become a Validator",
    )
    print("\n")

    subnet_owner, owner_data = subnet_owner_exists(BTQS_LOCK_CONFIG_FILE_PATH)
    if subnet_owner:
        owner_wallet = Wallet(
            name=owner_data.get("wallet_name"),
            path=config_data["wallets_path"],
            hotkey=owner_data.get("hotkey"),
        )
        print_info(
            f"Validator is adding stake to its own hotkey\n{owner_wallet}\n",
            emoji="🔖 ",
        )

        add_stake = exec_command(
            command="stake",
            sub_command="add",
            extra_args=[
                "--amount",
                1000,
                "--wallet-path",
                config_data["wallets_path"],
                "--chain",
                LOCALNET_ENDPOINT,
                "--wallet-name",
                owner_wallet.name,
                "--no-prompt",
                "--wallet-hotkey",
                owner_wallet.hotkey_str,
            ],
        )

        clean_stdout = remove_ansi_escape_sequences(add_stake.stdout)
        if "✅ Finalized" in clean_stdout:
            print_info("Stake added by Validator", emoji="📈 ")
            print_info_box(
                "Metagraph contains important information on a subnet. Displaying a metagraph is a useful way to see a snapshot of a subnet.",
                title="Info: Metagraph",
            )
            print_info("Viewing Metagraph for Subnet 1", emoji="\n🔎 ")
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

        else:
            print_error("\nFailed to add stake. Command output:\n")
            print(add_stake.stdout, end="")

        print("\n")
        print_info_box(
            "The validator's hotkey must be registered in the root network (netuid 0) to set root weights.",
            title="Root network registration",
        )

        print_info(
            f"Validator is registering to root network (netuid 0) ({owner_wallet})\n",
            emoji="\n🫚 ",
        )

        register_root = exec_command(
            command="root",
            sub_command="register",
            extra_args=[
                "--wallet-path",
                config_data["wallets_path"],
                "--chain",
                LOCALNET_ENDPOINT,
                "--wallet-name",
                owner_wallet.name,
                "--no-prompt",
                "--wallet-hotkey",
                owner_wallet.hotkey_str,
            ],
        )
        clean_stdout = remove_ansi_escape_sequences(register_root.stdout)
        if "✅ Registered" in clean_stdout:
            print_info("Successfully registered to the root network\n", emoji="✅ ")
        elif "✅ Already registered on root network" in clean_stdout:
            print_info("Validator is already registered to Root network\n", emoji="✅ ")
        else:
            print_error("\nFailed to register to root. Command output:\n")
            print(register_root.stdout, end="")

        print_info("Viewing Root list\n", emoji="🔎 ")
        subnets_list = exec_command(
            command="root",
            sub_command="list",
            extra_args=[
                "--chain",
                LOCALNET_ENDPOINT,
            ],
        )
        print(subnets_list.stdout, end="")

    else:
        print_error(
            "Subnet netuid 1 registered to the owner not found. Run `btqs subnet setup` first"
        )
        return


def add_weights(config_data):
    print_info_box(
        "🏋️ Setting **Root weights** in Bittensor means assigning relative importance to different subnets within the network, which directly influences their share of network rewards and resources.",
        title="Info: Setting Root weights",
    )
    subnet_owner, owner_data = subnet_owner_exists(BTQS_LOCK_CONFIG_FILE_PATH)
    if subnet_owner:
        owner_wallet = Wallet(
            name=owner_data.get("wallet_name"),
            path=config_data["wallets_path"],
            hotkey=owner_data.get("hotkey"),
        )
        print_info(
            "Validator is now setting weights of subnet 1 on the root network.\n Please wait... (Timeout: ~ 120 seconds)",
            emoji="🏋️ ",
        )
        max_retries = 60
        attempt = 0
        retry_patterns = [
            "ancient birth block",
            "Transaction has a bad signature",
            "SettingWeightsTooFast",
        ]

        while attempt < max_retries:
            try:
                set_weights = exec_command(
                    command="root",
                    sub_command="set-weights",
                    extra_args=[
                        "--wallet-path",
                        config_data["wallets_path"],
                        "--chain",
                        LOCALNET_ENDPOINT,
                        "--wallet-name",
                        owner_wallet.name,
                        "--no-prompt",
                        "--wallet-hotkey",
                        owner_wallet.hotkey_str,
                        "--netuid",
                        1,
                        "--weights",
                        1,
                    ],
                    internal_command=True,
                )
                clean_stdout = remove_ansi_escape_sequences(set_weights.stdout)

                if "✅ Finalized" in clean_stdout:
                    text = Text(
                        "Successfully set weights to Netuid 1\n",
                        style="bold light_goldenrod2",
                    )
                    sign = Text("🌟 ", style="bold yellow")
                    console.print(sign, text)
                    break

                elif any(pattern in clean_stdout for pattern in retry_patterns):
                    attempt += 1
                    if attempt < max_retries:
                        time.sleep(1)
                    else:
                        console.print(
                            "\n[red]Failed to set weights after multiple attempts. Please try again later\n"
                        )
                else:
                    console.print("\n[red]Failed to set weights. Command output:\n")
                    print(set_weights.stdout, end="")
                    break

            except KeyboardInterrupt:
                console.print("\n[yellow]Process interrupted by user. Exiting...")
                return

            except Exception as e:
                console.print(f"[red]An unexpected error occurred: {e}")
                break

        else:
            console.print(
                "[red]All retry attempts exhausted. Unable to set weights on the root network."
            )
    else:
        console.print(
            "[red]Subnet netuid 1 registered to the owner not found. Run `btqs subnet setup` first"
        )
        return


def display_live_metagraph(config_data):
    """
    Displays a live view of the metagraph.
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
            internal_command=True,
        )
        return result.stdout

    print("Starting live metagraph view. Press 'Ctrl + C' to exit.")

    try:
        while True:
            metagraph = get_metagraph()
            process_entries, cpu_usage_list, memory_usage_list = get_process_entries(
                config_data
            )
            clear_screen()
            print(metagraph)
            display_process_status_table(
                process_entries, cpu_usage_list, memory_usage_list
            )

            # Create a progress bar for 5 seconds
            print("\n")
            console.print("[green] Live view active: Press Ctrl + C to exit\n")
            for _ in tqdm(
                range(5),
                desc="Refreshing",
                bar_format="{desc}: {bar}",
                ascii=" ▖▘▝▗▚▞",
                ncols=20,
                colour="green",
            ):
                time.sleep(1)

    except KeyboardInterrupt:
        print("Exiting live view...")


def setup_subnet(config_data):
    os.makedirs(config_data["wallets_path"], exist_ok=True)
    subnet_owner, owner_data = subnet_owner_exists(BTQS_LOCK_CONFIG_FILE_PATH)
    if subnet_owner:
        owner_wallet = Wallet(
            name=owner_data.get("wallet_name"),
            path=config_data["wallets_path"],
            hotkey=owner_data.get("hotkey"),
        )
        input()

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
            "A running Subtensor not found. Please run `btqs chain start` first."
        )

    owner_data = config_data["Owner"]
    owner_wallet = Wallet(
        name=owner_data.get("wallet_name"),
        path=config_data["wallets_path"],
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
        create_subnet(owner_wallet, config_data)

    print_info("Listing all subnets\n", emoji="\n📋 ")
    print_info_box(
        "In the below table, the netuid 0 shown is root network that is automatically created when the local blockchain starts",
        title="Info: Root network (netuid 0)",
    )
    print("\n")
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
    print_info(
        "Creating a wallet (coldkey) and a hotkey to create a subnet.\n", emoji="🗂️ "
    )

    owner_wallet_name = typer.prompt(
        "Enter subnet owner wallet name", default="Alice", show_default=True
    )
    owner_hotkey_name = typer.prompt(
        "Enter subnet owner hotkey name", default="default", show_default=True
    )

    keypair = Keypair.create_from_uri(VALIDATOR_URI)
    owner_wallet = Wallet(
        path=config_data["wallets_path"],
        name=owner_wallet_name,
        hotkey=owner_hotkey_name,
    )
    owner_wallet.set_coldkey(keypair=keypair, encrypt=False, overwrite=True)
    owner_wallet.set_coldkeypub(keypair=keypair, encrypt=False, overwrite=True)
    owner_wallet.set_hotkey(keypair=keypair, encrypt=False, overwrite=True)

    console.print(
        "Executed command: [dark_orange] btcli wallet create --wallet-name",
        f"[dark_orange]{owner_hotkey_name} --wallet-hotkey {owner_wallet_name} --wallet-path {config_data['wallets_path']}",
    )

    config_data["Owner"] = {
        "wallet_name": owner_wallet_name,
        "hotkey": owner_hotkey_name,
        "subtensor_pid": config_data["pid"],
    }
    with open(BTQS_LOCK_CONFIG_FILE_PATH, "w") as config_file:
        yaml.safe_dump(config_data, config_file)


def create_subnet(owner_wallet, config_data):
    print_info("Creating a subnet.\n", emoji="\n🌎 ")

    create_subnet = exec_command(
        command="subnets",
        sub_command="create",
        extra_args=[
            "--wallet-path",
            config_data["wallets_path"],
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
        print_info("Subnet created successfully with netuid 1\n", emoji="🥇 ")

    print_info_box(
        "🔑 Creating a subnet involves signing with your *coldkey*, which is the permanent keypair associated with your account. "
        "It is typically used for long-term ownership and higher-value operations.\n\n"
        "🔥 When registering to a subnet, your *hotkey* is used. The hotkey is a more frequently used keypair "
        "designed for day-to-day interactions with the network."
    )

    print_info(
        f"Registering the subnet owner to Netuid 1\n{owner_wallet}\n", emoji="\n📝 "
    )

    register_subnet = exec_command(
        command="subnets",
        sub_command="register",
        extra_args=[
            "--wallet-path",
            config_data["wallets_path"],
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
        print_info("Registered the owner's hotkey to subnet 1", emoji="✅ ")
