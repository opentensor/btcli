#!/usr/bin/env python3
import asyncio
import curses
import os.path
import re
from pathlib import Path
from typing import Coroutine, Optional

import rich
import typer
import numpy as np
from bittensor_wallet import Wallet
from git import Repo, GitError
from rich.prompt import Confirm, FloatPrompt, Prompt, IntPrompt
from rich.table import Column, Table
from .src import HYPERPARAMS, defaults, HELP_PANELS
from bittensor_cli.src.bittensor import utils
from .src.bittensor.async_substrate_interface import SubstrateRequestException
from .src.commands import root, stake, subnets, sudo, wallets
from .src.commands import weights as weights_cmds
from bittensor_cli.src.bittensor.subtensor_interface import SubtensorInterface
from bittensor_cli.src.bittensor.utils import (
    console,
    err_console,
    verbose_console,
    is_valid_ss58_address,
)
from typing_extensions import Annotated
from websockets import ConnectionClosed
from yaml import safe_dump, safe_load

__version__ = "8.0.0"

_version_split = __version__.split(".")
__version_info__ = tuple(int(part) for part in _version_split)
_version_int_base = 1000
assert max(__version_info__) < _version_int_base

__version_as_int__: int = sum(
    e * (_version_int_base**i) for i, e in enumerate(reversed(__version_info__))
)
assert __version_as_int__ < 2**31  # fits in int32
__new_signature_version__ = 360

_epilog = "Made with [bold red]:heart:[/bold red] by Openτensor Foundaτion"

np.set_printoptions(precision=8, suppress=True, floatmode="fixed")


class Options:
    """
    Re-usable typer args
    """

    wallet_name = typer.Option(
        None,
        "--wallet-name",
        "-w",
        "--wallet_name",
        "--wallet.name",
        help="Name of wallet",
    )
    wallet_name_req = typer.Option(
        None,
        "--wallet-name",
        "-w",
        "--wallet_name",
        "--wallet.name",
        help="Name of wallet",
        prompt=True,
    )
    wallet_path = typer.Option(
        None,
        "--wallet-path",
        "-p",
        "--wallet_path",
        "--wallet.path",
        help="Filepath of root of wallets",
    )
    wallet_hotkey = typer.Option(
        None,
        "--hotkey",
        "-H",
        "--wallet_hotkey",
        "--wallet.hotkey",
        help="Hotkey of wallet",
    )
    wallet_hk_req = typer.Option(
        None,
        "--hotkey",
        "-H",
        "--wallet_hotkey",
        "--wallet.hotkey",
        help="Hotkey name of wallet",
        prompt=True,
    )
    mnemonic = typer.Option(
        None, help="Mnemonic used to regen your key i.e. horse cart dog ..."
    )
    seed = typer.Option(
        None, help="Seed hex string used to regen your key i.e. 0x1234..."
    )
    json = typer.Option(
        None,
        "--json",
        "-j",
        help="Path to a json file containing the encrypted key backup. (e.g. from PolkadotJS)",
    )
    json_password = typer.Option(
        None, "--json-password", help="Password to decrypt the json file."
    )
    use_password = typer.Option(
        True,
        help="Set true to protect the generated bittensor key with a password.",
        is_flag=True,
        flag_value=False,
    )
    public_hex_key = typer.Option(None, help="The public key in hex format.")
    ss58_address = typer.Option(None, help="The SS58 address of the coldkey")
    overwrite_coldkey = typer.Option(
        False,
        help="Overwrite the old coldkey with the newly generated coldkey",
        prompt=True,
    )
    overwrite_hotkey = typer.Option(
        False,
        help="Overwrite the old hotkey with the newly generated hotkey",
        prompt=True,
    )
    network = typer.Option(
        None,
        "--network",
        "--subtensor.network",
        help="The subtensor network to connect to. Default: finney.",
        show_default=False,
    )
    chain = typer.Option(
        None,
        "--chain",
        "--subtensor.chain_endpoint",
        help="The subtensor chain endpoint to connect to.",
        show_default=False,
    )
    netuids = typer.Option(
        [], "--netuids", "-n", help="Set the netuid(s) to filter by (e.g. `0 1 2`)"
    )
    netuid = typer.Option(
        None,
        help="The netuid (network unique identifier) of the subnet within the root network, (e.g. 1)",
        prompt=True,
    )
    reuse_last = typer.Option(
        False,
        "--reuse-last",
        help="Reuse the metagraph data you last retrieved. Only use this if you have already retrieved metagraph"
        "data",
    )
    html_output = typer.Option(
        False,
        "--html",
        help="Display the table as HTML in the browser, rather than in the Terminal.",
    )
    wait_for_inclusion = typer.Option(
        True, help="If set, waits until the transaction is included in a block."
    )
    wait_for_finalization = typer.Option(
        True,
        help="If set, waits until the transaction is finalized " "on the blockchain.",
    )
    prompt = typer.Option(
        True,
        "--prompt/--no-prompt",
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
        help="Do not output to the console besides critical information.",
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


def verbosity_console_handler(verbosity_level: int = 1) -> None:
    """
    Sets verbosity level of console output
    :param verbosity_level: int corresponding to verbosity level of console output (0 is quiet, 1 is normal, 2 is verbose)
    """
    if verbosity_level not in range(3):
        raise ValueError(f"Invalid verbosity level: {verbosity_level}")
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


def get_n_words(n_words: Optional[int]) -> int:
    """
    Prompts the user to select the number of words used in the mnemonic if not supplied or not within the
    acceptable criteria of [12, 15, 18, 21, 24]
    """
    while n_words not in [12, 15, 18, 21, 24]:
        n_words = int(
            Prompt.ask(
                "Choose number of words",
                choices=["12", "15", "18", "21", "24"],
                default=12,
            )
        )
    return n_words


def get_creation_data(
    mnemonic: str, seed: str, json: str, json_password: str
) -> tuple[str, str, str, str]:
    """
    Determines which of the key creation elements have been supplied, if any. If None have been supplied,
    prompts to user, and determines what they've supplied. Returns all elements in a tuple.
    """
    if not mnemonic and not seed and not json:
        prompt_answer = Prompt.ask("Enter mnemonic, seed, or json file location")
        if prompt_answer.startswith("0x"):
            seed = prompt_answer
        elif len(prompt_answer.split(" ")) > 1:
            mnemonic = prompt_answer
        else:
            json = prompt_answer
    if json and not json_password:
        json_password = Prompt.ask("Enter json backup password", password=True)
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

            instructions = "Use UP/DOWN to navigate, SPACE to toggle, ENTER to confirm."
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
            version = (
                f"BTCLI Version: {__version__}/"
                f"{Repo(os.path.dirname(os.path.dirname(__file__))).active_branch.name}"
            )
        except GitError:
            version = f"BTCLI Version: {__version__}"
        typer.echo(version)
        raise typer.Exit()


class CLIManager:
    """
    :var app: the main CLI Typer app
    :var config_app: the Typer app as it relates to config commands
    :var wallet_app: the Typer app as it relates to wallet commands
    :var root_app: the Typer app as it relates to root commands
    :var stake_app: the Typer app as it relates to stake commands
    :var sudo_app: the Typer app as it relates to sudo commands
    :var subnets_app: the Typer app as it relates to subnets commands
    :var not_subtensor: the `SubtensorInterface` object passed to the various commands that require it
    """

    not_subtensor: Optional[SubtensorInterface]
    app: typer.Typer
    config_app: typer.Typer
    wallet_app: typer.Typer
    root_app: typer.Typer
    subnets_app: typer.Typer
    weights_app: typer.Typer

    def __init__(self):
        self.config = {
            "wallet_name": None,
            "wallet_path": None,
            "wallet_hotkey": None,
            "network": None,
            "chain": None,
            "no_cache": False,
            "metagraph_cols": {
                "UID": True,
                "STAKE": True,
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
        self.not_subtensor = None
        self.config_base_path = os.path.expanduser(defaults.config.base_path)
        self.config_path = os.path.expanduser(defaults.config.path)

        self.app = typer.Typer(
            rich_markup_mode="rich", callback=self.main_callback, epilog=_epilog
        )
        self.config_app = typer.Typer(epilog=_epilog)
        self.wallet_app = typer.Typer(epilog=_epilog)
        self.root_app = typer.Typer(epilog=_epilog)
        self.stake_app = typer.Typer(epilog=_epilog)
        self.sudo_app = typer.Typer(epilog=_epilog)
        self.subnets_app = typer.Typer(epilog=_epilog)
        self.weights_app = typer.Typer(epilog=_epilog)

        # config alias
        self.app.add_typer(
            self.config_app,
            name="config",
            short_help="Config commands, aliases: `c`, `conf`",
        )
        self.app.add_typer(self.config_app, name="conf", hidden=True)
        self.app.add_typer(self.config_app, name="c", hidden=True)

        # wallet aliases
        self.app.add_typer(
            self.wallet_app,
            name="wallet",
            short_help="Wallet commands, aliases: `wallets`, `w`",
        )
        self.app.add_typer(self.wallet_app, name="w", hidden=True)
        self.app.add_typer(self.wallet_app, name="wallets", hidden=True)

        # root aliases
        self.app.add_typer(
            self.root_app,
            name="root",
            short_help="Root commands, alias: `r`",
        )
        self.app.add_typer(self.root_app, name="r", hidden=True)

        # stake aliases
        self.app.add_typer(
            self.stake_app,
            name="stake",
            short_help="Stake commands, alias: `st`",
        )
        self.app.add_typer(self.stake_app, name="st", hidden=True)

        # sudo aliases
        self.app.add_typer(
            self.sudo_app,
            name="sudo",
            short_help="Sudo commands, alias: `su`",
        )
        self.app.add_typer(self.sudo_app, name="su", hidden=True)

        # subnets aliases
        self.app.add_typer(
            self.subnets_app, name="subnets", short_help="Subnets commands, alias: `s`, `subnet`"
        )
        self.app.add_typer(self.subnets_app, name="s", hidden=True)
        self.app.add_typer(self.subnets_app, name="subnet", hidden=True)

        # weights aliases
        self.app.add_typer(
            self.weights_app,
            name="weights",
            short_help="Weights commands, aliases: `wt`, `weight`",
        )
        self.app.add_typer(self.weights_app, name="wt", hidden=True)
        self.app.add_typer(self.weights_app, name="weight", hidden=True)

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
            "history", rich_help_panel=HELP_PANELS["WALLET"]["INFORMATION"]
        )(self.wallet_history)
        self.wallet_app.command(
            "overview", rich_help_panel=HELP_PANELS["WALLET"]["INFORMATION"]
        )(self.wallet_overview)
        self.wallet_app.command(
            "transfer", rich_help_panel=HELP_PANELS["WALLET"]["OPERATIONS"]
        )(self.wallet_transfer)
        self.wallet_app.command(
            "inspect", rich_help_panel=HELP_PANELS["WALLET"]["INFORMATION"]
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
            "check-swap", rich_help_panel=HELP_PANELS["WALLET"]["SECURITY"]
        )(self.wallet_check_ck_swap)
        self.wallet_app.command(
            "sign", rich_help_panel=HELP_PANELS["WALLET"]["OPERATIONS"]
        )(self.wallet_sign)

        # root commands
        self.root_app.command("list")(self.root_list)
        self.root_app.command(
            "set-weights", rich_help_panel=HELP_PANELS["ROOT"]["WEIGHT_MGMT"]
        )(self.root_set_weights)
        self.root_app.command(
            "get-weights", rich_help_panel=HELP_PANELS["ROOT"]["WEIGHT_MGMT"]
        )(self.root_get_weights)
        self.root_app.command(
            "boost", rich_help_panel=HELP_PANELS["ROOT"]["WEIGHT_MGMT"]
        )(self.root_boost)
        self.root_app.command(
            "slash", rich_help_panel=HELP_PANELS["ROOT"]["WEIGHT_MGMT"]
        )(self.root_slash)
        self.root_app.command(
            "senate", rich_help_panel=HELP_PANELS["ROOT"]["GOVERNANCE"]
        )(self.root_senate)
        self.root_app.command(
            "senate-vote", rich_help_panel=HELP_PANELS["ROOT"]["GOVERNANCE"]
        )(self.root_senate_vote)
        self.root_app.command("register")(self.root_register)
        self.root_app.command(
            "proposals", rich_help_panel=HELP_PANELS["ROOT"]["GOVERNANCE"]
        )(self.root_proposals)
        self.root_app.command(
            "set-take", rich_help_panel=HELP_PANELS["ROOT"]["DELEGATION"]
        )(self.root_set_take)
        self.root_app.command(
            "delegate-stake", rich_help_panel=HELP_PANELS["ROOT"]["DELEGATION"]
        )(self.root_delegate_stake)
        self.root_app.command(
            "undelegate-stake", rich_help_panel=HELP_PANELS["ROOT"]["DELEGATION"]
        )(self.root_undelegate_stake)
        self.root_app.command(
            "my-delegates", rich_help_panel=HELP_PANELS["ROOT"]["DELEGATION"]
        )(self.root_my_delegates)
        self.root_app.command(
            "list-delegates", rich_help_panel=HELP_PANELS["ROOT"]["DELEGATION"]
        )(self.root_list_delegates)
        self.root_app.command(
            "nominate", rich_help_panel=HELP_PANELS["ROOT"]["GOVERNANCE"]
        )(self.root_nominate)

        # stake commands
        self.stake_app.command(
            "show", rich_help_panel=HELP_PANELS["STAKE"]["STAKE_MGMT"]
        )(self.stake_show)
        self.stake_app.command(
            "add", rich_help_panel=HELP_PANELS["STAKE"]["STAKE_MGMT"]
        )(self.stake_add)
        self.stake_app.command(
            "remove", rich_help_panel=HELP_PANELS["STAKE"]["STAKE_MGMT"]
        )(self.stake_remove)

        # stake-children commands
        children_app = typer.Typer()
        self.stake_app.add_typer(
            children_app,
            name="child",
            short_help="Child Hotkey commands, alias: `children`",
            rich_help_panel=HELP_PANELS["STAKE"]["CHILD"],
        )
        self.stake_app.add_typer(children_app, name="children", hidden=True)
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

        # subnets commands
        self.subnets_app.command(
            "hyperparameters", rich_help_panel=HELP_PANELS["SUBNETS"]["INFO"]
        )(self.sudo_get)
        self.subnets_app.command(
            "list", rich_help_panel=HELP_PANELS["SUBNETS"]["INFO"]
        )(self.subnets_list)
        self.subnets_app.command(
            "lock-cost", rich_help_panel=HELP_PANELS["SUBNETS"]["CREATION"]
        )(self.subnets_lock_cost)
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
            "metagraph", rich_help_panel=HELP_PANELS["SUBNETS"]["INFO"]
        )(self.subnets_metagraph)

        # weights commands
        self.weights_app.command(
            "reveal", rich_help_panel=HELP_PANELS["WEIGHTS"]["COMMIT_REVEAL"]
        )(self.weights_reveal)
        self.weights_app.command(
            "commit", rich_help_panel=HELP_PANELS["WEIGHTS"]["COMMIT_REVEAL"]
        )(self.weights_commit)

    def initialize_chain(
        self,
        network: Optional[str] = None,
        chain: Optional[str] = None,
    ) -> SubtensorInterface:
        """
        Intelligently initializes a connection to the chain, depending on the supplied (or in config) values. Set's the
        `self.not_subtensor` object to this created connection.

        :param network: Network name (e.g. finney, test, etc.)
        :param chain: the chain endpoint (e.g. ws://127.0.0.1:9945, wss://entrypoint-finney.opentensor.ai:443, etc.)
        """
        if not self.not_subtensor:
            if network or chain:
                self.not_subtensor = SubtensorInterface(network, chain)
            elif self.config["network"] or self.config["chain"]:
                self.not_subtensor = SubtensorInterface(
                    self.config["network"], self.config["chain"]
                )
            else:
                self.not_subtensor = SubtensorInterface(
                    defaults.subtensor.network, defaults.subtensor.chain_endpoint
                )
        return self.not_subtensor

    def _run_command(self, cmd: Coroutine) -> None:
        """
        Runs the supplied coroutine with `asyncio.run`
        """

        async def _run():
            if self.not_subtensor:
                async with self.not_subtensor:
                    await cmd
            else:
                await cmd

        try:
            return asyncio.run(_run())
        except ConnectionRefusedError:
            err_console.print(
                f"Connection refused when connecting to chain: {self.not_subtensor}"
            )
        except ConnectionClosed:
            pass
        except SubstrateRequestException as e:
            err_console.print(str(e))

    def main_callback(
        self,
        version: Annotated[
            Optional[bool], typer.Option("--version", callback=version_callback)
        ] = None,
    ):
        """
        Method called before all others when using any CLI command. Gives version if that flag is set, otherwise
        loads the config from the config file.
        """
        # create config file if it does not exist
        if not os.path.exists(self.config_path):
            directory_path = Path(self.config_base_path)
            directory_path.mkdir(exist_ok=True, parents=True)
            with open(self.config_path, "w+") as f:
                safe_dump(defaults.config.dictionary, f)
        # check config
        with open(self.config_path, "r") as f:
            config = safe_load(f)
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
            help="Restore the config for metagraph columns to its default setting (all enabled).",
        ),
    ):
        """
        Interactive module to update the config for which columns to display in the metagraph output.
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
        wallet_name: Optional[str] = typer.Option(
            None,
            "--wallet-name",
            "--name",
            "--wallet_name",
            help="Wallet name",
        ),
        wallet_path: Optional[str] = typer.Option(
            None,
            "--wallet-path",
            "--path",
            "-p",
            "--wallet_path",
            help="Path to root of wallets",
        ),
        wallet_hotkey: Optional[str] = typer.Option(
            None,
            "--wallet-hotkey",
            "--hotkey",
            "-k",
            "--wallet_hotkey",
            help="name of the wallet hotkey file",
        ),
        network: Optional[str] = typer.Option(
            None,
            "--network",
            "-n",
            "--subtensor.network",
            help="Network name: [finney, test, local]",
        ),
        chain: Optional[str] = typer.Option(
            None,
            "--chain",
            "-c",
            "--subtensor.chain_endpoint",
            help="chain endpoint for the network (e.g. ws://127.0.0.1:9945, "
            "wss://entrypoint-finney.opentensor.ai:443)",
        ),
        no_cache: Optional[bool] = typer.Option(
            False,
            "--no-cache",
            help="Disable caching of certain commands. This will disable the `--reuse-last` and `html` flags on "
            "commands such as `subnets metagraph`, `stake show` and `subnets list`.",
        ),
    ):
        """
        Sets values in config file
        """
        args = locals()
        args_list = [
            "wallet_name",
            "wallet_path",
            "wallet_hotkey",
            "network",
            "chain",
            "no_cache",
        ]
        bools = ["no_cache"]
        if not any(args.get(arg) for arg in args_list):
            arg = Prompt.ask("Which value would you like to update?", choices=args_list)
            if arg in bools:
                nc = Confirm.ask(
                    f"What value would you like to assign to [red]{arg}[/red]?",
                    default=False,
                )
                self.config[arg] = nc
            else:
                val = Prompt.ask(
                    f"What value would you like to assign to [red]{arg}[/red]?"
                )
                self.config[arg] = val

        if (n := args.get("network")) and n.startswith("ws"):
            if not Confirm.ask(
                "[yellow]Warning[/yellow] your 'network' appears to be a chain endpoint. "
                "Verify this is intentional"
            ):
                raise typer.Exit()
        for arg in args_list:
            if val := args.get(arg):
                self.config[arg] = val
        with open(self.config_path, "w") as f:
            safe_dump(self.config, f)

    def del_config(
        self,
        wallet_name: bool = typer.Option(
            False,
            "--wallet-name",
        ),
        wallet_path: bool = typer.Option(
            False,
            "--wallet-path",
        ),
        wallet_hotkey: bool = typer.Option(
            False,
            "--wallet-hotkey",
        ),
        network: bool = typer.Option(
            False,
            "--network",
        ),
        chain: bool = typer.Option(False, "--chain"),
        no_cache: bool = typer.Option(
            False,
            "--no-cache",
        ),
        all_items: bool = typer.Option(False, "--all"),
    ):
        """
        Setting the flags in this command will clear those items from your config file.

        # Usage

        - To clear the chain and network:

        [green]$[/green] btcli config clear --chain --network

        - To clear your config entirely:

        [green]$[/green] btcli config clear --all
        """
        if all_items:
            self.config = {}
        else:
            args = locals()
            for arg in [
                "wallet_name",
                "wallet_path",
                "wallet_hotkey",
                "network",
                "chain",
                "no_cache",
            ]:
                if args.get(arg):
                    self.config[arg] = None
        with open(self.config_path, "w") as f:
            safe_dump(self.config, f)

    def get_config(self):
        """
        Prints the current config file in a table
        """
        table = Table(Column("Name"), Column("Value"))
        for k, v in self.config.items():
            table.add_row(*[k, str(v)])
        console.print(table)

    def wallet_ask(
        self,
        wallet_name: Optional[str],
        wallet_path: Optional[str],
        wallet_hotkey: Optional[str],
        validate: bool = True,
    ) -> Wallet:
        """
        Generates a wallet object based on supplied values, validating the wallet is valid if flag is set
        :param wallet_name: name of the wallet
        :param wallet_path: root path of the wallets
        :param wallet_hotkey: name of the wallet hotkey file
        :param validate: flag whether to check for the wallet's validity
        :return: created Wallet object
        """
        wallet_name = wallet_name or self.config.get("wallet_name")
        wallet_path = wallet_path or self.config.get("wallet_path")
        wallet_hotkey = wallet_hotkey or self.config.get("wallet_hotkey")

        if not any([wallet_name, wallet_path, wallet_hotkey]):
            _wallet_str = typer.style("wallet", fg="blue")
            wallet_name = typer.prompt(f"Enter {_wallet_str} name")
            wallet = Wallet(name=wallet_name)
        else:
            wallet = Wallet(name=wallet_name, hotkey=wallet_hotkey, path=wallet_path)
        if validate:
            valid = utils.is_valid_wallet(wallet)
            if not valid[0]:
                utils.err_console.print(
                    f"[red]Error: Wallet does not appear valid. Please verify your wallet information: {wallet}[/red]"
                )
                raise typer.Exit()
            elif not valid[1]:
                if not Confirm.ask(
                    f"[yellow]Warning: Wallet appears valid, but hotkey '{wallet.hotkey_str}' does not. Proceed?"
                ):
                    raise typer.Exit()
        return wallet

    def wallet_list(
        self,
        wallet_path: str = typer.Option(
            defaults.wallet.path,
            "--wallet-path",
            "-p",
            help="Filepath of root of wallets",
            prompt=True,
        ),
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
    ):
        """
        Displays all wallets and their respective hotkeys present in the user's Bittensor configuration directory.

        The command organizes the information in a tree structure, displaying each
        wallet along with the `ss58` addresses for the coldkey public key and any hotkeys associated with it.
        The output is presented in a hierarchical tree format, with each wallet as a root node,
        and any associated hotkeys as child nodes. The ``ss58`` address is displayed for each
        coldkey and hotkey that is not encrypted and exists on the device.

        # Usage:

        Upon invocation, the command scans the wallet directory and prints a list of all wallets, indicating whether the
        public keys are available (`?` denotes unavailable or encrypted keys).

        # Example usage:

        [green]$[/green] btcli wallet list --path ~/.bittensor

        [italic]Note[/italic]: This command is read-only and does not modify the filesystem or the network state.
        It is intended for use within the Bittensor CLI to provide a quick overview of the user's wallets.
        """
        self.verbosity_handler(quiet, verbose)
        return self._run_command(wallets.wallet_list(wallet_path))

    def wallet_overview(
        self,
        wallet_name: Optional[str] = Options.wallet_name,
        wallet_path: Optional[str] = Options.wallet_path,
        wallet_hotkey: Optional[str] = Options.wallet_hotkey,
        all_wallets: bool = typer.Option(
            False, "--all", "-a", help="View overview for all wallets"
        ),
        sort_by: Optional[str] = typer.Option(
            None,
            help="Sort the hotkeys by the specified column title (e.g. name, uid, axon).",
        ),
        sort_order: Optional[str] = typer.Option(
            None,
            help="Sort the hotkeys in the specified ordering. (ascending/asc or descending/desc/reverse)",
        ),
        include_hotkeys: list[str] = typer.Option(
            [],
            "--include-hotkeys",
            "-in",
            help="Specify the hotkeys to include by name or ss58 address. (e.g. `hk1 hk2 hk3`). "
            "If left empty, all hotkeys not excluded will be included.",
        ),
        exclude_hotkeys: list[str] = typer.Option(
            [],
            "--exclude-hotkeys",
            "-ex",
            help="Specify the hotkeys to exclude by name or ss58 address. (e.g. `hk1 hk2 hk3`). "
            "If left empty, and no hotkeys included in --include-hotkeys, all hotkeys will be included.",
        ),
        netuids: list[int] = Options.netuids,
        network: str = Options.network,
        chain: str = Options.chain,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
    ):
        """
        Presents a detailed overview of the user's registered accounts on the Bittensor network.

        This command compiles and displays comprehensive information about each neuron associated with the user's
        wallets, including both hotkeys and coldkeys. It is especially useful for users managing multiple accounts or
        seeking a summary of their network activities and stake distributions.

        # Usage:

        The command offers various options to customize the output. Users can filter the displayed data by specific
        netuids, sort by different criteria, and choose to include all wallets in the user's configuration directory.
        The output is presented in a tabular format with the following columns:

        - COLDKEY: The SS58 address of the coldkey.

        - HOTKEY: The SS58 address of the hotkey.

        - UID: Unique identifier of the neuron.

        - ACTIVE: Indicates if the neuron is active.

        - STAKE(τ): Amount of stake in the neuron, in Tao.

        - RANK: The rank of the neuron within the network.

        - TRUST: Trust score of the neuron.

        - CONSENSUS: Consensus score of the neuron.

        - INCENTIVE: Incentive score of the neuron.

        - DIVIDENDS: Dividends earned by the neuron.

        - EMISSION(p): Emission received by the neuron, in Rho.

        - VTRUST: Validator trust score of the neuron.

        - VPERMIT: Indicates if the neuron has a validator permit.

        - UPDATED: Time since last update.

        - AXON: IP address and port of the neuron.

        - HOTKEY_SS58: Human-readable representation of the hotkey.


        # Example usage:

        [green]$[/green] btcli wallet overview

        [green]$[/green] btcli wallet overview --all --sort-by stake --sort-order descending

        [green]$[/green] btcli wallet overview -in hk1 -in hk2 --sort-by stake

        [italic]Note[/italic]: This command is read-only and does not modify the network state or account configurations.
        It provides a quick and comprehensive view of the user's network presence, making it ideal for monitoring account status,
        stake distribution, and overall contribution to the Bittensor network.
        """
        self.verbosity_handler(quiet, verbose)
        if include_hotkeys and exclude_hotkeys:
            utils.err_console.print(
                "[red]You have specified hotkeys for inclusion and exclusion. Pick only one or neither."
            )
            raise typer.Exit()

        if all_wallets:
            if not wallet_path:
                wallet_path = Prompt.ask(
                    "Enter the path of the wallets", default=defaults.wallet.path
                )
        wallet = self.wallet_ask(
            wallet_name, wallet_path, wallet_hotkey, validate=False
        )
        return self._run_command(
            wallets.overview(
                wallet,
                self.initialize_chain(network, chain),
                all_wallets,
                sort_by,
                sort_order,
                include_hotkeys,
                exclude_hotkeys,
                netuids_filter=netuids,
            )
        )

    def wallet_transfer(
        self,
        destination: str = typer.Option(
            None,
            "--destination",
            "--dest",
            "-d",
            prompt=True,
            help="Destination address of the wallet.",
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
        network: str = Options.network,
        chain: str = Options.chain,
        prompt: bool = Options.prompt,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
    ):
        """
        Transfer TAO tokens from one account to another on the Bittensor network.

        This command is used for transactions between different accounts, enabling users to send tokens to other
        participants on the network. The command displays the user's current balance before prompting for the amount
        to transfer, ensuring transparency and accuracy in the transaction.

        # Usage:

        The command requires specifying the destination address (public key) and the amount of TAO to be transferred.
        It checks for sufficient balance and prompts for confirmation before proceeding with the transaction.

        # Example usage:

        [green]$[/green] btcli wallet transfer --dest 5Dp8... --amount 100

        [italic]Note[/italic]: This command is crucial for executing token transfers within the Bittensor network.
        Users should verify the destination address and amount before confirming the transaction to avoid errors or loss of funds.
        """
        self.verbosity_handler(quiet, verbose)
        wallet = self.wallet_ask(wallet_name, wallet_path, wallet_hotkey)
        subtensor = self.initialize_chain(network, chain)
        return self._run_command(
            wallets.transfer(wallet, subtensor, destination, amount, prompt)
        )

    def wallet_swap_hotkey(
        self,
        wallet_name: Optional[str] = Options.wallet_name_req,
        wallet_path: Optional[str] = Options.wallet_path,
        wallet_hotkey: Optional[str] = Options.wallet_hk_req,
        network: Optional[str] = Options.network,
        chain: Optional[str] = Options.chain,
        destination_hotkey_name: Optional[str] = typer.Argument(
            None, help="Destination hotkey name."
        ),
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
        prompt: bool = Options.prompt,
    ):
        """
        [red]Swap hotkeys[/red] for a neuron on the network.

        # Usage:

        The command is used to swap the hotkey of a wallet for another hotkey on that same wallet.

        # Example usage:

        [green]$[/green] btcli wallet swap_hotkey new_hotkey --wallet-name your_wallet_name --wallet-hotkey original_hotkey
        """
        self.verbosity_handler(quiet, verbose)
        original_wallet = self.wallet_ask(wallet_name, wallet_path, wallet_hotkey)
        if not destination_hotkey_name:
            destination_hotkey_name = typer.prompt("Enter the destination hotkey name")
        new_wallet = self.wallet_ask(wallet_name, wallet_path, destination_hotkey_name)
        self.initialize_chain(network, chain)
        return self._run_command(
            wallets.swap_hotkey(original_wallet, new_wallet, self.not_subtensor, prompt)
        )

    def wallet_inspect(
        self,
        all_wallets: bool = typer.Option(
            False,
            "--all",
            "--all-wallets",
            "-a",
            help="Inspect all wallets within specified path.",
        ),
        wallet_name: str = Options.wallet_name,
        wallet_path: str = Options.wallet_path,
        wallet_hotkey: str = Options.wallet_hotkey,
        network: str = Options.network,
        chain: str = Options.chain,
        netuids: list[int] = Options.netuids,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
    ):
        """
        Detailed report of a user's wallet pairs (coldkey, hotkey) on the Bittensor network.

        This report includes balance and staking information for both the coldkey and hotkey associated with the wallet.

        The command gathers data on:

        - Coldkey balance and delegated stakes.
        - Hotkey stake and emissions per neuron on the network.
        - Delegate names and details fetched from the network.

        The resulting table includes columns for:

        - *Coldkey*: The coldkey associated with the user's wallet.

        - *Balance*: The balance of the coldkey.

        - *Delegate*: The name of the delegate to which the coldkey has staked funds.

        - *Stake*: The amount of stake held by both the coldkey and hotkey.

        - *Emission*: The emission or rewards earned from staking.

        - *Netuid*: The network unique identifier of the subnet where the hotkey is active.

        - *Hotkey*: The hotkey associated with the neuron on the network.

        # Usage:

        This command can be used to inspect a single wallet or all wallets located within a
        specified path. It is useful for a comprehensive overview of a user's participation
        and performance in the Bittensor network.

        # Example usage::

        [green]$[/green] btcli wallet inspect

        [green]$[/green] btcli wallet inspect --all -n 1 -n 2 -n 3

        [italic]Note[/italic]: The `inspect` command is for displaying information only and does not perform any
        transactions or state changes on the Bittensor network. It is intended to be used as
        part of the Bittensor CLI and not as a standalone function within user code.
        """
        self.verbosity_handler(quiet, verbose)
        # if all-wallets is entered, ask for path
        if all_wallets:
            if not wallet_path:
                wallet_path = Prompt.ask(
                    "Enter the path of the wallets", default=defaults.wallet.path
                )
        wallet = self.wallet_ask(
            wallet_name, wallet_path, wallet_hotkey, validate=False
        )
        self.initialize_chain(network, chain)
        return self._run_command(
            wallets.inspect(
                wallet,
                self.not_subtensor,
                netuids_filter=netuids,
                all_wallets=all_wallets,
            )
        )

    def wallet_faucet(
        self,
        wallet_name: Optional[str] = Options.wallet_name,
        wallet_path: Optional[str] = Options.wallet_path,
        wallet_hotkey: Optional[str] = Options.wallet_hotkey,
        network: Optional[str] = Options.network,
        chain: Optional[str] = Options.chain,
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
            help="Set flag to use CUDA to pow_register.",
        ),
        dev_id: Optional[int] = typer.Option(
            defaults.pow_register.cuda.dev_id,
            "--dev-id",
            "-d",
            help="Set the CUDA device id(s). Goes by the order of speed. (i.e. 0 is the fastest).",
        ),
        threads_per_block: Optional[int] = typer.Option(
            defaults.pow_register.cuda.tpb,
            "--threads-per-block",
            "-tbp",
            help="Set the number of Threads Per Block for CUDA.",
        ),
        max_successes: Optional[int] = typer.Option(
            3,
            "--max-successes",
            help="Set the maximum number of times to successfully run the faucet for this command.",
        ),
    ):
        """
        Obtain test TAO tokens by performing Proof of Work (PoW).

        This command is particularly useful for users who need test tokens for operations on a local chain.

        # IMPORTANT:
            *THIS COMMAND IS DISABLED ON FINNEY AND TESTNET.*

        # Usage:

        The command uses the PoW mechanism to validate the user's effort and rewards them with test TAO tokens. It is
        typically used in local chain environments where real value transactions are not necessary.

        # Example usage:

        [green]$[/green] btcli wallet faucet --faucet.num_processes 4 --faucet.cuda.use_cuda

        [italic]Note[/italic]: This command is meant for use in local environments where users can experiment with the network
        without using real TAO tokens. It's important for users to have the necessary hardware setup, especially when opting for
        CUDA-based GPU calculations. It is currently disabled on testnet and finney. You must use this on a local chain.
        """
        wallet = self.wallet_ask(wallet_name, wallet_path, wallet_hotkey)
        return self._run_command(
            wallets.faucet(
                wallet,
                self.initialize_chain(network, chain),
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
        wallet_name: Optional[str] = Options.wallet_name_req,
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
        Regenerate a coldkey for a wallet on the Bittensor network.

        This command is used to create a new coldkey from an existing mnemonic, seed, or JSON file.

        # Usage:

        Users can specify a mnemonic, a seed string, or a JSON file path to regenerate a coldkey.
        The command supports optional password protection for the generated key and can overwrite an existing coldkey.

        # Example usage:

        [green]$[/green] btcli wallet regen-coldkey --mnemonic "word1 word2 ... word12"


        [italic]Note[/italic]: This command is critical for users who need to regenerate their coldkey, possibly for recovery or
        security reasons. It should be used with caution to avoid overwriting existing keys unintentionally.
        """
        self.verbosity_handler(quiet, verbose)
        wallet = self.wallet_ask(
            wallet_name, wallet_path, wallet_hotkey, validate=False
        )
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
        wallet_name: Optional[str] = Options.wallet_name_req,
        wallet_path: Optional[str] = Options.wallet_path,
        wallet_hotkey: Optional[str] = Options.wallet_hotkey,
        public_key_hex: Optional[str] = Options.public_hex_key,
        ss58_address: Optional[str] = Options.ss58_address,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
    ):
        """
        Regenerate the public part of a coldkey (coldkeypub) for a wallet.

        This command is used when a user needs to recreate their coldkeypub from an existing public key or SS58 address.

        # Usage:

        The command requires either a public key in hexadecimal format or an ``SS58`` address to regenerate the
        coldkeypub. It optionally allows overwriting an existing coldkeypub file.

        # Example usage:

        [green]$[/green] btcli wallet regen_coldkeypub --ss58_address 5DkQ4...

        [italic]Note[/italic]: This command is particularly useful for users who need to regenerate their coldkeypub,
        perhaps due to file corruption or loss. It is a recovery-focused utility that ensures continued access to wallet
        functionalities.
        """
        self.verbosity_handler(quiet, verbose)
        wallet = self.wallet_ask(
            wallet_name, wallet_path, wallet_hotkey, validate=False
        )
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
        wallet_name: Optional[str] = Options.wallet_name_req,
        wallet_path: Optional[str] = Options.wallet_path,
        wallet_hotkey: Optional[str] = Options.wallet_hk_req,
        mnemonic: Optional[str] = Options.mnemonic,
        seed: Optional[str] = Options.seed,
        json: Optional[str] = Options.json,
        json_password: Optional[str] = Options.json_password,
        use_password: Optional[bool] = Options.use_password,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
    ):
        """
        Regenerates a hotkey for a wallet.

        Similar to regenerating a coldkey, this command creates a new hotkey from a mnemonic, seed, or JSON file.

        # Usage:

        Users can provide a mnemonic, seed string, or a JSON file to regenerate the hotkey.
        The command supports optional password protection and can overwrite an existing hotkey.

        # Example usage:

        [green]$[/green] btcli wallet regen_hotkey --seed 0x1234...

        [italic]Note[/italic]: This command is essential for users who need to regenerate their hotkey,
        possibly for security upgrades or key recovery.
        It should be used cautiously to avoid accidental overwrites of existing keys.
        """
        self.verbosity_handler(quiet, verbose)
        wallet = self.wallet_ask(wallet_name, wallet_path, wallet_hotkey)
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
        wallet_name: Optional[str] = Options.wallet_name_req,
        wallet_path: Optional[str] = Options.wallet_path,
        wallet_hotkey: Optional[str] = Options.wallet_hk_req,
        n_words: Optional[int] = None,
        use_password: bool = typer.Option(
            False,  # Overriden to False
            help="Set true to protect the generated bittensor key with a password.",
            is_flag=True,
            flag_value=True,
        ),
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
    ):
        """
        Create a new hotkey under a wallet.

        # Usage:

        This command is used to generate a new hotkey for managing a neuron or participating in the network,
        with an optional word count for the mnemonic and supports password protection. It also allows overwriting an
        existing hotkey.

        # Example usage:

        [green]$[/green] btcli wallet new-hotkey --n_words 24

        [italic]Note[/italic]: This command is useful for users who wish to create additional hotkeys
        for different purposes, such as running multiple miners or separating operational roles within the network.
        """
        self.verbosity_handler(quiet, verbose)
        wallet = self.wallet_ask(
            wallet_name, wallet_path, wallet_hotkey, validate=False
        )
        n_words = get_n_words(n_words)
        return self._run_command(wallets.new_hotkey(wallet, n_words, use_password))

    def wallet_new_coldkey(
        self,
        wallet_name: Optional[str] = Options.wallet_name,
        wallet_path: Optional[str] = Options.wallet_path,
        wallet_hotkey: Optional[str] = Options.wallet_hotkey,
        n_words: Optional[int] = None,
        use_password: Optional[bool] = Options.use_password,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
    ):
        """
        Create a new coldkey under a wallet. A coldkey, is essential for holding balances and performing high-value transactions.

        # Usage:

        The command creates a new coldkey with an optional word count for the mnemonic and supports password
        protection. It also allows overwriting an existing coldkey.

        # Example usage:

        [green]$[/green] btcli wallet new_coldkey --n_words 15

        [italic]Note[/italic]: This command is crucial for users who need to create a new coldkey for
        enhanced security or as part of setting up a new wallet. It's a foundational step in establishing
        a secure presence on the Bittensor network.
        """
        self.verbosity_handler(quiet, verbose)
        wallet = self.wallet_ask(
            wallet_name, wallet_path, wallet_hotkey, validate=False
        )
        n_words = get_n_words(n_words)
        return self._run_command(wallets.new_coldkey(wallet, n_words, use_password))

    def wallet_check_ck_swap(
        self,
        wallet_name: Optional[str] = Options.wallet_name,
        wallet_path: Optional[str] = Options.wallet_path,
        wallet_hotkey: Optional[str] = Options.wallet_hotkey,
        network: Optional[str] = Options.network,
        chain: Optional[str] = Options.chain,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
    ):
        """
        Check the scheduled swap status of a coldkey.

        # Usage:

        Users need to specify the wallet they want to check the swap status of.

        # Example usage:

        [green]$[/green] btcli wallet check_coldkey_swap

        [italic]Note[/italic]: This command is important for users who wish check if swap requests were made against their coldkey.
        """
        self.verbosity_handler(quiet, verbose)
        wallet = self.wallet_ask(wallet_name, wallet_path, wallet_hotkey)
        self.initialize_chain(network, chain)
        return self._run_command(wallets.check_coldkey_swap(wallet, self.not_subtensor))

    def wallet_create_wallet(
        self,
        wallet_name: Optional[str] = Options.wallet_name_req,
        wallet_path: Optional[str] = Options.wallet_path,
        wallet_hotkey: Optional[str] = Options.wallet_hk_req,
        n_words: Optional[int] = None,
        use_password: bool = Options.use_password,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
    ):
        """
        Generate both a new coldkey and hotkey under a specified wallet.

        This command is a comprehensive utility for creating a complete wallet setup with both cold
        and hotkeys.

        # Usage:
        The command facilitates the creation of a new coldkey and hotkey with an optional word count for the
        mnemonics. It supports password protection for the coldkey and allows overwriting of existing keys.

        # Example usage:

        [green]$[/green] btcli wallet create --n_words 21

        [italic]Note[/italic]: This command is ideal for new users setting up their wallet for the first time
        or for those who wish to completely renew their wallet keys. It ensures a fresh start with new keys
        for secure and effective participation in the network.
        """
        self.verbosity_handler(quiet, verbose)
        wallet = self.wallet_ask(
            wallet_name, wallet_path, wallet_hotkey, validate=False
        )
        n_words = get_n_words(n_words)
        return self._run_command(
            wallets.wallet_create(
                wallet,
                n_words,
                use_password,
            )
        )

    def wallet_balance(
        self,
        wallet_name: Optional[str] = Options.wallet_name,
        wallet_path: Optional[str] = Options.wallet_path,
        wallet_hotkey: Optional[str] = Options.wallet_hotkey,
        all_balances: Optional[bool] = typer.Option(
            False,
            "--all",
            "-a",
            help="Whether to display the balances for all wallets.",
        ),
        network: str = Options.network,
        chain: str = Options.chain,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
    ):
        """
        Check the balance of the wallet on the Bittensor network.
        This provides a detailed view of the wallet's coldkey balances, including free and staked balances.

        # Usage:

        The command lists the balances of all wallets in the user's configuration directory, showing the
        wallet name, coldkey address, and the respective free and staked balances.

        # Example usages:

        - To display the balance of a single wallet, use the command with the `--wallet-name` argument to specify
        the wallet name:

        [green]$[/green] btcli w balance --wallet-name WALLET

        [green]$[/green] btcli w balance

        - To display the balances of all wallets, use the `--all` argument:

        [green]$[/green] btcli w balance --all
        """
        self.verbosity_handler(quiet, verbose)
        if all_balances:
            if not wallet_path:
                wallet_path = Prompt.ask(
                    "Enter the path of the wallets", default=defaults.wallet.path
                )
        subtensor = self.initialize_chain(network, chain)
        wallet = self.wallet_ask(
            wallet_name, wallet_path, wallet_hotkey, validate=False
        )
        return self._run_command(
            wallets.wallet_balance(wallet, subtensor, all_balances)
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
        Fetch the latest transfers of the provided wallet on the Bittensor network.
        This provides a detailed view of the transfers carried out on the wallet.

        # Usage:

        The command lists the latest transfers of the provided wallet, showing the 'From', 'To', 'Amount',
        'Extrinsic ID' and 'Block Number'.

        # Example usage:

        [green]$[/green] btcli wallet history

        [italic]Note[/italic]: This command is essential for users to monitor their financial status on the Bittensor network.
        It helps in fetching info on all the transfers so that user can easily tally and cross-check the transactions.
        """
        self.verbosity_handler(quiet, verbose)
        wallet = self.wallet_ask(
            wallet_name, wallet_path, wallet_hotkey, validate=False
        )
        return self._run_command(wallets.wallet_history(wallet))

    def wallet_set_id(
        self,
        wallet_name: Optional[str] = Options.wallet_name,
        wallet_path: Optional[str] = Options.wallet_path,
        wallet_hotkey: Optional[str] = Options.wallet_hotkey,
        network: Optional[str] = Options.network,
        chain: Optional[str] = Options.chain,
        display_name: str = typer.Option(
            "",
            "--display-name",
            "--display",
            help="The display name for the identity.",
            prompt=True,
        ),
        legal_name: str = typer.Option(
            "",
            "--legal-name",
            "--legal",
            help="The legal name for the identity.",
            prompt=True,
        ),
        web_url: str = typer.Option(
            "", "--web-url", "--web", help="The web url for the identity.", prompt=True
        ),
        riot_handle: str = typer.Option(
            "",
            "--riot-handle",
            "--riot",
            help="The riot handle for the identity.",
            prompt=True,
        ),
        email: str = typer.Option(
            "", help="The email address for the identity.", prompt=True
        ),
        pgp_fingerprint: str = typer.Option(
            "",
            "--pgp-fingerprint",
            "--pgp",
            help="The pgp fingerprint for the identity.",
            prompt=True,
        ),
        image_url: str = typer.Option(
            "",
            "--image-url",
            "--image",
            help="The image url for the identity.",
            prompt=True,
        ),
        info_: str = typer.Option(
            "", "--info", "-i", help="The info for the identity.", prompt=True
        ),
        twitter_url: str = typer.Option(
            "",
            "-x",
            "-𝕏",
            "--twitter-url",
            "--twitter",
            help="The 𝕏 (Twitter) url for the identity.",
            prompt=True,
        ),
        validator_id: bool = typer.Option(
            "--validator/--not-validator",
            help="Are you updating a validator hotkey identity?",
            prompt=True,
        ),
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
        prompt: bool = Options.prompt,
    ):
        """
        Allows for the creation or update of a delegate's on-chain identity on the Bittensor network.

        This identity includes various attributes such as display name, legal name, web URL, PGP fingerprint, and
        contact information, among others.

        The command prompts the user for the different identity attributes and validates the
        input size for each attribute. It provides an option to update an existing validator
        hotkey identity. If the user consents to the transaction cost, the identity is updated
        on the blockchain.

        Each field has a maximum size of 64 bytes. The PGP fingerprint field is an exception
        and has a maximum size of 20 bytes. The user is prompted to enter the PGP fingerprint
        as a hex string, which is then converted to bytes. The user is also prompted to enter
        the coldkey or hotkey ``ss58`` address for the identity to be updated. If the user does
        not have a hotkey, the coldkey address is used by default.

        If setting a validator identity, the hotkey will be used by default. If the user is
        setting an identity for a subnet, the coldkey will be used by default.

        # Usage:

        The user should call this command from the command line and follow the interactive
        prompts to enter or update the identity information. The command will display the
        updated identity details in a table format upon successful execution.

        # Example usage:

        [green]$[/green] btcli wallet set_identity

        [italic]Note[/italic]: This command should only be used if the user is willing to incur the 1 TAO
        transaction fee associated with setting an identity on the blockchain. It is a high-level command
        that makes changes to the blockchain state and should not be used programmatically as
        part of other scripts or applications.
        """
        self.verbosity_handler(quiet, verbose)
        wallet = self.wallet_ask(wallet_name, wallet_path, wallet_hotkey)
        return self._run_command(
            wallets.set_id(
                wallet,
                self.initialize_chain(network, chain),
                display_name,
                legal_name,
                web_url,
                pgp_fingerprint,
                riot_handle,
                email,
                image_url,
                twitter_url,
                info_,
                validator_id,
                prompt,
            )
        )

    def wallet_get_id(
        self,
        key: str = typer.Option(
            None,
            "--key",
            "-k",
            "--ss58",
            help="The coldkey or hotkey ss58 address to query.",
            prompt=True,
        ),
        network: Optional[str] = Options.network,
        chain: Optional[str] = Options.chain,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
    ):
        """
        Retrieves and displays the identity details of a user's coldkey or hotkey.

        The command performs the following actions:

        - Connects to the subtensor network and retrieves the identity information.

        - Displays the information in a structured table format.

        The displayed table includes:

        - *Address*: The ``ss58`` address of the queried key.

        - *Item*: Various attributes of the identity such as stake, rank, and trust.

        - *Value*: The corresponding values of the attributes.

        # Usage:

        The user must provide an ss58 address as input to the command. If the address is not
        provided in the configuration, the user is prompted to enter one.

        # Example usage:

        [green]$[/green] btcli wallet get_identity --key <s58_address>

        [italic]Note[/italic]: This function is designed for CLI use and should be executed in a terminal.
        It is primarily used for informational purposes and has no side effects on the network state.
        """
        self.verbosity_handler(quiet, verbose)
        return self._run_command(
            wallets.get_id(self.initialize_chain(network, chain), key)
        )

    def wallet_sign(
        self,
        wallet_path: str = Options.wallet_path,
        wallet_name: str = Options.wallet_name_req,
        wallet_hotkey: str = Options.wallet_hotkey,
        use_hotkey: bool = typer.Option(
            False,
            "--use-hotkey",
            help="If specified, the message will be signed by the hotkey",
        ),
        message: str = typer.Option("", help="The message to encode and sign"),
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
    ):
        """
        Allows users to sign a message with the provided wallet or wallet hotkey.

        # Usage:

        The command generates a signature for a given message using the provided wallet

        # Example usage:

        [green]$[/green] btcli wallet sign --wallet-name default --message '{"something": "here", "timestamp": 1719908486}'

        [green]$[/green] btcli wallet sign --wallet-name default --wallet-hotkey hotkey --message
        '{"something": "here", "timestamp": 1719908486}'

        [italic]Note[/italic]: When using `btcli`, `w` is used interchangeably with `wallet`. You may use either based
        on your preference for brevity or clarity. This command is essential for users to easily prove their ownership
        over a coldkey or a hotkey.
        """
        self.verbosity_handler(quiet, verbose)
        wallet = self.wallet_ask(wallet_name, wallet_path, wallet_hotkey)
        if not use_hotkey:
            use_hotkey = typer.confirm(
                "Do you want to sign using the hotkey?", default=False
            )

        if use_hotkey and not wallet_hotkey:
            wallet_hotkey = typer.prompt("Enter your hotkey name")
            wallet = self.wallet_ask(wallet.name, wallet_path, wallet_hotkey)

        if not message:
            message = typer.prompt("Enter the message to encode and sign")

        return self._run_command(wallets.sign(wallet, message, use_hotkey))

    def root_list(
        self,
        network: Optional[str] = Options.network,
        chain: Optional[str] = Options.chain,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
    ):
        """
        Display the members of the root network (Netuid = 0) on the Bittensor network.

        This command provides an overview of the neurons that constitute the network's foundational layer.

        # Usage:
        Upon execution, the command fetches and lists the neurons in the root network, showing their unique identifiers
        (UIDs), names, addresses, stakes, and whether they are part of the senate (network governance body).

        # Example usage:

        [green]$[/green] btcli root list

        [italic]Note[/italic]: This command is useful for users interested in understanding the composition and
        governance structure of the Bittensor network's root layer. It provides insights into which neurons hold
        significant influence and responsibility within the network.
        """
        self.verbosity_handler(quiet, verbose)
        return self._run_command(
            root.root_list(subtensor=self.initialize_chain(network, chain))
        )

    def root_set_weights(
        self,
        network: str = Options.network,
        chain: str = Options.chain,
        wallet_name: str = Options.wallet_name_req,
        wallet_path: str = Options.wallet_path,
        wallet_hotkey: str = Options.wallet_hk_req,
        netuids: list[int] = typer.Option(
            None, help="Netuids, e.g. `-n 0 -n 1 -n 2` ..."
        ),
        weights: list[float] = typer.Argument(
            None,
            help="Weights: e.g. `0.02 0.03 0.01` ...",
        ),
        prompt: bool = Options.prompt,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
    ):
        """
        Set the weights for the oot network on the Bittensor network.

        This command is used by network senators to influence the distribution of network rewards and responsibilities.

        # Usage:

        The command allows setting weights for different subnets within the root network. Users need to specify the
        netuids (network unique identifiers) and corresponding weights they wish to assign.

        # Example usage:

        [green]$[/green]  btcli root set-weights 0.3 0.3 0.4 -n 1 -n 2 -n 3 --chain ws://127.0.0.1:9945


        [green]$[/green] This command is particularly important for network senators and requires a comprehensive understanding of the
        network's dynamics. It is a powerful tool that directly impacts the network's operational mechanics and reward
        distribution.
        """
        self.verbosity_handler(quiet, verbose)
        netuids = list_prompt(netuids, int, "Enter netuids")
        wallet = self.wallet_ask(wallet_name, wallet_path, wallet_hotkey)
        if not weights:
            weights = list_prompt([], float, "Weights: e.g. 0.02, 0.03, 0.01 ")
        self._run_command(
            root.set_weights(
                wallet, self.initialize_chain(network, chain), netuids, weights, prompt
            )
        )

    def root_get_weights(
        self,
        network: Optional[str] = Options.network,
        chain: Optional[str] = Options.chain,
        limit_min_col: Optional[int] = typer.Option(
            None,
            "--limit-min-col",
            "--min",
            help="Limit left display of the table to this column.",
        ),
        limit_max_col: Optional[int] = typer.Option(
            None,
            "--limit-max-col",
            "--max",
            help="Limit right display of the table to this column.",
        ),
        reuse_last: bool = Options.reuse_last,
        html_output: bool = Options.html_output,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
    ):
        """
        Retrieve the weights set for the root network on the Bittensor network.

        This command provides visibility into how network responsibilities and rewards are distributed among various
        subnets.

        # Usage:
        The command outputs a table listing the weights assigned to each subnet within the root network. This
        information is crucial for understanding the current influence and reward distribution among the subnets.

        # Example usage:

        [green]$[/green] btcli root get_weights

        [italic]Note[/italic]: This command is essential for users interested in the governance and operational
        dynamics of the Bittensor network. It offers transparency into how network rewards and responsibilities
        are allocated across different subnets.
        """
        self.verbosity_handler(quiet, verbose)
        if (reuse_last or html_output) and self.config.get("no_cache") is True:
            err_console.print(
                "Unable to use `--reuse-last` or `--html` when config no-cache is set."
            )
            raise typer.Exit()
        if not reuse_last:
            subtensor = self.initialize_chain(network, chain)
        else:
            subtensor = None
        return self._run_command(
            root.get_weights(
                subtensor,
                limit_min_col,
                limit_max_col,
                reuse_last,
                html_output,
                self.config.get("no_cache", False),
            )
        )

    def root_boost(
        self,
        network: Optional[str] = Options.network,
        chain: Optional[str] = Options.chain,
        wallet_name: str = Options.wallet_name_req,
        wallet_path: Optional[str] = Options.wallet_path,
        wallet_hotkey: Optional[str] = Options.wallet_hk_req,
        netuid: int = Options.netuid,
        amount: float = typer.Option(
            None,
            "--amount",
            "--increase",
            "-a",
            prompt=True,
            help="Amount (float) to boost, (e.g. 0.01)",
        ),
        prompt: bool = Options.prompt,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
    ):
        """
        Not currently working with new implementation

        [red]Boost the weights[/red] for a specific [red]subnet[/red] within the root network on the Bittensor
        network.

        # Usage:

        The command allows boosting the weights for different subnets within the root network.

        # Example usage:

        [green]$[/green] btcli root boost --netuid 1 --increase 0.01
        """
        self.verbosity_handler(quiet, verbose)
        wallet = self.wallet_ask(wallet_name, wallet_path, wallet_hotkey)
        return self._run_command(
            root.set_boost(
                wallet, self.initialize_chain(network, chain), netuid, amount, prompt
            )
        )

    def root_slash(
        self,
        network: Optional[str] = Options.network,
        chain: Optional[str] = Options.chain,
        wallet_name: str = Options.wallet_name_req,
        wallet_path: Optional[str] = Options.wallet_path,
        wallet_hotkey: Optional[str] = Options.wallet_hk_req,
        netuid: int = Options.netuid,
        amount: float = typer.Option(
            None,
            "--amount",
            "--decrease",
            "-a",
            prompt=True,
            help="Amount (float) to boost, (e.g. 0.01)",
        ),
        prompt: bool = Options.prompt,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
    ):
        """
        Decrease the weights for a specific subnet within the root network on the Bittensor network.

        # Usage:

        The command allows slashing (decreasing) the weights for different subnets within the root network.

        # Example usage:

        [green]$[/green] btcli root slash --netuid 1 --decrease 0.01

        Enter netuid (e.g. 1): 1
        Enter decrease amount (e.g. 0.01): 0.2
        Slashing weight for subnet: 1 by amount: 0.2

        """
        self.verbosity_handler(quiet, verbose)
        wallet = self.wallet_ask(wallet_name, wallet_path, wallet_hotkey)
        return self._run_command(
            root.set_slash(
                wallet, self.initialize_chain(network, chain), netuid, amount, prompt
            )
        )

    def root_senate_vote(
        self,
        network: Optional[str] = Options.network,
        chain: Optional[str] = Options.chain,
        wallet_name: Optional[str] = Options.wallet_name_req,
        wallet_path: Optional[str] = Options.wallet_path,
        wallet_hotkey: Optional[str] = Options.wallet_hk_req,
        proposal: str = typer.Option(
            None,
            "--proposal",
            "--proposal-hash",
            help="The hash of the proposal to vote on.",
        ),
        prompt: bool = Options.prompt,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
    ):
        """
        Cast a vote on an active proposal in Bittensor's governance protocol.

        This command is used by Senate members to vote on various proposals that shape the network's future.

        # Usage:

        The user needs to specify the hash of the proposal they want to vote on. The command then allows the Senate
        member to cast an 'Aye' or 'Nay' vote, contributing to the decision-making process.

        # Example usage:

        [green]$[/green] btcli root senate_vote --proposal <proposal_hash>

        [italic]Note[/italic]: This command is crucial for Senate members to exercise their voting rights on key proposals.
        It plays a vital role in the governance and evolution of the Bittensor network.
        """
        self.verbosity_handler(quiet, verbose)
        wallet = self.wallet_ask(wallet_name, wallet_path, wallet_hotkey)
        return self._run_command(
            root.senate_vote(
                wallet, self.initialize_chain(network, chain), proposal, prompt
            )
        )

    def root_senate(
        self,
        network: Optional[str] = Options.network,
        chain: Optional[str] = Options.chain,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
    ):
        """
        View the members of Bittensor's governance protocol, known as the Senate.

        This command lists the delegates involved in the decision-making process of the Bittensor network.

        # Usage:

        The command retrieves and displays a list of Senate members, showing their names and wallet addresses.
        This information is crucial for understanding who holds governance roles within the network.

        # Example usage:

        [green]$[/green] btcli root senate

        [italic]Note[/italic]: This command is particularly useful for users interested in the governance structure
        and participants of the Bittensor network. It provides transparency into the network's decision-making body.
        """
        self.verbosity_handler(quiet, verbose)
        return self._run_command(root.get_senate(self.initialize_chain(network, chain)))

    def root_register(
        self,
        network: Optional[str] = Options.network,
        chain: Optional[str] = Options.chain,
        wallet_name: Optional[str] = Options.wallet_name_req,
        wallet_path: Optional[str] = Options.wallet_path,
        wallet_hotkey: Optional[str] = Options.wallet_hk_req,
        prompt: bool = Options.prompt,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
    ):
        """
        Register a neuron on the Bittensor network by recycling some TAO (the network's native token).

        This command is used to add a new neuron to a specified subnet within the network, contributing to the
        decentralization and robustness of Bittensor.

        # Usage:

        Before registering, the command checks if the specified subnet exists and whether the user's balance is
        sufficient to cover the registration cost.

        The registration cost is determined by the current recycle amount for the specified subnet. If the balance is
        insufficient or the subnet does not exist, the command will exit with an appropriate error message.

        If the preconditions are met, and the user confirms the transaction (if `no_prompt` is not set), the command
        proceeds to register the neuron by recycling the required amount of TAO.

        The command structure includes:

        - Verification of subnet existence.

        - Checking the user's balance against the current recycle amount for the subnet.

        - User confirmation prompt for proceeding with registration.

        - Execution of the registration process.


        Columns Displayed in the confirmation prompt:

        - Balance: The current balance of the user's wallet in TAO.

        - Cost to Register: The required amount of TAO needed to register on the specified subnet.


        # Example usage:

        [green]$[/green] btcli subnets register --netuid 1

        [italic]Note[/italic]: This command is critical for users who wish to contribute a new neuron to the network.
        It requires careful consideration of the subnet selection and an understanding of the registration costs.
        Users should ensure their wallet is sufficiently funded before attempting to register a neuron.
        """
        self.verbosity_handler(quiet, verbose)
        wallet = self.wallet_ask(wallet_name, wallet_path, wallet_hotkey)
        return self._run_command(
            root.register(wallet, self.initialize_chain(network, chain), prompt)
        )

    def root_proposals(
        self,
        network: Optional[str] = Options.network,
        chain: Optional[str] = Options.chain,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
    ):
        """
        View active proposals for the senate within Bittensor's governance protocol.

        This command displays the details of ongoing proposals, including votes, thresholds, and proposal data.

        # Usage:

        The command lists all active proposals, showing their hash, voting threshold, number of ayes and nays, detailed
        votes by address, end block number, and call data associated with each proposal.

        # Example usage:

        [green]$[/green] btcli root proposals

        [italic]Note[/italic]: This command is essential for users who are actively participating in or monitoring the
        governance of the Bittensor network. It provides a detailed view of the proposals being considered, along with
        the community's response to each.
        """
        self.verbosity_handler(quiet, verbose)
        return self._run_command(root.proposals(self.initialize_chain(network, chain)))

    def root_set_take(
        self,
        network: Optional[str] = Options.network,
        chain: Optional[str] = Options.chain,
        wallet_name: Optional[str] = Options.wallet_name_req,
        wallet_path: Optional[str] = Options.wallet_path,
        wallet_hotkey: Optional[str] = Options.wallet_hk_req,
        take: float = typer.Option(None, help="The new take value."),
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
    ):
        """
        Allows users to change their delegate take.

        The command performs several checks:

        1. Hotkey is already a delegate
        2. New take value is within 0-18% range

        # Usage:

        To run the command, the user must have a configured wallet with both hotkey and coldkey. Also, the hotkey should already be a delegate.

        # Example usage:

        [green]$[/green] btcli root set_take --wallet-name my_wallet --wallet-hotkey my_hotkey

        [italic]Note[/italic]: This function can be used to update the takes individually for every subnet
        """
        self.verbosity_handler(quiet, verbose)
        wallet = self.wallet_ask(wallet_name, wallet_path, wallet_hotkey)
        if not take:
            max_value = typer.style("Max: 0.18", fg="red")
            min_value = typer.style("Min: 0.08", fg="blue")
            prompt_text = typer.style(
                "Enter take value (0.18 for 18%)", fg="green", bold=True
            )
            take = FloatPrompt.ask(f"{prompt_text} {min_value} {max_value}")
        return self._run_command(
            root.set_take(wallet, self.initialize_chain(network, chain), take)
        )

    def root_delegate_stake(
        self,
        delegate_ss58key: str = typer.Option(
            None, help="The `SS58` address of the delegate to stake to.", prompt=True
        ),
        amount: Optional[float] = typer.Option(
            None, help="The amount of Tao to stake. Do no specify if using `--all`"
        ),
        stake_all: Optional[bool] = typer.Option(
            False,
            "--all",
            "-a",
            help="If specified, the command stakes all available Tao. Do not specify if using"
            " `--amount`",
        ),
        wallet_name: Optional[str] = Options.wallet_name,
        wallet_path: Optional[str] = Options.wallet_path,
        wallet_hotkey: Optional[str] = Options.wallet_hotkey,
        network: Optional[str] = Options.network,
        chain: Optional[str] = Options.chain,
        prompt: bool = Options.prompt,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
    ):
        """
        Stakes Tao to a specified delegate on the Bittensor network.

        This action allocates the user's Tao to support a delegate, potentially earning staking rewards in return.

        The command interacts with the user to determine the delegate and the amount of Tao to be staked. If the
        `--all` flag is used, it delegates the entire available balance.

        # Usage:

        The user must specify the delegate's SS58 address and the amount of Tao to stake. The function sends a
        transaction to the subtensor network to delegate the specified amount to the chosen delegate. These values are
        prompted if not provided. You can list all delegates with `btcli root list-delegates`.

        # Example usage:

        [green]$[/green] btcli delegate-stake --delegate_ss58key <SS58_ADDRESS> --amount <AMOUNT>

        [green]$[/green] btcli delegate-stake --delegate_ss58key <SS58_ADDRESS> --all


        [italic]Note[/italic]: This command modifies the blockchain state and may incur transaction fees. It requires user confirmation
        and interaction, and is designed to be used within the Bittensor CLI environment. The user should ensure the delegate's address
        and the amount to be staked are correct before executing the command.
        """
        self.verbosity_handler(quiet, verbose)
        if amount and stake_all:
            err_console.print(
                "`--amount` and `--all` specified. Choose one or the other."
            )
        if not stake_all and not amount:
            while True:
                amount = FloatPrompt.ask(
                    "[blue bold]Amount to stake (TAO τ)[/blue bold]", console=console
                )
                confirmation = FloatPrompt.ask(
                    "[blue bold]Confirm the amount to stake (TAO τ)[/blue bold]",
                    console=console,
                )
                if amount == confirmation:
                    break
                else:
                    err_console.print(
                        "[red]The amounts do not match. Please try again.[/red]"
                    )

        wallet = self.wallet_ask(wallet_name, wallet_path, wallet_hotkey)
        return self._run_command(
            root.delegate_stake(
                wallet,
                self.initialize_chain(network, chain),
                float(amount),
                delegate_ss58key,
                prompt,
            )
        )

    def root_undelegate_stake(
        self,
        delegate_ss58key: str = typer.Option(
            None,
            help="The `SS58` address of the delegate to undelegate from.",
            prompt=True,
        ),
        amount: Optional[float] = typer.Option(
            None, help="The amount of Tao to unstake. Do no specify if using `--all`"
        ),
        unstake_all: Optional[bool] = typer.Option(
            False,
            "--all",
            "-a",
            help="If specified, the command undelegates all staked Tao from the delegate. Do not specify if using"
            " `--amount`",
        ),
        wallet_name: Optional[str] = Options.wallet_name,
        wallet_path: Optional[str] = Options.wallet_path,
        wallet_hotkey: Optional[str] = Options.wallet_hotkey,
        network: Optional[str] = Options.network,
        chain: Optional[str] = Options.chain,
        prompt: bool = Options.prompt,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
    ):
        """
        Allows users to withdraw their staked Tao from a delegate on the Bittensor network.

        This process is known as "undelegating" and it reverses the delegation process, freeing up the staked tokens.

        The command prompts the user for the amount of Tao to undelegate and the ``SS58`` address of the delegate from
        which to undelegate. If the ``--all`` flag is used, it will attempt to undelegate the entire staked amount from
        the specified delegate.

        # Usage:

        The user must provide the delegate's SS58 address and the amount of Tao to undelegate. The function will then
        send a transaction to the Bittensor network to process the undelegation.

        # Example usage:

        [green]$[/green] btcli undelegate --delegate_ss58key <SS58_ADDRESS> --amount <AMOUNT>

        [green]$[/green]  btcli undelegate --delegate_ss58key <SS58_ADDRESS> --all


        [italic]Note[/italic]: This command can result in a change to the blockchain state and may incur transaction fees.
        It is interactive and requires confirmation from the user before proceeding. It should be used with care as undelegating can
        affect the delegate's total stake and potentially the user's staking rewards.
        """
        self.verbosity_handler(quiet, verbose)
        if amount and unstake_all:
            err_console.print(
                "`--amount` and `--all` specified. Choose one or the other."
            )
        if not unstake_all and not amount:
            while True:
                amount = FloatPrompt.ask(
                    "[blue bold]Amount to unstake (TAO τ)[/blue bold]", console=console
                )
                confirmation = FloatPrompt.ask(
                    "[blue bold]Confirm the amount to unstake (TAO τ)[/blue bold]",
                    console=console,
                )
                if amount == confirmation:
                    break
                else:
                    err_console.print(
                        "[red]The amounts do not match. Please try again.[/red]"
                    )

        wallet = self.wallet_ask(wallet_name, wallet_path, wallet_hotkey)
        self._run_command(
            root.delegate_unstake(
                wallet,
                self.initialize_chain(network, chain),
                float(amount),
                delegate_ss58key,
                prompt,
            )
        )

    def root_my_delegates(
        self,
        network: Optional[str] = Options.network,
        chain: Optional[str] = Options.chain,
        wallet_name: Optional[str] = Options.wallet_name,
        wallet_path: Optional[str] = Options.wallet_path,
        wallet_hotkey: Optional[str] = Options.wallet_hotkey,
        all_wallets: bool = typer.Option(
            False,
            "--all-wallets",
            "--all",
            "-a",
            help="If specified, the command aggregates information across all wallets.",
        ),
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
    ):
        """
        Retrieves and displays a table of delegated stakes from a user's wallet(s) to various delegates.

        The command provides detailed insights into the user's
        staking activities and the performance of their chosen delegates.

        The table output includes the following columns:

        - Wallet: The name of the user's wallet.

        - OWNER: The name of the delegate's owner.

        - SS58: The truncated SS58 address of the delegate.

        - Delegation: The amount of Tao staked by the user to the delegate.

        - τ/24h: The earnings from the delegate to the user over the past 24 hours.

        - NOMS: The number of nominators for the delegate.

        - OWNER STAKE(τ): The stake amount owned by the delegate.

        - TOTAL STAKE(τ): The total stake amount held by the delegate.

        - SUBNETS: The list of subnets the delegate is a part of.

        - VPERMIT: Validator permits held by the delegate for various subnets.

        - 24h/kτ: Earnings per 1000 Tao staked over the last 24 hours.

        - Desc: A description of the delegate.


        The command also sums and prints the total amount of Tao delegated across all wallets.

        # Usage:

        The command can be run as part of the Bittensor CLI suite of tools and requires no parameters if a single wallet
        is used. If multiple wallets are present, the `--all` flag can be specified to aggregate information across
        all wallets.

        # Example usage:

        [green]$[/green] btcli root my-delegates
        [green]$[/green] btcli root my-delegates --all
        [green]$[/green] btcli root my-delegates --wallet-name my_wallet

        [italic]Note[/italic]: This function is typically called by the CLI parser and is not intended to be used directly in user code.
        """
        self.verbosity_handler(quiet, verbose)
        wallet = self.wallet_ask(wallet_name, wallet_path, wallet_hotkey)
        self._run_command(
            root.my_delegates(
                wallet, self.initialize_chain(network, chain), all_wallets
            )
        )

    def root_list_delegates(
        self,
        network: Optional[str] = Options.network,
        chain: Optional[str] = Options.chain,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
    ):
        """
        Displays a table of Bittensor network delegates, providing a comprehensive overview of delegate statistics and information.

        This table helps users make informed decisions on which delegates to allocate their TAO stake.

        The table columns include:

        - INDEX: The delegate's index in the sorted list.

        - DELEGATE: The name of the delegate.

        - SS58: The delegate's unique SS58 address (truncated for display).

        - NOMINATORS: The count of nominators backing the delegate.

        - DELEGATE STAKE(τ): The amount of delegate's own stake (not the TAO delegated from any nominators).

        - TOTAL STAKE(τ): The delegate's cumulative stake, including self-staked and nominators' stakes.

        - CHANGE/(4h): The percentage change in the delegate's stake over the last four hours.

        - SUBNETS: The subnets to which the delegate is registered.

        - VPERMIT: Indicates the subnets for which the delegate has validator permits.

        - NOMINATOR/(24h)/kτ: The earnings per 1000 τ staked by nominators in the last 24 hours.

        - DELEGATE/(24h): The total earnings of the delegate in the last 24 hours.

        - DESCRIPTION: A brief description of the delegate's purpose and operations.


        Sorting is done based on the `TOTAL STAKE` column in descending order. Changes in stake are highlighted:
        increases in green and decreases in red. Entries with no previous data are marked with ``NA``. Each delegate's
        name is a hyperlink to their respective URL, if available.

        # Example usage:

        [green]$[/green] btcli root list_delegates

        [green]$[/green] btcli root list_delegates --wallet-name my_wallet

        [green]$[/green] btcli root list_delegates --subtensor.network finney # can also be `test` or `local`

        [italic]Note[/italic]: This function is part of the Bittensor CLI tools and is intended for use within a
        console application. It prints directly to the console and does not return any value.
        """
        self.verbosity_handler(quiet, verbose)
        network_to_use = network or self.config["network"]
        if network_to_use not in ["local", "test"]:
            sub = self.initialize_chain(
                "archive", "wss://archive.chain.opentensor.ai:443"
            )
        else:
            sub = self.initialize_chain(network_to_use, chain)

        return self._run_command(root.list_delegates(sub))

    # TODO: Confirm if we need a command for this - currently registering to root auto makes u delegate
    def root_nominate(
        self,
        wallet_name: Optional[str] = Options.wallet_name_req,
        wallet_path: Optional[str] = Options.wallet_path,
        wallet_hotkey: Optional[str] = Options.wallet_hk_req,
        network: Optional[str] = Options.network,
        chain: Optional[str] = Options.chain,
        prompt: bool = Options.prompt,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
    ):
        """
        Facilitates a wallet to become a delegate on the Bittensor network.

        This command handles the nomination process, including wallet unlocking and verification of the hotkey's current
        delegate status.

        The command performs several checks:

        - Verifies that the hotkey is not already a delegate to prevent redundant nominations.

        - Tries to nominate the wallet and reports success or failure.

        Upon success, the wallet's hotkey is registered as a delegate on the network.

        # Usage:

        To run the command, the user must have a configured wallet with both hotkey and coldkey. If the wallet is not
        already nominated, this command will initiate the process.

        # Example usage:

        [green]$[/green] btcli root nominate

        [green]$[/green] btcli root nominate --wallet-name my_wallet --wallet-hotkey my_hotkey

        [italic]Note[/italic]: This function is intended to be used as a CLI command. It prints the outcome directly to the console
        and does not return any value. It should not be called programmatically in user code due to its interactive nature and
        side effects on the network state.
        """
        self.verbosity_handler(quiet, verbose)
        wallet = self.wallet_ask(wallet_name, wallet_path, wallet_hotkey)
        return self._run_command(
            root.nominate(wallet, self.initialize_chain(network, chain), prompt)
        )

    def stake_show(
        self,
        all_wallets: bool = typer.Option(
            False,
            "--all",
            "--all-wallets",
            "-a",
            help="When set, the command checks all coldkey wallets instead of just the specified wallet.",
        ),
        network: Optional[str] = Options.network,
        chain: Optional[str] = Options.chain,
        wallet_name: Optional[str] = Options.wallet_name,
        wallet_hotkey: Optional[str] = Options.wallet_hotkey,
        wallet_path: Optional[str] = Options.wallet_path,
        reuse_last: bool = Options.reuse_last,
        html_output: bool = Options.html_output,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
    ):
        """
        List all stake accounts associated with a user's wallet on the Bittensor network.

        This command provides a comprehensive view of the stakes associated with both hotkeys and delegates linked to
        the user's coldkey.

        # Usage:

        The command lists all stake accounts for a specified wallet or all wallets in the user's configuration
        directory. It displays the coldkey, balance, account details (hotkey/delegate name), stake amount, and the rate
        of return.

        The command compiles a table showing:

        - Coldkey: The coldkey associated with the wallet.

        - Balance: The balance of the coldkey.

        - Account: The name of the hotkey or delegate.

        - Stake: The amount of TAO staked to the hotkey or delegate.

        - Rate: The rate of return on the stake, typically shown in TAO per day.


        # Example usage:

        [green]$[/green] btcli stake show --all

        [italic]Note[/italic]: This command is essential for users who wish to monitor their stake distribution and returns across various
        accounts on the Bittensor network. It provides a clear and detailed overview of the user's staking activities.
        """
        self.verbosity_handler(quiet, verbose)
        if (reuse_last or html_output) and self.config.get("no_cache") is True:
            err_console.print(
                "Unable to use `--reuse-last` or `--html` when config no-cache is set."
            )
            raise typer.Exit()
        if not reuse_last:
            subtensor = self.initialize_chain(network, chain)
            wallet = self.wallet_ask(wallet_name, wallet_path, wallet_hotkey)
        else:
            subtensor = None
            wallet = self.wallet_ask(wallet_name, wallet_path, wallet_hotkey)
        return self._run_command(
            stake.show(
                wallet,
                subtensor,
                all_wallets,
                reuse_last,
                html_output,
                self.config.get("no_cache", False),
            )
        )

    def stake_add(
        self,
        stake_all: bool = typer.Option(
            False,
            "--all-tokens",
            "--all",
            "-a",
            help="When set, stakes all available tokens from the coldkey.",
        ),
        amount: float = typer.Option(
            0.0, "--amount", help="The amount of TAO tokens to stake"
        ),
        max_stake: float = typer.Option(
            0.0,
            "--max-stake",
            "-m",
            help="Sets the maximum amount of TAO to have staked in each hotkey.",
        ),
        hotkey_ss58_address: str = typer.Option(
            "",
            help="The SS58 address of the hotkey to unstake from.",
        ),
        include_hotkeys: list[str] = typer.Option(
            [],
            "--include-hotkeys",
            "-in",
            help="Specifies hotkeys by name or SS58 address to stake to. i.e `-in hk1 -in hk2`",
        ),
        exclude_hotkeys: list[str] = typer.Option(
            [],
            "--exclude-hotkeys",
            "-ex",
            help="Specifies hotkeys by name/SS58 address not to stake to (only use with `--all-hotkeys`.)"
            " i.e. `-ex hk3 -ex hk4`",
        ),
        all_hotkeys: bool = typer.Option(
            False,
            help="When set, stakes to all hotkeys associated with the wallet. Do not use if specifying "
            "hotkeys in `--include-hotkeys`.",
        ),
        wallet_name: str = Options.wallet_name,
        wallet_path: str = Options.wallet_path,
        wallet_hotkey: str = Options.wallet_hotkey,
        network: str = Options.network,
        chain: str = Options.chain,
        prompt: bool = Options.prompt,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
    ):
        """
        Stake TAO tokens to one or more hotkeys from a user's coldkey on the Bittensor network.

        This command is used to allocate tokens to different hotkeys, securing their position and influence on the
         network.

        # Usage:

        Users can specify the amount to stake, the hotkeys to stake to (either by name or ``SS58`` address), and whether
        to stake to all hotkeys. The command checks for sufficient balance and hotkey registration before proceeding
        with the staking process.


        The command prompts for confirmation before executing the staking operation.

        # Example usage:

        [green]$[/green] btcli stake add --amount 100 --wallet-name <my_wallet> --wallet-hotkey <my_hotkey>

        [italic]Note[/italic]: This command is critical for users who wish to distribute their stakes among different neurons (hotkeys) on the
        network. It allows for a strategic allocation of tokens to enhance network participation and influence.
        """
        self.verbosity_handler(quiet, verbose)
        wallet = self.wallet_ask(wallet_name, wallet_path, wallet_hotkey)

        if stake_all and amount:
            err_console.print(
                "Cannot specify an amount and 'stake-all'. Choose one or the other."
            )
            raise typer.Exit()

        if not stake_all and not amount:
            amount = FloatPrompt.ask("[blue bold]Amount to stake (TAO τ)[/blue bold]")

        if stake_all and not amount:
            if not Confirm.ask("Stake all available TAO tokens?", default=False):
                raise typer.Exit()

        if all_hotkeys and include_hotkeys:
            err_console.print(
                "You have specified hotkeys to include and the `--all-hotkeys` flag. The flag"
                "should only be used standalone (to use all hotkeys) or with `--exclude-hotkeys`."
            )
            raise typer.Exit()

        if include_hotkeys and exclude_hotkeys:
            err_console.print(
                "You have specified including and excluding hotkeys. Select one or the other."
            )
            raise typer.Exit()

        if not wallet_hotkey and not all_hotkeys and not include_hotkeys:
            _hotkey_str = typer.style("hotkey", fg="red")
            hotkey = typer.prompt(f"Enter {_hotkey_str} name to stake or ss58_address")
            if not is_valid_ss58_address(hotkey):
                wallet_hotkey = hotkey
                wallet = self.wallet_ask(
                    wallet.name, wallet_path, wallet_hotkey, validate=True
                )
            else:
                hotkey_ss58_address = hotkey

        return self._run_command(
            stake.stake_add(
                wallet,
                self.initialize_chain(network, chain),
                amount,
                stake_all,
                max_stake,
                include_hotkeys,
                exclude_hotkeys,
                all_hotkeys,
                prompt,
                hotkey_ss58_address,
            )
        )

    def stake_remove(
        self,
        network: Optional[str] = Options.network,
        chain: Optional[str] = Options.chain,
        wallet_name: str = Options.wallet_name,
        wallet_path: str = Options.wallet_path,
        wallet_hotkey: str = Options.wallet_hotkey,
        unstake_all: bool = typer.Option(
            False,
            "--unstake-all",
            "--all",
            help="When set, unstakes all staked tokens from the specified hotkeys.",
        ),
        amount: float = typer.Option(
            0.0, "--amount", "-a", help="The amount of TAO tokens to unstake."
        ),
        hotkey_ss58_address: str = typer.Option(
            "",
            help="The SS58 address of the hotkey to unstake from.",
        ),
        max_stake: float = typer.Option(
            0.0,
            "--max-stake",
            "--max",
            help="Sets the maximum amount of TAO to remain staked in each hotkey.",
        ),
        include_hotkeys: list[str] = typer.Option(
            [],
            "--include-hotkeys",
            "-in",
            help="Specifies hotkeys by name or SS58 address to unstake from. i.e `-in hk1 -in hk2`",
        ),
        exclude_hotkeys: list[str] = typer.Option(
            [],
            "--exclude-hotkeys",
            "-ex",
            help="Specifies hotkeys by name/SS58 address not to unstake from (only use with `--all-hotkeys`.)"
            " i.e. `-ex hk3 -ex hk4`",
        ),
        all_hotkeys: bool = typer.Option(
            False,
            help="When set, unstakes from all hotkeys associated with the wallet. Do not use if specifying "
            "hotkeys in `--include-hotkeys`.",
        ),
        prompt: bool = Options.prompt,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
    ):
        """
        Unstake TAO tokens from one or more hotkeys and transfer them back to the user's coldkey.

        This command is used to withdraw tokens previously staked to different hotkeys.

        # Usage:

        Users can specify the amount to unstake, the hotkeys to unstake from (either by name or `SS58` address), and
        whether to unstake from all hotkeys. The command checks for sufficient stake and prompts for confirmation before
        proceeding with the unstaking process.

        The command prompts for confirmation before executing the unstaking operation.

        # Example usage:

        [green]$[/green] btcli stake remove --amount 100 -in hk1 -in hk2

        [italic]Note[/italic]: This command is important for users who wish to reallocate their stakes or withdraw
        them from the network. It allows for flexible management of token stakes across different neurons (hotkeys) on the network.
        """
        self.verbosity_handler(quiet, verbose)
        wallet = self.wallet_ask(wallet_name, wallet_path, wallet_hotkey)
        if all_hotkeys and include_hotkeys:
            err_console.print(
                "You have specified hotkeys to include and the `--all-hotkeys` flag. The flag"
                "should only be used standalone (to use all hotkeys) or with `--exclude-hotkeys`."
            )
            raise typer.Exit()

        if include_hotkeys and exclude_hotkeys:
            err_console.print(
                "You have specified including and excluding hotkeys. Select one or the other."
            )
            raise typer.Exit()

        if (
            not wallet_hotkey
            and not hotkey_ss58_address
            and not all_hotkeys
            and not include_hotkeys
        ):
            _hotkey_str = typer.style("hotkey", fg="red")
            hotkey = typer.prompt(
                f"Enter {_hotkey_str} name to unstake or ss58_address"
            )
            if not is_valid_ss58_address(hotkey):
                wallet_hotkey = hotkey
                wallet = self.wallet_ask(
                    wallet.name, wallet_path, wallet_hotkey, validate=True
                )
            else:
                hotkey_ss58_address = hotkey

        if unstake_all and amount:
            err_console.print(
                "Cannot specify an amount and 'unstake-all'. Choose one or the other."
            )
            raise typer.Exit()

        if not unstake_all and not amount:
            amount = FloatPrompt.ask("[blue bold]Amount to unstake (TAO τ)[/blue bold]")

        if unstake_all and not amount:
            if not Confirm.ask("Unstake all staked TAO tokens?", default=False):
                raise typer.Exit()

        return self._run_command(
            stake.unstake(
                wallet,
                self.initialize_chain(network, chain),
                hotkey_ss58_address,
                all_hotkeys,
                include_hotkeys,
                exclude_hotkeys,
                amount,
                max_stake,
                unstake_all,
                prompt,
            )
        )

    def stake_get_children(
        self,
        wallet_name: Optional[str] = Options.wallet_name_req,
        wallet_hotkey: Optional[str] = Options.wallet_hk_req,
        wallet_path: Optional[str] = Options.wallet_path,
        network: Optional[str] = Options.network,
        chain: Optional[str] = Options.chain,
        netuid: Optional[int] = typer.Option(
            None,
            help="The netuid (network unique identifier) of the subnet within the root network, (e.g. 1)",
            prompt=False,
        ),
        all_netuids: bool = typer.Option(
            False,
            "--all-netuids",
            "--all",
            help="When set, gets children from all subnets on the bittensor network.",
        ),
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
    ):
        """
        Get all child hotkeys on a specified subnet on the Bittensor network.

        This command is used to view delegated authority to different hotkeys on the subnet.

        # Usage:
        Users can specify the subnet and see the children and the proportion that is given to them.

        The command compiles a table showing:

        - ChildHotkey: The hotkey associated with the child.
        - ParentHotKey: The hotkey associated with the parent.
        - Proportion: The proportion that is assigned to them.
        - Expiration: The expiration of the hotkey.

        # Example usage:

        [green]$[/green] btcli stake get_children --netuid 1
        [green]$[/green] btcli stake get_children --all-netuids

        [italic]Note[/italic]: This command is for users who wish to see child hotkeys among different neurons (hotkeys) on the network.
        """
        self.verbosity_handler(quiet, verbose)
        wallet = self.wallet_ask(wallet_name, wallet_path, wallet_hotkey)
        if all_netuids and netuid:
            err_console.print("Specify either netuid or all, not both.")
            raise typer.Exit()
        if all_netuids:
            netuid = None
        elif not netuid:
            netuid = IntPrompt.ask(
                "Enter netuid (leave blank for all)", default=None, show_default=True
            )
        return self._run_command(
            stake.get_children(wallet, self.initialize_chain(network, chain), netuid)
        )

    def stake_set_children(
        self,
        children: list[str] = typer.Option(
            [], "--children", "-c", help="Enter children hotkeys (ss58)", prompt=False
        ),
        wallet_name: str = Options.wallet_name_req,
        wallet_hotkey: str = Options.wallet_hk_req,
        wallet_path: str = Options.wallet_path,
        network: str = Options.network,
        chain: str = Options.chain,
        netuid: int = Options.netuid,
        proportions: list[float] = typer.Option(
            [],
            "--proportions",
            "-prop",
            help="Enter proportions for children as (sum less than 1)",
            prompt=False,
        ),
        wait_for_inclusion: bool = Options.wait_for_inclusion,
        wait_for_finalization: bool = Options.wait_for_finalization,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
    ):
        """
        Add children hotkeys on a specified subnet on the Bittensor network.

        This command is used to delegate authority to different hotkeys, securing their position and influence on the
        subnet.

        # Usage:

        Users can specify the amount or 'proportion' to delegate to child hotkeys (``SS58`` address),
        the user needs to have sufficient authority to make this call, and the sum of proportions cannot be greater
        than 1.

        The command prompts for confirmation before executing the set_children operation.

        # Example usage:

        [green]$[/green] btcli stake child set - <child_hotkey> -c <child_hotkey> --hotkey <parent_hotkey> --netuid 1 -prop 0.3 -prop 0.3

        [italic]Note[/italic]: This command is critical for users who wish to delegate children hotkeys among different
        neurons (hotkeys) on the network. It allows for a strategic allocation of authority to enhance network participation and influence.
        """
        self.verbosity_handler(quiet, verbose)
        children = list_prompt(children, str, "Enter the child hotkeys (ss58)")
        proportions = list_prompt(
            proportions,
            float,
            "Enter proportions equal to the number of children (sum not exceeding a total of 1.0)",
        )
        if len(proportions) != len(children):
            err_console.print("You must have as many proportions as you have children.")
            raise typer.Exit()
        if sum(proportions) > 1.0:
            err_console.print("Your proportion total must sum not exceed 1.0.")
            raise typer.Exit()
        wallet = self.wallet_ask(wallet_name, wallet_path, wallet_hotkey)
        return self._run_command(
            stake.set_children(
                wallet,
                self.initialize_chain(network, chain),
                netuid,
                children,
                proportions,
                wait_for_finalization,
                wait_for_inclusion,
            )
        )

    def stake_revoke_children(
        self,
        wallet_name: Optional[str] = Options.wallet_name_req,
        wallet_hotkey: Optional[str] = Options.wallet_hk_req,
        wallet_path: Optional[str] = Options.wallet_path,
        network: Optional[str] = Options.network,
        chain: Optional[str] = Options.chain,
        netuid: int = Options.netuid,
        wait_for_inclusion: bool = Options.wait_for_inclusion,
        wait_for_finalization: bool = Options.wait_for_finalization,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
    ):
        """
        Remove all children hotkeys on a specified subnet on the Bittensor network.

        This command is used to remove delegated authority from all child hotkeys, removing their position and influence
        on the subnet.

        # Usage:

        Users need to specify the parent hotkey and the subnet ID (netuid).
        The user needs to have sufficient authority to make this call.

        The command prompts for confirmation before executing the revoke_children operation.

        # Example usage:

        [green]$[/green] btcli stake child revoke --hotkey <parent_hotkey> --netuid 1

        [italic]Note[/italic]:This command is critical for users who wish to remove children hotkeys on the network.
        It allows for a complete removal of delegated authority to enhance network participation and influence.
        """
        self.verbosity_handler(quiet, verbose)
        wallet = self.wallet_ask(wallet_name, wallet_path, wallet_hotkey)
        return self._run_command(
            stake.revoke_children(
                wallet,
                self.initialize_chain(network, chain),
                netuid,
                wait_for_inclusion,
                wait_for_finalization,
            )
        )

    def stake_childkey_take(
        self,
        wallet_name: Optional[str] = Options.wallet_name_req,
        wallet_hotkey: Optional[str] = Options.wallet_hk_req,
        wallet_path: Optional[str] = Options.wallet_path,
        network: Optional[str] = Options.network,
        chain: Optional[str] = Options.chain,
        netuid: int = Options.netuid,
        wait_for_inclusion: bool = Options.wait_for_inclusion,
        wait_for_finalization: bool = Options.wait_for_finalization,
        prompt: bool = Options.prompt,
        take: Optional[float] = typer.Option(
            None,
            "--take",
            "-t",
            help="Enter take for your child hotkey",
            prompt=False,
        ),
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
    ):
        """
        Get and set your childkey take on a specified subnet on the Bittensor network.

        This command is used to set the take on your child hotkeys with limits between 0 - 18%.

        # Usage:

        Users need to specify their child hotkey and the subnet ID (netuid).

        The command prompts for confirmation before setting the childkey take.

        # Example usage:

        [green]$[/green] btcli stake child take --hotkey <child_hotkey> --netuid 1

        [green]$[/green] btcli stake child take --hotkey <child_hotkey> --take 0.12 --netuid 1
        ```

        [italic]]Note[/italic]: This command is critical for users who wish to modify their child hotkey take on the network.
        """
        self.verbosity_handler(quiet, verbose)
        wallet = self.wallet_ask(wallet_name, wallet_path, wallet_hotkey)
        return self._run_command(
            stake.childkey_take(
                wallet=wallet,
                subtensor=self.initialize_chain(network, chain),
                netuid=netuid,
                take=take,
                wait_for_inclusion=wait_for_inclusion,
                wait_for_finalization=wait_for_finalization,
                prompt=prompt,
            )
        )

    def sudo_set(
        self,
        network: Optional[str] = Options.network,
        chain: Optional[str] = Options.chain,
        wallet_name: str = Options.wallet_name,
        wallet_path: str = Options.wallet_path,
        wallet_hotkey: str = Options.wallet_hotkey,
        netuid: int = Options.netuid,
        param_name: str = typer.Option(
            "", "--param", "--parameter", help="The subnet hyperparameter to set"
        ),
        param_value: str = typer.Option(
            "", "--value", help="The subnet hyperparameter value to set."
        ),
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
    ):
        """
        Used to set hyperparameters for a specific subnet on the Bittensor network.

        This command allows subnet owners to modify various hyperparameters of theirs subnet, such as its tempo,
        emission rates, and other network-specific settings.

        # Usage:

        The command first prompts the user to enter the hyperparameter they wish to change and its new value.
        It then uses the user's wallet and configuration settings to authenticate and send the hyperparameter update
        to the specified subnet.

        # Example usage:

        [green]$[/green] btcli sudo set --netuid 1 --param 'tempo' --value '0.5'

        [italic]Note[/italic]: This command requires the user to specify the subnet identifier (``netuid``) and both
        the hyperparameter and its new value. It is intended for advanced users who are familiar with the network's
        functioning and the impact of changing these parameters.
        """
        self.verbosity_handler(quiet, verbose)
        if not param_name:
            param_name = Prompt.ask(
                "Enter hyperparameter", choices=list(HYPERPARAMS.keys())
            )
        if not param_value:
            param_value = Prompt.ask(f"Enter new value for {param_name}")
        wallet = self.wallet_ask(wallet_name, wallet_path, wallet_hotkey)
        return self._run_command(
            sudo.sudo_set_hyperparameter(
                wallet,
                self.initialize_chain(network, chain),
                netuid,
                param_name,
                param_value,
            )
        )

    def sudo_get(
        self,
        network: str = Options.network,
        chain: str = Options.chain,
        netuid: int = Options.netuid,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
    ):
        """
        Retrieve hyperparameters of a specific subnet.

        This command is used for both `sudo get` and `subnets hyperparameters`.

        # Usage:

        The command connects to the Bittensor network, queries the specified subnet, and returns a detailed list
        of all its hyperparameters. This includes crucial operational parameters that determine the subnet's
        performance and interaction within the network.

        # Example usage:

        [green]$[/green] btcli sudo get --netuid 1


        [italic]Note[/italic]: Users need to provide the `netuid` of the subnet whose hyperparameters they wish to view.
        This command is designed for informational purposes and does not alter any network settings or configurations.
        """
        self.verbosity_handler(quiet, verbose)
        return self._run_command(
            sudo.get_hyperparameters(self.initialize_chain(network, chain), netuid)
        )

    def subnets_list(
        self,
        network: str = Options.network,
        chain: str = Options.chain,
        reuse_last: bool = Options.reuse_last,
        html_output: bool = Options.html_output,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
    ):
        """
        List all subnets and their detailed information.

        This command is designed to provide users with comprehensive information about each subnet within the
        network, including its unique identifier (netuid), the number of neurons, maximum neuron capacity,
        emission rate, tempo, recycle register cost (burn), proof of work (PoW) difficulty, and the name or
        SS58 address of the subnet owner.

        # Usage:

        Upon invocation, the command performs the following actions:

        1. It initializes the Bittensor subtensor object with the user's configuration.

        2. It retrieves a list of all subnets in the network along with their detailed information.

        3. The command compiles this data into a table format, displaying key information about each subnet.


        In addition to the basic subnet details, the command also fetches delegate information to provide the
        name of the subnet owner where available. If the owner's name is not available, the owner's ``SS58``
        address is displayed.

        The command structure includes:

        - Initializing the Bittensor subtensor and retrieving subnet information.

        - Calculating the total number of neurons across all subnets.

        - Constructing a table that includes columns for `NETUID`, `N` (current neurons), `MAX_N`
        (maximum neurons), `EMISSION`, `TEMPO`, `BURN`, `POW` (proof of work difficulty), and
        `SUDO` (owner's name or `SS58` address).

        - Displaying the table with a footer that summarizes the total number of subnets and neurons.


        # Example usage:

        [green]$[/green] btcli subnets list

        [italic]Note[/italic]: This command is particularly useful for users seeking an overview of the Bittensor network's
        structure and the distribution of its resources and ownership information for each subnet.
        """
        self.verbosity_handler(quiet, verbose)
        if (reuse_last or html_output) and self.config.get("no_cache") is True:
            err_console.print(
                "Unable to use `--reuse-last` or `--html` when config no-cache is set."
            )
            raise typer.Exit()
        if reuse_last:
            subtensor = None
        else:
            subtensor = self.initialize_chain(network, chain)
        return self._run_command(
            subnets.subnets_list(
                subtensor, reuse_last, html_output, self.config.get("no_cache", False)
            )
        )

    def subnets_lock_cost(
        self,
        network: str = Options.network,
        chain: str = Options.chain,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
    ):
        """
        View the locking cost required for creating a new subnetwork.

        This command is designed to provide users with the current cost of registering a new subnetwork, which is a
        critical piece of information for anyone considering expanding the network's infrastructure.

        The current implementation anneals the cost of creating a subnet over a period of two days. If the cost is
        unappealing currently, check back in a day or two to see if it has reached a more amenable level.

        # Usage:

        Upon invocation, the command performs the following operations:

        1. It copies the user's current Bittensor configuration.

        2. It initializes the Bittensor subtensor object with this configuration.

        3. It then retrieves the subnet lock cost using the ``get_subnet_burn_cost()`` method from the subtensor object.

        4. The cost is displayed to the user in a readable format, indicating the amount of Tao required to lock for
        registering a new subnetwork.

        In case of any errors during the process (e.g., network issues, configuration problems), the command will catch
        these exceptions and inform the user that it failed to retrieve the lock cost, along with the specific error
        encountered.

        The command structure includes:

        - Copying and using the user's configuration for Bittensor.

        - Retrieving the current subnet lock cost from the Bittensor network.

        - Displaying the cost in a user-friendly manner.


        # Example usage:

        [green]$[/green] btcli subnets lock_cost

        [italic]Note[/italic]: This command is particularly useful for users who are planning to contribute to the Bittensor network
        by adding new subnetworks. Understanding the lock cost is essential for these users to make informed decisions about their
        potential contributions and investments in the network.
        """
        self.verbosity_handler(quiet, verbose)
        return self._run_command(
            subnets.lock_cost(self.initialize_chain(network, chain))
        )

    def subnets_create(
        self,
        wallet_name: str = Options.wallet_name,
        wallet_path: str = Options.wallet_path,
        wallet_hotkey: str = Options.wallet_hotkey,
        network: str = Options.network,
        chain: str = Options.chain,
        prompt: bool = Options.prompt,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
    ):
        """
        Register a new subnetwork on the Bittensor network :sparkles:.

        This command facilitates the creation and registration of a subnetwork, which involves interaction with the
        user's wallet and the Bittensor subtensor. It ensures that the user has the necessary credentials and
        configurations to successfully register a new subnetwork.

        # Usage:
        Upon invocation, the command performs several key steps to register a subnetwork:

        1. It copies the user's current configuration settings.

        2. It accesses the user's wallet using the provided configuration.

        3. It initializes the Bittensor subtensor object with the user's configuration.

        4. It then calls the `create` function of the subtensor object, passing the user's wallet and a prompt setting
        based on the user's configuration.


        If the user's configuration does not specify a wallet name and `no_prompt` is not set, the command will prompt
        the user to enter a wallet name. This name is then used in the registration process.

        The command structure includes:

        - Copying the user's configuration.

        - Accessing and preparing the user's wallet.

        - Initializing the Bittensor subtensor.

        - Registering the subnetwork with the necessary credentials.


        # Example usage:

        [green]$[/green] btcli subnets create

        [italic]Note[/italic]: This command is intended for advanced users of the Bittensor network who wish to contribute by adding new
        subnetworks. It requires a clear understanding of the network's functioning and the roles of subnetworks. Users
        should ensure that they have secured their wallet and are aware of the implications of adding a new subnetwork
        to the Bittensor ecosystem.
        """
        self.verbosity_handler(quiet, verbose)
        wallet = self.wallet_ask(wallet_name, wallet_path, wallet_hotkey)
        return self._run_command(
            subnets.create(wallet, self.initialize_chain(network, chain), prompt)
        )

    def subnets_pow_register(
        self,
        wallet_name: Optional[str] = Options.wallet_name_req,
        wallet_path: Optional[str] = Options.wallet_path,
        wallet_hotkey: Optional[str] = Options.wallet_hk_req,
        network: Optional[str] = Options.network,
        chain: Optional[str] = Options.chain,
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
            help="The number of nonces to process before checking for next block during registration",
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
            help="Set flag to use CUDA to pow_register.",
        ),
        dev_id: Optional[int] = typer.Option(
            defaults.pow_register.cuda.dev_id,
            "--dev-id",
            "-d",
            help="Set the CUDA device id(s). Goes by the order of speed. (i.e. 0 is the fastest).",
        ),
        threads_per_block: Optional[int] = typer.Option(
            defaults.pow_register.cuda.tpb,
            "--threads-per-block",
            "-tbp",
            help="Set the number of Threads Per Block for CUDA.",
        ),
    ):
        """
        Register a neuron on the Bittensor network using Proof of Work (PoW).

        This method is an alternative registration process that leverages computational work for securing a neuron's
        place on the network.

        # Usage:

        The command starts by verifying the existence of the specified subnet. If the subnet does not exist, it
        terminates with an error message. On successful verification, the PoW registration process is initiated, which
        requires solving computational puzzles.

        The command also supports additional wallet and subtensor arguments, enabling further customization of the
        registration process.

        # Example usage:

        [green]$[/green] btcli pow_register --netuid 1 --num_processes 4 --cuda

        [italic]Note[/italic]: This command is suited for users with adequate computational resources to participate in PoW registration.
        It requires a sound understanding of the network's operations and PoW mechanics. Users should ensure their systems
        meet the necessary hardware and software requirements, particularly when opting for CUDA-based GPU acceleration.

        This command may be disabled according to the subnet owner's directive. For example, on netuid 1 this is
        permanently disabled.
        """
        return self._run_command(
            subnets.pow_register(
                self.wallet_ask(wallet_name, wallet_path, wallet_hotkey),
                self.initialize_chain(network, chain),
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
        wallet_name: str = Options.wallet_name_req,
        wallet_path: str = Options.wallet_path,
        wallet_hotkey: str = Options.wallet_hk_req,
        chain: str = Options.chain,
        network: str = Options.network,
        netuid: int = Options.netuid,
        prompt: bool = Options.prompt,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
    ):
        """
        Register a neuron on the Bittensor network by recycling some TAO (the network's native token) :open_book:.

        This command is used to add a new neuron to a specified subnet within the network, contributing to the
        decentralization and robustness of Bittensor.

        # Usage:

        Before registering, the command checks if the specified subnet exists and whether the user's balance is
        sufficient to cover the registration cost.

        The registration cost is determined by the current recycle amount for the specified subnet. If the balance is
        insufficient or the subnet does not exist, the command will exit with an appropriate error message.

        If the preconditions are met, and the user confirms the transaction (if `no_prompt` is not set), the command
        proceeds to register the neuron by recycling the required amount of TAO.

        The command structure includes:

        - Verification of subnet existence.
        - Checking the user's balance against the current recycle amount for the subnet.
        - User confirmation prompt for proceeding with registration.
        - Execution of the registration process.

        Columns Displayed in the confirmation prompt:

        - Balance: The current balance of the user's wallet in TAO.
        - Cost to Register: The required amount of TAO needed to register on the specified subnet.

        # Example usage:

        [green]$[/green] btcli subnets register --netuid 1

        [italic]Note[/italic]:This command is critical for users who wish to contribute a new neuron to the network. It requires careful
        consideration of the subnet selection and an understanding of the registration costs. Users should ensure their
        wallet is sufficiently funded before attempting to register a neuron.
        """
        self.verbosity_handler(quiet, verbose)
        return self._run_command(
            subnets.register(
                self.wallet_ask(wallet_name, wallet_path, wallet_hotkey),
                self.initialize_chain(network, chain),
                netuid,
                prompt,
            )
        )

    def subnets_metagraph(
        self,
        netuid: Optional[int] = typer.Option(
            None,
            help="The netuid (network unique identifier) of the subnet within the root network, (e.g. 1). This "
            "is ignored when used with `--reuse-last`.",
        ),
        network: str = Options.network,
        chain: str = Options.chain,
        reuse_last: bool = Options.reuse_last,
        html_output: bool = Options.html_output,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
    ):
        """
        Retrieve and display the metagraph of a subnetwork.

        This metagraph contains detailed information about all the neurons (nodes)
        participating in the network, including their stakes, trust scores, and more.

        The table displayed includes the following columns for each neuron:

        - [bold]UID[/bold]: Unique identifier of the neuron.

        - [bold]STAKE(τ)[/bold]: Total stake of the neuron in Tao (τ).

        - [bold]RANK[/bold]: Rank score of the neuron.

        - [bold]TRUST[/bold]: Trust score assigned to the neuron by other neurons.

        - [bold]CONSENSUS[/bold]: Consensus score of the neuron.

        - [bold]INCENTIVE[/bold]: Incentive score representing the neuron's incentive alignment.

        - [bold]DIVIDENDS[/bold]: Dividends earned by the neuron.

        - [bold]EMISSION(p)[/bold]: Emission in Rho (p) received by the neuron.

        - [bold]VTRUST[/bold]: Validator trust score indicating the network's trust in the neuron as a validator.

        - [bold]VAL[/bold]: Validator status of the neuron.

        - [bold]UPDATED[/bold]: Number of blocks since the neuron's last update.

        - [bold]ACTIVE[/bold]: Activity status of the neuron.

        - [bold]AXON[/bold]: Network endpoint information of the neuron.

        - [bold]HOTKEY[/bold]: Partial hotkey (public key) of the neuron.

        - [bold]COLDKEY[/bold]: Partial coldkey (public key) of the neuron.


        The command also prints network-wide statistics such as total stake, issuance, and difficulty.

        # Usage:

        The user must specify the network UID to query the metagraph. If not specified, the default network UID is used.

        # Example usage:

        [green]$[/green] btcli subnet metagraph --netuid 0  # Root network

        [green]$[/green] btcli subnet metagraph --netuid 1 --network test

        [italic]Note[/italic]: This command provides a snapshot of the network's state at the time of calling.
        It is useful for network analysis and diagnostics. It is intended to be used as part of the Bittensor CLI and
        not as a standalone function within user code.
        """
        self.verbosity_handler(quiet, verbose)
        if (reuse_last or html_output) and self.config.get("no_cache") is True:
            err_console.print(
                "Unable to use `--reuse-last` or `--html` when config no-cache is set."
            )
            raise typer.Exit()

        if reuse_last:
            if netuid is not None:
                console.print("Cannot specify netuid when using `--reuse-last`")
                raise typer.Exit()
            subtensor = None
        else:
            if netuid is None:
                netuid = rich.prompt.IntPrompt.ask(
                    "Enter the netuid (network unique identifier) of the subnet within the root network, (e.g. 1)."
                )
            subtensor = self.initialize_chain(network, chain)

        return self._run_command(
            subnets.metagraph_cmd(
                subtensor,
                netuid,
                reuse_last,
                html_output,
                self.config.get("no_cache", False),
                self.config.get("metagraph_cols", {}),
            )
        )

    def weights_reveal(
        self,
        network: str = Options.network,
        chain: str = Options.chain,
        wallet_name: str = Options.wallet_name,
        wallet_path: str = Options.wallet_path,
        wallet_hotkey: str = Options.wallet_hotkey,
        netuid: int = Options.netuid,
        uids: list[int] = typer.Option(
            [],
            "--uids",
            "-u",
            help="Corresponding UIDs for the specified netuid, e.g. -u 1 -u 2 -u 3 ...",
        ),
        weights: list[float] = typer.Option(
            [],
            "--weights",
            "-w",
            help="Corresponding weights for the specified UIDs, e.g. `-w 0.2 -w 0.4 -w 0.1 ...",
        ),
        salt: list[int] = typer.Option(
            [],
            "--salt",
            "-s",
            help="Corresponding salt for the hash function, e.g. -s 163 -s 241 -s 217 ...",
        ),
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
    ):
        """
        Reveal weights for a specific subnet on the Bittensor network.

        # Usage:

        The command allows revealing weights for a specific subnet. Users need to specify the netuid (network unique
        identifier), corresponding UIDs, and weights they wish to reveal.


        # Example usage:

        [green]$[/green] btcli wt reveal --netuid 1 --uids 1,2,3,4 --weights 0.1,0.2,0.3,0.4 --salt 163,241,217,11,161,142,147,189

        [italic]Note[/italic]: This command is used to reveal weights for a specific subnet and requires the user to have the necessary permissions.
        """
        self.verbosity_handler(quiet, verbose)
        uids = list_prompt(uids, int, "Corresponding UIDs for the specified netuid")
        weights = list_prompt(
            weights, float, "Corresponding weights for the specified UIDs"
        )
        if len(uids) != len(weights):
            err_console.print(
                "The number of UIDs you specify must match up with the number of weights you specify"
            )
            raise typer.Exit()
        salt = list_prompt(salt, int, "Corresponding salt for the hash function")
        return self._run_command(
            weights_cmds.reveal_weights(
                self.initialize_chain(network, chain),
                self.wallet_ask(wallet_name, wallet_path, wallet_hotkey),
                netuid,
                uids,
                weights,
                salt,
                __version_as_int__,
            )
        )

    def weights_commit(
        self,
        network: str = Options.network,
        chain: str = Options.chain,
        wallet_name: str = Options.wallet_name,
        wallet_path: str = Options.wallet_path,
        wallet_hotkey: str = Options.wallet_hotkey,
        netuid: int = Options.netuid,
        uids: list[int] = typer.Option(
            [],
            "--uids",
            "-u",
            help="Corresponding UIDs for the specified netuid, e.g. -u 1 -u 2 -u 3 ...",
        ),
        weights: list[float] = typer.Option(
            [],
            "--weights",
            "-w",
            help="Corresponding weights for the specified UIDs, e.g. `-w 0.2 -w 0.4 -w 0.1 ...",
        ),
        salt: list[int] = typer.Option(
            [],
            "--salt",
            "-s",
            help="Corresponding salt for the hash function, e.g. -s 163 -s 241 -s 217 ...",
        ),
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
    ):
        """

        Commit weights for specific subnet on the Bittensor network.

        # Usage:

        The command allows committing weights for a specific subnet. Users need to specify the netuid (network unique
        identifier), corresponding UIDs, and weights they wish to commit.


        ### Example usage:

        [green]$[/green] btcli wt commit --netuid 1 --uids 1,2,3,4 --w 0.1 -w 0.2 -w 0.3 -w 0.4

        [italic]Note[/italic]: This command is used to commit weights for a specific subnet and requires the user to have the necessary
        permissions.
        """
        self.verbosity_handler(quiet, verbose)
        uids = list_prompt(uids, int, "Corresponding UIDs for the specified netuid")
        weights = list_prompt(
            weights, float, "Corresponding weights for the specified UIDs"
        )
        if len(uids) != len(weights):
            err_console.print(
                "The number of UIDs you specify must match up with the number of weights you specify"
            )
            raise typer.Exit()
        salt = list_prompt(salt, int, "Corresponding salt for the hash function")
        return self._run_command(
            weights_cmds.commit_weights(
                self.initialize_chain(network, chain),
                self.wallet_ask(wallet_name, wallet_path, wallet_hotkey),
                netuid,
                uids,
                weights,
                salt,
                __version_as_int__,
            )
        )

    def run(self):
        self.app()


def main():
    manager = CLIManager()
    manager.run()


if __name__ == "__main__":
    main()
