#!/usr/bin/env python3
import asyncio
import copy
import curses
import importlib
import json
import os.path
import re
import ssl
import sys
import traceback
import warnings
from dataclasses import fields
from pathlib import Path
from typing import Coroutine, Optional, Union

import numpy as np
import rich
import typer
from async_substrate_interface.errors import (
    SubstrateRequestException,
    ConnectionClosed,
    InvalidHandshake,
)
from bittensor_wallet import Wallet
from rich import box
from rich.prompt import Confirm, FloatPrompt, Prompt, IntPrompt
from rich.table import Column, Table
from rich.tree import Tree
from typing_extensions import Annotated
from yaml import safe_dump, safe_load

from bittensor_cli.src import (
    defaults,
    HELP_PANELS,
    WalletOptions as WO,
    WalletValidationTypes as WV,
    Constants,
    COLORS,
    HYPERPARAMS,
)
from bittensor_cli.src.bittensor import utils
from bittensor_cli.src.bittensor.balances import Balance
from bittensor_cli.src.bittensor.chain_data import SubnetHyperparameters
from bittensor_cli.src.bittensor.subtensor_interface import SubtensorInterface
from bittensor_cli.src.bittensor.utils import (
    console,
    err_console,
    verbose_console,
    json_console,
    is_valid_ss58_address,
    print_error,
    validate_chain_endpoint,
    validate_netuid,
    is_rao_network,
    get_effective_network,
    prompt_for_identity,
    validate_uri,
    prompt_for_subnet_identity,
    validate_rate_tolerance,
)
from bittensor_cli.src.commands import sudo, wallets, view
from bittensor_cli.src.commands import weights as weights_cmds
from bittensor_cli.src.commands.liquidity import liquidity
from bittensor_cli.src.commands.liquidity.utils import (
    prompt_liquidity,
    prompt_position_id,
)
from bittensor_cli.src.commands.stake import (
    children_hotkeys,
    list as list_stake,
    move as move_stake,
    add as add_stake,
    remove as remove_stake,
)
from bittensor_cli.src.commands.subnets import price, subnets
from bittensor_cli.version import __version__, __version_as_int__

try:
    from git import Repo, GitError
except ImportError:
    Repo = None

    class GitError(Exception):
        pass


_epilog = "Made with [bold red]:heart:[/bold red] by The Openτensor Foundaτion"

np.set_printoptions(precision=8, suppress=True, floatmode="fixed")


class Options:
    """
    Re-usable typer args
    """

    @classmethod
    def edit_help(cls, option_name: str, help_text: str):
        """
        Edits the `help` attribute of a copied given Typer option in this class, returning
        the modified Typer option.

        Args:
            option_name: the name of the option (e.g. "wallet_name")
            help_text: New help text to be used (e.g. "Wallet's name")

        Returns:
            Modified Typer Option with new help text.
        """
        copied_attr = copy.copy(getattr(cls, option_name))
        setattr(copied_attr, "help", help_text)
        return copied_attr

    wallet_name = typer.Option(
        None,
        "--wallet-name",
        "--name",
        "--wallet_name",
        "--wallet.name",
        help="Name of the wallet.",
    )
    wallet_path = typer.Option(
        None,
        "--wallet-path",
        "-p",
        "--wallet_path",
        "--wallet.path",
        help="Path where the wallets are located. For example: `/Users/btuser/.bittensor/wallets`.",
    )
    wallet_hotkey = typer.Option(
        None,
        "--hotkey",
        "-H",
        "--wallet_hotkey",
        "--wallet-hotkey",
        "--wallet.hotkey",
        help="Hotkey of the wallet",
    )
    wallet_ss58_address = typer.Option(
        None,
        "--wallet-name",
        "--name",
        "--wallet_name",
        "--wallet.name",
        "--address",
        "--ss58",
        "--ss58-address",
        help="SS58 address or wallet name to check. Leave empty to be prompted.",
    )
    wallet_hotkey_ss58 = typer.Option(
        None,
        "--hotkey",
        "--hotkey-ss58",
        "-H",
        "--wallet_hotkey",
        "--wallet_hotkey_ss58",
        "--wallet-hotkey",
        "--wallet-hotkey-ss58",
        "--wallet.hotkey",
        help="Hotkey name or SS58 address of the hotkey",
    )
    mnemonic = typer.Option(
        None,
        help='Mnemonic used to regenerate your key. For example: "horse cart dog ..."',
    )
    seed = typer.Option(
        None, help="Seed hex string used to regenerate your key. For example: 0x1234..."
    )
    json = typer.Option(
        None,
        "--json",
        "-j",
        help="Path to a JSON file containing the encrypted key backup. For example, a JSON file from PolkadotJS.",
    )
    json_password = typer.Option(
        None, "--json-password", help="Password to decrypt the JSON file."
    )
    use_password = typer.Option(
        True,
        help="Set this to `True` to protect the generated Bittensor key with a password.",
    )
    public_hex_key = typer.Option(None, help="The public key in hex format.")
    ss58_address = typer.Option(
        None, "--ss58", "--ss58-address", help="The SS58 address of the coldkey."
    )
    overwrite = typer.Option(
        False,
        "--overwrite/--no-overwrite",
        help="Overwrite the existing wallet file with the new one.",
    )
    network = typer.Option(
        None,
        "--network",
        "--subtensor.network",
        "--chain",
        "--subtensor.chain_endpoint",
        help="The subtensor network to connect to. Default: finney.",
        show_default=False,
    )
    netuids = typer.Option(
        None,
        "--netuids",
        "--netuid",
        "-n",
        help="Set the netuid(s) to exclude. Separate multiple netuids with a comma, for example: `-n 0,1,2`.",
    )
    netuid = typer.Option(
        None,
        help="The netuid of the subnet in the network, (e.g. 1).",
        prompt=True,
        callback=validate_netuid,
    )
    netuid_not_req = typer.Option(
        None,
        help="The netuid of the subnet in the network, (e.g. 1).",
        prompt=False,
    )
    all_netuids = typer.Option(
        False,
        help="Use all netuids",
        prompt=False,
    )
    weights = typer.Option(
        None,
        "--weights",
        "-w",
        help="Weights for the specified UIDs, e.g. `-w 0.2,0.4,0.1 ...` Must correspond to the order of the UIDs.",
    )
    reuse_last = typer.Option(
        False,
        "--reuse-last",
        help="Reuse the metagraph data you last retrieved."
        "Use this option only if you have already retrieved the metagraph."
        "data",
    )
    html_output = typer.Option(
        False,
        "--html",
        help="Display the table as HTML in the browser.",
    )
    wait_for_inclusion = typer.Option(
        True, help="If `True`, waits until the transaction is included in a block."
    )
    wait_for_finalization = typer.Option(
        True,
        help="If `True`, waits until the transaction is finalized on the blockchain.",
    )
    prompt = typer.Option(
        True,
        "--prompt/--no-prompt",
        " /--yes",
        "--prompt/--no_prompt",
        " /-y",
        help="Enable or disable interactive prompts.",
    )
    verbose = typer.Option(
        False,
        "--verbose",
        help="Enable verbose output.",
    )
    quiet = typer.Option(
        False,
        "--quiet",
        help="Display only critical information on the console.",
    )
    live = typer.Option(
        False,
        "--live",
        help="Display live view of the table",
    )
    uri = typer.Option(
        None,
        "--uri",
        help="Create wallet from uri (e.g. 'Alice', 'Bob', 'Charlie', 'Dave', 'Eve')",
        callback=validate_uri,
    )
    rate_tolerance = typer.Option(
        None,
        "--slippage",
        "--slippage-tolerance",
        "--tolerance",
        "--rate-tolerance",
        help="Set the rate tolerance percentage for transactions (default: 0.05 for 5%).",
        callback=validate_rate_tolerance,
    )
    safe_staking = typer.Option(
        None,
        "--safe-staking/--no-safe-staking",
        "--safe/--unsafe",
        show_default=False,
        help="Enable or disable safe staking mode [dim](default: enabled)[/dim].",
    )
    allow_partial_stake = typer.Option(
        None,
        "--allow-partial-stake/--no-allow-partial-stake",
        "--partial/--no-partial",
        "--allow/--not-allow",
        "--allow-partial/--not-partial",
        show_default=False,
        help="Enable or disable partial stake mode [dim](default: disabled)[/dim].",
    )
    dashboard_path = typer.Option(
        None,
        "--dashboard-path",
        "--dashboard_path",
        "--dash_path",
        "--dash.path",
        "--dashboard.path",
        help="Path to save the dashboard HTML file. For example: `~/.bittensor/dashboard`.",
    )
    json_output = typer.Option(
        False,
        "--json-output",
        "--json-out",
        help="Outputs the result of the command as JSON.",
    )
    period: int = typer.Option(
        16,
        "--period",
        "--era",
        help="Length (in blocks) for which the transaction should be valid.",
    )


def list_prompt(init_var: list, list_type: type, help_text: str) -> list:
    """
    Serves a similar purpose to rich.FloatPrompt or rich.Prompt, but for creating a list of those variables for
    a given type
    :param init_var: starting variable, this will generally be `None` if you intend to get something out of this
                     prompt, if it is not empty, it will return the same
    :param list_type: the type for each item in the list you're creating
    :param help_text: the helper text to display to the user in the prompt

    :return: list of the specified type of the user inputs
    """
    while not init_var:
        prompt = Prompt.ask(help_text)
        init_var = [list_type(x) for x in re.split(r"[ ,]+", prompt) if x]
    return init_var


def parse_to_list(
    raw_list: str, list_type: type, error_message: str, is_ss58: bool = False
) -> list:
    try:
        # Split the string by commas and convert each part to according to type
        parsed_list = [
            list_type(uid.strip()) for uid in raw_list.split(",") if uid.strip()
        ]

        # Validate in-case of ss58s
        if is_ss58:
            for item in parsed_list:
                if not is_valid_ss58_address(item):
                    raise typer.BadParameter(f"Invalid SS58 address: {item}")

        return parsed_list
    except ValueError:
        raise typer.BadParameter(error_message)


def verbosity_console_handler(verbosity_level: int = 1) -> None:
    """
    Sets verbosity level of console output
    :param verbosity_level: int corresponding to verbosity level of console output (0 is quiet, 1 is normal, 2 is
        verbose)
    """
    if verbosity_level not in range(4):
        raise ValueError(
            f"Invalid verbosity level: {verbosity_level}. "
            f"Must be one of: 0 (quiet + json output), 1 (normal), 2 (verbose), 3 (json output + verbose)"
        )
    if verbosity_level == 0:
        console.quiet = True
        err_console.quiet = True
        verbose_console.quiet = True
        json_console.quiet = False
    elif verbosity_level == 1:
        console.quiet = False
        err_console.quiet = False
        verbose_console.quiet = True
        json_console.quiet = True
    elif verbosity_level == 2:
        console.quiet = False
        err_console.quiet = False
        verbose_console.quiet = False
        json_console.quiet = True
    elif verbosity_level == 3:
        console.quiet = True
        err_console.quiet = True
        verbose_console.quiet = False
        json_console.quiet = False


def get_optional_netuid(netuid: Optional[int], all_netuids: bool) -> Optional[int]:
    """
    Parses options to determine if the user wants to use a specific netuid or all netuids (None)

    Returns:
        None if using all netuids, otherwise int for the netuid to use
    """
    if netuid is None and all_netuids is True:
        return None
    elif netuid is None and all_netuids is False:
        answer = Prompt.ask(
            f"Enter the [{COLORS.G.SUBHEAD_MAIN}]netuid"
            f"[/{COLORS.G.SUBHEAD_MAIN}] to use. Leave blank for all netuids",
            default=None,
            show_default=False,
        )
        if answer is None:
            return None
        if answer.lower() == "all":
            return None
        else:
            return int(answer)
    else:
        return netuid


def get_n_words(n_words: Optional[int]) -> int:
    """
    Prompts the user to select the number of words used in the mnemonic if not supplied or not within the
    acceptable criteria of [12, 15, 18, 21, 24]
    """
    while n_words not in [12, 15, 18, 21, 24]:
        n_words = int(
            Prompt.ask(
                "Choose the number of words",
                choices=["12", "15", "18", "21", "24"],
                default=12,
            )
        )
    return n_words


def parse_mnemonic(mnemonic: str) -> str:
    if "-" in mnemonic:
        items = sorted(
            [tuple(item.split("-")) for item in mnemonic.split(" ")],
            key=lambda x: int(x[0]),
        )
        if int(items[0][0]) != 1:
            err_console.print("Numbered mnemonics must begin with 1")
            raise typer.Exit()
        if [int(x[0]) for x in items] != list(
            range(int(items[0][0]), int(items[-1][0]) + 1)
        ):
            err_console.print(
                "Missing or duplicate numbers in a numbered mnemonic. "
                "Double-check your numbered mnemonics and try again."
            )
            raise typer.Exit()
        response = " ".join(item[1] for item in items)
    else:
        response = mnemonic
    return response


def get_creation_data(
    mnemonic: Optional[str],
    seed: Optional[str],
    json_path: Optional[str],
    json_password: Optional[str],
) -> tuple[str, str, str, str]:
    """
    Determines which of the key creation elements have been supplied, if any. If None have been supplied,
    prompts to user, and determines what they've supplied. Returns all elements in a tuple.
    """
    if not mnemonic and not seed and not json_path:
        choices = {
            1: "mnemonic",
            2: "seed hex string",
            3: "path to JSON File",
        }
        type_answer = IntPrompt.ask(
            "Select one of the following to enter\n"
            f"[{COLORS.G.HINT}][1][/{COLORS.G.HINT}] Mnemonic\n"
            f"[{COLORS.G.HINT}][2][/{COLORS.G.HINT}] Seed hex string\n"
            f"[{COLORS.G.HINT}][3][/{COLORS.G.HINT}] Path to JSON File\n",
            choices=["1", "2", "3"],
            show_choices=False,
        )
        prompt_answer = Prompt.ask(f"Please enter your {choices[type_answer]}")
        if type_answer == 1:
            mnemonic = prompt_answer
        elif type_answer == 2:
            seed = prompt_answer
            if seed.startswith("0x"):
                seed = seed[2:]
        elif type_answer == 3:
            json_path = prompt_answer
    elif mnemonic:
        mnemonic = parse_mnemonic(mnemonic)

    if json_path:
        if not os.path.exists(json_path):
            print_error(f"The JSON file '{json_path}' does not exist.")
            raise typer.Exit()

    if json_path and not json_password:
        json_password = Prompt.ask(
            "Enter the backup password for JSON file.", password=True
        )
    return mnemonic, seed, json_path, json_password


def config_selector(conf: dict, title: str):
    def curses_selector(stdscr):
        """
        Enhanced Curses TUI to make selections.
        """
        # Load the current selections from the config
        items = list(conf.keys())
        selections = conf

        # Track the current index for navigation
        current_index = 0

        # Hide cursor
        curses.curs_set(0)

        while True:
            stdscr.clear()
            height, width = stdscr.getmaxyx()
            stdscr.box()
            stdscr.addstr(0, (width - len(title)) // 2, title, curses.A_BOLD)

            instructions = (
                "Use UP/DOWN keys to navigate, SPACE to toggle, ENTER to confirm."
            )
            stdscr.addstr(
                2, (width - len(instructions)) // 2, instructions, curses.A_DIM
            )

            for idx, item in enumerate(items):
                indicator = "[x]" if selections[item] else "[ ]"
                line_text = f"  {item} {indicator}"
                x_pos = (width - len(line_text)) // 2

                if idx == current_index:
                    stdscr.addstr(
                        4 + idx, x_pos, line_text, curses.A_REVERSE | curses.A_BOLD
                    )
                else:
                    stdscr.addstr(4 + idx, x_pos, line_text)

            stdscr.refresh()

            key = stdscr.getch()
            if key == curses.KEY_UP:
                current_index = (current_index - 1) % len(items)
            elif key == curses.KEY_DOWN:
                current_index = (current_index + 1) % len(items)
            elif key == ord(" "):  # Toggle selection with spacebar
                selections[items[current_index]] = not selections[items[current_index]]
            elif key == ord("\n"):  # Exit with Enter key
                break

        return selections

    return curses.wrapper(curses_selector)


def version_callback(value: bool):
    """
    Prints the current version/branch-name
    """
    if value:
        try:
            repo = Repo(os.path.dirname(os.path.dirname(__file__)))
            version = (
                f"BTCLI version: {__version__}/"
                f"{repo.active_branch.name}/"
                f"{repo.commit()}"
            )
        except (TypeError, GitError):
            version = f"BTCLI version: {__version__}"
        typer.echo(version)
        raise typer.Exit()


def commands_callback(value: bool):
    """
    Prints a tree of commands for the app
    """
    if value:
        cli = CLIManager()
        console.print(cli.generate_command_tree())
        raise typer.Exit()


class CLIManager:
    """
    :var app: the main CLI Typer app
    :var config_app: the Typer app as it relates to config commands
    :var wallet_app: the Typer app as it relates to wallet commands
    :var stake_app: the Typer app as it relates to stake commands
    :var sudo_app: the Typer app as it relates to sudo commands
    :var subnets_app: the Typer app as it relates to subnets commands
    :var subtensor: the `SubtensorInterface` object passed to the various commands that require it
    """

    subtensor: Optional[SubtensorInterface]
    app: typer.Typer
    config_app: typer.Typer
    wallet_app: typer.Typer
    subnets_app: typer.Typer
    weights_app: typer.Typer
    utils_app = typer.Typer(epilog=_epilog)
    view_app: typer.Typer
    asyncio_runner = asyncio

    def __init__(self):
        self.config = {
            "wallet_name": None,
            "wallet_path": None,
            "wallet_hotkey": None,
            "network": None,
            "use_cache": True,
            "rate_tolerance": None,
            "safe_staking": True,
            "allow_partial_stake": False,
            "dashboard_path": None,
            # Commenting this out as this needs to get updated
            # "metagraph_cols": {
            #     "UID": True,
            #     "GLOBAL_STAKE": True,
            #     "LOCAL_STAKE": True,
            #     "STAKE_WEIGHT": True,
            #     "RANK": True,
            #     "TRUST": True,
            #     "CONSENSUS": True,
            #     "INCENTIVE": True,
            #     "DIVIDENDS": True,
            #     "EMISSION": True,
            #     "VTRUST": True,
            #     "VAL": True,
            #     "UPDATED": True,
            #     "ACTIVE": True,
            #     "AXON": True,
            #     "HOTKEY": True,
            #     "COLDKEY": True,
            # },
        }
        self.subtensor = None
        self.config_base_path = os.path.expanduser(defaults.config.base_path)
        self.config_path = os.path.expanduser(defaults.config.path)

        self.app = typer.Typer(
            rich_markup_mode="rich",
            callback=self.main_callback,
            epilog=_epilog,
            no_args_is_help=True,
        )
        self.config_app = typer.Typer(epilog=_epilog)
        self.wallet_app = typer.Typer(epilog=_epilog)
        self.stake_app = typer.Typer(epilog=_epilog)
        self.sudo_app = typer.Typer(epilog=_epilog)
        self.subnets_app = typer.Typer(epilog=_epilog)
        self.weights_app = typer.Typer(epilog=_epilog)
        self.view_app = typer.Typer(epilog=_epilog)
        self.liquidity_app = typer.Typer(epilog=_epilog)

        # config alias
        self.app.add_typer(
            self.config_app,
            name="config",
            short_help="Config commands, aliases: `c`, `conf`",
            no_args_is_help=True,
        )
        self.app.add_typer(
            self.config_app, name="conf", hidden=True, no_args_is_help=True
        )
        self.app.add_typer(self.config_app, name="c", hidden=True, no_args_is_help=True)

        # wallet aliases
        self.app.add_typer(
            self.wallet_app,
            name="wallet",
            short_help="Wallet commands, aliases: `wallets`, `w`",
            no_args_is_help=True,
        )
        self.app.add_typer(self.wallet_app, name="w", hidden=True, no_args_is_help=True)
        self.app.add_typer(
            self.wallet_app, name="wallets", hidden=True, no_args_is_help=True
        )

        # stake aliases
        self.app.add_typer(
            self.stake_app,
            name="stake",
            short_help="Stake commands, alias: `st`",
            no_args_is_help=True,
        )
        self.app.add_typer(self.stake_app, name="st", hidden=True, no_args_is_help=True)

        # sudo aliases
        self.app.add_typer(
            self.sudo_app,
            name="sudo",
            short_help="Sudo commands, alias: `su`",
            no_args_is_help=True,
        )
        self.app.add_typer(self.sudo_app, name="su", hidden=True, no_args_is_help=True)

        # subnets aliases
        self.app.add_typer(
            self.subnets_app,
            name="subnets",
            short_help="Subnets commands, alias: `s`, `subnet`",
            no_args_is_help=True,
        )
        self.app.add_typer(
            self.subnets_app, name="s", hidden=True, no_args_is_help=True
        )
        self.app.add_typer(
            self.subnets_app, name="subnet", hidden=True, no_args_is_help=True
        )

        # weights aliases
        self.app.add_typer(
            self.weights_app,
            name="weights",
            short_help="Weights commands, aliases: `wt`, `weight`",
            hidden=True,
            no_args_is_help=True,
        )
        self.app.add_typer(
            self.weights_app, name="wt", hidden=True, no_args_is_help=True
        )
        self.app.add_typer(
            self.weights_app, name="weight", hidden=True, no_args_is_help=True
        )

        # utils app
        self.app.add_typer(
            self.utils_app, name="utils", no_args_is_help=True, hidden=True
        )

        # view app
        self.app.add_typer(
            self.view_app,
            name="view",
            short_help="HTML view commands",
            no_args_is_help=True,
        )

        # config commands
        self.config_app.command("set")(self.set_config)
        self.config_app.command("get")(self.get_config)
        self.config_app.command("clear")(self.del_config)
        # self.config_app.command("metagraph", hidden=True)(self.metagraph_config)

        # wallet commands
        self.wallet_app.command(
            "list", rich_help_panel=HELP_PANELS["WALLET"]["MANAGEMENT"]
        )(self.wallet_list)
        self.wallet_app.command(
            "swap-hotkey", rich_help_panel=HELP_PANELS["WALLET"]["SECURITY"]
        )(self.wallet_swap_hotkey)
        self.wallet_app.command(
            "swap-coldkey", rich_help_panel=HELP_PANELS["WALLET"]["SECURITY"]
        )(self.wallet_swap_coldkey)
        self.wallet_app.command(
            "swap-check", rich_help_panel=HELP_PANELS["WALLET"]["SECURITY"]
        )(self.wallet_check_ck_swap)
        self.wallet_app.command(
            "regen-coldkey", rich_help_panel=HELP_PANELS["WALLET"]["SECURITY"]
        )(self.wallet_regen_coldkey)
        self.wallet_app.command(
            "regen-coldkeypub", rich_help_panel=HELP_PANELS["WALLET"]["SECURITY"]
        )(self.wallet_regen_coldkey_pub)
        self.wallet_app.command(
            "regen-hotkey", rich_help_panel=HELP_PANELS["WALLET"]["SECURITY"]
        )(self.wallet_regen_hotkey)
        self.wallet_app.command(
            "new-hotkey", rich_help_panel=HELP_PANELS["WALLET"]["MANAGEMENT"]
        )(self.wallet_new_hotkey)
        self.wallet_app.command(
            "new-coldkey", rich_help_panel=HELP_PANELS["WALLET"]["MANAGEMENT"]
        )(self.wallet_new_coldkey)
        self.wallet_app.command(
            "associate-hotkey", rich_help_panel=HELP_PANELS["WALLET"]["MANAGEMENT"]
        )(self.wallet_associate_hotkey)
        self.wallet_app.command(
            "create", rich_help_panel=HELP_PANELS["WALLET"]["MANAGEMENT"]
        )(self.wallet_create_wallet)
        self.wallet_app.command(
            "balance", rich_help_panel=HELP_PANELS["WALLET"]["INFORMATION"]
        )(self.wallet_balance)
        self.wallet_app.command(
            "history",
            rich_help_panel=HELP_PANELS["WALLET"]["INFORMATION"],
            hidden=True,
        )(self.wallet_history)
        self.wallet_app.command(
            "overview",
            rich_help_panel=HELP_PANELS["WALLET"]["INFORMATION"],
        )(self.wallet_overview)
        self.wallet_app.command(
            "transfer", rich_help_panel=HELP_PANELS["WALLET"]["OPERATIONS"]
        )(self.wallet_transfer)
        self.wallet_app.command(
            "inspect",
            rich_help_panel=HELP_PANELS["WALLET"]["INFORMATION"],
            hidden=True,
        )(self.wallet_inspect)
        self.wallet_app.command(
            "faucet", rich_help_panel=HELP_PANELS["WALLET"]["OPERATIONS"]
        )(self.wallet_faucet)
        self.wallet_app.command(
            "set-identity", rich_help_panel=HELP_PANELS["WALLET"]["IDENTITY"]
        )(self.wallet_set_id)
        self.wallet_app.command(
            "get-identity", rich_help_panel=HELP_PANELS["WALLET"]["IDENTITY"]
        )(self.wallet_get_id)
        self.wallet_app.command(
            "sign", rich_help_panel=HELP_PANELS["WALLET"]["OPERATIONS"]
        )(self.wallet_sign)

        # stake commands
        self.stake_app.command(
            "add", rich_help_panel=HELP_PANELS["STAKE"]["STAKE_MGMT"]
        )(self.stake_add)
        self.stake_app.command(
            "remove", rich_help_panel=HELP_PANELS["STAKE"]["STAKE_MGMT"]
        )(self.stake_remove)
        self.stake_app.command(
            "list", rich_help_panel=HELP_PANELS["STAKE"]["STAKE_MGMT"]
        )(self.stake_list)
        self.stake_app.command(
            "move", rich_help_panel=HELP_PANELS["STAKE"]["MOVEMENT"]
        )(self.stake_move)
        self.stake_app.command(
            "transfer", rich_help_panel=HELP_PANELS["STAKE"]["MOVEMENT"]
        )(self.stake_transfer)
        self.stake_app.command(
            "swap", rich_help_panel=HELP_PANELS["STAKE"]["MOVEMENT"]
        )(self.stake_swap)

        # stake-children commands
        children_app = typer.Typer()
        self.stake_app.add_typer(
            children_app,
            name="child",
            short_help="Child Hotkey commands, alias: `children`",
            rich_help_panel=HELP_PANELS["STAKE"]["CHILD"],
            no_args_is_help=True,
        )
        self.stake_app.add_typer(
            children_app, name="children", hidden=True, no_args_is_help=True
        )
        children_app.command("get")(self.stake_get_children)
        children_app.command("set")(self.stake_set_children)
        children_app.command("revoke")(self.stake_revoke_children)
        children_app.command("take")(self.stake_childkey_take)

        # sudo commands
        self.sudo_app.command("set", rich_help_panel=HELP_PANELS["SUDO"]["CONFIG"])(
            self.sudo_set
        )
        self.sudo_app.command("get", rich_help_panel=HELP_PANELS["SUDO"]["CONFIG"])(
            self.sudo_get
        )
        self.sudo_app.command(
            "senate", rich_help_panel=HELP_PANELS["SUDO"]["GOVERNANCE"]
        )(self.sudo_senate)
        self.sudo_app.command(
            "proposals", rich_help_panel=HELP_PANELS["SUDO"]["GOVERNANCE"]
        )(self.sudo_proposals)
        self.sudo_app.command(
            "senate-vote", rich_help_panel=HELP_PANELS["SUDO"]["GOVERNANCE"]
        )(self.sudo_senate_vote)
        self.sudo_app.command("set-take", rich_help_panel=HELP_PANELS["SUDO"]["TAKE"])(
            self.sudo_set_take
        )
        self.sudo_app.command("get-take", rich_help_panel=HELP_PANELS["SUDO"]["TAKE"])(
            self.sudo_get_take
        )

        # subnets commands
        self.subnets_app.command(
            "hyperparameters", rich_help_panel=HELP_PANELS["SUBNETS"]["INFO"]
        )(self.sudo_get)
        self.subnets_app.command(
            "list", rich_help_panel=HELP_PANELS["SUBNETS"]["INFO"]
        )(self.subnets_list)
        self.subnets_app.command(
            "burn-cost", rich_help_panel=HELP_PANELS["SUBNETS"]["CREATION"]
        )(self.subnets_burn_cost)
        self.subnets_app.command(
            "create", rich_help_panel=HELP_PANELS["SUBNETS"]["CREATION"]
        )(self.subnets_create)
        self.subnets_app.command(
            "pow-register", rich_help_panel=HELP_PANELS["SUBNETS"]["REGISTER"]
        )(self.subnets_pow_register)
        self.subnets_app.command(
            "register", rich_help_panel=HELP_PANELS["SUBNETS"]["REGISTER"]
        )(self.subnets_register)
        self.subnets_app.command(
            "metagraph", rich_help_panel=HELP_PANELS["SUBNETS"]["INFO"], hidden=True
        )(self.subnets_show)  # Aliased to `s show` for now
        self.subnets_app.command(
            "show", rich_help_panel=HELP_PANELS["SUBNETS"]["INFO"]
        )(self.subnets_show)
        self.subnets_app.command(
            "price", rich_help_panel=HELP_PANELS["SUBNETS"]["INFO"]
        )(self.subnets_price)
        self.subnets_app.command(
            "set-identity", rich_help_panel=HELP_PANELS["SUBNETS"]["IDENTITY"]
        )(self.subnets_set_identity)
        self.subnets_app.command(
            "get-identity", rich_help_panel=HELP_PANELS["SUBNETS"]["IDENTITY"]
        )(self.subnets_get_identity)
        self.subnets_app.command(
            "start", rich_help_panel=HELP_PANELS["SUBNETS"]["CREATION"]
        )(self.subnets_start)
        self.subnets_app.command(
            "check-start", rich_help_panel=HELP_PANELS["SUBNETS"]["INFO"]
        )(self.subnets_check_start)

        # weights commands
        self.weights_app.command(
            "reveal", rich_help_panel=HELP_PANELS["WEIGHTS"]["COMMIT_REVEAL"]
        )(self.weights_reveal)
        self.weights_app.command(
            "commit", rich_help_panel=HELP_PANELS["WEIGHTS"]["COMMIT_REVEAL"]
        )(self.weights_commit)

        # view commands
        self.view_app.command(
            "dashboard", rich_help_panel=HELP_PANELS["VIEW"]["DASHBOARD"]
        )(self.view_dashboard)

        # Sub command aliases
        # Wallet
        self.wallet_app.command(
            "swap_hotkey",
            hidden=True,
        )(self.wallet_swap_hotkey)
        self.wallet_app.command("swap_coldkey", hidden=True)(self.wallet_swap_coldkey)
        self.wallet_app.command("swap_check", hidden=True)(self.wallet_check_ck_swap)
        self.wallet_app.command(
            "regen_coldkey",
            hidden=True,
        )(self.wallet_regen_coldkey)
        self.wallet_app.command(
            "regen_coldkeypub",
            hidden=True,
        )(self.wallet_regen_coldkey_pub)
        self.wallet_app.command(
            "regen_hotkey",
            hidden=True,
        )(self.wallet_regen_hotkey)
        self.wallet_app.command(
            "new_hotkey",
            hidden=True,
        )(self.wallet_new_hotkey)
        self.wallet_app.command(
            "new_coldkey",
            hidden=True,
        )(self.wallet_new_coldkey)
        self.wallet_app.command(
            "set_identity",
            hidden=True,
        )(self.wallet_set_id)
        self.wallet_app.command(
            "get_identity",
            hidden=True,
        )(self.wallet_get_id)
        self.wallet_app.command("associate_hotkey")(self.wallet_associate_hotkey)

        # Subnets
        self.subnets_app.command("burn_cost", hidden=True)(self.subnets_burn_cost)
        self.subnets_app.command("pow_register", hidden=True)(self.subnets_pow_register)
        self.subnets_app.command("set_identity", hidden=True)(self.subnets_set_identity)
        self.subnets_app.command("get_identity", hidden=True)(self.subnets_get_identity)
        self.subnets_app.command("check_start", hidden=True)(self.subnets_check_start)

        # Sudo
        self.sudo_app.command("senate_vote", hidden=True)(self.sudo_senate_vote)
        self.sudo_app.command("get_take", hidden=True)(self.sudo_get_take)
        self.sudo_app.command("set_take", hidden=True)(self.sudo_set_take)

        # Liquidity
        self.app.add_typer(
            self.liquidity_app,
            name="liquidity",
            short_help="liquidity commands, aliases: `l`",
            no_args_is_help=True,
        )
        self.app.add_typer(
            self.liquidity_app, name="l", hidden=True, no_args_is_help=True
        )
        # liquidity commands
        self.liquidity_app.command(
            "add", rich_help_panel=HELP_PANELS["LIQUIDITY"]["LIQUIDITY_MGMT"]
        )(self.liquidity_add)
        self.liquidity_app.command(
            "list", rich_help_panel=HELP_PANELS["LIQUIDITY"]["LIQUIDITY_MGMT"]
        )(self.liquidity_list)
        self.liquidity_app.command(
            "modify", rich_help_panel=HELP_PANELS["LIQUIDITY"]["LIQUIDITY_MGMT"]
        )(self.liquidity_modify)
        self.liquidity_app.command(
            "remove", rich_help_panel=HELP_PANELS["LIQUIDITY"]["LIQUIDITY_MGMT"]
        )(self.liquidity_remove)

    def generate_command_tree(self) -> Tree:
        """
        Generates a rich.Tree of the commands, subcommands, and groups of this app
        """

        def build_rich_tree(data: dict, parent: Tree):
            for group, content in data.get("groups", {}).items():
                group_node = parent.add(
                    f"[bold cyan]{group}[/]"
                )  # Add group to the tree
                for command in content.get("commands", []):
                    group_node.add(f"[green]{command}[/]")  # Add commands to the group
                build_rich_tree(content, group_node)  # Recurse for subgroups

        def traverse_group(group: typer.Typer) -> dict:
            tree = {}
            if commands := [
                cmd.name for cmd in group.registered_commands if not cmd.hidden
            ]:
                tree["commands"] = commands
            for group in group.registered_groups:
                if "groups" not in tree:
                    tree["groups"] = {}
                if not group.hidden:
                    if group_transversal := traverse_group(group.typer_instance):
                        tree["groups"][group.name] = group_transversal

            return tree

        groups_and_commands = traverse_group(self.app)
        root = Tree("[bold magenta]BTCLI Commands[/]")  # Root node
        build_rich_tree(groups_and_commands, root)
        return root

    def initialize_chain(
        self,
        network: Optional[list[str]] = None,
    ) -> SubtensorInterface:
        """
        Intelligently initializes a connection to the chain, depending on the supplied (or in config) values. Sets the
        `self.subtensor` object to this created connection.

        :param network: Network name (e.g. finney, test, etc.) or
                        chain endpoint (e.g. ws://127.0.0.1:9945, wss://entrypoint-finney.opentensor.ai:443)
        """
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                "You are instantiating the AsyncSubstrateInterface Websocket outside of an event loop. "
                "Verify this is intended.",
            )
            if not self.subtensor:
                if network:
                    network_ = None
                    for item in network:
                        if item.startswith("ws"):
                            network_ = item
                            break
                        else:
                            network_ = item

                    not_selected_networks = [net for net in network if net != network_]
                    if not_selected_networks:
                        console.print(
                            f"Networks not selected: [dark_orange]{', '.join(not_selected_networks)}[/dark_orange]"
                        )

                    self.subtensor = SubtensorInterface(network_)
                elif self.config["network"]:
                    self.subtensor = SubtensorInterface(self.config["network"])
                    console.print(
                        f"Using the specified network [{COLORS.G.LINKS}]{self.config['network']}"
                        f"[/{COLORS.G.LINKS}] from config"
                    )
                else:
                    self.subtensor = SubtensorInterface(defaults.subtensor.network)
        return self.subtensor

    def _run_command(self, cmd: Coroutine, exit_early: bool = True):
        """
        Runs the supplied coroutine with `asyncio.run`
        """

        async def _run():
            initiated = False
            try:
                if self.subtensor:
                    async with self.subtensor:
                        initiated = True
                        result = await cmd
                else:
                    initiated = True
                    result = await cmd
                return result
            except (ConnectionRefusedError, ssl.SSLError, InvalidHandshake):
                err_console.print(f"Unable to connect to the chain: {self.subtensor}")
                verbose_console.print(traceback.format_exc())
            except (
                ConnectionClosed,
                SubstrateRequestException,
                KeyboardInterrupt,
                RuntimeError,
            ) as e:
                if isinstance(e, SubstrateRequestException):
                    err_console.print(str(e))
                elif isinstance(e, RuntimeError):
                    pass  # Temporarily to handle loop bound issues
                verbose_console.print(traceback.format_exc())
            except Exception as e:
                err_console.print(f"An unknown error has occurred: {e}")
                verbose_console.print(traceback.format_exc())
            finally:
                if initiated is False:
                    asyncio.create_task(cmd).cancel()
                if (
                    exit_early is True
                ):  # temporarily to handle multiple run commands in one session
                    try:
                        raise typer.Exit()
                    except Exception as e:  # ensures we always exit cleanly
                        if not isinstance(e, (typer.Exit, RuntimeError)):
                            err_console.print(f"An unknown error has occurred: {e}")

        return self.asyncio_runner(_run())

    def main_callback(
        self,
        version: Annotated[
            Optional[bool],
            typer.Option(
                "--version", callback=version_callback, help="Show BTCLI version"
            ),
        ] = None,
        commands: Annotated[
            Optional[bool],
            typer.Option(
                "--commands", callback=commands_callback, help="Show BTCLI commands"
            ),
        ] = None,
    ):
        """
        Command line interface (CLI) for Bittensor. Uses the values in the configuration file. These values can be
            overriden by passing them explicitly in the command line.
        """
        # Load or create the config file
        if os.path.exists(self.config_path):
            with open(self.config_path, "r") as f:
                config = safe_load(f)
        else:
            directory_path = Path(self.config_base_path)
            directory_path.mkdir(exist_ok=True, parents=True)
            config = defaults.config.dictionary.copy()
            with open(self.config_path, "w") as f:
                safe_dump(config, f)

        # Update missing values
        updated = False
        for key, value in defaults.config.dictionary.items():
            if key not in config:
                config[key] = value
                updated = True
            elif isinstance(value, dict):
                for sub_key, sub_value in value.items():
                    if sub_key not in config[key]:
                        config[key][sub_key] = sub_value
                        updated = True
        if updated:
            with open(self.config_path, "w") as f:
                safe_dump(config, f)

        for k, v in config.items():
            if k in self.config.keys():
                self.config[k] = v

        if sys.version_info < (3, 10):
            # For Python 3.9 or lower
            self.asyncio_runner = asyncio.get_event_loop().run_until_complete
        else:
            try:
                uvloop = importlib.import_module("uvloop")
                if sys.version_info >= (3, 11):
                    self.asyncio_runner = uvloop.run
                else:
                    uvloop.install()
                    self.asyncio_runner = asyncio.run
            except ModuleNotFoundError:
                self.asyncio_runner = asyncio.run

    def verbosity_handler(
        self, quiet: bool, verbose: bool, json_output: bool = False
    ) -> None:
        if quiet and verbose:
            err_console.print("Cannot specify both `--quiet` and `--verbose`")
            raise typer.Exit()
        if json_output and verbose:
            verbosity_console_handler(3)
        elif json_output or quiet:
            verbosity_console_handler(0)
        elif verbose:
            verbosity_console_handler(2)
        else:
            # Default to configuration if no flags provided
            quiet = self.config.get("quiet", False)
            verbose = self.config.get("verbose", False)

            if quiet:
                verbosity_console_handler(0)
            elif verbose:
                verbosity_console_handler(2)
            else:
                # Default verbosity level
                verbosity_console_handler(1)

    def metagraph_config(
        self,
        reset: bool = typer.Option(
            False,
            "--reset",
            help="Restore the display of metagraph columns to show all columns.",
        ),
    ):
        """
        Command option to configure the display of the metagraph columns.
        """
        if reset:
            selections_ = defaults.config.dictionary["metagraph_cols"]
        else:
            selections_ = config_selector(
                self.config["metagraph_cols"], "Metagraph Display Columns"
            )
        self.config["metagraph_cols"] = selections_
        with open(self.config_path, "w+") as f:
            safe_dump(self.config, f)

    def set_config(
        self,
        wallet_name: Optional[str] = Options.wallet_name,
        wallet_path: Optional[str] = Options.wallet_path,
        wallet_hotkey: Optional[str] = Options.wallet_hotkey,
        network: Optional[str] = Options.network,
        use_cache: Optional[bool] = typer.Option(
            None,
            "--cache/--no-cache",
            "--cache/--no_cache",
            help="Disable caching of some commands. This will disable the `--reuse-last` and `--html` flags on "
            "commands such as `subnets metagraph`, `stake show` and `subnets list`.",
        ),
        rate_tolerance: Optional[float] = typer.Option(
            None,
            "--slippage",
            "--slippage-tolerance",
            "--tolerance",
            help="Set the rate tolerance percentage for transactions (e.g. 0.1 for 0.1%).",
        ),
        safe_staking: Optional[bool] = typer.Option(
            None,
            "--safe-staking/--no-safe-staking",
            "--safe/--unsafe",
            help="Enable or disable safe staking mode.",
            show_default=False,
        ),
        allow_partial_stake: Optional[bool] = typer.Option(
            None,
            "--allow-partial-stake/--no-allow-partial-stake",
            "--partial/--no-partial",
            "--allow/--not-allow",
            show_default=False,
        ),
        dashboard_path: Optional[str] = Options.dashboard_path,
    ):
        """
        Sets or updates configuration values in the BTCLI config file.

        This command allows you to set default values that will be used across all BTCLI commands.

        USAGE
        Interactive mode:
            [green]$[/green] btcli config set

        Set specific values:
            [green]$[/green] btcli config set --wallet-name default --network finney
            [green]$[/green] btcli config set --safe-staking --rate-tolerance 0.1

        [bold]NOTE[/bold]:
        - Network values can be network names (e.g., 'finney', 'test') or websocket URLs
        - Rate tolerance is specified as a decimal (e.g., 0.05 for 0.05%)
        - Changes are saved to ~/.bittensor/btcli.yaml
        - Use '[green]$[/green] btcli config get' to view current settings
        """
        args = {
            "wallet_name": wallet_name,
            "wallet_path": wallet_path,
            "wallet_hotkey": wallet_hotkey,
            "network": network,
            "use_cache": use_cache,
            "rate_tolerance": rate_tolerance,
            "safe_staking": safe_staking,
            "allow_partial_stake": allow_partial_stake,
            "dashboard_path": dashboard_path,
        }
        bools = ["use_cache", "safe_staking", "allow_partial_stake"]
        if all(v is None for v in args.values()):
            # Print existing configs
            self.get_config()

            # Create numbering to choose from
            config_keys = list(args.keys())
            console.print("Which config setting would you like to update?\n")
            for idx, key in enumerate(config_keys, start=1):
                console.print(f"{idx}. {key}")

            choice = IntPrompt.ask(
                "\nEnter the [bold]number[/bold] of the config setting you want to update",
                choices=[str(i) for i in range(1, len(config_keys) + 1)],
                show_choices=False,
            )
            arg = config_keys[choice - 1]

            if arg in bools:
                nc = Confirm.ask(
                    f"What value would you like to assign to [red]{arg}[/red]?",
                    default=True,
                )
                self.config[arg] = nc

            elif arg == "rate_tolerance":
                while True:
                    val = FloatPrompt.ask(
                        f"What percentage would you like to set for [red]{arg}[/red]?\n"
                        f"Values are percentages (e.g. 0.05 for 5%)",
                        default=0.05,
                    )
                    try:
                        validated_val = validate_rate_tolerance(val)
                        self.config[arg] = validated_val
                        break
                    except typer.BadParameter as e:
                        print_error(str(e))
                        continue
            else:
                val = Prompt.ask(
                    f"What value would you like to assign to [red]{arg}[/red]?"
                )
                args[arg] = val
                self.config[arg] = val

        if n := args.get("network"):
            if n in Constants.networks:
                if not Confirm.ask(
                    f"You provided a network [dark_orange]{n}[/dark_orange] which is mapped to "
                    f"[dark_orange]{Constants.network_map[n]}[/dark_orange]\n"
                    "Do you want to continue?"
                ):
                    typer.Exit()
            else:
                valid_endpoint, error = validate_chain_endpoint(n)
                if valid_endpoint:
                    if valid_endpoint in Constants.network_map.values():
                        known_network = next(
                            key
                            for key, value in Constants.network_map.items()
                            if value == network
                        )
                        args["network"] = known_network
                        if not Confirm.ask(
                            f"You provided an endpoint [dark_orange]{n}[/dark_orange] which is mapped to "
                            f"[dark_orange]{known_network}[/dark_orange]\n"
                            "Do you want to continue?"
                        ):
                            typer.Exit()
                    else:
                        if not Confirm.ask(
                            f"You provided a chain endpoint URL [dark_orange]{n}[/dark_orange]\n"
                            "Do you want to continue?"
                        ):
                            raise typer.Exit()
                else:
                    print_error(f"{error}")
                    raise typer.Exit()

        for arg, val in args.items():
            if val is not None:
                self.config[arg] = val
        with open(self.config_path, "w") as f:
            safe_dump(self.config, f)

        # Print latest configs after updating
        self.get_config()

    def del_config(
        self,
        wallet_name: bool = typer.Option(False, *Options.wallet_name.param_decls),
        wallet_path: bool = typer.Option(False, *Options.wallet_path.param_decls),
        wallet_hotkey: bool = typer.Option(False, *Options.wallet_hotkey.param_decls),
        network: bool = typer.Option(False, *Options.network.param_decls),
        use_cache: bool = typer.Option(False, "--cache"),
        rate_tolerance: bool = typer.Option(
            False, "--slippage", "--slippage-tolerance", "--tolerance"
        ),
        safe_staking: bool = typer.Option(
            False, "--safe-staking/--no-safe-staking", "--safe/--unsafe"
        ),
        allow_partial_stake: bool = typer.Option(
            False,
            "--allow-partial-stake/--no-allow-partial-stake",
            "--partial/--no-partial",
            "--allow/--not-allow",
        ),
        all_items: bool = typer.Option(False, "--all"),
        dashboard_path: Optional[str] = Options.dashboard_path,
    ):
        """
        Clears the fields in the config file and sets them to 'None'.

        # EXAMPLE

            - To clear the 'chain' and 'network' fields:

                [green]$[/green] btcli config clear --chain --network

            - To clear your config entirely:

                [green]$[/green] btcli config clear --all
        """
        if all_items:
            if Confirm.ask("Do you want to clear all configurations?"):
                self.config = {}
                print("All configurations have been cleared and set to 'None'.")
            else:
                print("Operation cancelled.")
                return

        args = {
            "wallet_name": wallet_name,
            "wallet_path": wallet_path,
            "wallet_hotkey": wallet_hotkey,
            "network": network,
            "use_cache": use_cache,
            "rate_tolerance": rate_tolerance,
            "safe_staking": safe_staking,
            "allow_partial_stake": allow_partial_stake,
            "dashboard_path": dashboard_path,
        }

        # If no specific argument is provided, iterate over all
        if not any(args.values()):
            for arg in args.keys():
                if self.config.get(arg) is not None:
                    if Confirm.ask(
                        f"Do you want to clear the [dark_orange]{arg}[/dark_orange] config?"
                    ):
                        self.config[arg] = None
                        console.print(
                            f"Cleared [dark_orange]{arg}[/dark_orange] config and set to 'None'."
                        )
                    else:
                        console.print(
                            f"Skipped clearing [dark_orange]{arg}[/dark_orange] config."
                        )

        else:
            # Check each specified argument
            for arg, should_clear in args.items():
                if should_clear:
                    if self.config.get(arg) is not None:
                        if Confirm.ask(
                            f"Do you want to clear the [dark_orange]{arg}[/dark_orange] [bold cyan]({self.config.get(arg)})[/bold cyan] config?"
                        ):
                            self.config[arg] = None
                            console.print(
                                f"Cleared [dark_orange]{arg}[/dark_orange] config and set to 'None'."
                            )
                        else:
                            console.print(
                                f"Skipped clearing [dark_orange]{arg}[/dark_orange] config."
                            )
                    else:
                        console.print(
                            f"No config set for [dark_orange]{arg}[/dark_orange]. Use `btcli config set` to set it."
                        )
        with open(self.config_path, "w") as f:
            safe_dump(self.config, f)

    def get_config(self):
        """
        Prints the current config file in a table.
        """
        deprecated_configs = ["chain"]

        table = Table(
            Column("[bold white]Name", style="dark_orange"),
            Column("[bold white]Value", style="gold1"),
            Column("", style="medium_purple"),
            box=box.SIMPLE_HEAD,
        )

        for key, value in self.config.items():
            if key == "network":
                if value is None:
                    value = "None (default = finney)"
                else:
                    if value in Constants.networks:
                        value = value + f" ({Constants.network_map[value]})"
            if key == "rate_tolerance":
                value = f"{value} ({value * 100}%)" if value is not None else "None"

            elif key in deprecated_configs:
                continue

            if isinstance(value, dict):
                # Nested dictionaries: only metagraph for now, but more may be added later
                for idx, (sub_key, sub_value) in enumerate(value.items()):
                    table.add_row(key if idx == 0 else "", str(sub_key), str(sub_value))
            else:
                table.add_row(str(key), str(value), "")

        console.print(table)

    def ask_rate_tolerance(
        self,
        rate_tolerance: Optional[float],
    ) -> float:
        """
        Gets rate tolerance from args, config, or default.

        Args:
            rate_tolerance (Optional[float]): Explicitly provided slippage value

        Returns:
            float: rate tolerance value
        """
        if rate_tolerance is not None:
            console.print(
                f"[dim][blue]Rate tolerance[/blue]: [bold cyan]{rate_tolerance} ({rate_tolerance * 100}%)[/bold cyan]."
            )
            return rate_tolerance
        elif self.config.get("rate_tolerance") is not None:
            config_slippage = self.config["rate_tolerance"]
            console.print(
                f"[dim][blue]Rate tolerance[/blue]: [bold cyan]{config_slippage} ({config_slippage * 100}%)[/bold cyan] (from config)."
            )
            return config_slippage
        else:
            console.print(
                "[dim][blue]Rate tolerance[/blue]: "
                + f"[bold cyan]{defaults.rate_tolerance} ({defaults.rate_tolerance * 100}%)[/bold cyan] "
                + "by default. Set this using "
                + "[dark_sea_green3 italic]`btcli config set`[/dark_sea_green3 italic] "
                + "or "
                + "[dark_sea_green3 italic]`--tolerance`[/dark_sea_green3 italic] flag[/dim]"
            )
            return defaults.rate_tolerance

    def ask_safe_staking(
        self,
        safe_staking: Optional[bool],
    ) -> bool:
        """
        Gets safe staking setting from args, config, or default.

        Args:
            safe_staking (Optional[bool]): Explicitly provided safe staking value

        Returns:
            bool: Safe staking setting
        """
        if safe_staking is not None:
            console.print(
                f"[dim][blue]Safe staking[/blue]: [bold cyan]{'enabled' if safe_staking else 'disabled'}[/bold cyan]."
            )
            return safe_staking
        elif self.config.get("safe_staking") is not None:
            safe_staking = self.config["safe_staking"]
            console.print(
                f"[dim][blue]Safe staking[/blue]: [bold cyan]{'enabled' if safe_staking else 'disabled'}[/bold cyan] (from config)."
            )
            return safe_staking
        else:
            safe_staking = True
            console.print(
                "[dim][blue]Safe staking[/blue]: "
                + f"[bold cyan]{'enabled' if safe_staking else 'disabled'}[/bold cyan] "
                + "by default. Set this using "
                + "[dark_sea_green3 italic]`btcli config set`[/dark_sea_green3 italic] "
                + "or "
                + "[dark_sea_green3 italic]`--safe/--unsafe`[/dark_sea_green3 italic] flag[/dim]"
            )
            return safe_staking

    def ask_partial_stake(
        self,
        allow_partial_stake: Optional[bool],
    ) -> bool:
        """
        Gets partial stake setting from args, config, or default.

        Args:
            allow_partial_stake (Optional[bool]): Explicitly provided partial stake value

        Returns:
            bool: Partial stake setting
        """
        if allow_partial_stake is not None:
            console.print(
                f"[dim][blue]Partial staking[/blue]: [bold cyan]{'enabled' if allow_partial_stake else 'disabled'}[/bold cyan]."
            )
            return allow_partial_stake
        elif self.config.get("allow_partial_stake") is not None:
            config_partial = self.config["allow_partial_stake"]
            console.print(
                f"[dim][blue]Partial staking[/blue]: [bold cyan]{'enabled' if config_partial else 'disabled'}[/bold cyan] (from config)."
            )
            return config_partial
        else:
            console.print(
                "[dim][blue]Partial staking[/blue]: "
                + f"[bold cyan]{'enabled' if allow_partial_stake else 'disabled'}[/bold cyan] "
                + "by default. Set this using "
                + "[dark_sea_green3 italic]`btcli config set`[/dark_sea_green3 italic] "
                + "or "
                + "[dark_sea_green3 italic]`--partial/--no-partial`[/dark_sea_green3 italic] flag[/dim]"
            )
            return False

    def wallet_ask(
        self,
        wallet_name: Optional[str],
        wallet_path: Optional[str],
        wallet_hotkey: Optional[str],
        ask_for: Optional[list[str]] = None,
        validate: WV = WV.WALLET,
        return_wallet_and_hotkey: bool = False,
    ) -> Union[Wallet, tuple[Wallet, str]]:
        """
        Generates a wallet object based on supplied values, validating the wallet is valid if flag is set
        :param wallet_name: name of the wallet
        :param wallet_path: root path of the wallets
        :param wallet_hotkey: name of the wallet hotkey file
        :param validate: flag whether to check for the wallet's validity
        :param ask_for: aspect of the wallet (name, path, hotkey) to prompt the user for
        :param return_wallet_and_hotkey: if specified, will return both the wallet object, and the hotkey SS58
        :return: created Wallet object (or wallet, hotkey ss58)
        """
        ask_for = ask_for or []
        # Prompt for missing attributes specified in ask_for
        if WO.NAME in ask_for and not wallet_name:
            if self.config.get("wallet_name"):
                wallet_name = self.config.get("wallet_name")
                console.print(
                    f"Using the [blue]wallet name[/blue] from config:[bold cyan] {wallet_name}"
                )
            else:
                wallet_name = Prompt.ask(
                    "Enter the [blue]wallet name[/blue]"
                    + f" [{COLORS.G.HINT} italic](Hint: You can set this with `btcli config set --wallet-name`)",
                    default=defaults.wallet.name,
                )

        if WO.HOTKEY in ask_for and not wallet_hotkey:
            if self.config.get("wallet_hotkey"):
                wallet_hotkey = self.config.get("wallet_hotkey")
                console.print(
                    f"Using the [blue]wallet hotkey[/blue] from config:[bold cyan] {wallet_hotkey}"
                )
            else:
                wallet_hotkey = Prompt.ask(
                    "Enter the [blue]wallet hotkey[/blue][dark_sea_green3 italic]"
                    "(Hint: You can set this with `btcli config set --wallet-hotkey`)"
                    "[/dark_sea_green3 italic]",
                    default=defaults.wallet.hotkey,
                )
        if wallet_path:
            if wallet_path == "default":
                wallet_path = defaults.wallet.path

        elif self.config.get("wallet_path"):
            wallet_path = self.config.get("wallet_path")
            console.print(
                f"Using the [blue]wallet path[/blue] from config:[bold magenta] {wallet_path}"
            )
        else:
            wallet_path = defaults.wallet.path

        if WO.PATH in ask_for and not wallet_path:
            wallet_path = Prompt.ask(
                "Enter the [blue]wallet path[/blue]"
                "[dark_sea_green3 italic](Hint: You can set this with `btcli config set --wallet-path`)"
                "[/dark_sea_green3 italic]",
                default=defaults.wallet.path,
            )
        # Create the Wallet object
        if wallet_path:
            wallet_path = os.path.expanduser(wallet_path)
        wallet = Wallet(name=wallet_name, path=wallet_path, hotkey=wallet_hotkey)

        # Validate the wallet if required
        if validate == WV.WALLET or validate == WV.WALLET_AND_HOTKEY:
            valid = utils.is_valid_wallet(wallet)
            if not valid[0]:
                utils.err_console.print(
                    f"[red]Error: Wallet does not not exist. \n"
                    f"Please verify your wallet information: {wallet}[/red]"
                )
                raise typer.Exit()

            if validate == WV.WALLET_AND_HOTKEY and not valid[1]:
                utils.err_console.print(
                    f"[red]Error: Wallet '{wallet.name}' exists but the hotkey '{wallet.hotkey_str}' does not. \n"
                    f"Please verify your wallet information: {wallet}[/red]"
                )
                raise typer.Exit()
        if return_wallet_and_hotkey:
            valid = utils.is_valid_wallet(wallet)
            if valid[1]:
                return wallet, wallet.hotkey.ss58_address
            else:
                if wallet_hotkey and is_valid_ss58_address(wallet_hotkey):
                    return wallet, wallet_hotkey
                else:
                    hotkey = (
                        Prompt.ask(
                            "Enter the SS58 of the hotkey to use for this transaction."
                        )
                    ).strip()
                    if not is_valid_ss58_address(hotkey):
                        err_console.print(
                            f"[red]Error: {hotkey} is not valid SS58 address."
                        )
                        raise typer.Exit(1)
                    else:
                        return wallet, hotkey
        else:
            return wallet

    def wallet_list(
        self,
        wallet_path: str = Options.wallet_path,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
        json_output: bool = Options.json_output,
    ):
        """
        Displays all the wallets and their corresponding hotkeys that are located in the wallet path specified in the config.

        The output display shows each wallet and its associated `ss58` addresses for the coldkey public key and any hotkeys. The output is presented in a hierarchical tree format, with each wallet as a root node and any associated hotkeys as child nodes. The `ss58` address (or an `<ENCRYPTED>` marker, for encrypted hotkeys) is displayed for each coldkey and hotkey that exists on the device.

        Upon invocation, the command scans the wallet directory and prints a list of all the wallets, indicating whether the
        public keys are available (`?` denotes unavailable or encrypted keys).

        # EXAMPLE

        [green]$[/green] btcli wallet list --path ~/.bittensor

        [bold]NOTE[/bold]: This command is read-only and does not modify the filesystem or the blockchain state. It is intended for use with the Bittensor CLI to provide a quick overview of the user's wallets.
        """
        self.verbosity_handler(quiet, verbose, json_output)
        wallet = self.wallet_ask(
            None, wallet_path, None, ask_for=[WO.PATH], validate=WV.NONE
        )
        return self._run_command(wallets.wallet_list(wallet.path, json_output))

    def wallet_overview(
        self,
        wallet_name: Optional[str] = Options.wallet_name,
        wallet_path: Optional[str] = Options.wallet_path,
        wallet_hotkey: Optional[str] = Options.wallet_hotkey,
        all_wallets: bool = typer.Option(
            False, "--all", "-a", help="See an overview for all the wallets"
        ),
        sort_by: Optional[str] = typer.Option(
            None,
            "--sort-by",
            "--sort_by",
            help="Sort the hotkeys by the specified column title. For example: name, uid, axon.",
        ),
        sort_order: Optional[str] = typer.Option(
            None,
            "--sort-order",
            "--sort_order",
            help="Sort the hotkeys in the specified order (ascending/asc or descending/desc/reverse).",
        ),
        include_hotkeys: str = typer.Option(
            "",
            "--include-hotkeys",
            "-in",
            help="Hotkeys to include. Specify by name or ss58 address. "
            "If left empty, all hotkeys, except those in the '--exclude-hotkeys', will be included.",
        ),
        exclude_hotkeys: str = typer.Option(
            "",
            "--exclude-hotkeys",
            "-ex",
            help="Hotkeys to exclude. Specify by name or ss58 address. "
            "If left empty, all hotkeys, except those in the '--include-hotkeys', will be excluded.",
        ),
        netuids: str = Options.netuids,
        network: Optional[list[str]] = Options.network,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
        json_output: bool = Options.json_output,
    ):
        """
        Displays a detailed overview of the user's registered accounts on the Bittensor network.

        This command compiles and displays comprehensive information about each neuron associated with the user's wallets, including both hotkeys and coldkeys. It is especially useful for users managing multiple accounts or looking for a summary of their network activities and stake distributions.

        USAGE

        [green]$[/green] btcli wallet overview

        [green]$[/green] btcli wallet overview --all

        [bold]NOTE[/bold]: This command is read-only and does not modify the blockchain state or account configuration.
        It provides a quick and comprehensive view of the user's network presence, making it useful for monitoring account status,
        stake distribution, and overall contribution to the Bittensor network.
        """
        self.verbosity_handler(quiet, verbose, json_output)
        if include_hotkeys and exclude_hotkeys:
            utils.err_console.print(
                "[red]You have specified both the inclusion and exclusion options. Only one of these options is allowed currently."
            )
            raise typer.Exit()

        if netuids:
            netuids = parse_to_list(
                netuids,
                int,
                "Netuids must be a comma-separated list of ints, e.g., `--netuids 1,2,3,4`.",
            )

        ask_for = [WO.NAME] if not all_wallets else []
        validate = WV.WALLET if not all_wallets else WV.NONE
        wallet = self.wallet_ask(
            wallet_name, wallet_path, wallet_hotkey, ask_for=ask_for, validate=validate
        )

        if include_hotkeys:
            include_hotkeys = parse_to_list(
                include_hotkeys,
                str,
                "Hotkey names must be a comma-separated list, e.g., `--include-hotkeys hk1,hk2`.",
            )

        if exclude_hotkeys:
            exclude_hotkeys = parse_to_list(
                exclude_hotkeys,
                str,
                "Hotkeys names must be a comma-separated list, e.g., `--exclude-hotkeys hk1,hk2`.",
            )

        return self._run_command(
            wallets.overview(
                wallet,
                self.initialize_chain(network),
                all_wallets,
                sort_by,
                sort_order,
                include_hotkeys,
                exclude_hotkeys,
                netuids_filter=netuids,
                verbose=verbose,
                json_output=json_output,
            )
        )

    def wallet_transfer(
        self,
        destination_ss58_address: str = typer.Option(
            None,
            "--destination",
            "--dest",
            "-d",
            prompt="Enter the destination coldkey ss58 address",
            help="Destination address (ss58) of the wallet (coldkey).",
        ),
        amount: float = typer.Option(
            None,
            "--amount",
            "-a",
            help="Amount (in TAO) to transfer.",
        ),
        transfer_all: bool = typer.Option(
            False, "--all", prompt=False, help="Transfer all available balance."
        ),
        period: int = Options.period,
        wallet_name: str = Options.wallet_name,
        wallet_path: str = Options.wallet_path,
        wallet_hotkey: str = Options.wallet_hotkey,
        network: Optional[list[str]] = Options.network,
        prompt: bool = Options.prompt,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
        json_output: bool = Options.json_output,
    ):
        """
        Send TAO tokens from one wallet to another wallet on the Bittensor network.

        This command is used for transactions between different wallet accounts, enabling users to send tokens to other
        participants on the network. The command displays the user's current balance before prompting for the amount
        to transfer (send), ensuring transparency and accuracy in the transaction.

        USAGE

        The command requires that you specify the destination address (public key) and the amount of TAO you want transferred.
        It checks if sufficient balance exists in your wallet and prompts for confirmation before proceeding with the transaction.

        EXAMPLE

        [green]$[/green] btcli wallet transfer --dest 5Dp8... --amount 100

        [bold]NOTE[/bold]: This command is used for executing token transfers within the Bittensor network. Users should verify the destination address and the TAO amount before confirming the transaction to avoid errors or loss of funds.
        """
        if not is_valid_ss58_address(destination_ss58_address):
            print_error("You have entered an incorrect ss58 address. Please try again.")
            raise typer.Exit()

        self.verbosity_handler(quiet, verbose, json_output)
        wallet = self.wallet_ask(
            wallet_name,
            wallet_path,
            wallet_hotkey,
            ask_for=[WO.NAME],
            validate=WV.WALLET,
        )
        subtensor = self.initialize_chain(network)
        if transfer_all and amount:
            print_error("Cannot specify an amount and '--all' flag.")
            raise typer.Exit()
        elif transfer_all:
            amount = 0
        elif not amount:
            amount = FloatPrompt.ask("Enter amount (in TAO) to transfer.")
        return self._run_command(
            wallets.transfer(
                wallet=wallet,
                subtensor=subtensor,
                destination=destination_ss58_address,
                amount=amount,
                transfer_all=transfer_all,
                era=period,
                prompt=prompt,
                json_output=json_output,
            )
        )

    def wallet_swap_hotkey(
        self,
        wallet_name: Optional[str] = Options.wallet_name,
        wallet_path: Optional[str] = Options.wallet_path,
        wallet_hotkey: Optional[str] = Options.wallet_hotkey,
        netuid: Optional[int] = Options.netuid_not_req,
        all_netuids: bool = Options.all_netuids,
        network: Optional[list[str]] = Options.network,
        destination_hotkey_name: Optional[str] = typer.Argument(
            None, help="Destination hotkey name."
        ),
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
        prompt: bool = Options.prompt,
        json_output: bool = Options.json_output,
    ):
        """
        Swap hotkeys of a given wallet on the blockchain. For a registered key pair, for example, a (coldkeyA, hotkeyA) pair, this command swaps the hotkeyA with a new, unregistered, hotkeyB to move the original registration to the (coldkeyA, hotkeyB) pair.

        USAGE

        The command is used to swap the hotkey of a wallet for another hotkey on that same wallet.

        IMPORTANT

        - Make sure that your original key pair (coldkeyA, hotkeyA) is already registered.
        - Make sure that you use a newly created hotkeyB in this command. A hotkeyB that is already registered cannot be used in this command.
        - You can specify the netuid for which you want to swap the hotkey for. If it is not defined, the swap will be initiated for all subnets.
        - Finally, note that this command requires a fee of 1 TAO for recycling and this fee is taken from your wallet (coldkeyA).

        EXAMPLE

        [green]$[/green] btcli wallet swap_hotkey destination_hotkey_name --wallet-name your_wallet_name --wallet-hotkey original_hotkey --netuid 1
        """
        netuid = get_optional_netuid(netuid, all_netuids)
        self.verbosity_handler(quiet, verbose, json_output)
        original_wallet = self.wallet_ask(
            wallet_name,
            wallet_path,
            wallet_hotkey,
            ask_for=[WO.NAME, WO.PATH, WO.HOTKEY],
            validate=WV.WALLET_AND_HOTKEY,
        )
        if not destination_hotkey_name:
            destination_hotkey_name = typer.prompt(
                "Enter the destination hotkey name (within same wallet)"
            )

        new_wallet = self.wallet_ask(
            wallet_name,
            wallet_path,
            destination_hotkey_name,
            ask_for=[WO.NAME, WO.PATH, WO.HOTKEY],
            validate=WV.WALLET_AND_HOTKEY,
        )
        self.initialize_chain(network)
        return self._run_command(
            wallets.swap_hotkey(
                original_wallet, new_wallet, self.subtensor, netuid, prompt, json_output
            )
        )

    def wallet_inspect(
        self,
        all_wallets: bool = typer.Option(
            False,
            "--all",
            "--all-wallets",
            "-a",
            help="Inspect all the wallets at the specified wallet path.",
        ),
        wallet_name: str = Options.wallet_name,
        wallet_path: str = Options.wallet_path,
        wallet_hotkey: str = Options.wallet_hotkey,
        network: Optional[list[str]] = Options.network,
        netuids: str = Options.netuids,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
        json_output: bool = Options.json_output,
    ):
        """
        Displays the details of the user's wallet pairs (coldkey, hotkey) on the Bittensor network.

        The output is presented as a table with the below columns:

        - [blue bold]Coldkey[/blue bold]: The coldkey associated with the user's wallet.

        - [blue bold]Balance[/blue bold]: The balance of the coldkey.

        - [blue bold]Delegate[/blue bold]: The name of the delegate to which the coldkey has staked TAO.

        - [blue bold]Stake[/blue bold]: The amount of stake held by both the coldkey and hotkey.

        - [blue bold]Emission[/blue bold]: The emission or rewards earned from staking.

        - [blue bold]Netuid[/blue bold]: The network unique identifier of the subnet where the hotkey is active (i.e., validating).

        - [blue bold]Hotkey[/blue bold]: The hotkey associated with the neuron on the network.

        USAGE

        This command can be used to inspect a single wallet or all the wallets located at a specified path. It is useful for a comprehensive overview of a user's participation and performance in the Bittensor network.

        EXAMPLE

        [green]$[/green] btcli wallet inspect

        [green]$[/green] btcli wallet inspect --all -n 1 -n 2 -n 3

        [bold]Note[/bold]: The `inspect` command is for displaying information only and does not perform any transactions or state changes on the blockchain. It is intended to be used with Bittensor CLI and not as a standalone function in user code.
        """
        print_error("This command is disabled on the 'rao' network.")
        raise typer.Exit()
        self.verbosity_handler(quiet, verbose, json_output)

        if netuids:
            netuids = parse_to_list(
                netuids,
                int,
                "Netuids must be a comma-separated list of ints, e.g., `--netuids 1,2,3,4`.",
            )

        # if all-wallets is entered, ask for path
        ask_for = [WO.NAME, WO.PATH] if not all_wallets else [WO.PATH]
        validate = WV.WALLET if not all_wallets else WV.NONE
        wallet = self.wallet_ask(
            wallet_name, wallet_path, wallet_hotkey, ask_for=ask_for, validate=validate
        )

        self.initialize_chain(network)
        return self._run_command(
            wallets.inspect(
                wallet,
                self.subtensor,
                netuids_filter=netuids,
                all_wallets=all_wallets,
            )
        )

    def wallet_faucet(
        self,
        wallet_name: Optional[str] = Options.wallet_name,
        wallet_path: Optional[str] = Options.wallet_path,
        wallet_hotkey: Optional[str] = Options.wallet_hotkey,
        network: Optional[list[str]] = Options.network,
        # TODO add the following to config
        processors: Optional[int] = typer.Option(
            defaults.pow_register.num_processes,
            "--processors",
            help="Number of processors to use for proof of work (POW) registration.",
        ),
        update_interval: Optional[int] = typer.Option(
            defaults.pow_register.update_interval,
            "--update-interval",
            "-u",
            help="The number of nonces to process before checking for next block during registration",
        ),
        output_in_place: Optional[bool] = typer.Option(
            defaults.pow_register.output_in_place,
            help="Whether to output the registration statistics in-place.",
        ),
        verbose: Optional[bool] = typer.Option(  # TODO verbosity handler
            defaults.pow_register.verbose,
            "--verbose",
            "-v",
            help="Whether to output the registration statistics verbosely.",
        ),
        use_cuda: Optional[bool] = typer.Option(
            defaults.pow_register.cuda.use_cuda,
            "--use-cuda/--no-use-cuda",
            "--cuda/--no-cuda",
            help="Set flag to use CUDA for proof of work (POW) registration.",
        ),
        dev_id: Optional[int] = typer.Option(
            defaults.pow_register.cuda.dev_id,
            "--dev-id",
            "-d",
            help="Set the CUDA device id(s) in the order of speed, where 0 is the fastest.",
        ),
        threads_per_block: Optional[int] = typer.Option(
            defaults.pow_register.cuda.tpb,
            "--threads-per-block",
            "-tbp",
            help="Set the number of threads per block for CUDA.",
        ),
        max_successes: Optional[int] = typer.Option(
            3,
            "--max-successes",
            help="Set the maximum number of times to successfully run the faucet for this command.",
        ),
        prompt: bool = Options.prompt,
    ):
        """
        Obtain test TAO tokens by performing Proof of Work (PoW).

        This command is useful for users who need test tokens for operations on a local blockchain.

        [blue bold]IMPORTANT[/blue bold]: THIS COMMAND IS DISABLED ON FINNEY AND TESTNET.

        USAGE

        The command uses the proof-of-work (POW) mechanism to validate the user's effort and rewards them with test TAO tokens. It is
        typically used in local blockchain environments where transactions do not use real TAO tokens.

        EXAMPLE

        [green]$[/green] btcli wallet faucet --faucet.num_processes 4 --faucet.cuda.use_cuda

        [bold]Note[/bold]: This command is meant for used in local environments where users can experiment with the blockchain without using real TAO tokens. Users must have the necessary hardware setup, especially when opting for CUDA-based GPU calculations. It is currently disabled on testnet and mainnet (finney). You can only use this command on a local blockchain.
        """
        # TODO should we add json_output?
        wallet = self.wallet_ask(
            wallet_name,
            wallet_path,
            wallet_hotkey,
            ask_for=[WO.NAME, WO.PATH],
            validate=WV.WALLET,
        )
        return self._run_command(
            wallets.faucet(
                wallet,
                self.initialize_chain(network),
                threads_per_block,
                update_interval,
                processors,
                use_cuda,
                dev_id,
                output_in_place,
                verbose,
                max_successes,
                prompt,
            )
        )

    def wallet_regen_coldkey(
        self,
        wallet_name: Optional[str] = Options.wallet_name,
        wallet_path: Optional[str] = Options.wallet_path,
        wallet_hotkey: Optional[str] = Options.wallet_hotkey,
        mnemonic: Optional[str] = Options.mnemonic,
        seed: Optional[str] = Options.seed,
        json_path: Optional[str] = Options.json,
        json_password: Optional[str] = Options.json_password,
        use_password: Optional[bool] = Options.use_password,
        overwrite: bool = Options.overwrite,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
        json_output: bool = Options.json_output,
    ):
        """
        Regenerate a coldkey for a wallet on the Bittensor blockchain network.

        This command is used to create a new coldkey from an existing mnemonic, seed, or JSON file.

        USAGE

        Users can specify a mnemonic, a seed string, or a JSON file path to regenerate a coldkey. The command supports optional password protection for the generated key.

        EXAMPLE

        [green]$[/green] btcli wallet regen-coldkey --mnemonic "word1 word2 ... word12"


        [bold]Note[/bold]: This command is critical for users who need to regenerate their coldkey either for recovery or for security reasons.
        """
        self.verbosity_handler(quiet, verbose, json_output)

        if not wallet_path:
            wallet_path = Prompt.ask(
                "Enter the path for the wallets directory", default=defaults.wallet.path
            )
            wallet_path = os.path.expanduser(wallet_path)

        if not wallet_name:
            wallet_name = Prompt.ask(
                f"Enter the name of the [{COLORS.G.CK}]new wallet (coldkey)",
                default=defaults.wallet.name,
            )

        wallet = Wallet(wallet_name, wallet_hotkey, wallet_path)

        mnemonic, seed, json_path, json_password = get_creation_data(
            mnemonic, seed, json_path, json_password
        )
        return self._run_command(
            wallets.regen_coldkey(
                wallet,
                mnemonic,
                seed,
                json_path,
                json_password,
                use_password,
                overwrite,
                json_output,
            )
        )

    def wallet_regen_coldkey_pub(
        self,
        wallet_name: Optional[str] = Options.wallet_name,
        wallet_path: Optional[str] = Options.wallet_path,
        wallet_hotkey: Optional[str] = Options.wallet_hotkey,
        public_key_hex: Optional[str] = Options.public_hex_key,
        ss58_address: Optional[str] = Options.ss58_address,
        overwrite: bool = Options.overwrite,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
        json_output: bool = Options.json_output,
    ):
        """
        Regenerates the public part of a coldkey (coldkeypub.txt) for a wallet.

        Use this command when you need to move machine for subnet mining. Use the public key or SS58 address from your coldkeypub.txt that you have on another machine to regenerate the coldkeypub.txt on this new machine.

        USAGE

        The command requires either a public key in hexadecimal format or an ``SS58`` address from the existing coldkeypub.txt from old machine to regenerate the coldkeypub on the new machine.

        EXAMPLE

        [green]$[/green] btcli wallet regen_coldkeypub --ss58_address 5DkQ4...

        [bold]Note[/bold]: This command is particularly useful for users who need to regenerate their coldkeypub, perhaps due to file corruption or loss. You will need either ss58 address or public hex key from your old coldkeypub.txt for the wallet. It is a recovery-focused utility that ensures continued access to your wallet functionalities.
        """
        self.verbosity_handler(quiet, verbose, json_output)

        if not wallet_path:
            wallet_path = Prompt.ask(
                "Enter the path to the wallets directory", default=defaults.wallet.path
            )
            wallet_path = os.path.expanduser(wallet_path)

        if not wallet_name:
            wallet_name = Prompt.ask(
                f"Enter the name of the [{COLORS.G.CK}]new wallet (coldkey)",
                default=defaults.wallet.name,
            )
        wallet = Wallet(wallet_name, wallet_hotkey, wallet_path)

        if not ss58_address and not public_key_hex:
            prompt_answer = typer.prompt(
                "Enter the ss58_address or the public key in hex"
            )
            if prompt_answer.startswith("0x"):
                public_key_hex = prompt_answer
            else:
                ss58_address = prompt_answer
        if not utils.is_valid_bittensor_address_or_public_key(
            address=ss58_address if ss58_address else public_key_hex
        ):
            rich.print("[red]Error: Invalid SS58 address or public key![/red]")
            raise typer.Exit()
        return self._run_command(
            wallets.regen_coldkey_pub(
                wallet, ss58_address, public_key_hex, overwrite, json_output
            )
        )

    def wallet_regen_hotkey(
        self,
        wallet_name: Optional[str] = Options.wallet_name,
        wallet_path: Optional[str] = Options.wallet_path,
        wallet_hotkey: Optional[str] = Options.wallet_hotkey,
        mnemonic: Optional[str] = Options.mnemonic,
        seed: Optional[str] = Options.seed,
        json_path: Optional[str] = Options.json,
        json_password: Optional[str] = Options.json_password,
        use_password: bool = typer.Option(
            False,  # Overriden to False
            help="Set to 'True' to protect the generated Bittensor key with a password.",
        ),
        overwrite: bool = Options.overwrite,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
        json_output: bool = Options.json_output,
    ):
        """
        Regenerates a hotkey for a wallet.

        Similar to regenerating a coldkey, this command creates a new hotkey from a mnemonic, seed, or JSON file.

        USAGE

        Users can provide a mnemonic, seed string, or a JSON file to regenerate the hotkey. The command supports optional password protection and can overwrite an existing hotkey.

        # Example usage:

        [green]$[/green] btcli wallet regen_hotkey --seed 0x1234...
        [green]$[/green] btcli wallet regen-hotkey --mnemonic "word1 word2 ... word12"

        [bold]Note[/bold]: This command is essential for users who need to regenerate their hotkey, possibly for security upgrades or key recovery.
        It should be used with caution to avoid accidental overwriting of existing keys.
        """
        self.verbosity_handler(quiet, verbose, json_output)
        wallet = self.wallet_ask(
            wallet_name,
            wallet_path,
            wallet_hotkey,
            ask_for=[WO.NAME, WO.PATH, WO.HOTKEY],
            validate=WV.WALLET,
        )
        mnemonic, seed, json_path, json_password = get_creation_data(
            mnemonic, seed, json_path, json_password
        )
        return self._run_command(
            wallets.regen_hotkey(
                wallet,
                mnemonic,
                seed,
                json_path,
                json_password,
                use_password,
                overwrite,
                json_output,
            )
        )

    def wallet_new_hotkey(
        self,
        wallet_name: Optional[str] = Options.wallet_name,
        wallet_path: Optional[str] = Options.wallet_path,
        wallet_hotkey: Optional[str] = Options.wallet_hotkey,
        n_words: Optional[int] = typer.Option(
            None,
            "--n-words",
            "--n_words",
            help="The number of words used in the mnemonic. Options: [12, 15, 18, 21, 24]",
        ),
        use_password: bool = typer.Option(
            False,  # Overriden to False
            help="Set to 'True' to protect the generated Bittensor key with a password.",
        ),
        uri: Optional[str] = Options.uri,
        overwrite: bool = Options.overwrite,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
        json_output: bool = Options.json_output,
    ):
        """
        Create a new hotkey for a wallet.

        USAGE

        This command is used to generate a new hotkey for managing a neuron or participating in a subnet. It provides options for the mnemonic word count, and supports password protection. It also allows overwriting the
        existing hotkey.

        EXAMPLE

        [green]$[/green] btcli wallet new-hotkey --n_words 24

        [italic]Note[/italic]: This command is useful to create additional hotkeys for different purposes, such as running multiple subnet miners or subnet validators or separating operational roles within the Bittensor network.
        """
        self.verbosity_handler(quiet, verbose, json_output)

        if not wallet_name:
            wallet_name = Prompt.ask(
                f"Enter the [{COLORS.G.CK}]wallet name",
                default=defaults.wallet.name,
            )

        if not wallet_hotkey:
            wallet_hotkey = Prompt.ask(
                f"Enter the name of the [{COLORS.G.HK}]new hotkey",
                default=defaults.wallet.hotkey,
            )

        wallet = self.wallet_ask(
            wallet_name,
            wallet_path,
            wallet_hotkey,
            ask_for=[WO.NAME, WO.PATH, WO.HOTKEY],
            validate=WV.WALLET,
        )
        if not uri:
            n_words = get_n_words(n_words)
        return self._run_command(
            wallets.new_hotkey(
                wallet, n_words, use_password, uri, overwrite, json_output
            )
        )

    def wallet_associate_hotkey(
        self,
        wallet_name: Optional[str] = Options.wallet_name,
        wallet_path: Optional[str] = Options.wallet_path,
        wallet_hotkey: Optional[str] = Options.wallet_hotkey_ss58,
        network: Optional[list[str]] = Options.network,
        prompt: bool = Options.prompt,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
    ):
        """
        Associate a hotkey with a wallet(coldkey).

        USAGE

        This command is used to associate a hotkey with a wallet(coldkey).

        EXAMPLE

        [green]$[/green] btcli wallet associate-hotkey --hotkey-name hotkey_name
        [green]$[/green] btcli wallet associate-hotkey --hotkey-ss58 5DkQ4...
        """
        self.verbosity_handler(quiet, verbose)
        if not wallet_name:
            wallet_name = Prompt.ask(
                "Enter the [blue]wallet name[/blue] [dim](which you want to associate with the hotkey)[/dim]",
                default=self.config.get("wallet_name") or defaults.wallet.name,
            )
        if not wallet_hotkey:
            wallet_hotkey = Prompt.ask(
                "Enter the [blue]hotkey[/blue] name or "
                "[blue]hotkey ss58 address[/blue] [dim](to associate with your coldkey)[/dim]"
            )

        hotkey_display = None
        if is_valid_ss58_address(wallet_hotkey):
            hotkey_ss58 = wallet_hotkey
            wallet = self.wallet_ask(
                wallet_name,
                wallet_path,
                None,
                ask_for=[WO.NAME, WO.PATH],
                validate=WV.WALLET,
            )
            hotkey_display = (
                f"hotkey [{COLORS.GENERAL.HK}]{hotkey_ss58}[/{COLORS.GENERAL.HK}]"
            )
        else:
            wallet = self.wallet_ask(
                wallet_name,
                wallet_path,
                wallet_hotkey,
                ask_for=[WO.NAME, WO.PATH, WO.HOTKEY],
                validate=WV.WALLET_AND_HOTKEY,
            )
            hotkey_ss58 = wallet.hotkey.ss58_address
            hotkey_display = f"hotkey [blue]{wallet_hotkey}[/blue] [{COLORS.GENERAL.HK}]({hotkey_ss58})[/{COLORS.GENERAL.HK}]"

        return self._run_command(
            wallets.associate_hotkey(
                wallet,
                self.initialize_chain(network),
                hotkey_ss58,
                hotkey_display,
                prompt,
            )
        )

    def wallet_new_coldkey(
        self,
        wallet_name: Optional[str] = Options.wallet_name,
        wallet_path: Optional[str] = Options.wallet_path,
        wallet_hotkey: Optional[str] = Options.wallet_hotkey,
        n_words: Optional[int] = typer.Option(
            None,
            "--n-words",
            "--n_words",
            help="The number of words used in the mnemonic. Options: [12, 15, 18, 21, 24]",
        ),
        use_password: Optional[bool] = Options.use_password,
        uri: Optional[str] = Options.uri,
        overwrite: bool = Options.overwrite,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
        json_output: bool = Options.json_output,
    ):
        """
        Create a new coldkey. A coldkey is required for holding TAO balances and performing high-value transactions.

        USAGE

        The command creates a new coldkey. It provides options for the mnemonic word count, and supports password protection. It also allows overwriting an existing coldkey.

        EXAMPLE

        [green]$[/green] btcli wallet new_coldkey --n_words 15

        [bold]Note[/bold]: This command is crucial for users who need to create a new coldkey for enhanced security or as part of setting up a new wallet. It is a foundational step in establishing a secure presence on the Bittensor network.
        """
        self.verbosity_handler(quiet, verbose, json_output)

        if not wallet_path:
            wallet_path = Prompt.ask(
                "Enter the path to the wallets directory", default=defaults.wallet.path
            )

        if not wallet_name:
            wallet_name = Prompt.ask(
                f"Enter the name of the [{COLORS.G.CK}]new wallet (coldkey)",
                default=defaults.wallet.name,
            )

        wallet = self.wallet_ask(
            wallet_name,
            wallet_path,
            wallet_hotkey,
            ask_for=[WO.NAME, WO.PATH],
            validate=WV.NONE,
        )
        if not uri:
            n_words = get_n_words(n_words)
        return self._run_command(
            wallets.new_coldkey(
                wallet, n_words, use_password, uri, overwrite, json_output
            )
        )

    def wallet_check_ck_swap(
        self,
        wallet_ss58_address: Optional[str] = Options.wallet_ss58_address,
        wallet_path: Optional[str] = Options.wallet_path,
        wallet_hotkey: Optional[str] = Options.wallet_hotkey,
        scheduled_block: Optional[int] = typer.Option(
            None,
            "--block",
            help="Block number where the swap was scheduled",
        ),
        show_all: bool = typer.Option(
            False,
            "--all",
            "-a",
            help="Show all pending coldkey swaps",
        ),
        network: Optional[list[str]] = Options.network,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
    ):
        """
        Check the status of scheduled coldkey swaps.

        USAGE

        This command can be used in three ways:
        1. Show all pending swaps (--all)
        2. Check status of a specific wallet's swap or SS58 address
        3. Check detailed swap status with block number (--block)

        EXAMPLES

        Show all pending swaps:
        [green]$[/green] btcli wallet swap-check --all

        Check specific wallet's swap:
        [green]$[/green] btcli wallet swap-check --wallet-name my_wallet

        Check swap using SS58 address:
        [green]$[/green] btcli wallet swap-check --ss58 5DkQ4...

        Check swap details with block number:
        [green]$[/green] btcli wallet swap-check --wallet-name my_wallet --block 12345
        """
        # TODO add json_output if this ever gets used again (doubtful)
        self.verbosity_handler(quiet, verbose)
        self.initialize_chain(network)

        if show_all:
            return self._run_command(
                wallets.check_swap_status(self.subtensor, None, None)
            )

        if not wallet_ss58_address:
            wallet_ss58_address = Prompt.ask(
                "Enter [blue]wallet name[/blue] or [blue]SS58 address[/blue] [dim](leave blank to show all pending swaps)[/dim]"
            )
            if not wallet_ss58_address:
                return self._run_command(
                    wallets.check_swap_status(self.subtensor, None, None)
                )

        if is_valid_ss58_address(wallet_ss58_address):
            ss58_address = wallet_ss58_address
        else:
            wallet = self.wallet_ask(
                wallet_ss58_address,
                wallet_path,
                wallet_hotkey,
                ask_for=[WO.NAME, WO.PATH],
                validate=WV.WALLET,
            )
            ss58_address = wallet.coldkeypub.ss58_address

        if not scheduled_block:
            block_input = Prompt.ask(
                "[blue]Enter the block number[/blue] where the swap was scheduled [dim](optional, press enter to skip)[/dim]",
                default="",
            )
            if block_input:
                try:
                    scheduled_block = int(block_input)
                except ValueError:
                    print_error("Invalid block number")
                    raise typer.Exit()

        return self._run_command(
            wallets.check_swap_status(self.subtensor, ss58_address, scheduled_block)
        )

    def wallet_create_wallet(
        self,
        wallet_name: Optional[str] = Options.wallet_name,
        wallet_path: Optional[str] = Options.wallet_path,
        wallet_hotkey: Optional[str] = Options.wallet_hotkey,
        n_words: Optional[int] = None,
        use_password: bool = Options.use_password,
        uri: Optional[str] = Options.uri,
        overwrite: bool = Options.overwrite,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
        json_output: bool = Options.json_output,
    ):
        """
        Create a complete wallet by setting up both coldkey and hotkeys.

        USAGE

        The command creates a new coldkey and hotkey. It provides an option for mnemonic word count. It supports password protection for the coldkey and allows overwriting of existing keys.

        EXAMPLE

        [green]$[/green] btcli wallet create --n_words 21

        [bold]Note[/bold]: This command is for new users setting up their wallet for the first time, or for those who wish to completely renew their wallet keys. It ensures a fresh start with new keys for secure and effective participation in the Bittensor network.
        """
        self.verbosity_handler(quiet, verbose, json_output)
        if not wallet_path:
            wallet_path = Prompt.ask(
                "Enter the path of wallets directory", default=defaults.wallet.path
            )

        if not wallet_name:
            wallet_name = Prompt.ask(
                f"Enter the name of the [{COLORS.G.CK}]new wallet (coldkey)",
                default=defaults.wallet.name,
            )
        if not wallet_hotkey:
            wallet_hotkey = Prompt.ask(
                f"Enter the the name of the [{COLORS.G.HK}]new hotkey",
                default=defaults.wallet.hotkey,
            )

        wallet = self.wallet_ask(
            wallet_name,
            wallet_path,
            wallet_hotkey,
            ask_for=[WO.NAME, WO.PATH, WO.HOTKEY],
            validate=WV.NONE,
        )
        if not uri:
            n_words = get_n_words(n_words)
        return self._run_command(
            wallets.wallet_create(
                wallet, n_words, use_password, uri, overwrite, json_output
            )
        )

    def wallet_balance(
        self,
        wallet_name: Optional[str] = Options.wallet_name,
        wallet_path: Optional[str] = Options.wallet_path,
        wallet_hotkey: Optional[str] = Options.wallet_hotkey,
        ss58_addresses: Optional[list[str]] = Options.ss58_address,
        all_balances: Optional[bool] = typer.Option(
            False,
            "--all",
            "-a",
            help="Whether to display the balances for all the wallets.",
        ),
        network: Optional[list[str]] = Options.network,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
        json_output: bool = Options.json_output,
    ):
        """
        Check the balance of the wallet. This command shows a detailed view of the wallet's coldkey balances, including free and staked balances.

        You can also pass multiple ss58 addresses of coldkeys to check their balance (using --ss58).

        EXAMPLES:

        - To display the balance of a single wallet, use the command with the `--wallet-name` argument and provide the wallet name:

            [green]$[/green] btcli w balance --wallet-name WALLET

        - To use the default config values, use:

            [green]$[/green] btcli w balance

        - To display the balances of all your wallets, use the `--all` argument:

            [green]$[/green] btcli w balance --all

        - To display the balances of ss58 addresses, use the `--ss58` argument:

            [green]$[/green] btcli w balance --ss58 <ss58_address> --ss58 <ss58_address>

        """
        self.verbosity_handler(quiet, verbose, json_output)
        wallet = None
        if all_balances:
            ask_for = [WO.PATH]
            validate = WV.NONE
            wallet = self.wallet_ask(
                wallet_name,
                wallet_path,
                wallet_hotkey,
                ask_for=ask_for,
                validate=validate,
            )
        elif ss58_addresses:
            valid_ss58s = [
                ss58 for ss58 in set(ss58_addresses) if is_valid_ss58_address(ss58)
            ]

            invalid_ss58s = set(ss58_addresses) - set(valid_ss58s)
            for invalid_ss58 in invalid_ss58s:
                print_error(f"Incorrect ss58 address: {invalid_ss58}. Skipping.")

            if valid_ss58s:
                ss58_addresses = valid_ss58s
            else:
                raise typer.Exit()
        else:
            if wallet_name:
                coldkey_or_ss58 = wallet_name
            else:
                coldkey_or_ss58 = Prompt.ask(
                    "Enter the [blue]wallet name[/blue] or [blue]coldkey ss58 addresses[/blue] (comma-separated)",
                    default=self.config.get("wallet_name") or defaults.wallet.name,
                )

            # Split and validate ss58 addresses
            coldkey_or_ss58_list = [x.strip() for x in coldkey_or_ss58.split(",")]
            if any(is_valid_ss58_address(x) for x in coldkey_or_ss58_list):
                valid_ss58s = [
                    ss58 for ss58 in coldkey_or_ss58_list if is_valid_ss58_address(ss58)
                ]
                invalid_ss58s = set(coldkey_or_ss58_list) - set(valid_ss58s)
                for invalid_ss58 in invalid_ss58s:
                    print_error(f"Incorrect ss58 address: {invalid_ss58}. Skipping.")

                if valid_ss58s:
                    ss58_addresses = valid_ss58s
                else:
                    raise typer.Exit()
            else:
                wallet_name = (
                    coldkey_or_ss58_list[0] if coldkey_or_ss58_list else wallet_name
                )
                ask_for = [WO.NAME, WO.PATH]
                validate = WV.WALLET
                wallet = self.wallet_ask(
                    wallet_name,
                    wallet_path,
                    wallet_hotkey,
                    ask_for=ask_for,
                    validate=validate,
                )
        subtensor = self.initialize_chain(network)
        return self._run_command(
            wallets.wallet_balance(
                wallet, subtensor, all_balances, ss58_addresses, json_output
            )
        )

    def wallet_history(
        self,
        wallet_name: Optional[str] = Options.wallet_name,
        wallet_path: Optional[str] = Options.wallet_path,
        wallet_hotkey: Optional[str] = Options.wallet_hotkey,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
    ):
        """
        Show the history of the transfers carried out with the provided wallet on the Bittensor network.

        USAGE

        The output shows the latest transfers of the provided wallet, showing the columns 'From', 'To', 'Amount', 'Extrinsic ID' and 'Block Number'.

        EXAMPLE

        [green]$[/green] btcli wallet history

        """
        # TODO: Fetch effective network and redirect users accordingly - this only works on finney
        # TODO: Add json_output if this gets re-enabled
        # no_use_config_str = "Using the network [dark_orange]finney[/dark_orange] and ignoring network/chain configs"

        # if self.config.get("network"):
        #     if self.config.get("network") != "finney":
        #         console.print(no_use_config_str)

        # For Rao games
        print_error("This command is disabled on the 'rao' network.")
        raise typer.Exit()

        self.verbosity_handler(quiet, verbose)
        wallet = self.wallet_ask(
            wallet_name,
            wallet_path,
            wallet_hotkey,
            ask_for=[WO.NAME, WO.PATH],
            validate=WV.WALLET,
        )
        return self._run_command(wallets.wallet_history(wallet))

    def wallet_set_id(
        self,
        wallet_name: Optional[str] = Options.wallet_name,
        wallet_path: Optional[str] = Options.wallet_path,
        wallet_hotkey: Optional[str] = Options.wallet_hotkey,
        network: Optional[list[str]] = Options.network,
        name: str = typer.Option(
            "",
            "--name",
            help="The display name for the identity.",
        ),
        web_url: str = typer.Option(
            "",
            "--web-url",
            "--web",
            help="The web URL for the identity.",
        ),
        image_url: str = typer.Option(
            "",
            "--image-url",
            "--image",
            help="The image URL for the identity.",
        ),
        discord: str = typer.Option(
            "",
            "--discord",
            help="The Discord handle for the identity.",
        ),
        description: str = typer.Option(
            "",
            "--description",
            help="The description for the identity.",
        ),
        additional: str = typer.Option(
            "",
            "--additional",
            help="Additional details for the identity.",
        ),
        github_repo: str = typer.Option(
            "",
            "--github",
            help="The GitHub repository for the identity.",
        ),
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
        prompt: bool = Options.prompt,
        json_output: bool = Options.json_output,
    ):
        """
        Create or update the on-chain identity of a coldkey or a hotkey on the Bittensor network. [bold]Incurs a 1 TAO transaction fee.[/bold]

        The on-chain identity includes attributes such as display name, legal name, web URL, PGP fingerprint, and contact information, among others.

        The command prompts the user for the identity attributes and validates the input size for each attribute. It provides an option to update an existing validator hotkey identity. If the user consents to the transaction cost, the identity is updated on the blockchain.

        Each field has a maximum size of 64 bytes. The PGP fingerprint field is an exception and has a maximum size of 20 bytes. The user is prompted to enter the PGP fingerprint as a hex string, which is then converted to bytes. The user is also prompted to enter the coldkey or hotkey ``ss58`` address for the identity to be updated.

        If the user does not have a hotkey, the coldkey address is used by default. If setting a validator identity, the hotkey will be used by default. If the user is setting an identity for a subnet, the coldkey will be used by default.

        EXAMPLE

        [green]$[/green] btcli wallet set_identity

        [bold]Note[/bold]: This command should only be used if the user is willing to incur the a recycle fee associated with setting an identity on the blockchain. It is a high-level command that makes changes to the blockchain state and should not be used programmatically as part of other scripts or applications.
        """
        self.verbosity_handler(quiet, verbose, json_output)
        wallet = self.wallet_ask(
            wallet_name,
            wallet_path,
            wallet_hotkey,
            ask_for=[WO.NAME],
            validate=WV.WALLET,
        )

        current_identity = self._run_command(
            wallets.get_id(
                self.initialize_chain(network),
                wallet.coldkeypub.ss58_address,
                "Current on-chain identity",
            ),
            exit_early=False,
        )

        if prompt:
            if not Confirm.ask(
                "Cost to register an [blue]Identity[/blue] is [blue]0.1 TAO[/blue],"
                " are you sure you wish to continue?"
            ):
                console.print(":cross_mark: Aborted!")
                raise typer.Exit()

        identity = prompt_for_identity(
            current_identity,
            name,
            web_url,
            image_url,
            discord,
            description,
            additional,
            github_repo,
        )

        return self._run_command(
            wallets.set_id(
                wallet,
                self.initialize_chain(network),
                identity["name"],
                identity["url"],
                identity["image"],
                identity["discord"],
                identity["description"],
                identity["additional"],
                identity["github_repo"],
                prompt,
                json_output,
            )
        )

    def wallet_get_id(
        self,
        wallet_name: Optional[str] = Options.wallet_name,
        wallet_hotkey: Optional[str] = Options.wallet_hotkey,
        wallet_path: Optional[str] = Options.wallet_path,
        coldkey_ss58=typer.Option(
            None,
            "--ss58",
            "--coldkey_ss58",
            "--coldkey.ss58_address",
            "--coldkey.ss58",
            "--key",
            "-k",
            help="Coldkey address of the wallet",
        ),
        network: Optional[list[str]] = Options.network,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
        json_output: bool = Options.json_output,
    ):
        """
        Shows the identity details of a user's coldkey or hotkey.

        The command displays the information in a table format showing:

        - [blue bold]Address[/blue bold]: The ``ss58`` address of the queried key.

        - [blue bold]Item[/blue bold]: Various attributes of the identity such as stake, rank, and trust.

        - [blue bold]Value[/blue bold]: The corresponding values of the attributes.

        EXAMPLE

        [green]$[/green] btcli wallet get_identity --key <s58_address>

        [bold]Note[/bold]: This command is primarily used for informational purposes and has no side effects on the blockchain network state.
        """
        self.verbosity_handler(quiet, verbose, json_output)
        if not wallet_name:
            if coldkey_ss58:
                if not is_valid_ss58_address(coldkey_ss58):
                    print_error("You entered an invalid ss58 address")
                    raise typer.Exit()
            else:
                coldkey_or_ss58 = Prompt.ask(
                    "Enter the [blue]wallet name[/blue] or [blue]coldkey ss58 address[/blue]",
                    default=self.config.get("wallet_name") or defaults.wallet.name,
                )
                if is_valid_ss58_address(coldkey_or_ss58):
                    coldkey_ss58 = coldkey_or_ss58
                else:
                    wallet_name = coldkey_or_ss58 if coldkey_or_ss58 else wallet_name
                    wallet = self.wallet_ask(
                        wallet_name, wallet_path, wallet_hotkey, ask_for=[WO.NAME]
                    )
                    coldkey_ss58 = wallet.coldkeypub.ss58_address
        else:
            wallet = self.wallet_ask(
                wallet_name, wallet_path, wallet_hotkey, ask_for=[WO.NAME]
            )
            coldkey_ss58 = wallet.coldkeypub.ss58_address

        return self._run_command(
            wallets.get_id(self.initialize_chain(network), coldkey_ss58, json_output)
        )

    def wallet_sign(
        self,
        wallet_path: str = Options.wallet_path,
        wallet_name: str = Options.wallet_name,
        wallet_hotkey: str = Options.wallet_hotkey,
        use_hotkey: Optional[bool] = typer.Option(
            None,
            "--use-hotkey/--no-use-hotkey",
            help="If specified, the message will be signed by the hotkey. If not specified, the user will be prompted.",
        ),
        message: str = typer.Option("", help="The message to encode and sign"),
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
        json_output: bool = Options.json_output,
    ):
        """
        Allows users to sign a message with the provided wallet or wallet hotkey. Use this command to easily prove your ownership of a coldkey or a hotkey.

        USAGE

        Using the provided wallet (coldkey), the command generates a signature for a given message.

        EXAMPLES

        [green]$[/green] btcli wallet sign --wallet-name default --message '{"something": "here", "timestamp": 1719908486}'

        [green]$[/green] btcli wallet sign --wallet-name default --wallet-hotkey hotkey --message
        '{"something": "here", "timestamp": 1719908486}'
        """
        self.verbosity_handler(quiet, verbose, json_output)
        if use_hotkey is None:
            use_hotkey = Confirm.ask(
                f"Would you like to sign the transaction using your [{COLORS.G.HK}]hotkey[/{COLORS.G.HK}]?"
                f"\n[Type [{COLORS.G.HK}]y[/{COLORS.G.HK}] for [{COLORS.G.HK}]hotkey[/{COLORS.G.HK}]"
                f" and [{COLORS.G.CK}]n[/{COLORS.G.CK}] for [{COLORS.G.CK}]coldkey[/{COLORS.G.CK}]] "
                f"(default is [{COLORS.G.CK}]coldkey[/{COLORS.G.CK}])",
                default=False,
            )

        ask_for = [WO.HOTKEY, WO.PATH, WO.NAME] if use_hotkey else [WO.NAME, WO.PATH]
        validate = WV.WALLET_AND_HOTKEY if use_hotkey else WV.WALLET

        wallet = self.wallet_ask(
            wallet_name, wallet_path, wallet_hotkey, ask_for=ask_for, validate=validate
        )
        if not message:
            message = Prompt.ask("Enter the [blue]message[/blue] to encode and sign")

        return self._run_command(wallets.sign(wallet, message, use_hotkey, json_output))

    def wallet_swap_coldkey(
        self,
        wallet_name: Optional[str] = Options.wallet_name,
        wallet_path: Optional[str] = Options.wallet_path,
        wallet_hotkey: Optional[str] = Options.wallet_hotkey,
        new_wallet_or_ss58: Optional[str] = typer.Option(
            None,
            "--new-coldkey",
            "--new-coldkey-ss58",
            "--new-wallet",
            "--new",
            help="SS58 address of the new coldkey that will replace the current one.",
        ),
        network: Optional[list[str]] = Options.network,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
        force_swap: bool = typer.Option(
            False,
            "--force",
            "-f",
            "--force-swap",
            help="Force the swap even if the new coldkey is already scheduled for a swap.",
        ),
    ):
        """
        Schedule a coldkey swap for a wallet.

        This command allows you to schedule a coldkey swap for a wallet. You can either provide a new wallet name, or SS58 address.

        EXAMPLES

        [green]$[/green] btcli wallet schedule-coldkey-swap --new-wallet my_new_wallet

        [green]$[/green] btcli wallet schedule-coldkey-swap --new-coldkey-ss58 5Dk...X3q
        """
        self.verbosity_handler(quiet, verbose)

        if not wallet_name:
            wallet_name = Prompt.ask(
                "Enter the [blue]wallet name[/blue] which you want to swap the coldkey for",
                default=self.config.get("wallet_name") or defaults.wallet.name,
            )
        wallet = self.wallet_ask(
            wallet_name,
            wallet_path,
            wallet_hotkey,
            ask_for=[WO.NAME],
            validate=WV.WALLET,
        )
        console.print(
            f"\nWallet selected to swap the [blue]coldkey[/blue] from: \n"
            f"[dark_sea_green3]{wallet}[/dark_sea_green3]\n"
        )

        if not new_wallet_or_ss58:
            new_wallet_or_ss58 = Prompt.ask(
                "Enter the [blue]new wallet name[/blue] or [blue]SS58 address[/blue] of the new coldkey",
            )

        if is_valid_ss58_address(new_wallet_or_ss58):
            new_wallet_coldkey_ss58 = new_wallet_or_ss58
        else:
            new_wallet_name = new_wallet_or_ss58
            new_wallet = self.wallet_ask(
                new_wallet_name,
                wallet_path,
                wallet_hotkey,
                ask_for=[WO.NAME],
                validate=WV.WALLET,
            )
            console.print(
                f"\nNew wallet to swap the [blue]coldkey[/blue] to: \n"
                f"[dark_sea_green3]{new_wallet}[/dark_sea_green3]\n"
            )
            new_wallet_coldkey_ss58 = new_wallet.coldkeypub.ss58_address

        return self._run_command(
            wallets.schedule_coldkey_swap(
                wallet=wallet,
                subtensor=self.initialize_chain(network),
                new_coldkey_ss58=new_wallet_coldkey_ss58,
                force_swap=force_swap,
            )
        )

    def stake_list(
        self,
        network: Optional[list[str]] = Options.network,
        wallet_name: Optional[str] = Options.wallet_name,
        wallet_hotkey: Optional[str] = Options.wallet_hotkey,
        wallet_path: Optional[str] = Options.wallet_path,
        coldkey_ss58=typer.Option(
            None,
            "--ss58",
            "--coldkey_ss58",
            "--coldkey.ss58_address",
            "--coldkey.ss58",
            help="Coldkey address of the wallet",
        ),
        live: bool = Options.live,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
        no_prompt: bool = Options.prompt,
        json_output: bool = Options.json_output,
        # TODO add: all-wallets, reuse_last, html_output
    ):
        """
        Display detailed stake information for a wallet across all subnets.

        Shows stake allocations, exchange rates, and emissions for each hotkey.

        [bold]Common Examples:[/bold]

        1. Basic stake overview:
        [green]$[/green] btcli stake list --wallet.name my_wallet

        2. Live updating view with refresh:
        [green]$[/green] btcli stake list --wallet.name my_wallet --live

        3. View specific coldkey by address:
        [green]$[/green] btcli stake list --ss58 5Dk...X3q

        4. Verbose output with full values:
        [green]$[/green] btcli stake list --wallet.name my_wallet --verbose
        """
        self.verbosity_handler(quiet, verbose, json_output)

        wallet = None
        if coldkey_ss58:
            if not is_valid_ss58_address(coldkey_ss58):
                print_error("You entered an invalid ss58 address")
                raise typer.Exit()
        else:
            if wallet_name:
                coldkey_or_ss58 = wallet_name
            else:
                coldkey_or_ss58 = Prompt.ask(
                    "Enter the [blue]wallet name[/blue] or [blue]coldkey ss58 address[/blue]",
                    default=self.config.get("wallet_name") or defaults.wallet.name,
                )
            if is_valid_ss58_address(coldkey_or_ss58):
                coldkey_ss58 = coldkey_or_ss58
            else:
                wallet_name = coldkey_or_ss58 if coldkey_or_ss58 else wallet_name
                wallet = self.wallet_ask(
                    wallet_name, wallet_path, wallet_hotkey, ask_for=[WO.NAME, WO.PATH]
                )

        return self._run_command(
            list_stake.stake_list(
                wallet,
                coldkey_ss58,
                self.initialize_chain(network),
                live,
                verbose,
                no_prompt,
                json_output,
            )
        )

    def stake_add(
        self,
        stake_all: bool = typer.Option(
            False,
            "--all-tokens",
            "--all",
            "-a",
            help="When set, the command stakes all the available TAO from the coldkey.",
        ),
        amount: float = typer.Option(
            0.0, "--amount", help="The amount of TAO to stake"
        ),
        include_hotkeys: str = typer.Option(
            "",
            "--include-hotkeys",
            "-in",
            "--hotkey-ss58-address",
            help="Specifies hotkeys by name or ss58 address to stake to. For example, `-in hk1,hk2`",
        ),
        exclude_hotkeys: str = typer.Option(
            "",
            "--exclude-hotkeys",
            "-ex",
            help="Specifies hotkeys by name or ss58 address to not to stake to (use this option only with `--all-hotkeys`)"
            " i.e. `--all-hotkeys -ex hk3,hk4`",
        ),
        all_hotkeys: bool = typer.Option(
            False,
            help="When set, this command stakes to all hotkeys associated with the wallet. Do not use if specifying "
            "hotkeys in `--include-hotkeys`.",
        ),
        netuids: Optional[str] = Options.edit_help(
            "netuids",
            "Netuid(s) to for which to add stake. Specify multiple netuids by separating with a comma, e.g."
            "`btcli st add -n 1,2,3",
        ),
        all_netuids: bool = Options.all_netuids,
        wallet_name: str = Options.wallet_name,
        wallet_path: str = Options.wallet_path,
        wallet_hotkey: str = Options.wallet_hotkey,
        network: Optional[list[str]] = Options.network,
        rate_tolerance: Optional[float] = Options.rate_tolerance,
        safe_staking: Optional[bool] = Options.safe_staking,
        allow_partial_stake: Optional[bool] = Options.allow_partial_stake,
        period: int = Options.period,
        prompt: bool = Options.prompt,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
        json_output: bool = Options.json_output,
    ):
        """
        Stake TAO to one or more hotkeys on specific netuids with your coldkey.

        Stake is always added through your coldkey's free balance. For stake movement, please see `[green]$[/green] btcli stake move` command.

        [bold]Common Examples:[/bold]

        1. Interactive staking (guided prompts):
            [green]$[/green] btcli stake add

        2. Safe staking with rate tolerance of 10% with partial transaction disabled:
            [green]$[/green] btcli stake add --amount 100 --netuid 1 --safe --tolerance 0.1 --no-partial

        3. Allow partial stake if rates change with tolerance of 10%:
            [green]$[/green] btcli stake add --amount 300 --safe --partial --tolerance 0.1

        4. Unsafe staking with no rate protection:
            [green]$[/green] btcli stake add --amount 300 --netuid 1 --unsafe

        5. Stake to multiple hotkeys:
            [green]$[/green] btcli stake add --amount 200 --include-hotkeys hk_ss58_1,hk_ss58_2,hk_ss58_3

        6. Stake all balance to a subnet:
            [green]$[/green] btcli stake add --all --netuid 3

        7. Stake the same amount to multiple subnets:
            [green]$[/green] btcli stake add --amount 100 --netuids 4,5,6

        [bold]Safe Staking Parameters:[/bold]
        • [blue]--safe[/blue]: Enables rate tolerance checks
        • [blue]--tolerance[/blue]: Maximum % rate change allowed (0.05 = 5%)
        • [blue]--partial[/blue]: Complete partial stake if rates exceed tolerance

        """
        netuids = netuids or []
        self.verbosity_handler(quiet, verbose, json_output)
        safe_staking = self.ask_safe_staking(safe_staking)
        if safe_staking:
            rate_tolerance = self.ask_rate_tolerance(rate_tolerance)
            allow_partial_stake = self.ask_partial_stake(allow_partial_stake)
            console.print("\n")

        if netuids:
            netuids = parse_to_list(
                netuids, int, "Netuids must be ints separated by commas", False
            )
        else:
            netuid_ = get_optional_netuid(None, all_netuids)
            netuids = [netuid_] if netuid_ is not None else None
        if netuids:
            for netuid_ in netuids:
                # ensure no negative netuids make it into our list
                validate_netuid(netuid_)

        if stake_all and amount:
            print_error(
                "Cannot specify an amount and 'stake-all'. Choose one or the other."
            )
            return

        if stake_all and not amount:
            if not Confirm.ask("Stake all the available TAO tokens?", default=False):
                return

        if (
            stake_all
            and (isinstance(netuids, list) and len(netuids) > 1)
            or (netuids is None)
        ):
            print_error("Cannot stake all to multiple subnets.")
            return

        if all_hotkeys and include_hotkeys:
            print_error(
                "You have specified hotkeys to include and also the `--all-hotkeys` flag. The flag"
                "should only be used standalone (to use all hotkeys) or with `--exclude-hotkeys`."
            )
            return

        if include_hotkeys and exclude_hotkeys:
            print_error(
                "You have specified options for both including and excluding hotkeys. Select one or the other."
            )
            return

        if not wallet_hotkey and not all_hotkeys and not include_hotkeys:
            if not wallet_name:
                wallet_name = Prompt.ask(
                    "Enter the [blue]wallet name[/blue]",
                    default=self.config.get("wallet_name") or defaults.wallet.name,
                )
            if netuids is not None:
                hotkey_or_ss58 = Prompt.ask(
                    "Enter the [blue]wallet hotkey[/blue] name or [blue]ss58 address[/blue] to stake to [dim]"
                    "(or Press Enter to view delegates)[/dim]",
                )
            else:
                hotkey_or_ss58 = Prompt.ask(
                    "Enter the [blue]hotkey[/blue] name or [blue]ss58 address[/blue] to stake to",
                    default=self.config.get("wallet_hotkey") or defaults.wallet.hotkey,
                )

            if hotkey_or_ss58 == "":
                wallet = self.wallet_ask(
                    wallet_name, wallet_path, wallet_hotkey, ask_for=[WO.NAME, WO.PATH]
                )
                if len(netuids) > 1:
                    netuid_ = IntPrompt.ask(
                        "Enter the netuid for which to show delegates",
                        choices=[str(x) for x in netuids],
                    )
                else:
                    netuid_ = netuids[0]

                selected_hotkey = self._run_command(
                    subnets.show(
                        subtensor=self.initialize_chain(network),
                        netuid=netuid_,
                        sort=False,
                        max_rows=12,
                        prompt=False,
                        delegate_selection=True,
                    ),
                    exit_early=False,
                )
                if not selected_hotkey:
                    print_error("No delegate selected. Exiting.")
                    return
                include_hotkeys = selected_hotkey
            elif is_valid_ss58_address(hotkey_or_ss58):
                wallet = self.wallet_ask(
                    wallet_name, wallet_path, wallet_hotkey, ask_for=[WO.NAME, WO.PATH]
                )
                include_hotkeys = hotkey_or_ss58
            else:
                wallet_hotkey = hotkey_or_ss58
                wallet = self.wallet_ask(
                    wallet_name,
                    wallet_path,
                    wallet_hotkey,
                    ask_for=[WO.NAME, WO.HOTKEY, WO.PATH],
                    validate=WV.WALLET_AND_HOTKEY,
                )
                include_hotkeys = wallet.hotkey.ss58_address

        elif all_hotkeys or include_hotkeys or exclude_hotkeys:
            wallet = self.wallet_ask(
                wallet_name, wallet_path, wallet_hotkey, ask_for=[WO.NAME, WO.PATH]
            )
        else:
            wallet = self.wallet_ask(
                wallet_name,
                wallet_path,
                wallet_hotkey,
                ask_for=[WO.NAME, WO.PATH, WO.HOTKEY],
                validate=WV.WALLET_AND_HOTKEY,
            )

        if include_hotkeys:
            include_hotkeys = parse_to_list(
                include_hotkeys,
                str,
                "Hotkeys must be a comma-separated list of ss58s, e.g., `--include-hotkeys 5Grw....,5Grw....`.",
                is_ss58=True,
            )
        else:
            include_hotkeys = []

        if exclude_hotkeys:
            exclude_hotkeys = parse_to_list(
                exclude_hotkeys,
                str,
                "Hotkeys must be a comma-separated list of ss58s, e.g., `--exclude-hotkeys 5Grw....,5Grw....`.",
                is_ss58=True,
            )
        else:
            exclude_hotkeys = []

        # TODO: Ask amount for each subnet explicitly if more than one
        if not stake_all and not amount:
            free_balance = self._run_command(
                wallets.wallet_balance(
                    wallet, self.initialize_chain(network), False, None
                ),
                exit_early=False,
            )
            if free_balance == Balance.from_tao(0):
                print_error("You dont have any balance to stake.")
                return
            if netuids:
                amount = FloatPrompt.ask(
                    f"Amount to [{COLORS.G.SUBHEAD_MAIN}]stake (TAO τ)"
                )
            else:
                amount = FloatPrompt.ask(
                    f"Amount to [{COLORS.G.SUBHEAD_MAIN}]stake to each netuid (TAO τ)"
                )

            if amount <= 0:
                print_error(f"You entered an incorrect stake amount: {amount}")
                raise typer.Exit()
            if Balance.from_tao(amount) > free_balance:
                print_error(
                    f"You dont have enough balance to stake. Current free Balance: {free_balance}."
                )
                raise typer.Exit()

        return self._run_command(
            add_stake.stake_add(
                wallet,
                self.initialize_chain(network),
                netuids,
                stake_all,
                amount,
                prompt,
                all_hotkeys,
                include_hotkeys,
                exclude_hotkeys,
                safe_staking,
                rate_tolerance,
                allow_partial_stake,
                json_output,
                period,
            )
        )

    def stake_remove(
        self,
        network: Optional[list[str]] = Options.network,
        wallet_name: str = Options.wallet_name,
        wallet_path: str = Options.wallet_path,
        wallet_hotkey: str = Options.wallet_hotkey,
        netuid: Optional[int] = Options.netuid_not_req,
        all_netuids: bool = Options.all_netuids,
        unstake_all: bool = typer.Option(
            False,
            "--unstake-all",
            "--all",
            help="When set, this command unstakes all staked TAO + Alpha from the all hotkeys.",
        ),
        unstake_all_alpha: bool = typer.Option(
            False,
            "--unstake-all-alpha",
            "--all-alpha",
            help="When set, this command unstakes all staked Alpha from the all hotkeys.",
        ),
        amount: float = typer.Option(
            0.0, "--amount", "-a", help="The amount of TAO to unstake."
        ),
        hotkey_ss58_address: str = typer.Option(
            "",
            help="The ss58 address of the hotkey to unstake from.",
        ),
        include_hotkeys: str = typer.Option(
            "",
            "--include-hotkeys",
            "-in",
            help="Specifies the hotkeys by name or ss58 address to unstake from. For example, `-in hk1,hk2`",
        ),
        exclude_hotkeys: str = typer.Option(
            "",
            "--exclude-hotkeys",
            "-ex",
            help="Specifies the hotkeys by name or ss58 address not to unstake from (only use with `--all-hotkeys`)"
            " i.e. `--all-hotkeys -ex hk3,hk4`",
        ),
        all_hotkeys: bool = typer.Option(
            False,
            help="When set, this command unstakes from all the hotkeys associated with the wallet. Do not use if specifying "
            "hotkeys in `--include-hotkeys`.",
        ),
        rate_tolerance: Optional[float] = Options.rate_tolerance,
        safe_staking: Optional[bool] = Options.safe_staking,
        allow_partial_stake: Optional[bool] = Options.allow_partial_stake,
        period: int = Options.period,
        prompt: bool = Options.prompt,
        interactive: bool = typer.Option(
            False,
            "--interactive",
            "-i",
            help="Enter interactive mode for unstaking.",
        ),
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
        json_output: bool = Options.json_output,
    ):
        """
        Unstake TAO from one or more hotkeys and transfer them back to the user's coldkey wallet.

        This command is used to withdraw TAO or Alpha stake from different hotkeys.

        [bold]Common Examples:[/bold]

        1. Interactive unstaking (guided prompts):
            [green]$[/green] btcli stake remove

        2. Safe unstaking with 10% rate tolerance:
            [green]$[/green] btcli stake remove --amount 100 --netuid 1 --safe --tolerance 0.1

        3. Allow partial unstake if rates change:
            [green]$[/green] btcli stake remove --amount 300 --safe --partial

        4. Unstake from multiple hotkeys:
            [green]$[/green] btcli stake remove --amount 200 --include-hotkeys hk1,hk2,hk3

        5. Unstake all from a hotkey:
            [green]$[/green] btcli stake remove --all

        6. Unstake all Alpha from a hotkey and stake to Root:
            [green]$[/green] btcli stake remove --all-alpha

        [bold]Safe Staking Parameters:[/bold]
        • [blue]--safe[/blue]: Enables rate tolerance checks during unstaking
        • [blue]--tolerance[/blue]: Max allowed rate change (0.05 = 5%)
        • [blue]--partial[/blue]: Complete partial unstake if rates exceed tolerance
        """
        self.verbosity_handler(quiet, verbose, json_output)
        if not unstake_all and not unstake_all_alpha:
            safe_staking = self.ask_safe_staking(safe_staking)
            if safe_staking:
                rate_tolerance = self.ask_rate_tolerance(rate_tolerance)
                allow_partial_stake = self.ask_partial_stake(allow_partial_stake)
                console.print("\n")

        if interactive and any(
            [hotkey_ss58_address, include_hotkeys, exclude_hotkeys, all_hotkeys]
        ):
            print_error(
                "Interactive mode cannot be used with hotkey selection options like "
                "--include-hotkeys, --exclude-hotkeys, --all-hotkeys, or --hotkey."
            )
            raise typer.Exit()

        if unstake_all and unstake_all_alpha:
            print_error("Cannot specify both unstake-all and unstake-all-alpha.")
            raise typer.Exit()

        if not interactive and not unstake_all and not unstake_all_alpha:
            netuid = get_optional_netuid(netuid, all_netuids)
            if all_hotkeys and include_hotkeys:
                print_error(
                    "You have specified hotkeys to include and also the `--all-hotkeys` flag. The flag"
                    " should only be used standalone (to use all hotkeys) or with `--exclude-hotkeys`."
                )
                raise typer.Exit()

            if include_hotkeys and exclude_hotkeys:
                print_error(
                    "You have specified both including and excluding hotkeys options. Select one or the other."
                )
                raise typer.Exit()

            if unstake_all and amount:
                print_error(
                    "Cannot specify both a specific amount and 'unstake-all'. Choose one or the other."
                )
                raise typer.Exit()

            if amount and amount <= 0:
                print_error(f"You entered an incorrect unstake amount: {amount}")
                raise typer.Exit()

        if (
            not wallet_hotkey
            and not hotkey_ss58_address
            and not all_hotkeys
            and not include_hotkeys
            and not interactive
            and not unstake_all
            and not unstake_all_alpha
        ):
            if not wallet_name:
                wallet_name = Prompt.ask(
                    "Enter the [blue]wallet name[/blue]",
                    default=self.config.get("wallet_name") or defaults.wallet.name,
                )
            hotkey_or_ss58 = Prompt.ask(
                "Enter the [blue]hotkey[/blue] name or [blue]ss58 address[/blue] to unstake from [dim](or Press Enter to view existing staked hotkeys)[/dim]",
            )
            if hotkey_or_ss58 == "":
                wallet = self.wallet_ask(
                    wallet_name, wallet_path, wallet_hotkey, ask_for=[WO.NAME, WO.PATH]
                )
                interactive = True
            elif is_valid_ss58_address(hotkey_or_ss58):
                hotkey_ss58_address = hotkey_or_ss58
                wallet = self.wallet_ask(
                    wallet_name, wallet_path, wallet_hotkey, ask_for=[WO.NAME, WO.PATH]
                )
            else:
                wallet_hotkey = hotkey_or_ss58
                wallet = self.wallet_ask(
                    wallet_name,
                    wallet_path,
                    wallet_hotkey,
                    ask_for=[WO.NAME, WO.PATH, WO.HOTKEY],
                    validate=WV.WALLET_AND_HOTKEY,
                )

        elif unstake_all or unstake_all_alpha:
            if not wallet_name:
                wallet_name = Prompt.ask(
                    "Enter the [blue]wallet name[/blue]",
                    default=self.config.get("wallet_name") or defaults.wallet.name,
                )
            if include_hotkeys:
                if len(include_hotkeys) > 1:
                    print_error("Cannot unstake_all from multiple hotkeys at once.")
                    raise typer.Exit()
                elif is_valid_ss58_address(include_hotkeys[0]):
                    hotkey_ss58_address = include_hotkeys[0]
                else:
                    print_error("Invalid hotkey ss58 address.")
                    raise typer.Exit()
            elif all_hotkeys:
                wallet = self.wallet_ask(
                    wallet_name,
                    wallet_path,
                    wallet_hotkey,
                    ask_for=[WO.NAME, WO.PATH],
                )
            else:
                if not hotkey_ss58_address and not wallet_hotkey:
                    hotkey_or_ss58 = Prompt.ask(
                        "Enter the [blue]hotkey[/blue] name or [blue]ss58 address[/blue] to unstake all from [dim](or enter 'all' to unstake from all hotkeys)[/dim]",
                        default=self.config.get("wallet_hotkey")
                        or defaults.wallet.hotkey,
                    )
                else:
                    hotkey_or_ss58 = hotkey_ss58_address or wallet_hotkey

                if is_valid_ss58_address(hotkey_or_ss58):
                    hotkey_ss58_address = hotkey_or_ss58
                    wallet = self.wallet_ask(
                        wallet_name,
                        wallet_path,
                        wallet_hotkey,
                        ask_for=[WO.NAME, WO.PATH],
                    )
                elif hotkey_or_ss58 == "all":
                    all_hotkeys = True
                    wallet = self.wallet_ask(
                        wallet_name,
                        wallet_path,
                        wallet_hotkey,
                        ask_for=[WO.NAME, WO.PATH],
                    )
                else:
                    wallet_hotkey = hotkey_or_ss58
                    wallet = self.wallet_ask(
                        wallet_name,
                        wallet_path,
                        wallet_hotkey,
                        ask_for=[WO.NAME, WO.PATH, WO.HOTKEY],
                        validate=WV.WALLET_AND_HOTKEY,
                    )
            return self._run_command(
                remove_stake.unstake_all(
                    wallet=wallet,
                    subtensor=self.initialize_chain(network),
                    hotkey_ss58_address=hotkey_ss58_address,
                    unstake_all_alpha=unstake_all_alpha,
                    all_hotkeys=all_hotkeys,
                    include_hotkeys=include_hotkeys,
                    exclude_hotkeys=exclude_hotkeys,
                    prompt=prompt,
                    json_output=json_output,
                    era=period,
                )
            )
        elif (
            all_hotkeys
            or include_hotkeys
            or exclude_hotkeys
            or hotkey_ss58_address
            or interactive
            or unstake_all
            or unstake_all_alpha
        ):
            wallet = self.wallet_ask(
                wallet_name, wallet_path, wallet_hotkey, ask_for=[WO.NAME, WO.PATH]
            )
        else:
            wallet = self.wallet_ask(
                wallet_name,
                wallet_path,
                wallet_hotkey,
                ask_for=[WO.NAME, WO.PATH, WO.HOTKEY],
                validate=WV.WALLET_AND_HOTKEY,
            )

        if include_hotkeys:
            include_hotkeys = parse_to_list(
                include_hotkeys,
                str,
                "Hotkeys must be a comma-separated list of ss58s or names, e.g., `--include-hotkeys hk1,hk2`.",
                is_ss58=False,
            )

        if exclude_hotkeys:
            exclude_hotkeys = parse_to_list(
                exclude_hotkeys,
                str,
                "Hotkeys must be a comma-separated list of ss58s or names, e.g., `--exclude-hotkeys hk3,hk4`.",
                is_ss58=False,
            )

        return self._run_command(
            remove_stake.unstake(
                wallet=wallet,
                subtensor=self.initialize_chain(network),
                hotkey_ss58_address=hotkey_ss58_address,
                all_hotkeys=all_hotkeys,
                include_hotkeys=include_hotkeys,
                exclude_hotkeys=exclude_hotkeys,
                amount=amount,
                prompt=prompt,
                interactive=interactive,
                netuid=netuid,
                safe_staking=safe_staking,
                rate_tolerance=rate_tolerance,
                allow_partial_stake=allow_partial_stake,
                json_output=json_output,
                era=period,
            )
        )

    def stake_move(
        self,
        network: Optional[list[str]] = Options.network,
        wallet_name: Optional[str] = Options.wallet_name,
        wallet_path: Optional[str] = Options.wallet_path,
        wallet_hotkey: Optional[str] = Options.wallet_hotkey_ss58,
        origin_netuid: Optional[int] = typer.Option(
            None, "--origin-netuid", help="Origin netuid"
        ),
        destination_netuid: Optional[int] = typer.Option(
            None, "--dest-netuid", help="Destination netuid"
        ),
        destination_hotkey: Optional[str] = typer.Option(
            None, "--dest-ss58", "--dest", help="Destination hotkey", prompt=False
        ),
        amount: float = typer.Option(
            None,
            "--amount",
            help="The amount of TAO to stake",
            prompt=False,
        ),
        stake_all: bool = typer.Option(
            False, "--stake-all", "--all", help="Stake all", prompt=False
        ),
        period: int = Options.period,
        prompt: bool = Options.prompt,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
        json_output: bool = Options.json_output,
    ):
        """
        Move staked TAO between hotkeys while keeping the same coldkey ownership.

        This command allows you to:
        - Move stake from one hotkey to another hotkey
        - Move stake between different subnets
        - Keep the same coldkey ownership

        You can specify:
        - The origin subnet (--origin-netuid)
        - The destination subnet (--dest-netuid)
        - The destination hotkey (--dest-hotkey)
        - The amount to move (--amount)

        If no arguments are provided, an interactive selection menu will be shown.

        EXAMPLE

        [green]$[/green] btcli stake move
        """
        self.verbosity_handler(quiet, verbose, json_output)
        console.print(
            "[dim]This command moves stake from one hotkey to another hotkey while keeping the same coldkey.[/dim]"
        )
        if not destination_hotkey:
            dest_wallet_or_ss58 = Prompt.ask(
                "Enter the [blue]destination wallet[/blue] where destination hotkey is located or "
                "[blue]ss58 address[/blue]"
            )
            if is_valid_ss58_address(dest_wallet_or_ss58):
                destination_hotkey = dest_wallet_or_ss58
            else:
                dest_wallet = self.wallet_ask(
                    dest_wallet_or_ss58,
                    wallet_path,
                    None,
                    ask_for=[WO.NAME, WO.PATH],
                    validate=WV.WALLET,
                )
                destination_hotkey = Prompt.ask(
                    "Enter the [blue]destination hotkey[/blue] name",
                    default=dest_wallet.hotkey_str,
                )
                destination_wallet = self.wallet_ask(
                    dest_wallet_or_ss58,
                    wallet_path,
                    destination_hotkey,
                    ask_for=[WO.NAME, WO.PATH, WO.HOTKEY],
                    validate=WV.WALLET_AND_HOTKEY,
                )
                destination_hotkey = destination_wallet.hotkey.ss58_address
        else:
            if is_valid_ss58_address(destination_hotkey):
                destination_hotkey = destination_hotkey
            else:
                print_error(
                    "Invalid destination hotkey ss58 address. Please enter a valid ss58 address or wallet name."
                )
                raise typer.Exit()

        if not wallet_name:
            wallet_name = Prompt.ask(
                "Enter the [blue]origin wallet name[/blue]",
                default=self.config.get("wallet_name") or defaults.wallet.name,
            )
        wallet = self.wallet_ask(
            wallet_name, wallet_path, wallet_hotkey, ask_for=[WO.NAME, WO.PATH]
        )

        interactive_selection = False
        if not wallet_hotkey:
            origin_hotkey = Prompt.ask(
                "Enter the [blue]origin hotkey[/blue] name or "
                "[blue]ss58 address[/blue] where the stake will be moved from "
                "[dim](or Press Enter to view existing stakes)[/dim]"
            )
            if origin_hotkey == "":
                interactive_selection = True

            elif is_valid_ss58_address(origin_hotkey):
                origin_hotkey = origin_hotkey
            else:
                wallet = self.wallet_ask(
                    wallet_name,
                    wallet_path,
                    origin_hotkey,
                    ask_for=[WO.NAME, WO.PATH, WO.HOTKEY],
                    validate=WV.WALLET_AND_HOTKEY,
                )
                origin_hotkey = wallet.hotkey.ss58_address
        else:
            if is_valid_ss58_address(wallet_hotkey):
                origin_hotkey = wallet_hotkey
            else:
                wallet = self.wallet_ask(
                    wallet_name,
                    wallet_path,
                    wallet_hotkey,
                    ask_for=[],
                    validate=WV.WALLET_AND_HOTKEY,
                )
                origin_hotkey = wallet.hotkey.ss58_address

        if not interactive_selection:
            if origin_netuid is None:
                origin_netuid = IntPrompt.ask(
                    "Enter the [blue]origin subnet[/blue] (netuid) to move stake from"
                )

            if destination_netuid is None:
                destination_netuid = IntPrompt.ask(
                    "Enter the [blue]destination subnet[/blue] (netuid) to move stake to"
                )

        result = self._run_command(
            move_stake.move_stake(
                subtensor=self.initialize_chain(network),
                wallet=wallet,
                origin_netuid=origin_netuid,
                origin_hotkey=origin_hotkey,
                destination_netuid=destination_netuid,
                destination_hotkey=destination_hotkey,
                amount=amount,
                stake_all=stake_all,
                era=period,
                interactive_selection=interactive_selection,
                prompt=prompt,
            )
        )
        if json_output:
            json_console.print(json.dumps({"success": result}))
        return result

    def stake_transfer(
        self,
        network: Optional[list[str]] = Options.network,
        wallet_name: Optional[str] = Options.wallet_name,
        wallet_path: Optional[str] = Options.wallet_path,
        wallet_hotkey: Optional[str] = Options.wallet_hotkey_ss58,
        origin_netuid: Optional[int] = typer.Option(
            None,
            "--origin-netuid",
            help="The netuid to transfer stake from",
        ),
        dest_netuid: Optional[int] = typer.Option(
            None,
            "--dest-netuid",
            help="The netuid to transfer stake to",
        ),
        dest_ss58: Optional[str] = typer.Option(
            None,
            "--dest-ss58",
            "--dest",
            "--dest-coldkey",
            help="The destination wallet name or SS58 address to transfer stake to",
        ),
        amount: float = typer.Option(
            None,
            "--amount",
            "-a",
            help="Amount of stake to transfer",
        ),
        stake_all: bool = typer.Option(
            False, "--stake-all", "--all", help="Stake all", prompt=False
        ),
        period: int = Options.period,
        prompt: bool = Options.prompt,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
        json_output: bool = Options.json_output,
    ):
        """
        Transfer stake between coldkeys while keeping the same hotkey ownership.

        This command allows you to:
        - Transfer stake from one coldkey to another coldkey
        - Keep the same hotkey ownership
        - Transfer stake between different subnets

        You can specify:
        - The origin subnet (--origin-netuid)
        - The destination subnet (--dest-netuid)
        - The destination wallet/address (--dest)
        - The amount to transfer (--amount)
        - The origin wallet (--wallet-name)
        - The origin hotkey wallet/address (--wallet-hotkey)

        If no arguments are provided, an interactive selection menu will be shown.

        EXAMPLE

        Transfer 100 TAO from subnet 1 to subnet 2:
        [green]$[/green] btcli stake transfer --origin-netuid 1 --dest-netuid 2 --dest wallet2 --amount 100

        Using Destination SS58 address:
        [green]$[/green] btcli stake transfer --origin-netuid 1 --dest-netuid 2 --dest 5FrLxJsyJ5x9n2rmxFwosFraxFCKcXZDngEP9H7qjkKgHLcK --amount 100

        Using Origin hotkey SS58 address (useful when transferring stake from a delegate):
        [green]$[/green] btcli stake transfer --wallet-hotkey 5FrLxJsyJ5x9n2rmxFwosFraxFCKcXZDngEP9H7qjkKgHLcK --wallet-name sample_wallet

        Transfer all available stake from origin hotkey:
        [green]$[/green] btcli stake transfer --all --origin-netuid 1 --dest-netuid 2
        """
        self.verbosity_handler(quiet, verbose, json_output)
        console.print(
            "[dim]This command transfers stake from one coldkey to another while keeping the same hotkey.[/dim]"
        )

        if not dest_ss58:
            dest_ss58 = Prompt.ask(
                "Enter the [blue]destination wallet name[/blue] or [blue]coldkey SS58 address[/blue]"
            )

        if is_valid_ss58_address(dest_ss58):
            dest_ss58 = dest_ss58
        else:
            dest_wallet = self.wallet_ask(
                dest_ss58,
                wallet_path,
                None,
                ask_for=[WO.NAME, WO.PATH],
                validate=WV.WALLET,
            )
            dest_ss58 = dest_wallet.coldkeypub.ss58_address

        if not wallet_name:
            wallet_name = Prompt.ask(
                "Enter the [blue]origin wallet name[/blue]",
                default=self.config.get("wallet_name") or defaults.wallet.name,
            )
        wallet = self.wallet_ask(
            wallet_name, wallet_path, wallet_hotkey, ask_for=[WO.NAME]
        )

        interactive_selection = False
        if not wallet_hotkey:
            origin_hotkey = Prompt.ask(
                "Enter the [blue]origin hotkey[/blue] name or ss58 address [bold](stake will be transferred FROM here)[/bold] "
                "[dim](or press Enter to select from existing stakes)[/dim]"
            )
            if origin_hotkey == "":
                interactive_selection = True

            elif is_valid_ss58_address(origin_hotkey):
                origin_hotkey = origin_hotkey
            else:
                wallet = self.wallet_ask(
                    wallet_name,
                    wallet_path,
                    origin_hotkey,
                    ask_for=[WO.NAME, WO.PATH, WO.HOTKEY],
                    validate=WV.WALLET_AND_HOTKEY,
                )
                origin_hotkey = wallet.hotkey.ss58_address
        else:
            if is_valid_ss58_address(wallet_hotkey):
                origin_hotkey = wallet_hotkey
            else:
                wallet = self.wallet_ask(
                    wallet_name,
                    wallet_path,
                    wallet_hotkey,
                    ask_for=[],
                    validate=WV.WALLET_AND_HOTKEY,
                )
                origin_hotkey = wallet.hotkey.ss58_address

        if not interactive_selection:
            if origin_netuid is None:
                origin_netuid = IntPrompt.ask(
                    "Enter the [blue]origin subnet[/blue] (netuid)"
                )

            if dest_netuid is None:
                dest_netuid = IntPrompt.ask(
                    "Enter the [blue]destination subnet[/blue] (netuid)"
                )

        result = self._run_command(
            move_stake.transfer_stake(
                wallet=wallet,
                subtensor=self.initialize_chain(network),
                origin_hotkey=origin_hotkey,
                origin_netuid=origin_netuid,
                dest_netuid=dest_netuid,
                dest_coldkey_ss58=dest_ss58,
                amount=amount,
                era=period,
                interactive_selection=interactive_selection,
                stake_all=stake_all,
                prompt=prompt,
            )
        )
        if json_output:
            json_console.print(json.dumps({"success": result}))
        return result

    def stake_swap(
        self,
        network: Optional[list[str]] = Options.network,
        wallet_name: Optional[str] = Options.wallet_name,
        wallet_path: Optional[str] = Options.wallet_path,
        wallet_hotkey: Optional[str] = Options.wallet_hotkey,
        origin_netuid: Optional[int] = typer.Option(
            None,
            "--origin-netuid",
            "-o",
            "--origin",
            help="The netuid to swap stake from",
        ),
        dest_netuid: Optional[int] = typer.Option(
            None,
            "--dest-netuid",
            "-d",
            "--dest",
            help="The netuid to swap stake to",
        ),
        amount: float = typer.Option(
            None,
            "--amount",
            "-a",
            help="Amount of stake to swap",
        ),
        swap_all: bool = typer.Option(
            False,
            "--swap-all",
            "--all",
            help="Swap all available stake",
        ),
        period: int = Options.period,
        prompt: bool = Options.prompt,
        wait_for_inclusion: bool = Options.wait_for_inclusion,
        wait_for_finalization: bool = Options.wait_for_finalization,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
        json_output: bool = Options.json_output,
    ):
        """
        Swap stake between different subnets while keeping the same coldkey-hotkey pair ownership.

        This command allows you to:
        - Move stake from one subnet to another subnet
        - Keep the same coldkey ownership
        - Keep the same hotkey ownership

        You can specify:
        - The origin subnet (--origin-netuid)
        - The destination subnet (--dest-netuid)
        - The amount to swap (--amount)

        If no arguments are provided, an interactive selection menu will be shown.

        EXAMPLE

        Swap 100 TAO from subnet 1 to subnet 2:
        [green]$[/green] btcli stake swap --wallet-name default --wallet-hotkey default --origin-netuid 1 --dest-netuid 2 --amount 100
        """
        self.verbosity_handler(quiet, verbose, json_output)
        console.print(
            "[dim]This command moves stake from one subnet to another subnet while keeping "
            "the same coldkey-hotkey pair.[/dim]"
        )

        wallet = self.wallet_ask(
            wallet_name,
            wallet_path,
            wallet_hotkey,
            ask_for=[WO.NAME, WO.PATH, WO.HOTKEY],
            validate=WV.WALLET_AND_HOTKEY,
        )

        interactive_selection = False
        if origin_netuid is None and dest_netuid is None and not amount:
            interactive_selection = True
        else:
            if origin_netuid is None:
                origin_netuid = IntPrompt.ask(
                    "Enter the [blue]origin subnet[/blue] (netuid)"
                )
            if dest_netuid is None:
                dest_netuid = IntPrompt.ask(
                    "Enter the [blue]destination subnet[/blue] (netuid)"
                )
            if not amount and not swap_all:
                amount = FloatPrompt.ask("Enter the [blue]amount[/blue] to swap")

        result = self._run_command(
            move_stake.swap_stake(
                wallet=wallet,
                subtensor=self.initialize_chain(network),
                origin_netuid=origin_netuid,
                destination_netuid=dest_netuid,
                amount=amount,
                swap_all=swap_all,
                era=period,
                interactive_selection=interactive_selection,
                prompt=prompt,
                wait_for_inclusion=wait_for_inclusion,
                wait_for_finalization=wait_for_finalization,
            )
        )
        if json_output:
            json_console.print(json.dumps({"success": result}))
        return result

    def stake_get_children(
        self,
        wallet_name: Optional[str] = Options.wallet_name,
        wallet_hotkey: Optional[str] = Options.wallet_hotkey,
        wallet_path: Optional[str] = Options.wallet_path,
        network: Optional[list[str]] = Options.network,
        netuid: Optional[int] = typer.Option(
            None,
            help="The netuid of the subnet (e.g. 2)",
            prompt=False,
        ),
        all_netuids: bool = typer.Option(
            False,
            "--all-netuids",
            "--all",
            "--allnetuids",
            help="When set, gets the child hotkeys from all the subnets.",
        ),
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
        json_output: bool = Options.json_output,
    ):
        """
        Get all the child hotkeys on a specified subnet.

        Users can specify the subnet and see the child hotkeys and the proportion that is given to them. This command is used to view the authority delegated to different hotkeys on the subnet.

        EXAMPLE

        [green]$[/green] btcli stake child get --netuid 1
        [green]$[/green] btcli stake child get --all-netuids
        """
        self.verbosity_handler(quiet, verbose, json_output)
        wallet = self.wallet_ask(
            wallet_name,
            wallet_path,
            wallet_hotkey,
            ask_for=[WO.NAME, WO.PATH, WO.HOTKEY],
            validate=WV.WALLET_AND_HOTKEY,
        )

        if all_netuids and netuid:
            err_console.print("Specify either a netuid or `--all`, not both.")
            raise typer.Exit()

        if all_netuids:
            netuid = None

        elif not netuid:
            netuid = IntPrompt.ask(
                "Enter a netuid (leave blank for all)", default=None, show_default=True
            )

        result = self._run_command(
            children_hotkeys.get_children(
                wallet, self.initialize_chain(network), netuid
            )
        )
        if json_output:
            json_console.print(json.dumps(result))
        return result

    def stake_set_children(
        self,
        children: list[str] = typer.Option(
            [], "--children", "-c", help="Enter child hotkeys (ss58)", prompt=False
        ),
        wallet_name: str = Options.wallet_name,
        wallet_hotkey: str = Options.wallet_hotkey,
        wallet_path: str = Options.wallet_path,
        network: Optional[list[str]] = Options.network,
        netuid: Optional[int] = Options.netuid_not_req,
        all_netuids: bool = Options.all_netuids,
        proportions: list[float] = typer.Option(
            [],
            "--proportions",
            "--prop",
            help="Enter the stake weight proportions for the child hotkeys (sum should be less than or equal to 1)",
            prompt=False,
        ),
        wait_for_inclusion: bool = Options.wait_for_inclusion,
        wait_for_finalization: bool = Options.wait_for_finalization,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
        prompt: bool = Options.prompt,
        json_output: bool = Options.json_output,
    ):
        """
        Set child hotkeys on a specified subnet (or all). Overrides currently set children.

        Users can specify the 'proportion' to delegate to child hotkeys (ss58 address). The sum of proportions cannot be greater than 1.

        This command is used to delegate authority to different hotkeys, securing their position and influence on the subnet.

        EXAMPLE

        [green]$[/green] btcli stake child set -c 5FCL3gmjtQV4xxxxuEPEFQVhyyyyqYgNwX7drFLw7MSdBnxP -c 5Hp5dxxxxtGg7pu8dN2btyyyyVA1vELmM9dy8KQv3LxV8PA7 --hotkey default --netuid 1 -p 0.3 -p 0.7
        """
        self.verbosity_handler(quiet, verbose, json_output)
        netuid = get_optional_netuid(netuid, all_netuids)

        children = list_prompt(
            children,
            str,
            "Enter the child hotkeys (ss58), comma-separated for multiple",
        )

        proportions = list_prompt(
            proportions,
            float,
            "Enter comma-separated proportions equal to the number of children "
            "(sum not exceeding a total of 1.0)",
        )

        if len(proportions) != len(children):
            err_console.print("You must have as many proportions as you have children.")
            raise typer.Exit()

        if sum(proportions) > 1.0:
            err_console.print("Your proportion total must not exceed 1.0.")
            raise typer.Exit()

        wallet = self.wallet_ask(
            wallet_name,
            wallet_path,
            wallet_hotkey,
            ask_for=[WO.NAME, WO.HOTKEY],
            validate=WV.WALLET_AND_HOTKEY,
        )
        return self._run_command(
            children_hotkeys.set_children(
                wallet=wallet,
                subtensor=self.initialize_chain(network),
                netuid=netuid,
                children=children,
                proportions=proportions,
                wait_for_finalization=wait_for_finalization,
                wait_for_inclusion=wait_for_inclusion,
                prompt=prompt,
                json_output=json_output,
            )
        )

    def stake_revoke_children(
        self,
        wallet_name: Optional[str] = Options.wallet_name,
        wallet_hotkey: Optional[str] = Options.wallet_hotkey,
        wallet_path: Optional[str] = Options.wallet_path,
        network: Optional[list[str]] = Options.network,
        netuid: Optional[int] = typer.Option(
            None,
            help="The netuid of the subnet, (e.g. 8)",
            prompt=False,
        ),
        all_netuids: bool = typer.Option(
            False,
            "--all-netuids",
            "--all",
            "--allnetuids",
            help="When this flag is used it sets child hotkeys on all the subnets.",
        ),
        wait_for_inclusion: bool = Options.wait_for_inclusion,
        wait_for_finalization: bool = Options.wait_for_finalization,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
        prompt: bool = Options.prompt,
        json_output: bool = Options.json_output,
    ):
        """
        Remove all children hotkeys on a specified subnet (or all).

        This command is used to remove delegated authority from all child hotkeys, removing their position and influence on the subnet.

        EXAMPLE

        [green]$[/green] btcli stake child revoke --hotkey <parent_hotkey> --netuid 1
        """
        self.verbosity_handler(quiet, verbose, json_output)
        wallet = self.wallet_ask(
            wallet_name,
            wallet_path,
            wallet_hotkey,
            ask_for=[WO.NAME, WO.HOTKEY],
            validate=WV.WALLET_AND_HOTKEY,
        )
        if all_netuids and netuid:
            err_console.print("Specify either a netuid or '--all', not both.")
            raise typer.Exit()
        if all_netuids:
            netuid = None
        elif not netuid:
            netuid = IntPrompt.ask(
                "Enter netuid (leave blank for all)", default=None, show_default=True
            )
        return self._run_command(
            children_hotkeys.revoke_children(
                wallet,
                self.initialize_chain(network),
                netuid,
                wait_for_inclusion,
                wait_for_finalization,
                prompt=prompt,
                json_output=json_output,
            )
        )

    def stake_childkey_take(
        self,
        wallet_name: Optional[str] = Options.wallet_name,
        wallet_hotkey: Optional[str] = Options.wallet_hotkey,
        wallet_path: Optional[str] = Options.wallet_path,
        network: Optional[list[str]] = Options.network,
        hotkey: Optional[str] = None,
        netuid: Optional[int] = typer.Option(
            None,
            help="The netuid of the subnet, (e.g. 23)",
            prompt=False,
        ),
        all_netuids: bool = typer.Option(
            False,
            "--all-netuids",
            "--all",
            "--allnetuids",
            help="When this flag is used it sets child hotkeys on all the subnets.",
        ),
        take: Optional[float] = typer.Option(
            None,
            "--take",
            "-t",
            help="Use to set the take value for your child hotkey. When not used, the command will fetch the current "
            "take value.",
            prompt=False,
        ),
        wait_for_inclusion: bool = Options.wait_for_inclusion,
        wait_for_finalization: bool = Options.wait_for_finalization,
        prompt: bool = Options.prompt,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
        json_output: bool = Options.json_output,
    ):
        """
        Get and set your child hotkey take on a specified subnet.

        The child hotkey take must be between 0 - 18%.

        EXAMPLE

        To get the current take value, do not use the '--take' option:

            [green]$[/green] btcli stake child take --hotkey <child_hotkey> --netuid 1

        To set a new take value, use the '--take' option:

            [green]$[/green] btcli stake child take --hotkey <child_hotkey> --take 0.12 --netuid 1
        """
        self.verbosity_handler(quiet, verbose, json_output)
        wallet = self.wallet_ask(
            wallet_name,
            wallet_path,
            wallet_hotkey,
            ask_for=[WO.NAME, WO.HOTKEY],
            validate=WV.WALLET_AND_HOTKEY,
        )
        if all_netuids and netuid:
            err_console.print("Specify either a netuid or '--all', not both.")
            raise typer.Exit()
        if all_netuids:
            netuid = None
        elif not netuid:
            netuid = IntPrompt.ask(
                "Enter netuid (leave blank for all)", default=None, show_default=True
            )
        results: list[tuple[Optional[int], bool]] = self._run_command(
            children_hotkeys.childkey_take(
                wallet=wallet,
                subtensor=self.initialize_chain(network),
                netuid=netuid,
                take=take,
                hotkey=hotkey,
                wait_for_inclusion=wait_for_inclusion,
                wait_for_finalization=wait_for_finalization,
                prompt=prompt,
            )
        )
        if json_output:
            output = {}
            for netuid_, success in results:
                output[netuid_] = success
            json_console.print(json.dumps(output))
        return results

    def sudo_set(
        self,
        network: Optional[list[str]] = Options.network,
        wallet_name: str = Options.wallet_name,
        wallet_path: str = Options.wallet_path,
        wallet_hotkey: str = Options.wallet_hotkey,
        netuid: int = Options.netuid,
        param_name: str = typer.Option(
            "", "--param", "--parameter", help="The subnet hyperparameter to set"
        ),
        param_value: Optional[str] = typer.Option(
            "", "--value", help="Value to set the hyperparameter to."
        ),
        prompt: bool = Options.prompt,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
        json_output: bool = Options.json_output,
    ):
        """
        Used to set hyperparameters for a specific subnet.

        This command allows subnet owners to modify hyperparameters such as its tempo, emission rates, and other hyperparameters.

        EXAMPLE

        [green]$[/green] btcli sudo set --netuid 1 --param tempo --value 400
        """
        self.verbosity_handler(quiet, verbose, json_output)

        if not param_name or not param_value:
            hyperparams = self._run_command(
                sudo.get_hyperparameters(self.initialize_chain(network), netuid),
                exit_early=False,
            )
            if not hyperparams:
                raise typer.Exit()

        if not param_name:
            if not prompt:
                err_console.print(
                    "Param name not supplied with `--no-prompt` flag. Cannot continue"
                )
                return False
            hyperparam_list = [field.name for field in fields(SubnetHyperparameters)]
            console.print("Available hyperparameters:\n")
            for idx, param in enumerate(hyperparam_list, start=1):
                console.print(f"  {idx}. {param}")
            console.print()
            choice = IntPrompt.ask(
                "Enter the [bold]number[/bold] of the hyperparameter",
                choices=[str(i) for i in range(1, len(hyperparam_list) + 1)],
                show_choices=False,
            )
            param_name = hyperparam_list[choice - 1]

        if param_name in ["alpha_high", "alpha_low"]:
            if not prompt:
                err_console.print(
                    "`alpha_high` and `alpha_low` values cannot be set with `--no-prompt`"
                )
                return False
            param_name = "alpha_values"
            low_val = FloatPrompt.ask(
                "Enter the new value for [dark_orange]alpha_low[/dark_orange]"
            )
            high_val = FloatPrompt.ask(
                "Enter the new value for [dark_orange]alpha_high[/dark_orange]"
            )
            param_value = f"{low_val},{high_val}"

        if not param_value:
            if not prompt:
                err_console.print(
                    "Param value not supplied with `--no-prompt` flag. Cannot continue."
                )
                return False
            if HYPERPARAMS.get(param_name):
                param_value = Prompt.ask(
                    f"Enter the new value for [{COLORS.G.SUBHEAD}]{param_name}[/{COLORS.G.SUBHEAD}] "
                    f"in the VALUE column format"
                )
            else:
                param_value = None

        wallet = self.wallet_ask(
            wallet_name, wallet_path, wallet_hotkey, ask_for=[WO.NAME, WO.PATH]
        )
        result = self._run_command(
            sudo.sudo_set_hyperparameter(
                wallet,
                self.initialize_chain(network),
                netuid,
                param_name,
                param_value,
                prompt,
                json_output,
            )
        )
        if json_output:
            json_console.print(json.dumps({"success": result}))
        return result

    def sudo_get(
        self,
        network: Optional[list[str]] = Options.network,
        netuid: int = Options.netuid,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
        json_output: bool = Options.json_output,
    ):
        """
        Shows a list of the hyperparameters for the specified subnet.

        EXAMPLE

        [green]$[/green] btcli sudo get --netuid 1
        """
        self.verbosity_handler(quiet, verbose, json_output)
        return self._run_command(
            sudo.get_hyperparameters(
                self.initialize_chain(network), netuid, json_output
            )
        )

    def sudo_senate(
        self,
        network: Optional[list[str]] = Options.network,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
        json_output: bool = Options.json_output,
    ):
        """
        Shows the Senate members of the Bittensor's governance protocol.

        This command lists the delegates involved in the decision-making process of the Bittensor network, showing their names and wallet addresses. This information is crucial for understanding who holds governance roles within the network.

        EXAMPLE
        [green]$[/green] btcli sudo senate
        """
        self.verbosity_handler(quiet, verbose, json_output)
        return self._run_command(
            sudo.get_senate(self.initialize_chain(network), json_output)
        )

    def sudo_proposals(
        self,
        network: Optional[list[str]] = Options.network,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
        json_output: bool = Options.json_output,
    ):
        """
        View active proposals for the senate in the Bittensor's governance protocol.

        This command displays the details of ongoing proposals, including proposal hashes, votes, thresholds, and proposal data.

        EXAMPLE
        [green]$[/green] btcli sudo proposals
        """
        self.verbosity_handler(quiet, verbose, json_output)
        return self._run_command(
            sudo.proposals(self.initialize_chain(network), verbose, json_output)
        )

    def sudo_senate_vote(
        self,
        network: Optional[list[str]] = Options.network,
        wallet_name: Optional[str] = Options.wallet_name,
        wallet_path: Optional[str] = Options.wallet_path,
        wallet_hotkey: Optional[str] = Options.wallet_hotkey,
        proposal: str = typer.Option(
            None,
            "--proposal",
            "--proposal-hash",
            prompt="Enter the proposal hash",
            help="The hash of the proposal to vote on.",
        ),
        prompt: bool = Options.prompt,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
        vote: bool = typer.Option(
            None,
            "--vote-aye/--vote-nay",
            prompt="Enter y to vote Aye, or enter n to vote Nay",
            help="The vote casted on the proposal",
        ),
    ):
        """
        Cast a vote on an active proposal in Bittensor's governance protocol.

        This command is used by Senate members to vote on various proposals that shape the network's future. Use `btcli sudo proposals` to see the active proposals and their hashes.

        USAGE
        The user must specify the hash of the proposal they want to vote on. The command then allows the Senate member to cast a 'Yes' or 'No' vote, contributing to the decision-making process on the proposal. This command is crucial for Senate members to exercise their voting rights on key proposals. It plays a vital role in the governance and evolution of the Bittensor network.

        EXAMPLE
        [green]$[/green] btcli sudo senate_vote --proposal <proposal_hash>
        """
        # TODO discuss whether this should receive json_output. I don't think it should.
        self.verbosity_handler(quiet, verbose)
        wallet = self.wallet_ask(
            wallet_name,
            wallet_path,
            wallet_hotkey,
            ask_for=[WO.NAME, WO.PATH, WO.HOTKEY],
            validate=WV.WALLET_AND_HOTKEY,
        )
        return self._run_command(
            sudo.senate_vote(
                wallet, self.initialize_chain(network), proposal, vote, prompt
            )
        )

    def sudo_set_take(
        self,
        network: Optional[list[str]] = Options.network,
        wallet_name: Optional[str] = Options.wallet_name,
        wallet_path: Optional[str] = Options.wallet_path,
        wallet_hotkey: Optional[str] = Options.wallet_hotkey,
        take: float = typer.Option(None, help="The new take value."),
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
        json_output: bool = Options.json_output,
    ):
        """
        Allows users to change their delegate take percentage.

        This command can be used to update the delegate takes. To run the command, the user must have a configured wallet with both hotkey and coldkey.
        The command makes sure the new take value is within 0-18% range.

        EXAMPLE
        [green]$[/green] btcli sudo set-take --wallet-name my_wallet --wallet-hotkey my_hotkey
        """
        max_value = 0.18
        min_value = 0.00
        self.verbosity_handler(quiet, verbose, json_output)

        wallet = self.wallet_ask(
            wallet_name,
            wallet_path,
            wallet_hotkey,
            ask_for=[WO.NAME, WO.PATH, WO.HOTKEY],
            validate=WV.WALLET_AND_HOTKEY,
        )

        self._run_command(
            sudo.display_current_take(self.initialize_chain(network), wallet),
            exit_early=False,
        )

        if not take:
            take = FloatPrompt.ask(
                f"Enter [blue]take value[/blue] (0.18 for 18%) [blue]Min: {min_value} Max: {max_value}"
            )
        if not (min_value <= take <= max_value):
            print_error(
                f"Take value must be between {min_value} and {max_value}. Provided value: {take}"
            )
            raise typer.Exit()

        result = self._run_command(
            sudo.set_take(wallet, self.initialize_chain(network), take)
        )
        if json_output:
            json_console.print(json.dumps({"success": result}))
        return result

    def sudo_get_take(
        self,
        network: Optional[list[str]] = Options.network,
        wallet_name: Optional[str] = Options.wallet_name,
        wallet_path: Optional[str] = Options.wallet_path,
        wallet_hotkey: Optional[str] = Options.wallet_hotkey,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
        json_output: bool = Options.json_output,
    ):
        """
        Allows users to check their delegate take percentage.

        This command can be used to fetch the delegate take of your hotkey.

        EXAMPLE
        [green]$[/green] btcli sudo get-take --wallet-name my_wallet --wallet-hotkey my_hotkey
        """
        self.verbosity_handler(quiet, verbose, json_output)

        wallet = self.wallet_ask(
            wallet_name,
            wallet_path,
            wallet_hotkey,
            ask_for=[WO.NAME, WO.PATH, WO.HOTKEY],
            validate=WV.WALLET_AND_HOTKEY,
        )
        if json_output:
            result = self._run_command(
                sudo.get_current_take(self.initialize_chain(network), wallet)
            )
            json_console.print(json.dumps({"current_take": result}))
        else:
            self._run_command(
                sudo.display_current_take(self.initialize_chain(network), wallet)
            )

    def subnets_list(
        self,
        network: Optional[list[str]] = Options.network,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
        live_mode: bool = Options.live,
        json_output: bool = Options.json_output,
    ):
        """
         List all subnets and their detailed information.

         [bold]Common Examples:[/bold]

         1. List all subnets:
         [green]$[/green] btcli subnets list

         2. List all subnets in live mode:
         [green]$[/green] btcli subnets list --live

        [bold]Output Columns:[/bold]
         • [white]Netuid[/white] - Subnet identifier number
         • [white]Name[/white] - Subnet name with currency symbol (τ/α/β etc)
         • [white]Price (τ_in/α_in)[/white] - Exchange rate (TAO per alpha token)
         • [white]Market Cap (α * Price)[/white] - Total value in TAO (alpha tokens × price)
         • [white]Emission (τ)[/white] - TAO rewards emitted per block to subnet
         • [white]P (τ_in, α_in)[/white] - Pool reserves (Tao reserves, alpha reserves) in liquidity pool
         • [white]Stake (α_out)[/white] - Total staked alpha tokens across all hotkeys (alpha outstanding)
         • [white]Supply (α)[/white] - Circulating alpha token supply
         • [white]Tempo (k/n)[/white] - Block interval for subnet updates

         EXAMPLE

         [green]$[/green] btcli subnets list
        """
        if json_output and live_mode:
            print_error("Cannot use `--json-output` and `--live` at the same time.")
            return
        self.verbosity_handler(quiet, verbose, json_output)
        subtensor = self.initialize_chain(network)
        return self._run_command(
            subnets.subnets_list(
                subtensor,
                False,  # reuse-last
                False,  # html-output
                not self.config.get("use_cache", True),
                verbose,
                live_mode,
                json_output,
            )
        )

    def subnets_price(
        self,
        network: Optional[list[str]] = Options.network,
        netuids: str = Options.edit_help(
            "netuids",
            "Netuids to show the price for. Separate multiple netuids with a comma, for example: `-n 0,1,2`.",
        ),
        interval_hours: int = typer.Option(
            24,
            "--interval-hours",
            "--interval",
            help="The number of hours to show the historical price for.",
        ),
        all_netuids: bool = typer.Option(
            False,
            "--all-netuids",
            "--all",
            help="Show the price for all subnets.",
        ),
        log_scale: bool = typer.Option(
            False,
            "--log-scale",
            "--log",
            help="Show the price in log scale.",
        ),
        html_output: bool = Options.html_output,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
        json_output: bool = Options.json_output,
    ):
        """
        Shows the historical price of a subnet for the past 24 hours.

        This command displays the historical price of a subnet for the past 24 hours.
        If the `--all` flag is used, the command will display the price for all subnets in html format.
        If the `--html` flag is used, the command will display the price in an HTML chart.
        If the `--log-scale` flag is used, the command will display the price in log scale.
        If no html flag is used, the command will display the price in the cli.

        EXAMPLE

        [green]$[/green] btcli subnets price --netuid 1
        [green]$[/green] btcli subnets price --netuid 1 --html --log
        [green]$[/green] btcli subnets price --all --html
        [green]$[/green] btcli subnets price --netuids 1,2,3,4 --html
        """
        if json_output and html_output:
            print_error("Cannot specify both `--json-output` and `--html`")
            return
        self.verbosity_handler(quiet=quiet, verbose=verbose, json_output=json_output)
        if netuids:
            netuids = parse_to_list(
                netuids,
                int,
                "Netuids must be a comma-separated list of ints, e.g., `--netuids 1,2,3,4`.",
            )
        if all_netuids and netuids:
            print_error("Cannot specify both --netuid and --all-netuids")
            return

        if not netuids and not all_netuids:
            netuids = Prompt.ask(
                "Enter the [blue]netuid(s)[/blue] to view the price of in comma-separated format [dim]"
                "(or Press Enter to view all subnets)[/dim]",
            )
            if not netuids:
                all_netuids = True
            else:
                netuids = parse_to_list(
                    netuids,
                    int,
                    "Netuids must be a comma-separated list of ints, e.g., `--netuids 1,2,3,4`.",
                )

        if all_netuids and not json_output:
            html_output = True

        return self._run_command(
            price.price(
                self.initialize_chain(network),
                netuids,
                all_netuids,
                interval_hours,
                html_output,
                log_scale,
                json_output,
            )
        )

    def subnets_show(
        self,
        network: Optional[list[str]] = Options.network,
        netuid: int = Options.netuid,
        sort: bool = typer.Option(
            False,
            "--sort",
            help="Sort the subnets by uid.",
        ),
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
        prompt: bool = Options.prompt,
        json_output: bool = Options.json_output,
    ):
        """
        Displays detailed information about a subnet including participants and their state.

        EXAMPLE

        [green]$[/green] btcli subnets list
        """
        self.verbosity_handler(quiet, verbose, json_output)
        subtensor = self.initialize_chain(network)
        return self._run_command(
            subnets.show(
                subtensor=subtensor,
                netuid=netuid,
                sort=sort,
                max_rows=None,
                delegate_selection=False,
                verbose=verbose,
                prompt=prompt,
                json_output=json_output,
            )
        )

    def subnets_burn_cost(
        self,
        network: Optional[list[str]] = Options.network,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
        json_output: bool = Options.json_output,
    ):
        """
        Shows the required amount of TAO to be recycled for creating a new subnet, i.e., cost of registering a new subnet.

        The current implementation anneals the cost of creating a subnet over a period of two days. If the displayed cost is unappealing to you, check back in a day or two to see if it has decreased to a more affordable level.

        EXAMPLE

        [green]$[/green] btcli subnets burn_cost
        """
        self.verbosity_handler(quiet, verbose, json_output)
        return self._run_command(
            subnets.burn_cost(self.initialize_chain(network), json_output)
        )

    def subnets_create(
        self,
        wallet_name: str = Options.wallet_name,
        wallet_path: str = Options.wallet_path,
        wallet_hotkey: str = Options.wallet_hotkey,
        network: Optional[list[str]] = Options.network,
        subnet_name: Optional[str] = typer.Option(
            None, "--subnet-name", help="Name of the subnet"
        ),
        github_repo: Optional[str] = typer.Option(
            None, "--github-repo", "--repo", help="GitHub repository URL"
        ),
        subnet_contact: Optional[str] = typer.Option(
            None,
            "--subnet-contact",
            "--contact",
            "--email",
            help="Contact email for subnet",
        ),
        subnet_url: Optional[str] = typer.Option(
            None, "--subnet-url", "--url", help="Subnet URL"
        ),
        discord: Optional[str] = typer.Option(
            None, "--discord-handle", "--discord", help="Discord handle"
        ),
        description: Optional[str] = typer.Option(
            None, "--description", help="Description"
        ),
        logo_url: Optional[str] = typer.Option(None, "--logo-url", help="Logo URL"),
        additional_info: Optional[str] = typer.Option(
            None, "--additional-info", help="Additional information"
        ),
        json_output: bool = Options.json_output,
        prompt: bool = Options.prompt,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
    ):
        """
        Registers a new subnet on the network.

        This command allows you to create a new subnet and set the subnet's identity.
        You also have the option to set your own identity after the registration is complete.

        [bold]Common Examples:[/bold]

        1. Interactive subnet creation:
        [green]$[/green] btcli subnets create

        2. Create with GitHub repo and contact email:
        [green]$[/green] btcli subnets create --subnet-name MySubnet --github-repo https://github.com/myorg/mysubnet --subnet-contact team@mysubnet.net
        """
        self.verbosity_handler(quiet, verbose, json_output)
        wallet = self.wallet_ask(
            wallet_name,
            wallet_path,
            wallet_hotkey,
            ask_for=[
                WO.NAME,
                WO.HOTKEY,
                WO.PATH,
            ],
            validate=WV.WALLET_AND_HOTKEY,
        )
        identity = prompt_for_subnet_identity(
            current_identity={},
            subnet_name=subnet_name,
            github_repo=github_repo,
            subnet_contact=subnet_contact,
            subnet_url=subnet_url,
            discord=discord,
            description=description,
            logo_url=logo_url,
            additional=additional_info,
        )
        self._run_command(
            subnets.create(
                wallet, self.initialize_chain(network), identity, json_output, prompt
            )
        )

    def subnets_check_start(
        self,
        network: Optional[list[str]] = Options.network,
        netuid: int = Options.netuid,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
    ):
        """
        Checks if a subnet's emission schedule can be started.

        This command verifies if a subnet's emission schedule can be started based on the subnet's registration block.

        Example:
        [green]$[/green] btcli subnets check-start --netuid 1
        """
        self.verbosity_handler(quiet, verbose)
        return self._run_command(
            subnets.get_start_schedule(self.initialize_chain(network), netuid)
        )

    def subnets_start(
        self,
        wallet_name: str = Options.wallet_name,
        wallet_path: str = Options.wallet_path,
        wallet_hotkey: str = Options.wallet_hotkey,
        network: Optional[list[str]] = Options.network,
        netuid: int = Options.netuid,
        prompt: bool = Options.prompt,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
    ):
        """
        Starts a subnet's emission schedule.

        The owner of the subnet must call this command to start the emission schedule.

        Example:
        [green]$[/green] btcli subnets start --netuid 1
        [green]$[/green] btcli subnets start --netuid 1 --wallet-name alice
        """
        self.verbosity_handler(quiet, verbose)
        if not wallet_name:
            wallet_name = Prompt.ask(
                "Enter the [blue]wallet name[/blue] [dim](which you used to create the subnet)[/dim]",
                default=self.config.get("wallet_name") or defaults.wallet.name,
            )
        wallet = self.wallet_ask(
            wallet_name,
            wallet_path,
            wallet_hotkey,
            ask_for=[
                WO.NAME,
            ],
            validate=WV.WALLET,
        )
        return self._run_command(
            subnets.start_subnet(
                wallet,
                self.initialize_chain(network),
                netuid,
                prompt,
            )
        )

    def subnets_get_identity(
        self,
        network: Optional[list[str]] = Options.network,
        netuid: int = Options.netuid,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
        json_output: bool = Options.json_output,
    ):
        """
        Get the identity information for a subnet.

        This command displays the identity information of a subnet including name, GitHub repo, contact details, etc.

        [green]$[/green] btcli subnets get-identity --netuid 1
        """
        self.verbosity_handler(quiet, verbose, json_output)
        return self._run_command(
            subnets.get_identity(
                self.initialize_chain(network), netuid, json_output=json_output
            )
        )

    def subnets_set_identity(
        self,
        wallet_name: str = Options.wallet_name,
        wallet_path: str = Options.wallet_path,
        wallet_hotkey: str = Options.wallet_hotkey,
        network: Optional[list[str]] = Options.network,
        netuid: int = Options.netuid,
        subnet_name: Optional[str] = typer.Option(
            None, "--subnet-name", "--name", help="Name of the subnet"
        ),
        github_repo: Optional[str] = typer.Option(
            None, "--github-repo", "--repo", help="GitHub repository URL"
        ),
        subnet_contact: Optional[str] = typer.Option(
            None,
            "--subnet-contact",
            "--contact",
            "--email",
            help="Contact email for subnet",
        ),
        subnet_url: Optional[str] = typer.Option(
            None, "--subnet-url", "--url", help="Subnet URL"
        ),
        discord: Optional[str] = typer.Option(
            None, "--discord-handle", "--discord", help="Discord handle"
        ),
        description: Optional[str] = typer.Option(
            None, "--description", help="Description"
        ),
        logo_url: Optional[str] = typer.Option(None, "--logo-url", help="Logo URL"),
        additional_info: Optional[str] = typer.Option(
            None, "--additional-info", help="Additional information"
        ),
        json_output: bool = Options.json_output,
        prompt: bool = Options.prompt,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
    ):
        """
        Set or update the identity information for a subnet.

        This command allows subnet owners to set or update identity information like name, GitHub repo, contact details, etc.

        [bold]Common Examples:[/bold]

        1. Interactive subnet identity setting:
        [green]$[/green] btcli subnets set-identity --netuid 1

        2. Set subnet identity with specific values:
        [green]$[/green] btcli subnets set-identity --netuid 1 --subnet-name MySubnet --github-repo https://github.com/myorg/mysubnet --subnet-contact team@mysubnet.net
        """
        self.verbosity_handler(quiet, verbose, json_output)
        wallet = self.wallet_ask(
            wallet_name,
            wallet_path,
            wallet_hotkey,
            ask_for=[WO.NAME],
            validate=WV.WALLET,
        )

        current_identity = self._run_command(
            subnets.get_identity(
                self.initialize_chain(network),
                netuid,
                f"Current Subnet {netuid}'s Identity",
            ),
            exit_early=False,
        )
        if current_identity is None:
            if json_output:
                json_console.print('{"success": false}')
            return

        identity = prompt_for_subnet_identity(
            current_identity=current_identity,
            subnet_name=subnet_name,
            github_repo=github_repo,
            subnet_contact=subnet_contact,
            subnet_url=subnet_url,
            discord=discord,
            description=description,
            logo_url=logo_url,
            additional=additional_info,
        )

        success = self._run_command(
            subnets.set_identity(
                wallet, self.initialize_chain(network), netuid, identity, prompt
            )
        )
        if json_output:
            json_console.print(json.dumps({"success": success}))

    def subnets_pow_register(
        self,
        wallet_name: Optional[str] = Options.wallet_name,
        wallet_path: Optional[str] = Options.wallet_path,
        wallet_hotkey: Optional[str] = Options.wallet_hotkey,
        network: Optional[list[str]] = Options.network,
        netuid: int = Options.netuid,
        # TODO add the following to config
        processors: Optional[int] = typer.Option(
            defaults.pow_register.num_processes,
            "--processors",
            help="Number of processors to use for POW registration.",
        ),
        update_interval: Optional[int] = typer.Option(
            defaults.pow_register.update_interval,
            "--update-interval",
            "-u",
            help="The number of nonces to process before checking for the next block during registration",
        ),
        output_in_place: Optional[bool] = typer.Option(
            defaults.pow_register.output_in_place,
            help="Whether to output the registration statistics in-place.",
        ),
        verbose: Optional[bool] = typer.Option(  # TODO verbosity here
            defaults.pow_register.verbose,
            "--verbose",
            "-v",
            help="Whether to output the registration statistics verbosely.",
        ),
        use_cuda: Optional[bool] = typer.Option(
            defaults.pow_register.cuda.use_cuda,
            "--use-cuda/--no-use-cuda",
            "--cuda/--no-cuda",
            help="Set the flag to use CUDA for POW registration.",
        ),
        dev_id: Optional[int] = typer.Option(
            defaults.pow_register.cuda.dev_id,
            "--dev-id",
            "-d",
            help="Set the CUDA device id(s), in the order of the device speed (0 is the fastest).",
        ),
        threads_per_block: Optional[int] = typer.Option(
            defaults.pow_register.cuda.tpb,
            "--threads-per-block",
            "-tbp",
            help="Set the number of threads per block for CUDA.",
        ),
        prompt: bool = Options.prompt,
    ):
        """
        Register a neuron (a subnet validator or a subnet miner) using Proof of Work (POW).

        This method is an alternative registration process that uses computational work for securing a neuron's place on the subnet.

        The command starts by verifying the existence of the specified subnet. If the subnet does not exist, it terminates with an error message. On successful verification, the POW registration process is initiated, which requires solving computational puzzles.

        The command also supports additional wallet and subtensor arguments, enabling further customization of the registration process.

        EXAMPLE

        [green]$[/green] btcli pow_register --netuid 1 --num_processes 4 --cuda

        [blue bold]Note[/blue bold]: This command is suitable for users with adequate computational resources to participate in POW registration.
        It requires a sound understanding of the network's operations and POW mechanics. Users should ensure their systems meet the necessary hardware and software requirements, particularly when opting for CUDA-based GPU acceleration.

        This command may be disabled by the subnet owner. For example, on netuid 1 this is permanently disabled.
        """
        return self._run_command(
            subnets.pow_register(
                self.wallet_ask(
                    wallet_name,
                    wallet_path,
                    wallet_hotkey,
                    ask_for=[WO.NAME, WO.PATH, WO.HOTKEY],
                    validate=WV.WALLET_AND_HOTKEY,
                ),
                self.initialize_chain(network),
                netuid,
                processors,
                update_interval,
                output_in_place,
                verbose,
                use_cuda,
                dev_id,
                threads_per_block,
                prompt=prompt,
            )
        )

    def subnets_register(
        self,
        wallet_name: str = Options.wallet_name,
        wallet_path: str = Options.wallet_path,
        wallet_hotkey: str = Options.wallet_hotkey,
        network: Optional[list[str]] = Options.network,
        netuid: int = Options.netuid,
        period: Optional[
            int
        ] = typer.Option(  # Should not be Options.period bc this needs to be an Optional[int]
            None,
            "--period",
            "--era",
            help="Length (in blocks) for which the transaction should be valid. Note that it is possible that if you "
            "use an era for this transaction that you may pay a different fee to register than the one stated.",
        ),
        json_output: bool = Options.json_output,
        prompt: bool = Options.prompt,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
    ):
        """
        Register a neuron (a subnet validator or a subnet miner) in the specified subnet by recycling some TAO.

        Before registering, the command checks if the specified subnet exists and whether the user's balance is sufficient to cover the registration cost.

        The registration cost is determined by the current recycle amount for the specified subnet. If the balance is insufficient or the subnet does not exist, the command will exit with an error message.

        EXAMPLE

        [green]$[/green] btcli subnets register --netuid 1
        """
        self.verbosity_handler(quiet, verbose, json_output)
        wallet = self.wallet_ask(
            wallet_name,
            wallet_path,
            wallet_hotkey,
            ask_for=[WO.NAME, WO.HOTKEY],
            validate=WV.WALLET_AND_HOTKEY,
        )
        return self._run_command(
            subnets.register(
                wallet,
                self.initialize_chain(network),
                netuid,
                period,
                json_output,
                prompt,
            )
        )

    def subnets_metagraph(
        self,
        netuid: Optional[int] = typer.Option(
            None,
            help="The netuid of the subnet (e.g. 1). This option "
            "is ignored when used with `--reuse-last`.",
        ),
        network: Optional[list[str]] = Options.network,
        reuse_last: bool = Options.reuse_last,
        html_output: bool = Options.html_output,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
    ):
        """
        Shows the metagraph of a subnet.

        The displayed metagraph, representing a snapshot of the subnet's state at the time of calling, contains detailed information about all the neurons (subnet validator and subnet miner nodes) participating in the subnet, including the neuron's stake, trust score, and more.

        The table displayed includes the following columns for each neuron:

        - [bold]UID[/bold]: Unique identifier of the neuron.

        - [bold]STAKE(τ)[/bold]: Total stake of the neuron in TAO (τ).

        - [bold]RANK[/bold]: Rank score of the neuron.

        - [bold]TRUST[/bold]: Trust score assigned to the neuron by other neurons.

        - [bold]CONSENSUS[/bold]: Consensus score of the neuron.

        - [bold]INCENTIVE[/bold]: Incentive score representing the neuron's incentive alignment.

        - [bold]DIVIDENDS[/bold]: Dividends earned by the neuron.

        - [bold]EMISSION(p)[/bold]: Emission in rho (p) received by the neuron.

        - [bold]VTRUST[/bold]: Validator trust score indicating the network's trust in the neuron as a validator.

        - [bold]VAL[/bold]: Validator status of the neuron.

        - [bold]UPDATED[/bold]: Number of blocks since the neuron's last update.

        - [bold]ACTIVE[/bold]: Activity status of the neuron.

        - [bold]AXON[/bold]: Network endpoint information of the neuron.

        - [bold]HOTKEY[/bold]: Partial hotkey (public key) of the neuron.

        - [bold]COLDKEY[/bold]: Partial coldkey (public key) of the neuron.

        The command also prints network-wide statistics such as total stake, issuance, and difficulty.

        The user must specify the netuid to query the metagraph. If not specified, the default netuid from the config is used.

        EXAMPLE

        Show the metagraph of the root network (netuid 0) on finney (mainnet):

            [green]$[/green] btcli subnet metagraph --netuid 0

        Show the metagraph of subnet 1 on the testnet:

            [green]$[/green] btcli subnet metagraph --netuid 1 --network test

        [blue bold]Note[/blue bold]: This command is not intended to be used as a standalone function within user code.
        """
        self.verbosity_handler(quiet, verbose)
        if (reuse_last or html_output) and self.config.get("use_cache") is False:
            err_console.print(
                "Unable to use `--reuse-last` or `--html` when config `no-cache` is set to `True`. "
                "Set the`no-cache` field to `False` by using `btcli config set` or editing the config.yml file."
            )
            raise typer.Exit()

        # For Rao games
        effective_network = get_effective_network(self.config, network)
        if is_rao_network(effective_network):
            print_error("This command is disabled on the 'rao' network.")
            raise typer.Exit()

        if reuse_last:
            if netuid is not None:
                console.print("Cannot specify netuid when using `--reuse-last`")
                raise typer.Exit()
            subtensor = None
        else:
            if netuid is None:
                netuid = rich.prompt.IntPrompt.ask("Enter the netuid (e.g. 1)")
            subtensor = self.initialize_chain(network)

        return self._run_command(
            subnets.metagraph_cmd(
                subtensor,
                netuid,
                reuse_last,
                html_output,
                not self.config.get("use_cache", True),
                self.config.get("metagraph_cols", {}),
            )
        )

    def weights_reveal(
        self,
        network: Optional[list[str]] = Options.network,
        wallet_name: str = Options.wallet_name,
        wallet_path: str = Options.wallet_path,
        wallet_hotkey: str = Options.wallet_hotkey,
        netuid: int = Options.netuid,
        uids: str = typer.Option(
            None,
            "--uids",
            "-u",
            help="Corresponding UIDs for the specified netuid, e.g. -u 1,2,3 ...",
        ),
        weights: str = Options.weights,
        salt: str = typer.Option(
            None,
            "--salt",
            "-s",
            help="Corresponding salt for the hash function, e.g. -s 163,241,217 ...",
        ),
        json_output: bool = Options.json_output,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
        prompt: bool = Options.prompt,
    ):
        """
        Reveal weights for a specific subnet.

        You must specify the netuid, the UIDs you are interested in, and weights you wish to reveal.

        EXAMPLE

        [green]$[/green] btcli wt reveal --netuid 1 --uids 1,2,3,4 --weights 0.1,0.2,0.3,0.4 --salt 163,241,217,11,161,142,147,189
        """
        self.verbosity_handler(quiet, verbose, json_output)
        uids = list_prompt(uids, int, "UIDs of interest for the specified netuid")
        weights = list_prompt(
            weights, float, "Corresponding weights for the specified UIDs"
        )
        if uids:
            uids = parse_to_list(
                uids,
                int,
                "Uids must be a comma-separated list of ints, e.g., `--uids 1,2,3,4`.",
            )
        else:
            uids = list_prompt(
                uids, int, "Corresponding UIDs for the specified netuid (eg: 1,2,3)"
            )

        if weights:
            weights = parse_to_list(
                weights,
                float,
                "Weights must be a comma-separated list of floats, e.g., `--weights 0.3,0.4,0.3`.",
            )
        else:
            weights = list_prompt(
                weights,
                float,
                "Corresponding weights for the specified UIDs (eg: 0.2,0.3,0.4)",
            )

        if len(uids) != len(weights):
            err_console.print(
                "The number of UIDs you specify must match up with the specified number of weights"
            )
            return

        if salt:
            salt = parse_to_list(
                salt,
                int,
                "Salt must be a comma-separated list of ints, e.g., `--weights 123,163,194`.",
            )
        else:
            salt = list_prompt(salt, int, "Corresponding salt for the hash function")

        wallet = self.wallet_ask(
            wallet_name,
            wallet_path,
            wallet_hotkey,
            ask_for=[WO.NAME, WO.PATH, WO.HOTKEY],
            validate=WV.WALLET_AND_HOTKEY,
        )

        return self._run_command(
            weights_cmds.reveal_weights(
                self.initialize_chain(network),
                wallet,
                netuid,
                uids,
                weights,
                salt,
                __version_as_int__,
                prompt=prompt,
                json_output=json_output,
            )
        )

    def weights_commit(
        self,
        network: Optional[list[str]] = Options.network,
        wallet_name: str = Options.wallet_name,
        wallet_path: str = Options.wallet_path,
        wallet_hotkey: str = Options.wallet_hotkey,
        netuid: int = Options.netuid,
        uids: str = typer.Option(
            None,
            "--uids",
            "-u",
            help="UIDs of interest for the specified netuid, e.g. -u 1,2,3 ...",
        ),
        weights: str = Options.weights,
        salt: str = typer.Option(
            None,
            "--salt",
            "-s",
            help="Corresponding salt for the hash function, e.g. -s 163 -s 241 -s 217 ...",
        ),
        json_output: bool = Options.json_output,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
        prompt: bool = Options.prompt,
    ):
        """

        Commit weights for specific subnet.

        Use this command to commit weights for a specific subnet. You must specify the netuid, the UIDs you are interested in, and the weights you wish to commit.

        EXAMPLE

        [green]$[/green] btcli wt commit --netuid 1 --uids 1,2,3,4 --w 0.1,0.2,0.3

        [italic]Note[/italic]: This command is used to commit weights for a specific subnet and requires the user to have the necessary
        permissions.
        """
        self.verbosity_handler(quiet, verbose, json_output)

        if uids:
            uids = parse_to_list(
                uids,
                int,
                "Uids must be a comma-separated list of ints, e.g., `--uids 1,2,3,4`.",
            )
        else:
            uids = list_prompt(
                uids, int, "UIDs of interest for the specified netuid (eg: 1,2,3)"
            )

        if weights:
            weights = parse_to_list(
                weights,
                float,
                "Weights must be a comma-separated list of floats, e.g., `--weights 0.3,0.4,0.3`.",
            )
        else:
            weights = list_prompt(
                weights,
                float,
                "Corresponding weights for the specified UIDs (eg: 0.2,0.3,0.4)",
            )
        if len(uids) != len(weights):
            err_console.print(
                "The number of UIDs you specify must match up with the specified number of weights"
            )
            return

        if salt:
            salt = parse_to_list(
                salt,
                int,
                "Salt must be a comma-separated list of ints, e.g., `--weights 123,163,194`.",
            )
        else:
            salt = list_prompt(salt, int, "Corresponding salt for the hash function")

        wallet = self.wallet_ask(
            wallet_name,
            wallet_path,
            wallet_hotkey,
            ask_for=[WO.NAME, WO.PATH, WO.HOTKEY],
            validate=WV.WALLET_AND_HOTKEY,
        )
        return self._run_command(
            weights_cmds.commit_weights(
                self.initialize_chain(network),
                wallet,
                netuid,
                uids,
                weights,
                salt,
                __version_as_int__,
                json_output=json_output,
                prompt=prompt,
            )
        )

    def view_dashboard(
        self,
        network: Optional[list[str]] = Options.network,
        wallet_name: str = Options.wallet_name,
        wallet_path: str = Options.wallet_path,
        wallet_hotkey: str = Options.wallet_hotkey,
        coldkey_ss58: Optional[str] = typer.Option(
            None,
            "--coldkey-ss58",
            "--ss58",
            help="Coldkey SS58 address to view dashboard for",
        ),
        use_wry: bool = typer.Option(
            False, "--use-wry", "--html", help="Display output in browser window."
        ),
        save_file: bool = typer.Option(
            False, "--save-file", "--save", help="Save the dashboard HTML file"
        ),
        dashboard_path: Optional[str] = Options.dashboard_path,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
    ):
        """
        Display html dashboard with subnets list, stake, and neuron information.
        """
        self.verbosity_handler(quiet, verbose)

        if use_wry and save_file:
            print_error("Cannot save file when using browser output.")
            return

        if save_file:
            if not dashboard_path:
                dashboard_path = Prompt.ask(
                    "Enter the [blue]path[/blue] where the dashboard HTML file will be saved",
                    default=self.config.get("dashboard_path")
                    or defaults.dashboard.path,
                )

        if coldkey_ss58:
            if not is_valid_ss58_address(coldkey_ss58):
                print_error(f"Invalid SS58 address: {coldkey_ss58}")
                raise typer.Exit()
            wallet = None
        else:
            wallet = self.wallet_ask(
                wallet_name, wallet_path, wallet_hotkey, ask_for=[WO.NAME, WO.PATH]
            )

        return self._run_command(
            view.display_network_dashboard(
                wallet=wallet,
                subtensor=self.initialize_chain(network),
                use_wry=use_wry,
                save_file=save_file,
                dashboard_path=dashboard_path,
                coldkey_ss58=coldkey_ss58,
            )
        )

    def liquidity_add(
        self,
        network: Optional[list[str]] = Options.network,
        wallet_name: str = Options.wallet_name,
        wallet_path: str = Options.wallet_path,
        wallet_hotkey: str = Options.wallet_hotkey,
        netuid: Optional[int] = Options.netuid,
        liquidity_: Optional[float] = typer.Option(
            None,
            "--liquidity",
            help="Amount of liquidity to add to the subnet.",
        ),
        price_low: Optional[float] = typer.Option(
            None,
            "--price-low",
            "--price_low",
            "--liquidity-price-low",
            "--liquidity_price_low",
            help="Low price for the adding liquidity position.",
        ),
        price_high: Optional[float] = typer.Option(
            None,
            "--price-high",
            "--price_high",
            "--liquidity-price-high",
            "--liquidity_price_high",
            help="High price for the adding liquidity position.",
        ),
        prompt: bool = Options.prompt,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
        json_output: bool = Options.json_output,
    ):
        """Add liquidity to the swap (as a combination of TAO + Alpha)."""
        self.verbosity_handler(quiet, verbose, json_output)
        if not netuid:
            netuid = Prompt.ask(
                f"Enter the [{COLORS.G.SUBHEAD_MAIN}]netuid[/{COLORS.G.SUBHEAD_MAIN}] to use",
                default=None,
                show_default=False,
            )

        wallet, hotkey = self.wallet_ask(
            wallet_name=wallet_name,
            wallet_path=wallet_path,
            wallet_hotkey=wallet_hotkey,
            ask_for=[WO.NAME, WO.HOTKEY, WO.PATH],
            validate=WV.WALLET,
            return_wallet_and_hotkey=True,
        )
        # Determine the liquidity amount.
        if liquidity_:
            liquidity_ = Balance.from_tao(liquidity_)
        else:
            liquidity_ = prompt_liquidity("Enter the amount of liquidity")

        # Determine price range
        if price_low:
            price_low = Balance.from_tao(price_low)
        else:
            price_low = prompt_liquidity("Enter liquidity position low price")

        if price_high:
            price_high = Balance.from_tao(price_high)
        else:
            price_high = prompt_liquidity(
                "Enter liquidity position high price (must be greater than low price)"
            )

        if price_low >= price_high:
            err_console.print("The low price must be lower than the high price.")
            return False

        return self._run_command(
            liquidity.add_liquidity(
                subtensor=self.initialize_chain(network),
                wallet=wallet,
                hotkey_ss58=hotkey,
                netuid=netuid,
                liquidity=liquidity_,
                price_low=price_low,
                price_high=price_high,
                prompt=prompt,
                json_output=json_output,
            )
        )

    def liquidity_list(
        self,
        network: Optional[list[str]] = Options.network,
        wallet_name: str = Options.wallet_name,
        wallet_path: str = Options.wallet_path,
        wallet_hotkey: str = Options.wallet_hotkey,
        netuid: Optional[int] = Options.netuid,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
        json_output: bool = Options.json_output,
    ):
        """Displays liquidity positions in given subnet."""
        self.verbosity_handler(quiet, verbose, json_output)
        if not netuid:
            netuid = IntPrompt.ask(
                f"Enter the [{COLORS.G.SUBHEAD_MAIN}]netuid[/{COLORS.G.SUBHEAD_MAIN}] to use",
                default=None,
                show_default=False,
            )

        wallet = self.wallet_ask(
            wallet_name=wallet_name,
            wallet_path=wallet_path,
            wallet_hotkey=wallet_hotkey,
            ask_for=[WO.NAME, WO.PATH],
            validate=WV.WALLET,
        )
        self._run_command(
            liquidity.show_liquidity_list(
                subtensor=self.initialize_chain(network),
                wallet=wallet,
                netuid=netuid,
                json_output=json_output,
            )
        )

    def liquidity_remove(
        self,
        network: Optional[list[str]] = Options.network,
        wallet_name: str = Options.wallet_name,
        wallet_path: str = Options.wallet_path,
        wallet_hotkey: str = Options.wallet_hotkey,
        netuid: Optional[int] = Options.netuid,
        position_id: Optional[int] = typer.Option(
            None,
            "--position-id",
            "--position_id",
            help="Position ID for modification or removal.",
        ),
        all_liquidity_ids: Optional[bool] = typer.Option(
            False,
            "--all",
            "--a",
            help="Whether to remove all liquidity positions for given subnet.",
        ),
        prompt: bool = Options.prompt,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
        json_output: bool = Options.json_output,
    ):
        """Remove liquidity from the swap (as a combination of TAO + Alpha)."""

        self.verbosity_handler(quiet, verbose, json_output)

        if all_liquidity_ids and position_id:
            print_error("Cannot specify both --all and --position-id.")
            return

        if not position_id and not all_liquidity_ids:
            position_id = prompt_position_id()

        if not netuid:
            netuid = IntPrompt.ask(
                f"Enter the [{COLORS.G.SUBHEAD_MAIN}]netuid[/{COLORS.G.SUBHEAD_MAIN}] to use",
                default=None,
                show_default=False,
            )

        wallet, hotkey = self.wallet_ask(
            wallet_name=wallet_name,
            wallet_path=wallet_path,
            wallet_hotkey=wallet_hotkey,
            ask_for=[WO.NAME, WO.HOTKEY, WO.PATH],
            validate=WV.WALLET,
            return_wallet_and_hotkey=True,
        )
        return self._run_command(
            liquidity.remove_liquidity(
                subtensor=self.initialize_chain(network),
                wallet=wallet,
                hotkey_ss58=hotkey,
                netuid=netuid,
                position_id=position_id,
                prompt=prompt,
                all_liquidity_ids=all_liquidity_ids,
                json_output=json_output,
            )
        )

    def liquidity_modify(
        self,
        network: Optional[list[str]] = Options.network,
        wallet_name: str = Options.wallet_name,
        wallet_path: str = Options.wallet_path,
        wallet_hotkey: str = Options.wallet_hotkey,
        netuid: Optional[int] = Options.netuid,
        position_id: Optional[int] = typer.Option(
            None,
            "--position-id",
            "--position_id",
            help="Position ID for modification or removing.",
        ),
        liquidity_delta: Optional[float] = typer.Option(
            None,
            "--liquidity-delta",
            "--liquidity_delta",
            help="Liquidity amount for modification.",
        ),
        prompt: bool = Options.prompt,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
        json_output: bool = Options.json_output,
    ):
        """Modifies the liquidity position for the given subnet."""
        self.verbosity_handler(quiet, verbose, json_output)
        if not netuid:
            netuid = IntPrompt.ask(
                f"Enter the [{COLORS.G.SUBHEAD_MAIN}]netuid[/{COLORS.G.SUBHEAD_MAIN}] to use",
            )

        wallet, hotkey = self.wallet_ask(
            wallet_name=wallet_name,
            wallet_path=wallet_path,
            wallet_hotkey=wallet_hotkey,
            ask_for=[WO.NAME, WO.HOTKEY, WO.PATH],
            validate=WV.WALLET,
            return_wallet_and_hotkey=True,
        )

        if not position_id:
            position_id = prompt_position_id()

        if liquidity_delta:
            liquidity_delta = Balance.from_tao(liquidity_delta)
        else:
            liquidity_delta = prompt_liquidity(
                f"Enter the [blue]liquidity delta[/blue] to modify position with id "
                f"[blue]{position_id}[/blue] (can be positive or negative)",
                negative_allowed=True,
            )

        return self._run_command(
            liquidity.modify_liquidity(
                subtensor=self.initialize_chain(network),
                wallet=wallet,
                hotkey_ss58=hotkey,
                netuid=netuid,
                position_id=position_id,
                liquidity_delta=liquidity_delta,
                prompt=prompt,
                json_output=json_output,
            )
        )

    @staticmethod
    @utils_app.command("convert")
    def convert(
        from_rao: Optional[str] = typer.Option(
            None, "--rao", help="Convert amount from Rao"
        ),
        from_tao: Optional[float] = typer.Option(
            None, "--tao", help="Convert amount from Tao"
        ),
    ):
        """
        Allows for converting between tao and rao using the specified flags
        """
        if from_tao is None and from_rao is None:
            err_console.print("Specify `--rao` and/or `--tao`.")
            raise typer.Exit()
        if from_rao is not None:
            rao = int(float(from_rao))
            console.print(
                f"{rao}{Balance.rao_unit}",
                "=",
                Balance.from_rao(rao),
            )
        if from_tao is not None:
            tao = float(from_tao)
            console.print(
                f"{Balance.unit}{tao}",
                "=",
                f"{Balance.from_tao(tao).rao}{Balance.rao_unit}",
            )

    def run(self):
        self.app()


def main():
    manager = CLIManager()
    manager.run()


if __name__ == "__main__":
    main()
