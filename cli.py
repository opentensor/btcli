#!/usr/bin/env python3
import asyncio
import os.path
from typing import Optional, Coroutine

from bittensor_wallet import Wallet
from git import Repo
import rich
from rich.prompt import Confirm, Prompt
from rich.table import Table, Column
import typer
from typing_extensions import Annotated
from websockets import ConnectionClosed
from yaml import safe_load, safe_dump

from src import defaults, utils
from src.commands import wallets, root
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
        show_default=False
    )
    chain = typer.Option(
        None,
        help="The subtensor chain endpoint to connect to.",
        show_default=False
    )
    netuids = typer.Option([], help="Set the netuid(s) to filter by (e.g. `0 1 2`)")


def get_n_words(n_words: Optional[int]) -> int:
    while n_words not in [12, 15, 18, 21, 24]:
        n_words: int = Prompt.ask(
            "Choose number of words: 12, 15, 18, 21, 24",
            choices=[12, 15, 18, 21, 24],
            default=12,
        )
    return n_words


def get_creation_data(mnemonic, seed, json, json_password):
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
    if value:
        typer.echo(
            f"BTCLI Version: {__version__}/{Repo(os.path.dirname(__file__)).active_branch.name}"
        )
        raise typer.Exit()


class CLIManager:
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

        # delegates commands
        self.root_app.command("list")(self.root_list)

    def initialize_chain(
        self,
        network: str = typer.Option("default_network", help="Network name"),
        chain: str = typer.Option("default_chain", help="Chain name"),
    ):
        if not self.not_subtensor:
            if network or chain:
                self.not_subtensor = SubtensorInterface(network, chain)
            elif self.config["chain"] or self.config["chain"]:
                self.not_subtensor = SubtensorInterface(
                    self.config["network"], self.config["chain"]
                )
            else:
                self.not_subtensor = SubtensorInterface(defaults.subtensor.network, defaults.subtensor.chain_endpoint)
        console.print(f"[yellow] Connected to [/yellow][white]{self.not_subtensor}")

    def _run_command(self, cmd: Coroutine):
        try:
            asyncio.run(cmd)
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
        # check config
        with open(os.path.expanduser("~/.bittensor/config.yml"), "r") as f:
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
        args = locals()
        for arg in ["wallet_name", "wallet_path", "wallet_hotkey", "network", "chain"]:
            if val := args.get(arg):
                self.config[arg] = val
        with open(os.path.expanduser("~/.bittensor/config.yml"), "w") as f:
            safe_dump(self.config, f)

    def get_config(self):
        table = Table(Column("Name"), Column("Value"))
        for k, v in self.config.items():
            table.add_row(*[k, v])
        console.print(table)

    def wallet_ask(
        self,
        wallet_name: str,
        wallet_path: str,
        wallet_hotkey: str,
        validate=True,
    ):
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
        all_wallets: Optional[bool] = typer.Option(
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
        include_hotkeys: Optional[list[str]] = typer.Option(
            [],
            help="Specify the hotkeys to include by name or ss58 address. (e.g. `hk1 hk2 hk3`). "
            "If left empty, all hotkeys not excluded will be included.",
        ),
        exclude_hotkeys: Optional[list[str]] = typer.Option(
            [],
            help="Specify the hotkeys to exclude by name or ss58 address. (e.g. `hk1 hk2 hk3`). "
            "If left empty, and no hotkeys included in --include-hotkeys, all hotkeys will be included.",
        ),
        netuids: Optional[list[int]] = Options.netuids,
        network: Optional[str] = Options.network,
        chain: Optional[str] = Options.chain,
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
        btcli wallet overview --include-hotkeys hk1 hk2 --sort-by stake
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
        self.initialize_chain(network, chain)
        return self._run_command(
            wallets.overview(
                wallet,
                self.not_subtensor,
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
        wallet_name: Optional[str] = Options.wallet_name,
        wallet_path: Optional[str] = Options.wallet_path,
        wallet_hotkey: Optional[str] = Options.wallet_hotkey,
        network: Optional[str] = Options.network,
        chain: Optional[str] = Options.chain,
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
        wallet_name: Optional[str] = Options.wallet_name,
        wallet_path: Optional[str] = Options.wallet_path,
        wallet_hotkey: Optional[str] = Options.wallet_hotkey,
        network: Optional[str] = Options.network,
        chain: Optional[str] = Options.chain,
        netuids: Optional[list[int]] = Options.netuids,
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
        btcli wallet inspect --all
        ```

        #### Note:
        The ``inspect`` command is for displaying information only and does not perform any
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
        self.initialize_chain(network, chain)
        return self._run_command(
            wallets.faucet(
                wallet,
                self.not_subtensor,
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
        display_name: Optional[str] = typer.Option(
            "",
            "--display-name",
            "--display",
            help="The display name for the identity.",
            prompt=True,
        ),
        legal_name: Optional[str] = typer.Option(
            "",
            "--legal-name",
            "--legal",
            help="The legal name for the identity.",
            prompt=True,
        ),
        web_url: Optional[str] = typer.Option(
            "", "--web-url", "--web", help="The web url for the identity.", prompt=True
        ),
        riot_handle: Optional[str] = typer.Option(
            "",
            "--riot-handle",
            "--riot",
            help="The riot handle for the identity.",
            prompt=True,
        ),
        email: Optional[str] = typer.Option(
            "", help="The email address for the identity.", prompt=True
        ),
        pgp_fingerprint: Optional[str] = typer.Option(
            "",
            "--pgp-fingerprint",
            "--pgp",
            help="The pgp fingerprint for the identity.",
            prompt=True,
        ),
        image_url: Optional[str] = typer.Option(
            "",
            "--image-url",
            "--image",
            help="The image url for the identity.",
            prompt=True,
        ),
        info_: Optional[str] = typer.Option(
            "", "--info", "-i", help="The info for the identity.", prompt=True
        ),
        twitter_url: Optional[str] = typer.Option(
            "",
            "-x",
            "-𝕏",
            "--twitter-url",
            "--twitter",
            help="The 𝕏 (Twitter) url for the identity.",
            prompt=True,
        ),
        validator_id: Optional[bool] = typer.Option(
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
        self.initialize_chain(network, chain)
        return self._run_command(
            root.root_list(subtensor=self.not_subtensor)
        )



    def run(self):
        self.app()


if __name__ == "__main__":
    manager = CLIManager()
    manager.run()
