#!/usr/bin/env python3
import asyncio
import curses
import os.path
import re
import ssl
import sys
from pathlib import Path
from typing import Coroutine, Optional
from dataclasses import fields

import rich
import typer
import numpy as np
from bittensor_wallet import Wallet
from rich import box
from rich.prompt import Confirm, FloatPrompt, Prompt, IntPrompt
from rich.table import Column, Table
from bittensor_cli.src import (
    defaults,
    HELP_PANELS,
    WalletOptions as WO,
    WalletValidationTypes as WV,
    Constants,
    COLOR_PALETTE,
)
from bittensor_cli.src.bittensor import utils
from bittensor_cli.src.bittensor.balances import Balance
from bittensor_cli.src.bittensor.async_substrate_interface import (
    SubstrateRequestException,
)
from bittensor_cli.src.commands import sudo, wallets
from bittensor_cli.src.commands import weights as weights_cmds
from bittensor_cli.src.commands.subnets import price, subnets
from bittensor_cli.src.commands.stake import children_hotkeys, stake, move
from bittensor_cli.src.bittensor.subtensor_interface import SubtensorInterface
from bittensor_cli.src.bittensor.chain_data import SubnetHyperparameters
from bittensor_cli.src.bittensor.utils import (
    console,
    err_console,
    verbose_console,
    is_valid_ss58_address,
    print_error,
    validate_chain_endpoint,
    validate_netuid,
    is_rao_network,
    get_effective_network,
    prompt_for_identity,
    validate_uri,
    prompt_for_subnet_identity,
    print_linux_dependency_message,
    is_linux,
)
from typing_extensions import Annotated
from textwrap import dedent
from websockets import ConnectionClosed
from yaml import safe_dump, safe_load

try:
    from git import Repo, GitError
except ImportError:

    class GitError(Exception):
        pass


__version__ = "8.2.0rc15"


_core_version = re.match(r"^\d+\.\d+\.\d+", __version__).group(0)
_version_split = _core_version.split(".")
__version_info__ = tuple(int(part) for part in _version_split)
_version_int_base = 1000
assert max(__version_info__) < _version_int_base

__version_as_int__: int = sum(
    e * (_version_int_base**i) for i, e in enumerate(reversed(__version_info__))
)
assert __version_as_int__ < 2**31  # fits in int32
__new_signature_version__ = 360

_epilog = "Made with [bold red]:heart:[/bold red] by The Openτensor Foundaτion"

np.set_printoptions(precision=8, suppress=True, floatmode="fixed")


class Options:
    """
    Re-usable typer args
    """

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
    mnemonic = typer.Option(
        None,
        help="Mnemonic used to regenerate your key. For example: horse cart dog ...",
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
        is_flag=True,
        flag_value=False,
    )
    public_hex_key = typer.Option(None, help="The public key in hex format.")
    ss58_address = typer.Option(
        None, "--ss58", "--ss58-address", help="The SS58 address of the coldkey."
    )
    overwrite_coldkey = typer.Option(
        False,
        help="Overwrite the old coldkey with the newly generated coldkey.",
        prompt=True,
    )
    overwrite_hotkey = typer.Option(
        False,
        help="Overwrite the old hotkey with the newly generated hotkey.",
        prompt=True,
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
        help="The netuid of the subnet in the root network, (e.g. 1).",
        prompt=True,
        callback=validate_netuid,
    )
    netuid_not_req = typer.Option(
        None,
        help="The netuid of the subnet in the root network, (e.g. 1).",
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
    csv_output = typer.Option(
        False,
        "--csv",
        help="Output as a csv",
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
        help="If `True`, waits until the transaction is finalized "
        "on the blockchain.",
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
    :param verbosity_level: int corresponding to verbosity level of console output (0 is quiet, 1 is normal, 2 is verbose)
    """
    if verbosity_level not in range(3):
        raise ValueError(
            f"Invalid verbosity level: {verbosity_level}. Must be one of: 0 (quiet), 1 (normal), 2 (verbose)"
        )
    if verbosity_level == 0:
        console.quiet = True
        err_console.quiet = True
        verbose_console.quiet = True
    elif verbosity_level == 1:
        console.quiet = False
        err_console.quiet = False
        verbose_console.quiet = True
    elif verbosity_level == 2:
        console.quiet = False
        err_console.quiet = False
        verbose_console.quiet = False


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
            f"Enter the [{COLOR_PALETTE['GENERAL']['SUBHEADING_MAIN']}]netuid[/{COLOR_PALETTE['GENERAL']['SUBHEADING_MAIN']}] to use. Leave blank for all netuids",
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
    json: Optional[str],
    json_password: Optional[str],
) -> tuple[str, str, str, str]:
    """
    Determines which of the key creation elements have been supplied, if any. If None have been supplied,
    prompts to user, and determines what they've supplied. Returns all elements in a tuple.
    """
    if not mnemonic and not seed and not json:
        prompt_answer = Prompt.ask(
            "Enter the mnemonic, or the seed hex string, or the location of the JSON file."
        )
        if prompt_answer.startswith("0x"):
            seed = prompt_answer
        elif len(prompt_answer.split(" ")) > 1:
            mnemonic = parse_mnemonic(prompt_answer)
        else:
            json = prompt_answer
    elif mnemonic:
        mnemonic = parse_mnemonic(mnemonic)

    if json:
        if not os.path.exists(json):
            print_error(f"The JSON file '{json}' does not exist.")
            raise typer.Exit()

    if json and not json_password:
        json_password = Prompt.ask(
            "Enter the backup password for JSON file.", password=True
        )
    return mnemonic, seed, json, json_password


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
        except (NameError, GitError):
            version = f"BTCLI version: {__version__}"
        typer.echo(version)
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

    def __init__(self):
        self.config = {
            "wallet_name": None,
            "wallet_path": None,
            "wallet_hotkey": None,
            "network": None,
            "use_cache": True,
            "metagraph_cols": {
                "UID": True,
                "GLOBAL_STAKE": True,
                "LOCAL_STAKE": True,
                "STAKE_WEIGHT": True,
                "RANK": True,
                "TRUST": True,
                "CONSENSUS": True,
                "INCENTIVE": True,
                "DIVIDENDS": True,
                "EMISSION": True,
                "VTRUST": True,
                "VAL": True,
                "UPDATED": True,
                "ACTIVE": True,
                "AXON": True,
                "HOTKEY": True,
                "COLDKEY": True,
            },
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

        # config commands
        self.config_app.command("set")(self.set_config)
        self.config_app.command("get")(self.get_config)
        self.config_app.command("clear")(self.del_config)
        self.config_app.command("metagraph")(self.metagraph_config)

        # wallet commands
        self.wallet_app.command(
            "list", rich_help_panel=HELP_PANELS["WALLET"]["MANAGEMENT"]
        )(self.wallet_list)
        self.wallet_app.command(
            "swap-hotkey", rich_help_panel=HELP_PANELS["WALLET"]["SECURITY"]
        )(self.wallet_swap_hotkey)
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

        # weights commands
        self.weights_app.command(
            "reveal", rich_help_panel=HELP_PANELS["WEIGHTS"]["COMMIT_REVEAL"]
        )(self.weights_reveal)
        self.weights_app.command(
            "commit", rich_help_panel=HELP_PANELS["WEIGHTS"]["COMMIT_REVEAL"]
        )(self.weights_commit)

        # Sub command aliases
        # Weights
        self.wallet_app.command(
            "swap_hotkey",
            hidden=True,
        )(self.wallet_swap_hotkey)
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

        # Subnets
        self.subnets_app.command("burn_cost", hidden=True)(self.subnets_burn_cost)
        self.subnets_app.command("pow_register", hidden=True)(self.subnets_pow_register)

        # Sudo
        self.sudo_app.command("senate_vote", hidden=True)(self.sudo_senate_vote)
        self.sudo_app.command("get_take", hidden=True)(self.sudo_get_take)
        self.sudo_app.command("set_take", hidden=True)(self.sudo_set_take)

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
        if not self.subtensor:
            if network:
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
                    f"Using the specified network [{COLOR_PALETTE['GENERAL']['LINKS']}]{self.config['network']}[/{COLOR_PALETTE['GENERAL']['LINKS']}] from config"
                )
            else:
                self.subtensor = SubtensorInterface(defaults.subtensor.network)
        return self.subtensor

    def _run_command(self, cmd: Coroutine) -> None:
        """
        Runs the supplied coroutine with `asyncio.run`
        """

        async def _run():
            try:
                if self.subtensor:
                    async with self.subtensor:
                        result = await cmd
                else:
                    result = await cmd
                return result
            except (ConnectionRefusedError, ssl.SSLError):
                err_console.print(f"Unable to connect to the chain: {self.subtensor}")
                asyncio.create_task(cmd).cancel()
                raise typer.Exit()
            except ConnectionClosed:
                asyncio.create_task(cmd).cancel()
                raise typer.Exit()
            except SubstrateRequestException as e:
                err_console.print(str(e))
                raise typer.Exit()

        if sys.version_info < (3, 10):
            # For Python 3.9 or lower
            return asyncio.get_event_loop().run_until_complete(_run())
        else:
            # For Python 3.10 or higher
            return asyncio.run(_run())

    def main_callback(
        self,
        version: Annotated[
            Optional[bool], typer.Option("--version", callback=version_callback)
        ] = None,
    ):
        """
        Command line interface (CLI) for Bittensor. Uses the values in the configuration file. These values can be overriden by passing them explicitly in the command line.
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

    def verbosity_handler(self, quiet: bool, verbose: bool):
        if quiet and verbose:
            err_console.print("Cannot specify both `--quiet` and `--verbose`")
            raise typer.Exit()

        if quiet:
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
    ):
        """
        Sets the values in the config file. To set the metagraph configuration, use the command `btcli config metagraph`
        """
        args = {
            "wallet_name": wallet_name,
            "wallet_path": wallet_path,
            "wallet_hotkey": wallet_hotkey,
            "network": network,
            "use_cache": use_cache,
        }
        bools = ["use_cache"]
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
        all_items: bool = typer.Option(False, "--all"),
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

            elif key in deprecated_configs:
                continue

            if isinstance(value, dict):
                # Nested dictionaries: only metagraph for now, but more may be added later
                for idx, (sub_key, sub_value) in enumerate(value.items()):
                    table.add_row(key if idx == 0 else "", str(sub_key), str(sub_value))
            else:
                table.add_row(str(key), str(value), "")

        console.print(table)
        console.print(
            dedent(
                """
            [red]Deprecation notice[/red]: The chain endpoint config is now deprecated. You can use the network config to pass chain endpoints.
            """
            )
        )

    def wallet_ask(
        self,
        wallet_name: Optional[str],
        wallet_path: Optional[str],
        wallet_hotkey: Optional[str],
        ask_for: list[str] = [],
        validate: WV = WV.WALLET,
    ) -> Wallet:
        """
        Generates a wallet object based on supplied values, validating the wallet is valid if flag is set
        :param wallet_name: name of the wallet
        :param wallet_path: root path of the wallets
        :param wallet_hotkey: name of the wallet hotkey file
        :param validate: flag whether to check for the wallet's validity
        :param ask_type: aspect of the wallet (name, path, hotkey) to prompt the user for
        :return: created Wallet object
        """
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
                    + f" [{COLOR_PALETTE['GENERAL']['HINT']} italic](Hint: You can set this with `btcli config set --wallet-name`)",
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
                    "Enter the [blue]wallet hotkey[/blue]"
                    + " [dark_sea_green3 italic](Hint: You can set this with `btcli config set --wallet-hotkey`)[/dark_sea_green3 italic]",
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
                + " [dark_sea_green3 italic](Hint: You can set this with `btcli config set --wallet-path`)[/dark_sea_green3 italic]",
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
        return wallet

    def wallet_list(
        self,
        wallet_path: str = Options.wallet_path,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
    ):
        """
        Displays all the wallets and their corresponding hotkeys that are located in the wallet path specified in the config.

        The output display shows each wallet and its associated `ss58` addresses for the coldkey public key and any hotkeys. The output is presented in a hierarchical tree format, with each wallet as a root node and any associated hotkeys as child nodes. The `ss58` address is displayed for each coldkey and hotkey that is not encrypted and exists on the device.

        Upon invocation, the command scans the wallet directory and prints a list of all the wallets, indicating whether the
        public keys are available (`?` denotes unavailable or encrypted keys).

        # EXAMPLE

        [green]$[/green] btcli wallet list --path ~/.bittensor

        [bold]NOTE[/bold]: This command is read-only and does not modify the filesystem or the blockchain state. It is intended for use with the Bittensor CLI to provide a quick overview of the user's wallets.
        """
        self.verbosity_handler(quiet, verbose)
        wallet = self.wallet_ask(
            None, wallet_path, None, ask_for=[WO.PATH], validate=WV.NONE
        )
        return self._run_command(wallets.wallet_list(wallet.path))

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
    ):
        """
        Displays a detailed overview of the user's registered accounts on the Bittensor network.

        This command compiles and displays comprehensive information about each neuron associated with the user's wallets, including both hotkeys and coldkeys. It is especially useful for users managing multiple accounts or looking for a summary of their network activities and stake distributions.

        USAGE

        The command offers various options to customize the output. Users can filter the displayed data by specific
        netuid, sort by different criteria, and choose to include all the wallets in the user's wallet path location.
        The output is presented in a tabular format with the following columns:

        - COLDKEY: The SS58 address of the coldkey.

        - HOTKEY: The SS58 address of the hotkey.

        - UID: Unique identifier of the neuron.

        - ACTIVE: Indicates if the neuron is active.

        - STAKE(τ): Amount of stake in the neuron, in TAO.

        - RANK: The rank of the neuron within the network.

        - TRUST: Trust score of the neuron.

        - CONSENSUS: Consensus score of the neuron.

        - INCENTIVE: Incentive score of the neuron.

        - DIVIDENDS: Dividends earned by the neuron.

        - EMISSION(p): Emission received by the neuron, expressed in rho.

        - VTRUST: Validator trust score of the neuron.

        - VPERMIT: Indicates if the neuron has a validator permit.

        - UPDATED: Time since last update.

        - AXON: IP address and port of the neuron.

        - HOTKEY_SS58: Human-readable representation of the hotkey.


        # EXAMPLE:

        [green]$[/green] btcli wallet overview

        [green]$[/green] btcli wallet overview --all --sort-by stake --sort-order descending

        [green]$[/green] btcli wallet overview -in hk1,hk2 --sort-by stake

        [bold]NOTE[/bold]: This command is read-only and does not modify the blockchain state or account configuration.
        It provides a quick and comprehensive view of the user's network presence, making it useful for monitoring account status,
        stake distribution, and overall contribution to the Bittensor network.
        """
        self.verbosity_handler(quiet, verbose)
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

        ask_for = [WO.NAME, WO.PATH] if not all_wallets else [WO.PATH]
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
            prompt=True,
            help="Amount (in TAO) to transfer.",
        ),
        wallet_name: str = Options.wallet_name,
        wallet_path: str = Options.wallet_path,
        wallet_hotkey: str = Options.wallet_hotkey,
        network: Optional[list[str]] = Options.network,
        prompt: bool = Options.prompt,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
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

        self.verbosity_handler(quiet, verbose)
        wallet = self.wallet_ask(
            wallet_name,
            wallet_path,
            wallet_hotkey,
            ask_for=[WO.NAME, WO.PATH],
            validate=WV.WALLET,
        )

        # For Rao games - temporarilyt commented out
        effective_network = get_effective_network(self.config, network)
        # if is_rao_network(effective_network):
        #     print_error("This command is disabled on the 'rao' network.")
        #     raise typer.Exit()

        subtensor = self.initialize_chain(network)
        return self._run_command(
            wallets.transfer(
                wallet, subtensor, destination_ss58_address, amount, prompt
            )
        )

    def wallet_swap_hotkey(
        self,
        wallet_name: Optional[str] = Options.wallet_name,
        wallet_path: Optional[str] = Options.wallet_path,
        wallet_hotkey: Optional[str] = Options.wallet_hotkey,
        network: Optional[list[str]] = Options.network,
        destination_hotkey_name: Optional[str] = typer.Argument(
            None, help="Destination hotkey name."
        ),
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
        prompt: bool = Options.prompt,
    ):
        """
        Swap hotkeys of a given wallet on the blockchain. For a registered key pair, for example, a (coldkeyA, hotkeyA) pair, this command swaps the hotkeyA with a new, unregistered, hotkeyB to move the original registration to the (coldkeyA, hotkeyB) pair.

        USAGE

        The command is used to swap the hotkey of a wallet for another hotkey on that same wallet.

        IMPORTANT

        - Make sure that your original key pair (coldkeyA, hotkeyA) is already registered.
        - Make sure that you use a newly created hotkeyB in this command. A hotkeyB that is already registered cannot be used in this command.
        - Finally, note that this command requires a fee of 1 TAO for recycling and this fee is taken from your wallet (coldkeyA).

        EXAMPLE

        [green]$[/green] btcli wallet swap_hotkey destination_hotkey_name --wallet-name your_wallet_name --wallet-hotkey original_hotkey
        """
        self.verbosity_handler(quiet, verbose)
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
            wallets.swap_hotkey(original_wallet, new_wallet, self.subtensor, prompt)
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
        self.verbosity_handler(quiet, verbose)

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
            )
        )

    def wallet_regen_coldkey(
        self,
        wallet_name: Optional[str] = Options.wallet_name,
        wallet_path: Optional[str] = Options.wallet_path,
        wallet_hotkey: Optional[str] = Options.wallet_hotkey,
        mnemonic: Optional[str] = Options.mnemonic,
        seed: Optional[str] = Options.seed,
        json: Optional[str] = Options.json,
        json_password: Optional[str] = Options.json_password,
        use_password: Optional[bool] = Options.use_password,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
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
        self.verbosity_handler(quiet, verbose)

        if not wallet_path:
            wallet_path = Prompt.ask(
                "Enter the path for the wallets directory", default=defaults.wallet.path
            )
            wallet_path = os.path.expanduser(wallet_path)

        if not wallet_name:
            wallet_name = Prompt.ask(
                f"Enter the name of the [{COLOR_PALETTE['GENERAL']['COLDKEY']}]new wallet (coldkey)",
                default=defaults.wallet.name,
            )

        wallet = Wallet(wallet_name, wallet_hotkey, wallet_path)

        mnemonic, seed, json, json_password = get_creation_data(
            mnemonic, seed, json, json_password
        )
        return self._run_command(
            wallets.regen_coldkey(
                wallet,
                mnemonic,
                seed,
                json,
                json_password,
                use_password,
            )
        )

    def wallet_regen_coldkey_pub(
        self,
        wallet_name: Optional[str] = Options.wallet_name,
        wallet_path: Optional[str] = Options.wallet_path,
        wallet_hotkey: Optional[str] = Options.wallet_hotkey,
        public_key_hex: Optional[str] = Options.public_hex_key,
        ss58_address: Optional[str] = Options.ss58_address,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
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
        self.verbosity_handler(quiet, verbose)

        if not wallet_path:
            wallet_path = Prompt.ask(
                "Enter the path to the wallets directory", default=defaults.wallet.path
            )
            wallet_path = os.path.expanduser(wallet_path)

        if not wallet_name:
            wallet_name = Prompt.ask(
                f"Enter the name of the [{COLOR_PALETTE['GENERAL']['COLDKEY']}]new wallet (coldkey)",
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
            wallets.regen_coldkey_pub(wallet, ss58_address, public_key_hex)
        )

    def wallet_regen_hotkey(
        self,
        wallet_name: Optional[str] = Options.wallet_name,
        wallet_path: Optional[str] = Options.wallet_path,
        wallet_hotkey: Optional[str] = Options.wallet_hotkey,
        mnemonic: Optional[str] = Options.mnemonic,
        seed: Optional[str] = Options.seed,
        json: Optional[str] = Options.json,
        json_password: Optional[str] = Options.json_password,
        use_password: bool = typer.Option(
            False,  # Overriden to False
            help="Set to 'True' to protect the generated Bittensor key with a password.",
            is_flag=True,
            flag_value=True,
        ),
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
    ):
        """
        Regenerates a hotkey for a wallet.

        Similar to regenerating a coldkey, this command creates a new hotkey from a mnemonic, seed, or JSON file.

        USAGE

        Users can provide a mnemonic, seed string, or a JSON file to regenerate the hotkey. The command supports optional password protection and can overwrite an existing hotkey.

        # Example usage:

        [green]$[/green] btcli wallet regen_hotkey --seed 0x1234...

        [bold]Note[/bold]: This command is essential for users who need to regenerate their hotkey, possibly for security upgrades or key recovery.
        It should be used with caution to avoid accidental overwriting of existing keys.
        """
        self.verbosity_handler(quiet, verbose)
        wallet = self.wallet_ask(
            wallet_name,
            wallet_path,
            wallet_hotkey,
            ask_for=[WO.NAME, WO.PATH, WO.HOTKEY],
            validate=WV.WALLET,
        )
        mnemonic, seed, json, json_password = get_creation_data(
            mnemonic, seed, json, json_password
        )
        return self._run_command(
            wallets.regen_hotkey(
                wallet,
                mnemonic,
                seed,
                json,
                json_password,
                use_password,
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
            is_flag=True,
            flag_value=True,
        ),
        uri: Optional[str] = Options.uri,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
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
        self.verbosity_handler(quiet, verbose)

        if not wallet_name:
            wallet_name = Prompt.ask(
                f"Enter the [{COLOR_PALETTE['GENERAL']['COLDKEY']}]wallet name",
                default=defaults.wallet.name,
            )

        if not wallet_hotkey:
            wallet_hotkey = Prompt.ask(
                f"Enter the name of the [{COLOR_PALETTE['GENERAL']['HOTKEY']}]new hotkey",
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
        return self._run_command(wallets.new_hotkey(wallet, n_words, use_password, uri))

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
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
    ):
        """
        Create a new coldkey. A coldkey is required for holding TAO balances and performing high-value transactions.

        USAGE

        The command creates a new coldkey. It provides options for the mnemonic word count, and supports password protection. It also allows overwriting an existing coldkey.

        EXAMPLE

        [green]$[/green] btcli wallet new_coldkey --n_words 15

        [bold]Note[/bold]: This command is crucial for users who need to create a new coldkey for enhanced security or as part of setting up a new wallet. It is a foundational step in establishing a secure presence on the Bittensor network.
        """
        self.verbosity_handler(quiet, verbose)

        if not wallet_path:
            wallet_path = Prompt.ask(
                "Enter the path to the wallets directory", default=defaults.wallet.path
            )

        if not wallet_name:
            wallet_name = Prompt.ask(
                f"Enter the name of the [{COLOR_PALETTE['GENERAL']['COLDKEY']}]new wallet (coldkey)",
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
            wallets.new_coldkey(wallet, n_words, use_password, uri)
        )

    def wallet_check_ck_swap(
        self,
        wallet_name: Optional[str] = Options.wallet_name,
        wallet_path: Optional[str] = Options.wallet_path,
        wallet_hotkey: Optional[str] = Options.wallet_hotkey,
        network: Optional[list[str]] = Options.network,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
    ):
        """
        Check the status of your scheduled coldkey swap.

        USAGE

        Users should provide the old coldkey wallet to check the swap status.

        EXAMPLE

        [green]$[/green] btcli wallet check_coldkey_swap
        """
        self.verbosity_handler(quiet, verbose)
        wallet = self.wallet_ask(wallet_name, wallet_path, wallet_hotkey)
        self.initialize_chain(network)
        return self._run_command(wallets.check_coldkey_swap(wallet, self.subtensor))

    def wallet_create_wallet(
        self,
        wallet_name: Optional[str] = Options.wallet_name,
        wallet_path: Optional[str] = Options.wallet_path,
        wallet_hotkey: Optional[str] = Options.wallet_hotkey,
        n_words: Optional[int] = None,
        use_password: bool = Options.use_password,
        uri: Optional[str] = Options.uri,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
    ):
        """
        Create a complete wallet by setting up both coldkey and hotkeys.

        USAGE

        The command creates a new coldkey and hotkey. It provides an option for mnemonic word count. It supports password protection for the coldkey and allows overwriting of existing keys.

        EXAMPLE

        [green]$[/green] btcli wallet create --n_words 21

        [bold]Note[/bold]: This command is for new users setting up their wallet for the first time, or for those who wish to completely renew their wallet keys. It ensures a fresh start with new keys for secure and effective participation in the Bittensor network.
        """
        if not wallet_path:
            wallet_path = Prompt.ask(
                "Enter the path of wallets directory", default=defaults.wallet.path
            )

        if not wallet_name:
            wallet_name = Prompt.ask(
                f"Enter the name of the [{COLOR_PALETTE['GENERAL']['COLDKEY']}]new wallet (coldkey)",
                default=defaults.wallet.name,
            )
        if not wallet_hotkey:
            wallet_hotkey = Prompt.ask(
                f"Enter the the name of the [{COLOR_PALETTE['GENERAL']['HOTKEY']}]new hotkey",
                default=defaults.wallet.hotkey,
            )

        self.verbosity_handler(quiet, verbose)
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
                wallet,
                n_words,
                use_password,
                uri,
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
        self.verbosity_handler(quiet, verbose)
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
            wallets.wallet_balance(wallet, subtensor, all_balances, ss58_addresses)
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
        discord_handle: str = typer.Option(
            "",
            "--discord",
            help="The Discord handle for the identity.",
        ),
        description: str = typer.Option(
            "",
            "--description",
            help="The description for the identity.",
        ),
        additional_info: str = typer.Option(
            "",
            "--additional",
            help="Additional details for the identity.",
        ),
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
        prompt: bool = Options.prompt,
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
        self.verbosity_handler(quiet, verbose)
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
            )
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
            discord_handle,
            description,
            additional_info,
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
                prompt,
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
        wallet = None
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

        self.verbosity_handler(quiet, verbose)
        return self._run_command(
            wallets.get_id(self.initialize_chain(network), coldkey_ss58)
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
        self.verbosity_handler(quiet, verbose)
        if use_hotkey is None:
            use_hotkey = Confirm.ask(
                f"Would you like to sign the transaction using your [{COLOR_PALETTE['GENERAL']['HOTKEY']}]hotkey[/{COLOR_PALETTE['GENERAL']['HOTKEY']}]?"
                f"\n[Type [{COLOR_PALETTE['GENERAL']['HOTKEY']}]y[/{COLOR_PALETTE['GENERAL']['HOTKEY']}] for [{COLOR_PALETTE['GENERAL']['HOTKEY']}]hotkey[/{COLOR_PALETTE['GENERAL']['HOTKEY']}]"
                f" and [{COLOR_PALETTE['GENERAL']['COLDKEY']}]n[/{COLOR_PALETTE['GENERAL']['COLDKEY']}] for [{COLOR_PALETTE['GENERAL']['COLDKEY']}]coldkey[/{COLOR_PALETTE['GENERAL']['COLDKEY']}]] (default is [{COLOR_PALETTE['GENERAL']['COLDKEY']}]coldkey[/{COLOR_PALETTE['GENERAL']['COLDKEY']}])",
                default=False,
            )

        ask_for = [WO.HOTKEY, WO.PATH, WO.NAME] if use_hotkey else [WO.NAME, WO.PATH]
        validate = WV.WALLET_AND_HOTKEY if use_hotkey else WV.WALLET

        wallet = self.wallet_ask(
            wallet_name, wallet_path, wallet_hotkey, ask_for=ask_for, validate=validate
        )
        if not message:
            message = Prompt.ask("Enter the [blue]message[/blue] to encode and sign")

        return self._run_command(wallets.sign(wallet, message, use_hotkey))

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
        # TODO add: all-wallets, reuse_last, html_output
    ):
        """List all stake accounts for wallet."""
        self.verbosity_handler(quiet, verbose)

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
            stake.stake_list(
                wallet, coldkey_ss58, self.initialize_chain(network), live, verbose
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
        max_stake: float = typer.Option(
            0.0,
            "--max-stake",
            "-m",
            help="Stake is sent to a hotkey only until the hotkey's total stake is less than or equal to this maximum staked TAO. If a hotkey already has stake greater than this amount, then stake is not added to this hotkey.",
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
        netuid: Optional[int] = Options.netuid_not_req,
        all_netuids: bool = Options.all_netuids,
        wallet_name: str = Options.wallet_name,
        wallet_path: str = Options.wallet_path,
        wallet_hotkey: str = Options.wallet_hotkey,
        network: Optional[list[str]] = Options.network,
        prompt: bool = Options.prompt,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
    ):
        """
        Stake TAO to one or more hotkeys associated with the user's coldkey.

        This command is used by a subnet validator to stake to their own hotkey. Compare this command with "btcli root delegate" that is typically run by a TAO holder to delegate their TAO to a delegate's hotkey.

        This command is used by a subnet validator to allocate stake TAO to their different hotkeys, securing their position and influence on the network.

        EXAMPLE

        [green]$[/green] btcli stake add --amount 100 --wallet-name <my_wallet> --wallet-hotkey <my_hotkey>
        """
        self.verbosity_handler(quiet, verbose)
        netuid = get_optional_netuid(netuid, all_netuids)

        if stake_all and amount:
            err_console.print(
                "Cannot specify an amount and 'stake-all'. Choose one or the other."
            )
            raise typer.Exit()

        if stake_all and not amount:
            if not Confirm.ask("Stake all the available TAO tokens?", default=False):
                raise typer.Exit()

        if all_hotkeys and include_hotkeys:
            err_console.print(
                "You have specified hotkeys to include and also the `--all-hotkeys` flag. The flag"
                "should only be used standalone (to use all hotkeys) or with `--exclude-hotkeys`."
            )
            raise typer.Exit()

        if include_hotkeys and exclude_hotkeys:
            err_console.print(
                "You have specified options for both including and excluding hotkeys. Select one or the other."
            )
            raise typer.Exit()

        if not wallet_hotkey and not all_hotkeys and not include_hotkeys:
            if not wallet_name:
                wallet_name = Prompt.ask(
                    "Enter the [blue]wallet name[/blue]",
                    default=self.config.get("wallet_name") or defaults.wallet.name,
                )
            if netuid is not None:
                hotkey_or_ss58 = Prompt.ask(
                    "Enter the [blue]wallet hotkey[/blue] name or [blue]ss58 address[/blue] to stake to [dim](or Press Enter to view delegates)[/dim]",
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
                selected_hotkey = self._run_command(
                    subnets.show(
                        subtensor=self.initialize_chain(network),
                        netuid=netuid,
                        max_rows=12,
                        prompt=False,
                        delegate_selection=True,
                    )
                )
                if selected_hotkey is None:
                    print_error("No delegate selected. Exiting.")
                    raise typer.Exit()
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
            included_hotkeys = parse_to_list(
                include_hotkeys,
                str,
                "Hotkeys must be a comma-separated list of ss58s, e.g., `--include-hotkeys 5Grw....,5Grw....`.",
                is_ss58=True,
            )
        else:
            included_hotkeys = []

        if exclude_hotkeys:
            excluded_hotkeys = parse_to_list(
                exclude_hotkeys,
                str,
                "Hotkeys must be a comma-separated list of ss58s, e.g., `--exclude-hotkeys 5Grw....,5Grw....`.",
                is_ss58=True,
            )
        else:
            excluded_hotkeys = []

        # TODO: Ask amount for each subnet explicitly if more than one
        if not stake_all and not amount and not max_stake:
            free_balance, staked_balance = self._run_command(
                wallets.wallet_balance(
                    wallet, self.initialize_chain(network), False, None
                )
            )
            if free_balance == Balance.from_tao(0):
                print_error("You dont have any balance to stake.")
                raise typer.Exit()
            if netuid is not None:
                amount = FloatPrompt.ask(
                    f"Amount to [{COLOR_PALETTE['GENERAL']['SUBHEADING_MAIN']}]stake (TAO τ)"
                )
            else:
                amount = FloatPrompt.ask(
                    f"Amount to [{COLOR_PALETTE['GENERAL']['SUBHEADING_MAIN']}]stake to each netuid (TAO τ)"
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
            stake.stake_add(
                wallet,
                self.initialize_chain(network),
                netuid,
                stake_all,
                amount,
                False,
                prompt,
                max_stake,
                all_hotkeys,
                included_hotkeys,
                excluded_hotkeys,
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
            hidden=True,
            help="When set, this command unstakes all staked TAO + Alpha from the all hotkeys.",
        ),
        unstake_all_alpha: bool = typer.Option(
            False,
            "--unstake-all-alpha",
            "--all-alpha",
            hidden=True,
            help="When set, this command unstakes all staked Alpha from the all hotkeys.",
        ),
        amount: float = typer.Option(
            0.0, "--amount", "-a", help="The amount of TAO to unstake."
        ),
        hotkey_ss58_address: str = typer.Option(
            "",
            help="The ss58 address of the hotkey to unstake from.",
        ),
        keep_stake: float = typer.Option(
            0.0,
            "--keep-stake",
            "--keep",
            help="Sets the maximum amount of TAO to remain staked in each hotkey.",
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
        prompt: bool = Options.prompt,
        interactive: bool = typer.Option(
            False,
            "--interactive",
            "-i",
            help="Enter interactive mode for unstaking.",
        ),
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
    ):
        """
        Unstake TAO from one or more hotkeys and transfer them back to the user's coldkey.

        This command is used to withdraw TAO previously staked to different hotkeys.

        EXAMPLE

        [green]$[/green] btcli stake remove --amount 100 -in hk1,hk2

        [blue bold]Note[/blue bold]: This command is for users who wish to reallocate their stake or withdraw them from the network. It allows for flexible management of TAO stake across different neurons (hotkeys) on the network.
        """
        self.verbosity_handler(quiet, verbose)
        # TODO: Coldkey related unstakes need to be updated. Patching for now.
        unstake_all_alpha = False
        unstake_all = False

        if interactive and any(
            [hotkey_ss58_address, include_hotkeys, exclude_hotkeys, all_hotkeys]
        ):
            err_console.print(
                "Interactive mode cannot be used with hotkey selection options like --include-hotkeys, --exclude-hotkeys, --all-hotkeys, or --hotkey."
            )
            raise typer.Exit()

        if unstake_all and unstake_all_alpha:
            err_console.print("Cannot specify both unstake-all and unstake-all-alpha.")
            raise typer.Exit()

        if not interactive and not unstake_all and not unstake_all_alpha:
            netuid = get_optional_netuid(netuid, all_netuids)
            if all_hotkeys and include_hotkeys:
                err_console.print(
                    "You have specified hotkeys to include and also the `--all-hotkeys` flag. The flag"
                    " should only be used standalone (to use all hotkeys) or with `--exclude-hotkeys`."
                )
                raise typer.Exit()

            if include_hotkeys and exclude_hotkeys:
                err_console.print(
                    "You have specified both including and excluding hotkeys options. Select one or the other."
                )
                raise typer.Exit()

            if unstake_all and amount:
                err_console.print(
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
            included_hotkeys = parse_to_list(
                include_hotkeys,
                str,
                "Hotkeys must be a comma-separated list of ss58s or names, e.g., `--include-hotkeys hk1,hk2`.",
                is_ss58=False,
            )
        else:
            included_hotkeys = []

        if exclude_hotkeys:
            excluded_hotkeys = parse_to_list(
                exclude_hotkeys,
                str,
                "Hotkeys must be a comma-separated list of ss58s or names, e.g., `--exclude-hotkeys hk3,hk4`.",
                is_ss58=False,
            )
        else:
            excluded_hotkeys = []

        return self._run_command(
            stake.unstake(
                wallet,
                self.initialize_chain(network),
                hotkey_ss58_address,
                all_hotkeys,
                included_hotkeys,
                excluded_hotkeys,
                amount,
                keep_stake,
                unstake_all,
                prompt,
                interactive,
                netuid=netuid,
                unstake_all_alpha=unstake_all_alpha,
            )
        )

    def stake_move(
        self,
        network: Optional[list[str]] = Options.network,
        wallet_name=Options.wallet_name,
        wallet_path=Options.wallet_path,
        wallet_hotkey=Options.wallet_hotkey,
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
        prompt: bool = Options.prompt,
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
        console.print(
            "[dim]This command moves stake from one hotkey to another hotkey while keeping the same coldkey.[/dim]"
        )
        if not destination_hotkey:
            dest_wallet_or_ss58 = Prompt.ask(
                "Enter the [blue]destination wallet[/blue] where destination hotkey is located or [blue]ss58 address[/blue]"
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
            wallet = self.wallet_ask(
                wallet_name,
                wallet_path,
                wallet_hotkey,
                ask_for=[],
                validate=WV.WALLET_AND_HOTKEY,
            )
            origin_hotkey = wallet.hotkey.ss58_address

        if not interactive_selection:
            if not origin_netuid:
                origin_netuid = IntPrompt.ask(
                    "Enter the [blue]origin subnet[/blue] (netuid) to move stake from"
                )

            if not destination_netuid:
                destination_netuid = IntPrompt.ask(
                    "Enter the [blue]destination subnet[/blue] (netuid) to move stake to"
                )

        return self._run_command(
            move.move_stake(
                subtensor=self.initialize_chain(network),
                wallet=wallet,
                origin_netuid=origin_netuid,
                origin_hotkey=origin_hotkey,
                destination_netuid=destination_netuid,
                destination_hotkey=destination_hotkey,
                amount=amount,
                stake_all=stake_all,
                interactive_selection=interactive_selection,
                prompt=prompt,
            )
        )

    def stake_transfer(
        self,
        network: Optional[list[str]] = Options.network,
        wallet_name: Optional[str] = Options.wallet_name,
        wallet_path: Optional[str] = Options.wallet_path,
        wallet_hotkey: Optional[str] = Options.wallet_hotkey,
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
        prompt: bool = Options.prompt,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
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

        If no arguments are provided, an interactive selection menu will be shown.

        EXAMPLE

        Transfer 100 TAO from subnet 1 to subnet 2:
        [green]$[/green] btcli stake transfer --origin-netuid 1 --dest-netuid 2 --dest wallet2 --amount 100

        Using SS58 address:
        [green]$[/green] btcli stake transfer --origin-netuid 1 --dest-netuid 2 --dest 5FrLxJsyJ5x9n2rmxFwosFraxFCKcXZDngEP9H7qjkKgHLcK --amount 100
        """
        console.print(
            "[dim]This command transfers stake from one coldkey to another while keeping the same hotkey.[/dim]"
        )
        self.verbosity_handler(quiet, verbose)

        wallet = self.wallet_ask(
            wallet_name,
            wallet_path,
            wallet_hotkey,
            ask_for=[WO.NAME, WO.PATH, WO.HOTKEY],
            validate=WV.WALLET_AND_HOTKEY,
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

        interactive_selection = False
        if origin_netuid is None and dest_netuid is None and not amount:
            interactive_selection = True
        else:
            if origin_netuid is None:
                origin_netuid = IntPrompt.ask(
                    "Enter the [blue]origin subnet[/blue] (netuid)"
                )
            if not amount:
                amount = FloatPrompt.ask("Enter the [blue]amount[/blue] to transfer")

            if dest_netuid is None:
                dest_netuid = IntPrompt.ask(
                    "Enter the [blue]destination subnet[/blue] (netuid)"
                )

        return self._run_command(
            move.transfer_stake(
                wallet=wallet,
                subtensor=self.initialize_chain(network),
                origin_netuid=origin_netuid,
                dest_netuid=dest_netuid,
                dest_coldkey_ss58=dest_ss58,
                amount=amount,
                interactive_selection=interactive_selection,
                prompt=prompt,
            )
        )

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
        prompt: bool = Options.prompt,
        wait_for_inclusion: bool = Options.wait_for_inclusion,
        wait_for_finalization: bool = Options.wait_for_finalization,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
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
        console.print(
            "[dim]This command moves stake from one subnet to another subnet while keeping the same coldkey-hotkey pair.[/dim]"
        )
        self.verbosity_handler(quiet, verbose)

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

        return self._run_command(
            move.swap_stake(
                wallet=wallet,
                subtensor=self.initialize_chain(network),
                origin_netuid=origin_netuid,
                destination_netuid=dest_netuid,
                amount=amount,
                swap_all=swap_all,
                interactive_selection=interactive_selection,
                prompt=prompt,
                wait_for_inclusion=wait_for_inclusion,
                wait_for_finalization=wait_for_finalization,
            )
        )

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
    ):
        """
        Get all the child hotkeys on a specified subnet.

        Users can specify the subnet and see the child hotkeys and the proportion that is given to them. This command is used to view the authority delegated to different hotkeys on the subnet.

        EXAMPLE

        [green]$[/green] btcli stake child get --netuid 1
        [green]$[/green] btcli stake child get --all-netuids
        """
        self.verbosity_handler(quiet, verbose)
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

        return self._run_command(
            children_hotkeys.get_children(
                wallet, self.initialize_chain(network), netuid
            )
        )

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
            "-p",
            help="Enter the stake weight proportions for the child hotkeys (sum should be less than or equal to 1)",
            prompt=False,
        ),
        wait_for_inclusion: bool = Options.wait_for_inclusion,
        wait_for_finalization: bool = Options.wait_for_finalization,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
    ):
        """
        Set child hotkeys on specified subnets.

        Users can specify the 'proportion' to delegate to child hotkeys (ss58 address). The sum of proportions cannot be greater than 1.

        This command is used to delegate authority to different hotkeys, securing their position and influence on the subnet.

        EXAMPLE

        [green]$[/green] btcli stake child set -c 5FCL3gmjtQV4xxxxuEPEFQVhyyyyqYgNwX7drFLw7MSdBnxP -c 5Hp5dxxxxtGg7pu8dN2btyyyyVA1vELmM9dy8KQv3LxV8PA7 --hotkey default --netuid 1 -p 0.3 -p 0.7
        """
        self.verbosity_handler(quiet, verbose)
        netuid = get_optional_netuid(netuid, all_netuids)

        children = list_prompt(
            children,
            str,
            "Enter the child hotkeys (ss58), comma-separated for multiple",
        )

        proportions = list_prompt(
            proportions,
            float,
            "Enter comma-separated proportions equal to the number of children (sum not exceeding a total of 1.0)",
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
            ask_for=[WO.NAME, WO.PATH, WO.HOTKEY],
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
    ):
        """
        Remove all children hotkeys on a specified subnet.

        This command is used to remove delegated authority from all child hotkeys, removing their position and influence on the subnet.

        EXAMPLE

        [green]$[/green] btcli stake child revoke --hotkey <parent_hotkey> --netuid 1
        """
        self.verbosity_handler(quiet, verbose)
        wallet = self.wallet_ask(
            wallet_name,
            wallet_path,
            wallet_hotkey,
            ask_for=[WO.NAME, WO.PATH, WO.HOTKEY],
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
            help="Use to set the take value for your child hotkey. When not used, the command will fetch the current take value.",
            prompt=False,
        ),
        wait_for_inclusion: bool = Options.wait_for_inclusion,
        wait_for_finalization: bool = Options.wait_for_finalization,
        prompt: bool = Options.prompt,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
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
        self.verbosity_handler(quiet, verbose)
        wallet = self.wallet_ask(
            wallet_name,
            wallet_path,
            wallet_hotkey,
            ask_for=[WO.NAME, WO.PATH, WO.HOTKEY],
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
        param_value: str = typer.Option(
            "", "--value", help="Value to set the hyperparameter to."
        ),
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
    ):
        """
        Used to set hyperparameters for a specific subnet.

        This command allows subnet owners to modify hyperparameters such as its tempo, emission rates, and other hyperparameters.

        EXAMPLE

        [green]$[/green] btcli sudo set --netuid 1 --param tempo --value 400
        """
        self.verbosity_handler(quiet, verbose)

        hyperparams = self._run_command(
            sudo.get_hyperparameters(self.initialize_chain(network), netuid)
        )

        if not hyperparams:
            raise typer.Exit()

        if not param_name:
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

        if not param_value:
            param_value = Prompt.ask(
                f"Enter the new value for [{COLOR_PALETTE['GENERAL']['SUBHEADING']}]{param_name}[/{COLOR_PALETTE['GENERAL']['SUBHEADING']}] in the VALUE column format"
            )

        wallet = self.wallet_ask(
            wallet_name, wallet_path, wallet_hotkey, ask_for=[WO.NAME, WO.PATH]
        )
        return self._run_command(
            sudo.sudo_set_hyperparameter(
                wallet,
                self.initialize_chain(network),
                netuid,
                param_name,
                param_value,
            )
        )

    def sudo_get(
        self,
        network: Optional[list[str]] = Options.network,
        netuid: int = Options.netuid,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
    ):
        """
        Shows a list of the hyperparameters for the specified subnet.

        The output of this command is the same as that of `btcli subnets hyperparameters`.

        EXAMPLE

        [green]$[/green] btcli sudo get --netuid 1
        """
        self.verbosity_handler(quiet, verbose)
        return self._run_command(
            sudo.get_hyperparameters(self.initialize_chain(network), netuid)
        )

    def sudo_senate(
        self,
        network: Optional[list[str]] = Options.network,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
    ):
        """
        Shows the Senate members of the Bittensor's governance protocol.

        This command lists the delegates involved in the decision-making process of the Bittensor network, showing their names and wallet addresses. This information is crucial for understanding who holds governance roles within the network.

        EXAMPLE
        [green]$[/green] btcli sudo senate
        """
        self.verbosity_handler(quiet, verbose)
        return self._run_command(sudo.get_senate(self.initialize_chain(network)))

    def sudo_proposals(
        self,
        network: Optional[list[str]] = Options.network,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
    ):
        """
        View active proposals for the senate in the Bittensor's governance protocol.

        This command displays the details of ongoing proposals, including proposal hashes, votes, thresholds, and proposal data.

        EXAMPLE
        [green]$[/green] btcli sudo proposals
        """
        self.verbosity_handler(quiet, verbose)
        return self._run_command(sudo.proposals(self.initialize_chain(network)))

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
        self.verbosity_handler(quiet, verbose)

        wallet = self.wallet_ask(
            wallet_name,
            wallet_path,
            wallet_hotkey,
            ask_for=[WO.NAME, WO.PATH, WO.HOTKEY],
            validate=WV.WALLET_AND_HOTKEY,
        )

        current_take = self._run_command(
            sudo.get_current_take(self.initialize_chain(network), wallet)
        )
        console.print(
            f"Current take is [{COLOR_PALETTE['POOLS']['RATE']}]{current_take * 100.:.2f}%"
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

        return self._run_command(
            sudo.set_take(wallet, self.initialize_chain(network), take)
        )

    def sudo_get_take(
        self,
        network: Optional[list[str]] = Options.network,
        wallet_name: Optional[str] = Options.wallet_name,
        wallet_path: Optional[str] = Options.wallet_path,
        wallet_hotkey: Optional[str] = Options.wallet_hotkey,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
    ):
        """
        Allows users to check their delegate take percentage.

        This command can be used to fetch the delegate take of your hotkey.

        EXAMPLE
        [green]$[/green] btcli sudo get-take --wallet-name my_wallet --wallet-hotkey my_hotkey
        """
        self.verbosity_handler(quiet, verbose)

        wallet = self.wallet_ask(
            wallet_name,
            wallet_path,
            wallet_hotkey,
            ask_for=[WO.NAME, WO.PATH, WO.HOTKEY],
            validate=WV.WALLET_AND_HOTKEY,
        )

        current_take = self._run_command(
            sudo.get_current_take(self.initialize_chain(network), wallet)
        )
        console.print(
            f"Current take is [{COLOR_PALETTE['POOLS']['RATE']}]{current_take * 100.:.2f}%"
        )

    def subnets_list(
        self,
        network: Optional[list[str]] = Options.network,
        # reuse_last: bool = Options.reuse_last,
        # html_output: bool = Options.html_output,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
        live_mode: bool = Options.live,
    ):
        """
        List all subnets and their detailed information.

        This command displays a table with the below columns:

        - NETUID: The subnet's netuid.
        - N: The number of neurons (subnet validators and subnet miners) in the subnet.
        - MAX_N: The maximum allowed number of neurons in the subnet.
        - EMISSION: The percentage of emissions to the subnet as of the last tempo.
        - TEMPO: The subnet's tempo, expressed in number of blocks.
        - RECYCLE: The recycle register cost for this subnet.
        - POW: The proof of work (PoW) difficulty.
        - SUDO: The subnet owner's name or the owner's ss58 address.

        EXAMPLE

        [green]$[/green] btcli subnets list
        """
        self.verbosity_handler(quiet, verbose)
        # if (reuse_last or html_output) and self.config.get("use_cache") is False:
        #     err_console.print(
        #         "Unable to use `--reuse-last` or `--html` when config 'no-cache' is set to 'True'. "
        #         "Change the config to 'False' using `btcli config set`."
        #     )
        #     raise typer.Exit()
        # if reuse_last:
        #     subtensor = None
        # else:
        subtensor = self.initialize_chain(network)
        return self._run_command(
            subnets.subnets_list(
                subtensor,
                False,  # reuse-last
                False,  # html-output
                not self.config.get("use_cache", True),
                verbose,
                live_mode,
            )
        )

    def subnets_price(
        self,
        network: Optional[list[str]] = Options.network,
        netuids: str = typer.Option(
            None,
            "--netuids",
            "--netuid",
            "-n",
            help="Netuid(s) to show the price for.",
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
        csv_output: bool = Options.csv_output,
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
        if netuids:
            netuids = parse_to_list(
                netuids,
                int,
                "Netuids must be a comma-separated list of ints, e.g., `--netuids 1,2,3,4`.",
            )
        if all_netuids and netuids:
            print_error("Cannot specify both --netuid and --all-netuids")
            raise typer.Exit()

        if not netuids and not all_netuids:
            netuids = Prompt.ask(
                "Enter the [blue]netuid(s)[/blue] to view the price of in comma-separated format [dim](or Press Enter to view all subnets)[/dim]",
            )
            if not netuids:
                all_netuids = True
                html_output = True
            else:
                netuids = parse_to_list(
                    netuids,
                    int,
                    "Netuids must be a comma-separated list of ints, e.g., `--netuids 1,2,3,4`.",
                )

        if all_netuids:
            html_output = True

        if html_output and is_linux():
            print_linux_dependency_message()

        return self._run_command(
            price.price(
                self.initialize_chain(network),
                netuids,
                all_netuids,
                interval_hours,
                html_output,
                csv_output
                log_scale,
            )
        )

    def subnets_show(
        self,
        network: Optional[list[str]] = Options.network,
        netuid: int = Options.netuid,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
        prompt: bool = Options.prompt,
    ):
        """
        Displays detailed information about a subnet including participants and their state.

        EXAMPLE

        [green]$[/green] btcli subnets list
        """
        self.verbosity_handler(quiet, verbose)
        subtensor = self.initialize_chain(network)
        return self._run_command(
            subnets.show(
                subtensor,
                netuid,
                verbose=verbose,
                prompt=prompt,
            )
        )

    def subnets_burn_cost(
        self,
        network: Optional[list[str]] = Options.network,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
    ):
        """
        Shows the required amount of TAO to be recycled for creating a new subnet, i.e., cost of registering a new subnet.

        The current implementation anneals the cost of creating a subnet over a period of two days. If the displayed cost is unappealing to you, check back in a day or two to see if it has decreased to a more affordable level.

        EXAMPLE

        [green]$[/green] btcli subnets burn_cost
        """
        self.verbosity_handler(quiet, verbose)
        return self._run_command(subnets.burn_cost(self.initialize_chain(network)))

    def subnets_create(
        self,
        wallet_name: str = Options.wallet_name,
        wallet_path: str = Options.wallet_path,
        wallet_hotkey: str = Options.wallet_hotkey,
        network: Optional[list[str]] = Options.network,
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
        prompt: bool = Options.prompt,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
    ):
        """
        Registers a new subnet.

        EXAMPLE

        [green]$[/green] btcli subnets create
        """
        self.verbosity_handler(quiet, verbose)
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
            subnet_name=subnet_name,
            github_repo=github_repo,
            subnet_contact=subnet_contact,
        )
        success = self._run_command(
            subnets.create(wallet, self.initialize_chain(network), identity, prompt)
        )

        if success and prompt:
            set_id = Confirm.ask(
                "[dark_sea_green3]Do you want to set/update your identity?",
                default=False,
                show_default=True,
            )
            if set_id:
                self.wallet_set_id(
                    wallet_name=wallet.name,
                    wallet_hotkey=wallet.hotkey,
                    wallet_path=wallet.path,
                    network=network,
                    prompt=prompt,
                    quiet=quiet,
                    verbose=verbose,
                )

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
            )
        )

    def subnets_register(
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
        Register a neuron (a subnet validator or a subnet miner) in the specified subnet by recycling some TAO.

        Before registering, the command checks if the specified subnet exists and whether the user's balance is sufficient to cover the registration cost.

        The registration cost is determined by the current recycle amount for the specified subnet. If the balance is insufficient or the subnet does not exist, the command will exit with an error message.

        EXAMPLE

        [green]$[/green] btcli subnets register --netuid 1
        """
        self.verbosity_handler(quiet, verbose)
        wallet = self.wallet_ask(
            wallet_name,
            wallet_path,
            wallet_hotkey,
            ask_for=[WO.NAME, WO.PATH, WO.HOTKEY],
            validate=WV.WALLET_AND_HOTKEY,
        )
        return self._run_command(
            subnets.register(
                wallet,
                self.initialize_chain(network),
                netuid,
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
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
    ):
        """
        Reveal weights for a specific subnet.

        You must specify the netuid, the UIDs you are interested in, and weights you wish to reveal.

        EXAMPLE

        [green]$[/green] btcli wt reveal --netuid 1 --uids 1,2,3,4 --weights 0.1,0.2,0.3,0.4 --salt 163,241,217,11,161,142,147,189
        """
        self.verbosity_handler(quiet, verbose)
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
            raise typer.Exit()

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
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
    ):
        """

        Commit weights for specific subnet.

        Use this command to commit weights for a specific subnet. You must specify the netuid, the UIDs you are interested in, and the weights you wish to commit.

        EXAMPLE

        [green]$[/green] btcli wt commit --netuid 1 --uids 1,2,3,4 --w 0.1,0.2,0.3

        [italic]Note[/italic]: This command is used to commit weights for a specific subnet and requires the user to have the necessary
        permissions.
        """
        self.verbosity_handler(quiet, verbose)

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
            raise typer.Exit()

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
