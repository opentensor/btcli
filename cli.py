import asyncio

import rich
import typer
from typing import Optional

from src import wallets


# re-usable args
class Options:
    wallet_name = typer.Option(None, help="Name of wallet")
    wallet_path = typer.Option(None, help="Filepath of wallet")
    wallet_hotkey = typer.Option(None, help="Hotkey of wallet")
    mnemonic = typer.Option(
        None, help="Mnemonic used to regen your key i.e. horse cart dog ..."
    )
    seed = typer.Option(
        None, help="Seed hex string used to regen your key i.e. 0x1234..."
    )
    json = typer.Option(
        None,
        help="Path to a json file containing the encrypted key backup. (e.g. from PolkadotJS)",
    )
    json_password = typer.Option(None, help="Password to decrypt the json file.")
    use_password = typer.Option(
        False,
        help="Set true to protect the generated bittensor key with a password.",
    )
    public_hex_key = typer.Option(None, help="The public key in hex format.")
    ss58_address = typer.Option(None, help="The SS58 address of the coldkey")
    overwrite_coldkey = typer.Option(
        False, help="Overwrite the old coldkey with the newly generated coldkey"
    )
    overwrite_hotkey = typer.Option(
        False, help="Overwrite the old hotkey with the newly generated hotkey"
    )


class NotSubtensor:
    def __init__(self, network: str, chain: str):
        self.network = network
        self.chain = chain

    def __str__(self):
        return f"NotSubtensor(network={self.network}, chain={self.chain})"


class Wallet:
    def __init__(
            self,
                 name: Optional[str] = None,
            hotkey: Optional[str] = None,
            path: Optional[str] = None,
            config: Optional["Config"] = None
    ):
        pass


def get_n_words(n_words: Optional[int]) -> int:
    while n_words not in [12, 15, 18, 21, 24]:
        n_words = typer.prompt(
            "Choose number of words: 12, 15, 18, 21, 24", type=int, default=12
        )
    return n_words


class CLIManager:
    def __init__(self):
        self.app = typer.Typer()
        self.wallet_app = typer.Typer()
        self.delegates_app = typer.Typer()

        # wallet aliases
        self.app.add_typer(self.wallet_app, name="wallet")
        self.app.add_typer(self.wallet_app, name="w", hidden=True)
        self.app.add_typer(self.wallet_app, name="wallets", hidden=True)

        # delegates aliases
        self.app.add_typer(self.delegates_app, name="delegates")
        self.app.add_typer(self.delegates_app, name="d", hidden=True)

        self.wallet_app.command("")(self.wallet_ask)
        self.wallet_app.command("list")(self.wallet_list)
        self.wallet_app.command("regen-coldkey")(self.wallet_regen_coldkey)
        self.delegates_app.command("list")(self.delegates_list)

        self.not_subtensor = None

    def initialize_chain(
        self,
        network: str = typer.Option("default_network", help="Network name"),
        chain: str = typer.Option("default_chain", help="Chain name"),
    ):
        if not self.not_subtensor:
            self.not_subtensor = NotSubtensor(network, chain)
            typer.echo(f"Initialized with {self.not_subtensor}")

    @staticmethod
    def wallet_ask(wallet_name: str, wallet_path: str, wallet_hotkey: str):
        if not any([wallet_name, wallet_path, wallet_hotkey]):
            wallet_name = typer.prompt("Enter wallet name:")
            wallet = Wallet(name=wallet_name)
        elif wallet_name:
            wallet = Wallet(name=wallet_name)
        elif wallet_path:
            wallet = Wallet(path=wallet_path)
        elif wallet_hotkey:
            wallet = Wallet(hotkey=wallet_hotkey)
        # TODO Wallet(config)
        else:
            raise typer.BadParameter("Could not create wallet")
        return wallet

    def wallet_list(self, network: str = typer.Option("local", help="Network name")):
        asyncio.run(wallets.WalletListCommand.run(self.not_subtensor, network))

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
        Executes the ``regen_coldkey`` command to regenerate a coldkey for a wallet on the Bittensor network.

        This command is used to create a new coldkey from an existing mnemonic, seed, or JSON file.

        Usage: Users can specify a mnemonic, a seed string, or a JSON file path to regenerate a coldkey.
        The command supports optional password protection for the generated key and can overwrite an existing coldkey.

        Example usage: `btcli wallet regen_coldkey --mnemonic "word1 word2 ... word12"`

        Note: This command is critical for users who need to regenerate their coldkey, possibly for recovery or security reasons.
        It should be used with caution to avoid overwriting existing keys unintentionally.
        """

        wallet = self.wallet_ask(wallet_name, wallet_path, wallet_hotkey)
        if not mnemonic and not seed and not json:
            prompt_answer = typer.prompt("Enter mnemonic, seed, or json file location")
            if prompt_answer.startswith("0x"):
                seed = prompt_answer
            elif len(prompt_answer.split(" ")) > 1:
                mnemonic = prompt_answer
            else:
                json = prompt_answer
        if json and not json_password:
            json_password = typer.prompt("Enter json backup password", hide_input=True)
        asyncio.run(
            wallets.RegenColdkeyCommand.run(
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
            False, help="Overwrites the existing coldkeypub file with the new one."
        ),
    ):
        """
        Executes the ``regen_coldkeypub`` command to regenerate the public part of a coldkey (coldkeypub) for a wallet on the Bittensor network.

        This command is used when a user needs to recreate their coldkeypub from an existing public key or SS58 address.

        Usage:
            The command requires either a public key in hexadecimal format or an ``SS58`` address to regenerate the coldkeypub. It optionally allows overwriting an existing coldkeypub file.

        Example usage::

            btcli wallet regen_coldkeypub --ss58_address 5DkQ4...

        Note:
            This command is particularly useful for users who need to regenerate their coldkeypub, perhaps due to file corruption or loss.
            It is a recovery-focused utility that ensures continued access to wallet functionalities.
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
        if not bittensor.utils.is_valid_bittensor_address_or_public_key(
            address=ss58_address if ss58_address else public_key_hex
        ):
            rich.print("[red]Error: Invalid SS58 address or public key![/red]")
            raise typer.Exit()
        asyncio.run(
            wallets.RegenColdkeypubCommand.run(
                wallet, public_key_hex, ss58_address, overwrite_coldkeypub
            )
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
        use_password: Optional[bool] = Options.use_password,
        overwrite_hotkey: Optional[bool] = Options.overwrite_hotkey,
    ):
        """
        Executes the ``regen_hotkey`` command to regenerate a hotkey for a wallet on the Bittensor network.

        Similar to regenerating a coldkey, this command creates a new hotkey from a mnemonic, seed, or JSON file.

        Usage:
            Users can provide a mnemonic, seed string, or a JSON file to regenerate the hotkey.
            The command supports optional password protection and can overwrite an existing hotkey.

        Example usage::

            btcli wallet regen_hotkey
            btcli wallet regen_hotkey --seed 0x1234...

        Note:
            This command is essential for users who need to regenerate their hotkey, possibly for security upgrades or key recovery.
            It should be used cautiously to avoid accidental overwrites of existing keys.
        """
        wallet = self.wallet_ask(wallet_name, wallet_path, wallet_hotkey)
        if not wallet_hotkey:  # TODO no prompt
            # TODO add to wallet object
            wallet_hotkey = typer.prompt(
                "Enter hotkey name", default=defaults.wallet.hotkey
            )
        if not mnemonic and not seed and not json:
            prompt_answer = typer.prompt("Enter mnemonic, seed, or json file location")
            if prompt_answer.startswith("0x"):
                seed = prompt_answer
            elif len(prompt_answer.split(" ")) > 1:
                mnemonic = prompt_answer
            else:
                json = prompt_answer
        if json and not json_password:
            json_password = typer.prompt("Enter json backup password", hide_input=True)
        asyncio.run(
            wallets.RegenHotkeyCommand.run(
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
        wallet_hotkey: Optional[str] = Options.wallet_hotkey,
        n_words: Optional[int] = None,
        use_password: Optional[bool] = Options.use_password,
        overwrite_hotkey: Optional[bool] = Options.overwrite_hotkey,
    ):
        """
        Executes the ``new_hotkey`` command to create a new hotkey under a wallet on the Bittensor network.

        This command is used to generate a new hotkey for managing a neuron or participating in the network.

        Usage:
            The command creates a new hotkey with an optional word count for the mnemonic and supports password protection.
            It also allows overwriting an existing hotkey.

        Example usage::

            btcli wallet new_hotkey --n_words 24

        Note:
            This command is useful for users who wish to create additional hotkeys for different purposes,
            such as running multiple miners or separating operational roles within the network.
        """
        wallet = self.wallet_ask(wallet_name, wallet_path, wallet_hotkey)
        if not wallet_hotkey:  # TODO no prompt
            # TODO add to wallet object
            wallet_hotkey = typer.prompt(
                "Enter hotkey name", default=defaults.wallet.hotkey
            )
        n_words = get_n_words(n_words)
        asyncio.run(
            wallets.NewHotkeyCommand.run(wallet, use_password, overwrite_hotkey)
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
        Executes the ``new_coldkey`` command to create a new coldkey under a wallet on the Bittensor network.

        This command generates a coldkey, which is essential for holding balances and performing high-value transactions.

        Usage:
            The command creates a new coldkey with an optional word count for the mnemonic and supports password protection.
            It also allows overwriting an existing coldkey.

        Example usage::

            btcli wallet new_coldkey --n_words 15

        Note:
            This command is crucial for users who need to create a new coldkey for enhanced security or as part of setting up a new wallet.
            It's a foundational step in establishing a secure presence on the Bittensor network.
        """
        wallet = self.wallet_ask(wallet_name, wallet_path, wallet_hotkey)
        n_words = get_n_words(n_words)
        asyncio.run(
            wallets.NewColdkeyCommand.run(
                wallet, n_words, use_password, overwrite_coldkey
            )
        )

    def wallet_create_wallet(
        self,
        wallet_name: Optional[str] = Options.wallet_name,
        wallet_path: Optional[str] = Options.wallet_path,
        wallet_hotkey: Optional[str] = Options.wallet_hotkey,
        n_words: Optional[int] = None,
        use_password: Optional[bool] = Options.use_password,
        overwrite_hotkey: Optional[bool] = Options.overwrite_hotkey,
        overwrite_coldkey: Optional[bool] = Options.overwrite_coldkey,
    ):
        """
        Executes the ``create`` command to generate both a new coldkey and hotkey under a specified wallet on the Bittensor network.

        This command is a comprehensive utility for creating a complete wallet setup with both cold and hotkeys.

        Usage:
            The command facilitates the creation of a new coldkey and hotkey with an optional word count for the mnemonics.
            It supports password protection for the coldkey and allows overwriting of existing keys.

        Example usage::

            btcli wallet create --n_words 21

        Note:
            This command is ideal for new users setting up their wallet for the first time or for those who wish to completely renew their wallet keys.
            It ensures a fresh start with new keys for secure and effective participation in the network.
        """
        n_words = get_n_words(n_words)
        if not wallet_hotkey:  # TODO no prompt
            # TODO add to wallet object
            wallet_hotkey = typer.prompt(
                "Enter hotkey name", default=defaults.wallet.hotkey
            )

    def delegates_list(
        self,
        wallet_name: Optional[str] = typer.Option(None, help="Wallet name"),
        network: str = typer.Option("test", help="Network name"),
    ):
        if not wallet_name:
            wallet_name = typer.prompt("Please enter the wallet name")
        asyncio.run(delegates.ListDelegatesCommand.run(wallet_name, network))

    def run(self):
        self.app()


if __name__ == "__main__":
    manager = CLIManager()
    manager.run()
