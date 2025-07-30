from typing import Optional

from rich.prompt import FloatPrompt
from bittensor_cli.cli import CLIManager, Options
from bittensor_cli.src import (
    WalletOptions as WO,
    WalletValidationTypes as WV,
)
import typer
from ptn_cli.src.commands.collateral import (
    list as list_collateral,
    deposit as deposit_collateral,
    withdraw as withdraw_collateral
)

_epilog = "Made with [bold red]:heart:[/bold red] by The Proprieτary Trading Neτwork"

class PTNOptions:
    ptn_network = typer.Option(
        "finney",
        "--network",
        "--subtensor.network",
        help="The subtensor network to connect to.",
    )
    amount = typer.Option(
        None,
        "--amount",
        help="Amount of Theta to use for collateral",
    )
    prompt = typer.Option(
        True,
        "--prompt",
        help="Whether to prompt for confirmation",
    )



class PTNCLIManager(CLIManager):

    collateral_app: typer.Typer

    def __init__(self):
        super().__init__()

        self.collateral_app = typer.Typer(epilog=_epilog)

        self.app.add_typer(
            self.collateral_app,
            name="collateral",
            short_help="Collateral commands, aliasas: `collateral`",
            no_args_is_help=True
        )

        self.collateral_app.command(
            "list", rich_help_panel="Collateral Management"
        )(self.collateral_list)
        self.collateral_app.command(
            "deposit", rich_help_panel="Collateral Operations"
        )(self.collateral_deposit)
        self.collateral_app.command(
            "withdraw", rich_help_panel="Collateral Operations"
        )(self.collateral_withdraw)

    def collateral_list(
        self,
        wallet_name: Optional[str] = Options.wallet_name,
        wallet_path: Optional[str] = Options.wallet_path,
        wallet_hotkey: Optional[str] = Options.wallet_hotkey_ss58,
        network: str = PTNOptions.ptn_network,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
        json_output: bool = Options.json_output,
    ):
        """
        List collateral balance for a miner address
        """
        self.verbosity_handler(quiet, verbose, json_output)

        ask_for = [WO.NAME, WO.HOTKEY]
        wallet = self.wallet_ask(
            wallet_name,
            wallet_path,
            wallet_hotkey,
            ask_for=ask_for,
            validate=WV.WALLET_AND_HOTKEY,
        )

        return self._run_command(
            list_collateral.collateral_list(
                wallet,
                network,
                quiet,
                verbose,
                json_output
            )
        )

    def collateral_deposit(
        self,
        wallet_name: Optional[str] = Options.wallet_name,
        wallet_path: Optional[str] = Options.wallet_path,
        wallet_hotkey: Optional[str] = Options.wallet_hotkey_ss58,
        network: str = PTNOptions.ptn_network,
        amount: Optional[float] = PTNOptions.amount,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
        json_output: bool = Options.json_output,
    ):
        """
        Deposit collateral from the Proprieτary Trading Neτwork
        """

        self.verbosity_handler(quiet, verbose, json_output)

        ask_for = [WO.NAME, WO.HOTKEY]
        wallet = self.wallet_ask(
            wallet_name,
            wallet_path,
            wallet_hotkey,
            ask_for=ask_for,
            validate=WV.WALLET_AND_HOTKEY,
        )

        if amount is None:
            amount = FloatPrompt.ask("Enter collateral deposit amount")

        return self._run_command(
            deposit_collateral.deposit(
                wallet,
                network,
                amount,
                quiet,
                verbose,
                json_output
            )
        )

    def collateral_withdraw(
        self,
        wallet_name: Optional[str] = Options.wallet_name,
        wallet_path: Optional[str] = Options.wallet_path,
        wallet_hotkey: Optional[str] = Options.wallet_hotkey_ss58,
        network: str = PTNOptions.ptn_network,
        amount: Optional[float] = PTNOptions.amount,
        prompt: bool = PTNOptions.prompt,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
        json_output: bool = Options.json_output,
    ):
        """
        Withdraw collateral from the Proprieτary Trading Neτwork
        """
        self.verbosity_handler(quiet, verbose, json_output)

        ask_for = [WO.NAME, WO.HOTKEY]
        wallet = self.wallet_ask(
            wallet_name,
            wallet_path,
            wallet_hotkey,
            ask_for=ask_for,
            validate=WV.WALLET_AND_HOTKEY,
        )

        if amount is None:
            amount = FloatPrompt.ask("Enter collateral withdrawal amount")

        return self._run_command(
            withdraw_collateral.withdraw(
                wallet,
                network,
                amount,
                prompt,
                quiet,
                verbose,
                json_output
            )
        )


def main():
    manager = PTNCLIManager()
    manager.run()


if __name__ == "__main__":
    main()
