from typing import Optional

from rich.prompt import FloatPrompt, IntPrompt, Prompt
from bittensor_cli.cli import CLIManager, Options
from bittensor_cli.src import (
    WalletOptions as WO,
    WalletValidationTypes as WV,
)
from bittensor_cli.src.bittensor.utils import (
    console,
)
import typer
from vanta_cli.src.commands.collateral import (
    list as list_collateral,
    deposit as deposit_collateral,
    withdraw as withdraw_collateral
)
from vanta_cli.src.commands.asset import (
    select as select_asset
)

_epilog = "Made with [bold red]:heart:[/bold red] by The Vanτa Neτwork"

class VantaOptions:
    vanta_network = typer.Option(
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



class VantaCLIManager(CLIManager):

    collateral_app: typer.Typer
    asset_app: typer.Typer

    def __init__(self):
        super().__init__()

        self.collateral_app = typer.Typer(epilog=_epilog)
        self.asset_app = typer.Typer(epilog=_epilog)

        self.app.add_typer(
            self.collateral_app,
            name="collateral",
            short_help="Collateral commands, alias: `collateral`",
            no_args_is_help=True
        )
        self.app.add_typer(
            self.asset_app,
            name="asset",
            short_help="Asset command for choosing asset",
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

        self.asset_app.command(
            "select", rich_help_panel="Asset class selection"
        )(self.asset_select)

    def collateral_list(
        self,
        wallet_name: Optional[str] = Options.wallet_name,
        wallet_path: Optional[str] = Options.wallet_path,
        wallet_hotkey: Optional[str] = Options.wallet_hotkey_ss58,
        network: str = VantaOptions.vanta_network,
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
        network: str = VantaOptions.vanta_network,
        amount: Optional[float] = VantaOptions.amount,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
        json_output: bool = Options.json_output,
    ):
        """
        Deposit collateral from the Vanτa Neτwork
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
        network: str = VantaOptions.vanta_network,
        amount: Optional[float] = VantaOptions.amount,
        prompt: bool = VantaOptions.prompt,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
        json_output: bool = Options.json_output,
    ):
        """
        Withdraw collateral from the Vanτa Neτwork
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

    def asset_select(
        self,
        wallet_name: Optional[str] = Options.wallet_name,
        wallet_path: Optional[str] = Options.wallet_path,
        wallet_hotkey: Optional[str] = Options.wallet_hotkey_ss58,
        network: str = VantaOptions.vanta_network,
        prompt: bool = VantaOptions.prompt,
        quiet: bool = Options.quiet,
        verbose: bool = Options.verbose,
        json_output: bool = Options.json_output,
    ):
        self.verbosity_handler(quiet, verbose, json_output)

        ask_for = [WO.NAME, WO.HOTKEY]
        wallet = self.wallet_ask(
            wallet_name,
            wallet_path,
            wallet_hotkey,
            ask_for=ask_for,
            validate=WV.WALLET_AND_HOTKEY,
        )

        assets = ["crypto", "forex", "equities"]

        for idx, asset in enumerate(assets, start=1):
            console.print(f"{idx}. {asset}")

        choice = IntPrompt.ask(
            "\nEnter the [bold]number[/bold] of the asset class you want to select",
            choices=[str(i) for i in range(1, len(assets) + 1)],
            show_choices=False,
        )
        asset_choice = assets[choice - 1]

        return self._run_command(
            select_asset.select(
                wallet,
                network,
                asset_choice,
                prompt,
                quiet,
                verbose,
                json_output
            )
        )


def main():
    manager = VantaCLIManager()
    manager.run()

if __name__ == "__main__":
    main()
