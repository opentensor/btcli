#!/usr/bin/env python3
import asyncio
import os.path
import re
from typing import Optional, Coroutine, Collection

from bittensor_wallet import Wallet
from git import Repo
import rich
from rich.prompt import Confirm, Prompt, FloatPrompt
from rich.table import Table, Column
import typer
from typing_extensions import Annotated
from websockets import ConnectionClosed
from yaml import safe_load, safe_dump

from src import defaults, utils
from src.commands import wallets, root, stake
from src.subtensor_interface import SubtensorInterface
from src.bittensor.async_substrate_interface import SubstrateRequestException
from src.utils import console, err_console

__version__ = "8.0.0"


class Options:
    """
    Re-usable typer args
    """

    wallet_name = typer.Option(None, "--wallet-name", "-w", help="Name of wallet")
    wallet_path = typer.Option(
        None, "--wallet-path", "-p", help="Filepath of root of wallets"
    )
    wallet_hotkey = typer.Option(None, "--hotkey", "-H", help="Hotkey of wallet")
    wallet_hk_req = typer.Option(
        None,
        "--hotkey",
        "-H",
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
        None,
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
        help="The subtensor network to connect to. Default: finney.",
        show_default=False,
    )
    chain = typer.Option(
        None, help="The subtensor chain endpoint to connect to.", show_default=False
    )
    netuids = typer.Option(
        [], "--netuids", "-n", help="Set the netuid(s) to filter by (e.g. `0 1 2`)"
    )
    netuid = typer.Option(
        None,
        help="The netuid (network unique identifier) of the subnet within the root network, (e.g. 1)",
        prompt=True,
    )


def list_prompt(init_var: list, list_type: type, help_text: str) -> list:
    while not init_var:
        prompt = Prompt.ask(help_text)
        init_var = [list_type(x) for x in re.split(r"[ ,]+", prompt) if x]
    return init_var


def get_n_words(n_words: Optional[int]) -> int:
    """
    Prompts the user to select the number of words used in the mnemonic if not supplied or not within the
    acceptable criteria of [12, 15, 18, 21, 24]
    """
    while n_words not in [12, 15, 18, 21, 24]:
        n_words = int(
            Prompt.ask(
                "Choose number of words: 12, 15, 18, 21, 24",
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


def version_callback(value: bool):
    """
    Prints the current version/branch-name
    """
    if value:
        typer.echo(
            f"BTCLI Version: {__version__}/{Repo(os.path.dirname(__file__)).active_branch.name}"
        )
        raise typer.Exit()


class CLIManager:
    """
    :var app: the main CLI Typer app
    :var config_app: the Typer app as it relates to config commands
    :var wallet_app: the Typer app as it relates to wallet commands
    :var root_app: the Typer app as it relates to root commands
    :var stake_app: the Typer app as it relates to stake commands
    :var not_subtensor: the `SubtensorInterface` object passed to the various commands that require it
    """

    not_subtensor: Optional[SubtensorInterface]
    app: typer.Typer
    config_app: typer.Typer
    wallet_app: typer.Typer
    root_app: typer.Typer

    def __init__(self):
        self.config = {
            "wallet_name": None,
            "wallet_path": None,
            "wallet_hotkey": None,
            "network": None,
            "chain": None,
        }
        self.not_subtensor = None

        self.app = typer.Typer(rich_markup_mode="markdown", callback=self.main_callback)
        self.config_app = typer.Typer()
        self.wallet_app = typer.Typer()
        self.root_app = typer.Typer()
        self.stake_app = typer.Typer()

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
        self.app.add_typer(self.root_app, name="d", hidden=True)

        # stake aliases
        self.app.add_typer(
            self.stake_app,
            name="stake",
            short_help="Stake commands, alias: `st`",
        )
        self.app.add_typer(self.stake_app, name="st", hidden=True)

        # config commands
        self.config_app.command("set")(self.set_config)
        self.config_app.command("get")(self.get_config)

        # wallet commands
        self.wallet_app.command("list")(self.wallet_list)
        self.wallet_app.command("regen-coldkey")(self.wallet_regen_coldkey)
        self.wallet_app.command("regen-coldkeypub")(self.wallet_regen_coldkey_pub)
        self.wallet_app.command("regen-hotkey")(self.wallet_regen_hotkey)
        self.wallet_app.command("new-hotkey")(self.wallet_new_hotkey)
        self.wallet_app.command("new-coldkey")(self.wallet_new_coldkey)
        self.wallet_app.command("create")(self.wallet_create_wallet)
        self.wallet_app.command("balance")(self.wallet_balance)
        self.wallet_app.command("history")(self.wallet_history)
        self.wallet_app.command("overview")(self.wallet_overview)
        self.wallet_app.command("transfer")(self.wallet_transfer)
        self.wallet_app.command("inspect")(self.wallet_inspect)
        self.wallet_app.command("faucet")(self.wallet_faucet)
        self.wallet_app.command("set-identity")(self.wallet_set_id)
        self.wallet_app.command("get-identity")(self.wallet_get_id)
        self.wallet_app.command("check-swap")(self.wallet_check_ck_swap)

        # root commands
        self.root_app.command("list")(self.root_list)
        self.root_app.command("set-weights")(self.root_set_weights)
        self.root_app.command("get-weights")(self.root_get_weights)
        self.root_app.command("boost")(self.root_boost)
        self.root_app.command("senate")(self.root_senate)
        self.root_app.command("senate-vote")(self.root_senate_vote)
        self.root_app.command("register")(self.root_register)
        self.root_app.command("proposals")(self.root_proposals)
        self.root_app.command("set-take")(self.root_set_take)
        self.root_app.command("delegate-stake")(self.root_delegate_stake)
        self.root_app.command("undelegate-stake")(self.root_undelegate_stake)
        self.root_app.command("my-delegates")(self.root_my_delegates)
        self.root_app.command("list-delegates")(self.root_list_delegates)
        self.root_app.command("nominate")(self.root_nominate)

        # stake commands
        self.stake_app.command("show")(self.stake_show)
        self.stake_app.command("add")(self.stake_add)
        self.stake_app.command("get-children")(self.stake_get_children)
        self.stake_app.command("set-children")(self.stake_set_children)

    def initialize_chain(
        self,
        network: Optional[str] = typer.Option("default_network", help="Network name"),
        chain: Optional[str] = typer.Option("default_chain", help="Chain name"),
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
            elif self.config["chain"] or self.config["chain"]:
                self.not_subtensor = SubtensorInterface(
                    self.config["network"], self.config["chain"]
                )
            else:
                self.not_subtensor = SubtensorInterface(
                    defaults.subtensor.network, defaults.subtensor.chain_endpoint
                )
        console.print(f"[yellow] Connected to [/yellow][white]{self.not_subtensor}")
        return self.not_subtensor

    def _run_command(self, cmd: Coroutine) -> None:
        """
        Runs the supplied coroutine with asyncio.run
        """
        try:
            return asyncio.run(cmd)
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
        fp = os.path.expanduser(defaults.config.path)
        # create config file if it does not exist
        if not os.path.exists(fp):
            with open(fp, "w") as f:
                safe_dump(defaults.config.dictionary, f)
        # check config
        with open(fp, "r") as f:
            config = safe_load(f)
        for k, v in config.items():
            if k in self.config.keys():
                self.config[k] = v

    def set_config(
        self,
        wallet_name: Optional[str] = typer.Option(
            None,
            "--wallet-name",
            "--name",
            help="Wallet name",
        ),
        wallet_path: Optional[str] = typer.Option(
            None,
            "--wallet-path",
            "--path",
            "-p",
            help="Path to root of wallets",
        ),
        wallet_hotkey: Optional[str] = typer.Option(
            None, "--wallet-hotkey", "--hotkey", "-k", help="Path to root of wallets"
        ),
        network: Optional[str] = typer.Option(
            None,
            "--network",
            "-n",
            help="Network name: [finney, test, local]",
        ),
        chain: Optional[str] = typer.Option(
            None,
            "--chain",
            "-c",
            help="Chain name",
        ),
    ):
        """
        Sets values in config file
        :param wallet_name: name of the wallet
        :param wallet_path: root path of the wallets
        :param wallet_hotkey: name of the wallet hotkey file
        :param network: name of the network (e.g. finney, test, local)
        :param chain: chain endpoint for the network (e.g. ws://127.0.0.1:9945,
                      wss://entrypoint-finney.opentensor.ai:443)
        """
        args = locals()
        for arg in ["wallet_name", "wallet_path", "wallet_hotkey", "network", "chain"]:
            if val := args.get(arg):
                self.config[arg] = val
        with open(os.path.expanduser("~/.bittensor/config.yml"), "w") as f:
            safe_dump(self.config, f)

    def get_config(self):
        """
        Prints the current config file in a table
        """
        table = Table(Column("Name"), Column("Value"))
        for k, v in self.config.items():
            table.add_row(*[k, v])
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
            wallet_name = typer.prompt("Enter wallet name")
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
    ):
        """
        # wallet list
        Executes the `list` command which enumerates all wallets and their respective hotkeys present in the user's
        Bittensor configuration directory.

        The command organizes the information in a tree structure, displaying each
        wallet along with the `ss58` addresses for the coldkey public key and any hotkeys associated with it.
        The output is presented in a hierarchical tree format, with each wallet as a root node,
        and any associated hotkeys as child nodes. The ``ss58`` address is displayed for each
        coldkey and hotkey that is not encrypted and exists on the device.

        ## Usage:
        Upon invocation, the command scans the wallet directory and prints a list of all wallets, indicating whether the
        public keys are available (`?` denotes unavailable or encrypted keys).

        ### Example usage:
        ```
        btcli wallet list --path ~/.bittensor
        ```

        #### Note:
        This command is read-only and does not modify the filesystem or the network state. It is intended for use within
         the Bittensor CLI to provide a quick overview of the user's wallets.
        """
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
    ):
        """
        # wallet overview
        Executes the `overview` command to present a detailed overview of the user's registered accounts on the
        Bittensor network.

        This command compiles and displays comprehensive information about each neuron associated with the user's
        wallets, including both hotkeys and coldkeys. It is especially useful for users managing multiple accounts or
        seeking a summary of their network activities and stake distributions.

        ## Usage:
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


        ### Example usage:

        - ```
        btcli wallet overview
        ```

        - ```
        btcli wallet overview --all --sort-by stake --sort-order descending
        ```

        - ```
        btcli wallet overview -in hk1 -in hk2 --sort-by stake
        ```

        #### Note:
        This command is read-only and does not modify the network state or account configurations. It provides a quick
        and comprehensive view of the user's network presence, making it ideal for monitoring account status, stake
        distribution, and overall contribution to the Bittensor network.
        """
        if include_hotkeys and exclude_hotkeys:
            utils.err_console.print(
                "[red]You have specified hotkeys for inclusion and exclusion. Pick only one or neither."
            )
            raise typer.Exit()
        # if all-wallets is entered, ask for path
        if all_wallets:
            if not wallet_path:
                wallet_path = Prompt.ask(
                    "Enter the path of the wallets", default=defaults.wallet.path
                )
        wallet = self.wallet_ask(wallet_name, wallet_path, wallet_hotkey)
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
    ):
        """
        # wallet transfer
        Executes the ``transfer`` command to transfer TAO tokens from one account to another on the Bittensor network.

        This command is used for transactions between different accounts, enabling users to send tokens to other
        participants on the network. The command displays the user's current balance before prompting for the amount
        to transfer, ensuring transparency and accuracy in the transaction.

        ## Usage:
        The command requires specifying the destination address (public key) and the amount of TAO to be transferred.
        It checks for sufficient balance and prompts for confirmation before proceeding with the transaction.

        ### Example usage:
        ```
        btcli wallet transfer --dest 5Dp8... --amount 100
        ```

        #### Note:
        This command is crucial for executing token transfers within the Bittensor network. Users should verify the
        destination address and amount before confirming the transaction to avoid errors or loss of funds.
        """
        wallet = self.wallet_ask(wallet_name, wallet_path, wallet_hotkey)
        self.initialize_chain(network, chain)
        return self._run_command(
            wallets.transfer(wallet, self.not_subtensor, destination, amount)
        )

    def wallet_swap_hotkey(
        self,
        wallet_name: Optional[str] = Options.wallet_name,
        wallet_path: Optional[str] = Options.wallet_path,
        wallet_hotkey: Optional[str] = Options.wallet_hotkey,
        network: Optional[str] = Options.network,
        chain: Optional[str] = Options.chain,
        destination_hotkey_name: Optional[str] = typer.Argument(
            help="Destination hotkey name."
        ),
    ):
        """
        # wallet swap-hotkey
        Executes the `swap_hotkey` command to swap the hotkeys for a neuron on the network.

        ## Usage:
        The command is used to swap the hotkey of a wallet for another hotkey on that same wallet.

        ### Example usage:
        ```
        btcli wallet swap_hotkey new_hotkey --wallet-name your_wallet_name --wallet-hotkey original_hotkey
        ```
        """
        original_wallet = self.wallet_ask(wallet_name, wallet_path, wallet_hotkey)
        new_wallet = self.wallet_ask(wallet_name, wallet_path, destination_hotkey_name)
        self.initialize_chain(network, chain)
        return self._run_command(
            wallets.swap_hotkey(original_wallet, new_wallet, self.not_subtensor)
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
    ):
        """
        # wallet inspect
        Executes the ``inspect`` command, which compiles and displays a detailed report of a user's wallet pairs
        (coldkey, hotkey) on the Bittensor network.

        This report includes balance and staking information for both the coldkey and hotkey associated with the wallet.

        The command gathers data on:

        - Coldkey balance and delegated stakes.
        - Hotkey stake and emissions per neuron on the network.
        - Delegate names and details fetched from the network.

        The resulting table includes columns for:

        - **Coldkey**: The coldkey associated with the user's wallet.

        - **Balance**: The balance of the coldkey.

        - **Delegate**: The name of the delegate to which the coldkey has staked funds.

        - **Stake**: The amount of stake held by both the coldkey and hotkey.

        - **Emission**: The emission or rewards earned from staking.

        - **Netuid**: The network unique identifier of the subnet where the hotkey is active.

        - **Hotkey**: The hotkey associated with the neuron on the network.

        ## Usage:
        This command can be used to inspect a single wallet or all wallets located within a
        specified path. It is useful for a comprehensive overview of a user's participation
        and performance in the Bittensor network.

        #### Example usage::
        ```
        btcli wallet inspect
        ```

        ```
        btcli wallet inspect --all -n 1 -n 2 -n 3
        ```

        #### Note:
        The `inspect` command is for displaying information only and does not perform any
        transactions or state changes on the Bittensor network. It is intended to be used as
        part of the Bittensor CLI and not as a standalone function within user code.
        """
        # if all-wallets is entered, ask for path
        if all_wallets:
            if not wallet_path:
                wallet_path = Prompt.ask(
                    "Enter the path of the wallets", default=defaults.wallet.path
                )
        wallet = self.wallet_ask(wallet_name, wallet_path, wallet_hotkey)
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
            "-processors",
            "-p",
            help="Number of processors to use for POW registration.",
        ),
        update_interval: Optional[int] = typer.Option(
            defaults.pow_register.update_interval,
            "-update-interval",
            "-u",
            help="The number of nonces to process before checking for next block during registration",
        ),
        output_in_place: Optional[bool] = typer.Option(
            defaults.pow_register.output_in_place,
            help="Whether to output the registration statistics in-place.",
        ),
        verbose: Optional[bool] = typer.Option(
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
        # wallet faucet
        Executes the `faucet` command to obtain test TAO tokens by performing Proof of Work (PoW).

        This command is particularly useful for users who need test tokens for operations on a local chain.

        ## IMPORTANT:
            **THIS COMMAND IS DISABLED ON FINNEY AND TESTNET.**

        ## Usage:
        The command uses the PoW mechanism to validate the user's effort and rewards them with test TAO tokens. It is
        typically used in local chain environments where real value transactions are not necessary.

        ### Example usage:
        ```
        btcli wallet faucet --faucet.num_processes 4 --faucet.cuda.use_cuda
        ```

        #### Note:
        This command is meant for use in local environments where users can experiment with the network without using
        real TAO tokens. It's important for users to have the necessary hardware setup, especially when opting for
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
        wallet_name: Optional[str] = Options.wallet_name,
        wallet_path: Optional[str] = Options.wallet_path,
        wallet_hotkey: Optional[str] = Options.wallet_hotkey,
        mnemonic: Optional[str] = Options.mnemonic,
        seed: Optional[str] = Options.seed,
        json: Optional[str] = Options.json,
        json_password: Optional[str] = Options.json_password,
        use_password: Optional[bool] = Options.use_password,
        overwrite_coldkey: Optional[bool] = Options.overwrite_coldkey,
    ):
        """
        # wallet regen-coldkey
        Executes the `regen-coldkey` command to regenerate a coldkey for a wallet on the Bittensor network.

        This command is used to create a new coldkey from an existing mnemonic, seed, or JSON file.

        ## Usage:
        Users can specify a mnemonic, a seed string, or a JSON file path to regenerate a coldkey.
        The command supports optional password protection for the generated key and can overwrite an existing coldkey.

        ### Example usage:
        ```
        btcli wallet regen_coldkey --mnemonic "word1 word2 ... word12"
        ```

        ### Note: This command is critical for users who need to regenerate their coldkey, possibly for recovery or
        security reasons. It should be used with caution to avoid overwriting existing keys unintentionally.
        """

        wallet = self.wallet_ask(wallet_name, wallet_path, wallet_hotkey)
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
                overwrite_coldkey,
            )
        )

    def wallet_regen_coldkey_pub(
        self,
        wallet_name: Optional[str] = Options.wallet_name,
        wallet_path: Optional[str] = Options.wallet_path,
        wallet_hotkey: Optional[str] = Options.wallet_hotkey,
        public_key_hex: Optional[str] = Options.public_hex_key,
        ss58_address: Optional[str] = Options.ss58_address,
        overwrite_coldkeypub: Optional[bool] = typer.Option(
            False,
            help="Overwrites the existing coldkeypub file with the new one.",
            prompt=True,
        ),
    ):
        """
        # wallet regen-coldkeypub
        Executes the `regen-coldkeypub` command to regenerate the public part of a coldkey (coldkeypub) for a wallet
        on the Bittensor network.

        This command is used when a user needs to recreate their coldkeypub from an existing public key or SS58 address.

        ## Usage:
        The command requires either a public key in hexadecimal format or an ``SS58`` address to regenerate the
        coldkeypub. It optionally allows overwriting an existing coldkeypub file.

        ### Example usage:
        ```
        btcli wallet regen_coldkeypub --ss58_address 5DkQ4...
        ```

        ### Note:
            This command is particularly useful for users who need to regenerate their coldkeypub, perhaps due to file
            corruption or loss. It is a recovery-focused utility that ensures continued access to wallet
            functionalities.
        """
        wallet = self.wallet_ask(wallet_name, wallet_path, wallet_hotkey)
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
                wallet, public_key_hex, ss58_address, overwrite_coldkeypub
            )
        )

    def wallet_regen_hotkey(
        self,
        wallet_name: Optional[str] = Options.wallet_name,
        wallet_path: Optional[str] = Options.wallet_path,
        wallet_hotkey: Optional[str] = Options.wallet_hk_req,
        mnemonic: Optional[str] = Options.mnemonic,
        seed: Optional[str] = Options.seed,
        json: Optional[str] = Options.json,
        json_password: Optional[str] = Options.json_password,
        use_password: Optional[bool] = Options.use_password,
        overwrite_hotkey: Optional[bool] = Options.overwrite_hotkey,
    ):
        """
        # wallet regen-hotkey
        Executes the `regen-hotkey` command to regenerate a hotkey for a wallet on the Bittensor network.

        Similar to regenerating a coldkey, this command creates a new hotkey from a mnemonic, seed, or JSON file.

        ## Usage:
        Users can provide a mnemonic, seed string, or a JSON file to regenerate the hotkey.
        The command supports optional password protection and can overwrite an existing hotkey.

        ### Example usage:
        ```
        btcli wallet regen_hotkey --seed 0x1234...
        ```

        ### Note:
        This command is essential for users who need to regenerate their hotkey, possibly for security upgrades or
        key recovery.
        It should be used cautiously to avoid accidental overwrites of existing keys.
        """
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
                overwrite_hotkey,
            )
        )

    def wallet_new_hotkey(
        self,
        wallet_name: Optional[str] = Options.wallet_name,
        wallet_path: Optional[str] = Options.wallet_path,
        wallet_hotkey: Optional[str] = Options.wallet_hk_req,
        n_words: Optional[int] = None,
        use_password: bool = Options.use_password,
        overwrite_hotkey: bool = Options.overwrite_hotkey,
    ):
        """
        # wallet new-hotkey
        Executes the `new-hotkey` command to create a new hotkey under a wallet on the Bittensor network.

        ## Usage
        This command is used to generate a new hotkey for managing a neuron or participating in the network,
        with an optional word count for the mnemonic and supports password protection. It also allows overwriting an
        existing hotkey.


        ### Example usage:
        ```
            btcli wallet new-hotkey --n_words 24
        ```

        ### Note:
        This command is useful for users who wish to create additional hotkeys for different purposes, such as
        running multiple miners or separating operational roles within the network.
        """
        wallet = self.wallet_ask(
            wallet_name, wallet_path, wallet_hotkey, validate=False
        )
        n_words = get_n_words(n_words)
        return self._run_command(
            wallets.new_hotkey(wallet, n_words, use_password, overwrite_hotkey)
        )

    def wallet_new_coldkey(
        self,
        wallet_name: Optional[str] = Options.wallet_name,
        wallet_path: Optional[str] = Options.wallet_path,
        wallet_hotkey: Optional[str] = Options.wallet_hotkey,
        n_words: Optional[int] = None,
        use_password: Optional[bool] = Options.use_password,
        overwrite_coldkey: Optional[bool] = typer.Option(),
    ):
        """
        # wallet new-coldkey
        Executes the `new-coldkey` command to create a new coldkey under a wallet on the Bittensor network. This
        command generates a coldkey, which is essential for holding balances and performing high-value transactions.

        ## Usage:
        The command creates a new coldkey with an optional word count for the mnemonic and supports password
        protection. It also allows overwriting an existing coldkey.

        ### Example usage::
        ```
        btcli wallet new_coldkey --n_words 15
        ```

        ### Note:
        This command is crucial for users who need to create a new coldkey for enhanced security or as part of
        setting up a new wallet. It's a foundational step in establishing a secure presence on the Bittensor
        network.
        """
        wallet = self.wallet_ask(wallet_name, wallet_path, wallet_hotkey)
        n_words = get_n_words(n_words)
        return self._run_command(
            wallets.new_coldkey(wallet, n_words, use_password, overwrite_coldkey)
        )

    def wallet_check_ck_swap(
        self,
        wallet_name: Optional[str] = Options.wallet_name,
        wallet_path: Optional[str] = Options.wallet_path,
        wallet_hotkey: Optional[str] = Options.wallet_hotkey,
        network: Optional[str] = Options.network,
        chain: Optional[str] = Options.chain,
    ):
        """
        # wallet check-swap
        Executes the `check-swap` command to check swap status of a coldkey in the Bittensor network.

        ## Usage:
        Users need to specify the wallet they want to check the swap status of.

        ### Example usage:
        ```
        btcli wallet check_coldkey_swap
        ```

        #### Note:
        This command is important for users who wish check if swap requests were made against their coldkey.
        """
        wallet = self.wallet_ask(wallet_name, wallet_path, wallet_hotkey)
        self.initialize_chain(network, chain)
        return self._run_command(wallets.check_coldkey_swap(wallet, self.not_subtensor))

    def wallet_create_wallet(
        self,
        wallet_name: Optional[str] = Options.wallet_name,
        wallet_path: Optional[str] = Options.wallet_path,
        wallet_hotkey: Optional[str] = Options.wallet_hk_req,
        n_words: Optional[int] = None,
        use_password: Optional[bool] = Options.use_password,
        overwrite_hotkey: Optional[bool] = Options.overwrite_hotkey,
        overwrite_coldkey: Optional[bool] = Options.overwrite_coldkey,
    ):
        """
        # wallet create
        Executes the `create` command to generate both a new coldkey and hotkey under a specified wallet on the
        Bittensor network.

        This command is a comprehensive utility for creating a complete wallet setup with both cold
        and hotkeys.


        ## Usage:
        The command facilitates the creation of a new coldkey and hotkey with an optional word count for the
        mnemonics. It supports password protection for the coldkey and allows overwriting of existing keys.

        ### Example usage:
        ```
        btcli wallet create --n_words 21
        ```

        ### Note:
        This command is ideal for new users setting up their wallet for the first time or for those who wish to
        completely renew their wallet keys. It ensures a fresh start with new keys for secure and effective
        participation in the network.
        """
        wallet = self.wallet_ask(
            wallet_name, wallet_path, wallet_hotkey, validate=False
        )
        n_words = get_n_words(n_words)
        return self._run_command(
            wallets.wallet_create(
                wallet, n_words, use_password, overwrite_coldkey, overwrite_hotkey
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
        network: Optional[str] = typer.Option(
            defaults.subtensor.network,
            help="The subtensor network to connect to.",
            prompt=True,
        ),
        chain: Optional[str] = Options.chain,
    ):
        """
        # wallet balance
        Executes the `balance` command to check the balance of the wallet on the Bittensor network.
        This command provides a detailed view of the wallet's coldkey balances, including free and staked balances.

        ## Usage:
        The command lists the balances of all wallets in the user's configuration directory, showing the
        wallet name, coldkey address, and the respective free and staked balances.

        ### Example usages:

        - To display the balance of a single wallet, use the command with the `--wallet.name` argument to specify
        the wallet name:

        ```
        btcli w balance --wallet.name WALLET
        ```

        ```
        btcli w balance
        ```

        - To display the balances of all wallets, use the `--all` argument:

        ```
        btcli w balance --all
        ```
        """
        subtensor = SubtensorInterface(network, chain)
        wallet = self.wallet_ask(wallet_name, wallet_path, wallet_hotkey)
        return self._run_command(
            wallets.wallet_balance(wallet, subtensor, all_balances)
        )

    def wallet_history(
        self,
        wallet_name: Optional[str] = Options.wallet_name,
        wallet_path: Optional[str] = Options.wallet_path,
        wallet_hotkey: Optional[str] = Options.wallet_hotkey,
    ):
        """
        # wallet history
        Executes the `history` command to fetch the latest transfers of the provided wallet on the Bittensor network.
        This command provides a detailed view of the transfers carried out on the wallet.

        ## Usage:
        The command lists the latest transfers of the provided wallet, showing the 'From', 'To', 'Amount',
        'Extrinsic ID' and 'Block Number'.

        ### Example usage:
        ```
        btcli wallet history
        ```

        #### Note:
        This command is essential for users to monitor their financial status on the Bittensor network.
        It helps in fetching info on all the transfers so that user can easily tally and cross-check the transactions.
        """
        wallet = self.wallet_ask(wallet_name, wallet_path, wallet_hotkey)
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
    ):
        """
        # wallet set-identity
        Executes the `set-identity` command within the Bittensor network, which allows for the creation or update of a
        delegate's on-chain identity.

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

        ## Usage:
        The user should call this command from the command line and follow the interactive
        prompts to enter or update the identity information. The command will display the
        updated identity details in a table format upon successful execution.

        ### Example usage:
        ```
        btcli wallet set_identity
        ```

        #### Note:
        This command should only be used if the user is willing to incur the 1 TAO transaction
        fee associated with setting an identity on the blockchain. It is a high-level command
        that makes changes to the blockchain state and should not be used programmatically as
        part of other scripts or applications.
        """
        wallet = self.wallet_ask(wallet_name, wallet_path, wallet_hotkey)
        self.initialize_chain(network, chain)
        return self._run_command(
            wallets.set_id(
                wallet,
                self.not_subtensor,
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
    ):
        """
        # wallet get-id
        Executes the `get-identity` command, which retrieves and displays the identity details of a user's coldkey or
        hotkey associated with the Bittensor network. This function queries the subtensor chain for information such as
        the stake, rank, and trust associated with the provided key.

        The command performs the following actions:

        - Connects to the subtensor network and retrieves the identity information.

        - Displays the information in a structured table format.

        The displayed table includes:

        - **Address**: The ``ss58`` address of the queried key.

        - **Item**: Various attributes of the identity such as stake, rank, and trust.

        - **Value**: The corresponding values of the attributes.

        ## Usage:
        The user must provide an ss58 address as input to the command. If the address is not
        provided in the configuration, the user is prompted to enter one.

        ### Example usage:
        ```
        btcli wallet get_identity --key <s58_address>
        ```

        #### Note:
        This function is designed for CLI use and should be executed in a terminal. It is
        primarily used for informational purposes and has no side effects on the network state.
        """

    def root_list(
        self,
        network: Optional[str] = Options.network,
        chain: Optional[str] = Options.chain,
    ):
        """
        # root list
        Executes the `list` command to display the members of the root network on the Bittensor network.

        This command provides an overview of the neurons that constitute the network's foundational layer.

        ## Usage:
        Upon execution, the command fetches and lists the neurons in the root network, showing their unique identifiers
        (UIDs), names, addresses, stakes, and whether they are part of the senate (network governance body).

        ### Example usage:

        ```

        $ btcli root list

        UID  NAME                             ADDRESS                                                STAKE(τ)  SENATOR

        0                                     5CaCUPsSSdKWcMJbmdmJdnWVa15fJQuz5HsSGgVdZffpHAUa    27086.37070  Yes

        1    RaoK9                            5GmaAk7frPXnAxjbQvXcoEzMGZfkrDee76eGmKoB3wxUburE      520.24199  No

        2    Openτensor Foundaτion            5F4tQyWrhfGVcNhoqeiNsR6KjD4wMZ2kfhLj4oHYuyHbZAc3  1275437.45895  Yes

        3    RoundTable21                     5FFApaS75bv5pJHfAp2FVLBj9ZaXuFDjEypsaBNc1wCfe52v    84718.42095  Yes

        4                                     5HK5tp6t2S59DywmHRWPBVJeJ86T61KjurYqeooqj8sREpeN   168897.40859  Yes

        5    Rizzo                            5CXRfP2ekFhe62r7q3vppRajJmGhTi7vwvb2yr79jveZ282w    53383.34400  No

        6    τaosτaτs and BitAPAI             5Hddm3iBFD2GLT5ik7LZnT3XJUnRnN8PoeCFgGQgawUVKNm8   646944.73569  Yes

        ...

        ```


        #### Note:
        This command is useful for users interested in understanding the composition and governance structure of the
        Bittensor network's root layer. It provides insights into which neurons hold significant influence and
        responsibility within the network.
        """
        return self._run_command(
            root.root_list(subtensor=self.initialize_chain(network, chain))
        )

    def root_set_weights(
        self,
        network: str = Options.network,
        chain: str = Options.chain,
        wallet_name: str = Options.wallet_name,
        wallet_path: str = Options.wallet_path,
        wallet_hotkey: str = Options.wallet_hk_req,
        netuids: list[int] = typer.Option(
            None, help="Netuids, e.g. `-n 0 -n 1 -n 2` ..."
        ),
        weights: list[float] = typer.Argument(
            None,
            help="Weights: e.g. `0.02 0.03 0.01` ...",
        ),
    ):
        """
        # root set-weights
        Executes the `set-weights` command to set the weights for the root network on the Bittensor network.

        This command is used by network senators to influence the distribution of network rewards and responsibilities.

        ## Usage:
        The command allows setting weights for different subnets within the root network. Users need to specify the
        netuids (network unique identifiers) and corresponding weights they wish to assign.

        ### Example usage::
        ```
        btcli root set-weights 0.3 0.3 0.4 -n 1 -n 2 -n 3 --chain ws://127.0.0.1:9945
        ```

        #### Note:
        This command is particularly important for network senators and requires a comprehensive understanding of the
        network's dynamics. It is a powerful tool that directly impacts the network's operational mechanics and reward
        distribution.
        """
        netuids = list_prompt(netuids, int, "Enter netuids")
        wallet = self.wallet_ask(wallet_name, wallet_path, wallet_hotkey)
        self._run_command(
            root.set_weights(
                wallet, self.initialize_chain(network, chain), netuids, weights
            )
        )

    def root_get_weights(
        self,
        network: Optional[str] = Options.network,
        chain: Optional[str] = Options.chain,
    ):
        """
        # root get-weights
        Executes the `get-weights` command to retrieve the weights set for the root network on the Bittensor network.

        This command provides visibility into how network responsibilities and rewards are distributed among various
        subnets.

        ## Usage:
        The command outputs a table listing the weights assigned to each subnet within the root network. This
        information is crucial for understanding the current influence and reward distribution among the subnets.

        ### Example usage:

        ```

        $ btcli root get_weights

                                                Root Network Weights

        UID        0        1        2       3        4        5       8        9       11     13      18       19

        1    100.00%        -        -       -        -        -       -        -        -      -       -        -

        2          -   40.00%    5.00%  10.00%   10.00%   10.00%  10.00%    5.00%        -      -  10.00%        -

        3          -        -   25.00%       -   25.00%        -  25.00%        -        -      -  25.00%        -

        4          -        -    7.00%   7.00%   20.00%   20.00%  20.00%        -    6.00%      -  20.00%        -

        5          -   20.00%        -  10.00%   15.00%   15.00%  15.00%    5.00%        -      -  10.00%   10.00%

        6          -        -        -       -   10.00%   10.00%  25.00%   25.00%        -      -  30.00%        -

        7          -   60.00%        -       -   20.00%        -       -        -   20.00%      -       -        -

        8          -   49.35%        -   7.18%   13.59%   21.14%   1.53%    0.12%    7.06%  0.03%       -        -

        9    100.00%        -        -       -        -        -       -        -        -      -       -        -


        ```

        #### Note:
        This command is essential for users interested in the governance and operational dynamics of the Bittensor
        network. It offers transparency into how network rewards and responsibilities are allocated across different
        subnets.
        """
        return self._run_command(
            root.get_weights(self.initialize_chain(network, chain))
        )

    def root_boost(
        self,
        network: Optional[str] = Options.network,
        chain: Optional[str] = Options.chain,
        wallet_name: Optional[str] = Options.wallet_name,
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
    ):
        """
        # root boost
        Not currently working with new implementation

        Executes the `boost` command to boost the weights for a specific subnet within the root network on the Bittensor
        network.

        ## Usage:
        The command allows boosting the weights for different subnets within the root network.

        ### Example usage:

        ```

        $ btcli root boost --netuid 1 --increase 0.01

        Boosting weight for subnet: 1 by amount: 0.1

        Normalized weights:

        tensor([
        0.0000, 0.5455, 0.0000, 0.0000, 0.0000, 0.0000, 0.0000, 0.0000, 0.0000,
        0.0000, 0.0000, 0.0000, 0.0000, 0.0000, 0.0000, 0.0000, 0.0000, 0.0000,
        0.0000, 0.0000, 0.0000, 0.0000, 0.4545, 0.0000, 0.0000, 0.0000, 0.0000,
        0.0000, 0.0000, 0.0000, 0.0000, 0.0000, 0.0000, 0.0000, 0.0000, 0.0000,
        0.0000, 0.0000, 0.0000, 0.0000, 0.0000]) ->
        tensor([0.0000, 0.5455, 0.0000, 0.0000, 0.0000, 0.0000, 0.0000, 0.0000, 0.0000,
        0.0000, 0.0000, 0.0000, 0.0000, 0.0000, 0.0000, 0.0000, 0.0000, 0.0000,
        0.0000, 0.0000, 0.0000, 0.0000, 0.4545, 0.0000, 0.0000, 0.0000, 0.0000,
        0.0000, 0.0000, 0.0000, 0.0000, 0.0000, 0.0000, 0.0000, 0.0000, 0.0000,
        0.0000, 0.0000, 0.0000, 0.0000, 0.0000]
        )


        Do you want to set the following root weights?:

        weights: tensor([
        0.0000, 0.5455, 0.0000, 0.0000, 0.0000, 0.0000, 0.0000, 0.0000, 0.0000,
        0.0000, 0.0000, 0.0000, 0.0000, 0.0000, 0.0000, 0.0000, 0.0000, 0.0000,
        0.0000, 0.0000, 0.0000, 0.0000, 0.4545, 0.0000, 0.0000, 0.0000, 0.0000,
        0.0000, 0.0000, 0.0000, 0.0000, 0.0000, 0.0000, 0.0000, 0.0000, 0.0000,
        0.0000, 0.0000, 0.0000, 0.0000, 0.0000])

        uids: tensor([ 0,  1,  2,  3,  4,  5,  6,  7,  8,  9, 10, 11, 12, 13, 14, 15, 16, 17,
        18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35,
        36, 37, 38, 39, 40])? [y/n]: y

        ✅ Finalized

        ⠙ 📡 Setting root weights on test ...2023-11-28 22:09:14.001 |     SUCCESS      | Set weights
                           Finalized: True


        ```
        """
        wallet = self.wallet_ask(wallet_name, wallet_path, wallet_hotkey)
        return self._run_command(
            root.set_boost(
                wallet, self.initialize_chain(network, chain), netuid, amount
            )
        )

    def root_slash(
        self,
        network: Optional[str] = Options.network,
        chain: Optional[str] = Options.chain,
        wallet_name: Optional[str] = Options.wallet_name,
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
    ):
        """
        # root slash
        Executes the `slash` command to decrease the weights for a specific subnet within the root network on the
        Bittensor network.

        ## Usage:
        The command allows slashing (decreasing) the weights for different subnets within the root network.

        ### Example usage:

        ```
        $ btcli root slash --netuid 1 --decrease 0.01

        Enter netuid (e.g. 1): 1
        Enter decrease amount (e.g. 0.01): 0.2
        Slashing weight for subnet: 1 by amount: 0.2

        Normalized weights:

        tensor([
        0.0000, 0.4318, 0.0000, 0.0000, 0.0000, 0.0000, 0.0000, 0.0000, 0.0000,
        0.0000, 0.0000, 0.0000, 0.0000, 0.0000, 0.0000, 0.0000, 0.0000, 0.0000,
        0.0000, 0.0000, 0.0000, 0.0000, 0.5682, 0.0000, 0.0000, 0.0000, 0.0000,
        0.0000, 0.0000, 0.0000, 0.0000, 0.0000, 0.0000, 0.0000, 0.0000, 0.0000,
        0.0000, 0.0000, 0.0000, 0.0000, 0.0000]) -> tensor([
        0.0000, 0.4318, 0.0000, 0.0000, 0.0000, 0.0000, 0.0000, 0.0000, 0.0000,
        0.0000, 0.0000, 0.0000, 0.0000, 0.0000, 0.0000, 0.0000, 0.0000, 0.0000,
        0.0000, 0.0000, 0.0000, 0.0000, 0.5682, 0.0000, 0.0000, 0.0000, 0.0000,
        0.0000, 0.0000, 0.0000, 0.0000, 0.0000, 0.0000, 0.0000, 0.0000, 0.0000,
        0.0000, 0.0000, 0.0000, 0.0000, 0.0000]
        )

        Do you want to set the following root weights?:

        weights: tensor([
                0.0000, 0.4318, 0.0000, 0.0000, 0.0000, 0.0000, 0.0000, 0.0000, 0.0000,
                0.0000, 0.0000, 0.0000, 0.0000, 0.0000, 0.0000, 0.0000, 0.0000, 0.0000,
                0.0000, 0.0000, 0.0000, 0.0000, 0.5682, 0.0000, 0.0000, 0.0000, 0.0000,
                0.0000, 0.0000, 0.0000, 0.0000, 0.0000, 0.0000, 0.0000, 0.0000, 0.0000,
                0.0000, 0.0000, 0.0000, 0.0000, 0.0000])

        uids: tensor([ 0,  1,  2,  3,  4,  5,  6,  7,  8,  9, 10, 11, 12, 13, 14, 15, 16, 17,
                18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35,
                36, 37, 38, 39, 40])? [y/n]: y

        ⠙ 📡 Setting root weights on test ...2023-11-28 22:09:14.001 |     SUCCESS      | Set weights
                           Finalized: True


        ```
        """
        wallet = self.wallet_ask(wallet_name, wallet_path, wallet_hotkey)
        return self._run_command(
            root.set_boost(
                wallet, self.initialize_chain(network, chain), netuid, amount
            )
        )

    def root_senate_vote(
        self,
        network: Optional[str] = Options.network,
        chain: Optional[str] = Options.chain,
        wallet_name: Optional[str] = Options.wallet_name,
        wallet_path: Optional[str] = Options.wallet_path,
        wallet_hotkey: Optional[str] = Options.wallet_hk_req,
        proposal: str = typer.Option(
            None,
            "--proposal",
            "--proposal-hash",
            help="The hash of the proposal to vote on.",
        ),
    ):
        """
        # root senate-vote
        Executes the `senate-vote` command to cast a vote on an active proposal in Bittensor's governance protocol.

        This command is used by Senate members to vote on various proposals that shape the network's future.

        ## Usage:
        The user needs to specify the hash of the proposal they want to vote on. The command then allows the Senate
        member to cast an 'Aye' or 'Nay' vote, contributing to the decision-making process.

        ### Example usage:

        ```
        btcli root senate_vote --proposal <proposal_hash>
        ```

        #### Note:
        This command is crucial for Senate members to exercise their voting rights on key proposals. It plays a vital
        role in the governance and evolution of the Bittensor network.
        """
        wallet = self.wallet_ask(wallet_name, wallet_path, wallet_hotkey)
        return self._run_command(
            root.senate_vote(wallet, self.initialize_chain(network, chain), proposal)
        )

    def root_senate(
        self,
        network: Optional[str] = Options.network,
        chain: Optional[str] = Options.chain,
    ):
        """
        # root senate
        Executes the `senate` command to view the members of Bittensor's governance protocol, known as the Senate.

        This command lists the delegates involved in the decision-making process of the Bittensor network.

        ## Usage:
        The command retrieves and displays a list of Senate members, showing their names and wallet addresses.
        This information is crucial for understanding who holds governance roles within the network.

        ### Example usage:

        ```
        btcli root senate
        ```

        #### Note:
        This command is particularly useful for users interested in the governance structure and participants of the
        Bittensor network. It provides transparency into the network's decision-making body.
        """
        return self._run_command(root.get_senate(self.initialize_chain(network, chain)))

    def root_register(
        self,
        network: Optional[str] = Options.network,
        chain: Optional[str] = Options.chain,
        netuid: int = Options.netuid,
        wallet_name: Optional[str] = Options.wallet_name,
        wallet_path: Optional[str] = Options.wallet_path,
        wallet_hotkey: Optional[str] = Options.wallet_hk_req,
    ):
        """
        # root register
        Executes the `register` command to register a neuron on the Bittensor network by recycling some TAO (the
         network's native token).

        This command is used to add a new neuron to a specified subnet within the network, contributing to the
        decentralization and robustness of Bittensor.

        ## Usage:
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


        ### Example usage:

        ```
        btcli subnets register --netuid 1
        ```

        #### Note:
        This command is critical for users who wish to contribute a new neuron to the network. It requires careful
        consideration of the subnet selection and an understanding of the registration costs. Users should ensure their
        wallet is sufficiently funded before attempting to register a neuron.
        """
        wallet = self.wallet_ask(wallet_name, wallet_path, wallet_hotkey)
        return self._run_command(
            root.register(wallet, self.initialize_chain(network, chain), netuid)
        )

    def root_proposals(
        self,
        network: Optional[str] = Options.network,
        chain: Optional[str] = Options.chain,
    ):
        """
        # root proposals
        Executes the `proposals` command to view active proposals within Bittensor's governance protocol.

        This command displays the details of ongoing proposals, including votes, thresholds, and proposal data.

        ## Usage:
        The command lists all active proposals, showing their hash, voting threshold, number of ayes and nays, detailed
        votes by address, end block number, and call data associated with each proposal.

        ### Example usage:

        ```
        btcli root proposals
        ```

        #### Note:
        This command is essential for users who are actively participating in or monitoring the governance of the
        Bittensor network. It provides a detailed view of the proposals being considered, along with the community's
        response to each.
        """
        return self._run_command(root.proposals(self.initialize_chain(network, chain)))

    def root_set_take(
        self,
        network: Optional[str] = Options.network,
        chain: Optional[str] = Options.chain,
        wallet_name: Optional[str] = Options.wallet_name,
        wallet_path: Optional[str] = Options.wallet_path,
        wallet_hotkey: Optional[str] = Options.wallet_hk_req,
        take: float = typer.Option(None, help="The new take value."),
    ):
        """
        # root set-take
        Executes the `set-take` command, which sets the delegate take.

        The command performs several checks:

        1. Hotkey is already a delegate
        2. New take value is within 0-18% range

        ## Usage:
        To run the command, the user must have a configured wallet with both hotkey and coldkey. Also, the hotkey should already be a delegate.

        ### Example usage:
        btcli root set_take --wallet.name my_wallet --wallet.hotkey my_hotkey

        #### Note:
        This function can be used to update the takes individually for every subnet
        """
        wallet = self.wallet_ask(wallet_name, wallet_path, wallet_hotkey)
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
    ):
        """
        # root delegate-stake
        Executes the `delegate-stake` command, which stakes Tao to a specified delegate on the Bittensor network.

        This action allocates the user's Tao to support a delegate, potentially earning staking rewards in return.

        The command interacts with the user to determine the delegate and the amount of Tao to be staked. If the
        `--all` flag is used, it delegates the entire available balance.

        ## Usage:
        The user must specify the delegate's SS58 address and the amount of Tao to stake. The function sends a
        transaction to the subtensor network to delegate the specified amount to the chosen delegate. These values are
        prompted if not provided.

        ### Example usage:

        ```
        btcli delegate-stake --delegate_ss58key <SS58_ADDRESS> --amount <AMOUNT>

        btcli delegate-stake --delegate_ss58key <SS58_ADDRESS> --all
        ```


        #### Note:
        This command modifies the blockchain state and may incur transaction fees. It requires user confirmation and
        interaction, and is designed to be used within the Bittensor CLI environment. The user should ensure the
        delegate's address and the amount to be staked are correct before executing the command.
        """
        # TODO instruct users how to show all delegates (I think list-delegates, but have to be sure)
        if amount and stake_all:
            err_console.print(
                "`--amount` and `--all` specified. Choose one or the other."
            )
        if not stake_all and not amount:
            amount = typer.prompt(
                "How much would you like to stake, in TAO?",
                confirmation_prompt="Confirm you wish to stake: τ",
            )
        wallet = self.wallet_ask(wallet_name, wallet_path, wallet_hotkey)
        return self._run_command(
            root.delegate_stake(
                wallet, self.initialize_chain(network, chain), amount, delegate_ss58key
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
    ):
        """
        # root undelegate-stake
        Executes the ``undelegate`` command, allowing users to withdraw their staked Tao from a delegate on the Bittensor
        network.

        This process is known as "undelegating" and it reverses the delegation process, freeing up the staked tokens.

        The command prompts the user for the amount of Tao to undelegate and the ``SS58`` address of the delegate from
        which to undelegate. If the ``--all`` flag is used, it will attempt to undelegate the entire staked amount from
        the specified delegate.

        ## Usage:
        The user must provide the delegate's SS58 address and the amount of Tao to undelegate. The function will then
        send a transaction to the Bittensor network to process the undelegation.

        ### Example usage:

        ```
        btcli undelegate --delegate_ss58key <SS58_ADDRESS> --amount <AMOUNT>

        btcli undelegate --delegate_ss58key <SS58_ADDRESS> --all

        ```

        #### Note:
        This command can result in a change to the blockchain state and may incur transaction fees. It is interactive
        and requires confirmation from the user before proceeding. It should be used with care as undelegating can
        affect the delegate's total stake and
        potentially the user's staking rewards.
        """
        if amount and unstake_all:
            err_console.print(
                "`--amount` and `--all` specified. Choose one or the other."
            )
        if not unstake_all and not amount:
            amount = typer.prompt(
                "How much would you like to unstake, in TAO?",
                confirmation_prompt="Confirm you wish to unstake: τ",
            )
        wallet = self.wallet_ask(wallet_name, wallet_path, wallet_hotkey)
        self._run_command(
            root.delegate_unstake(
                wallet, self.initialize_chain(network, chain), amount, delegate_ss58key
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
            "all-wallets",
            "--all",
            "-a",
            help="If specified, the command aggregates information across all wallets.",
        ),
    ):
        """
        # root my-delegates
        Executes the `my-delegates` command within the Bittensor CLI, which retrieves and displays a table of delegated
        stakes from a user's wallet(s) to various delegates on the Bittensor network.

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

        ## Usage:
        The command can be run as part of the Bittensor CLI suite of tools and requires no parameters if a single wallet
        is used. If multiple wallets are present, the `--all` flag can be specified to aggregate information across
        all wallets.

        ### Example usage:

        ```
        btcli root my-delegates
        btcli root my-delegates --all
        btcli root my-delegates --wallet-name my_wallet

        ```

        #### Note:
        This function is typically called by the CLI parser and is not intended to be used directly in user code.
        """
        wallet = self.wallet_ask(wallet_name, wallet_path, wallet_hotkey)
        self._run_command(
            root.my_delegates(
                wallet, self.initialize_chain(network, chain), all_wallets
            )
        )

    def root_list_delegates(self):
        """
        # root list-delegates
        Displays a formatted table of Bittensor network delegates, providing a comprehensive overview of delegate
        statistics and information.

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

        ### Example usage:

        ```
        btcli root list_delegates

        btcli root list_delegates --wallet.name my_wallet

        btcli root list_delegates --subtensor.network finney # can also be `test` or `local`

        ```

        #### Note:
        This function is part of the Bittensor CLI tools and is intended for use within a console application. It prints
        directly to the console and does not return any value.
        """
        sub = self.initialize_chain("archive", "wss://archive.chain.opentensor.ai:443")
        return self._run_command(root.list_delegates(sub))

    def root_nominate(
        self,
        wallet_name: Optional[str] = Options.wallet_name,
        wallet_path: Optional[str] = Options.wallet_path,
        wallet_hotkey: Optional[str] = Options.wallet_hk_req,
        network: Optional[str] = Options.network,
        chain: Optional[str] = Options.chain,
    ):
        """
        # root nominate
        Executes the `nominate` command, which facilitates a wallet to become a delegate on the Bittensor network.

        This command handles the nomination process, including wallet unlocking and verification of the hotkey's current
        delegate status.

        The command performs several checks:

        - Verifies that the hotkey is not already a delegate to prevent redundant nominations.

        - Tries to nominate the wallet and reports success or failure.

        Upon success, the wallet's hotkey is registered as a delegate on the network.

        ## Usage:
        To run the command, the user must have a configured wallet with both hotkey and coldkey. If the wallet is not
        already nominated, this command will initiate the process.

        ### Example usage:
        ```

        btcli root nominate

        btcli root nominate --wallet.name my_wallet --wallet.hotkey my_hotkey

        ```

        #### Note:
        This function is intended to be used as a CLI command. It prints the outcome directly to the console and does
        not return any value. It should not be called programmatically in user code due to its interactive nature and
        side effects on the network state.
        """
        wallet = self.wallet_ask(wallet_name, wallet_path, wallet_hotkey)
        return self._run_command(
            root.nominate(wallet, self.initialize_chain(network, chain))
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
    ):
        """
        # stake show
        Executes the `show` command to list all stake accounts associated with a user's wallet on the Bittensor network.

        This command provides a comprehensive view of the stakes associated with both hotkeys and delegates linked to
        the user's coldkey.

        ## Usage:
        The command lists all stake accounts for a specified wallet or all wallets in the user's configuration
        directory. It displays the coldkey, balance, account details (hotkey/delegate name), stake amount, and the rate
        of return.

        The command compiles a table showing:

        - Coldkey: The coldkey associated with the wallet.

        - Balance: The balance of the coldkey.

        - Account: The name of the hotkey or delegate.

        - Stake: The amount of TAO staked to the hotkey or delegate.

        - Rate: The rate of return on the stake, typically shown in TAO per day.


        ### Example usage:

        ```
        btcli stake show --all
        ```

        #### Note:
        This command is essential for users who wish to monitor their stake distribution and returns across various
        accounts on the Bittensor network. It provides a clear and detailed overview of the user's staking activities.
        """
        wallet = self.wallet_ask(wallet_name, wallet_path, wallet_hotkey)
        return self._run_command(
            stake.show(wallet, self.initialize_chain(network, chain), all_wallets)
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
        uid: int = typer.Option(
            None,
            "--uid",
            "-u",
            help="The unique identifier of the neuron to which the stake is to be added.",
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
    ):
        """
        # stake add
        Executes the `stake_add` command to stake tokens to one or more hotkeys from a user's coldkey on the Bittensor
        network.

        This command is used to allocate tokens to different hotkeys, securing their position and influence on the
         network.

        ## Usage:
        Users can specify the amount to stake, the hotkeys to stake to (either by name or ``SS58`` address), and whether
        to stake to all hotkeys. The command checks for sufficient balance and hotkey registration before proceeding
        with the staking process.


        The command prompts for confirmation before executing the staking operation.

        ### Example usage:

        ```
        btcli stake add --amount 100 --wallet-name <my_wallet> --wallet-hotkey <my_hotkey>
        ```

        #### Note:
        This command is critical for users who wish to distribute their stakes among different neurons (hotkeys) on the
        network. It allows for a strategic allocation of tokens to enhance network participation and influence.
        """
        if stake_all and amount:
            err_console.print(
                "Cannot specify an amount and 'stake-all'. Choose one or the other."
            )
            raise typer.Exit()
        if not stake_all and not amount:
            amount = FloatPrompt.ask("Please enter an amount to stake.")
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
        wallet = self.wallet_ask(wallet_name, wallet_path, wallet_hotkey)
        return self._run_command(
            stake.stake_add(
                wallet,
                self.initialize_chain(network, chain),
                uid,
                amount,
                stake_all,
                max_stake,
                include_hotkeys,
                exclude_hotkeys,
                all_hotkeys,
            )
        )

    def stake_get_children(
        self,
        wallet_name: Optional[str] = Options.wallet_name,
        wallet_hotkey: Optional[str] = Options.wallet_hk_req,
        wallet_path: Optional[str] = Options.wallet_path,
        network: Optional[str] = Options.network,
        chain: Optional[str] = Options.chain,
        netuid: int = Options.netuid,
    ):
        """
        # stake get-children
        Executes the `get_children_info` command to get all child hotkeys on a specified subnet on the Bittensor network.

        This command is used to view delegated authority to different hotkeys on the subnet.

        ## Usage:
        Users can specify the subnet and see the children and the proportion that is given to them.

        The command compiles a table showing:

        - ChildHotkey: The hotkey associated with the child.

        - ParentHotKey: The hotkey associated with the parent.

        - Proportion: The proportion that is assigned to them.

        - Expiration: The expiration of the hotkey.


        ### Example usage:

        ```
            btcli stake get_children --netuid 1
        ```

        #### Note:
        This command is for users who wish to see child hotkeys among different neurons (hotkeys) on the network.
        """
        wallet = self.wallet_ask(wallet_name, wallet_path, wallet_hotkey)
        return self._run_command(
            stake.get_children(wallet, self.initialize_chain(network, chain), netuid)
        )

    def stake_set_children(
        self,
        children: list[str] = typer.Option(
            [], "--children", "-c", help="Enter children hotkeys (ss58)", prompt=False
        ),
        wallet_name: str = Options.wallet_name,
        wallet_hotkey: str = Options.wallet_hk_req,
        wallet_path: str = Options.wallet_path,
        network: str = Options.network,
        chain: str = Options.chain,
        netuid: int = Options.netuid,
        proportions: list[float] = typer.Option(
            [],
            "--proportions",
            "-p",
            help="Enter proportions for children as (sum less than 1)",
            prompt=False,
        ),
    ):
        """
        # stake set-children
        Executes the `set_children` command to add children hotkeys on a specified subnet on the Bittensor network.

        This command is used to delegate authority to different hotkeys, securing their position and influence on the
        subnet.

        ## Usage:
        Users can specify the amount or 'proportion' to delegate to child hotkeys (``SS58`` address),
        the user needs to have sufficient authority to make this call, and the sum of proportions cannot be greater
        than 1.

        The command prompts for confirmation before executing the set_children operation.

        ### Example usage:

        ```
        btcli stake set_children - <child_hotkey> -c <child_hotkey> --hotkey <parent_hotkey> --netuid 1
        -p 0.3 -p 0.3
        ```

        #### Note:
        This command is critical for users who wish to delegate children hotkeys among different neurons (hotkeys) on
        the network. It allows for a strategic allocation of authority to enhance network participation and influence.
        """
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
            )
        )

    def run(self):
        self.app()


if __name__ == "__main__":
    manager = CLIManager()
    manager.run()
