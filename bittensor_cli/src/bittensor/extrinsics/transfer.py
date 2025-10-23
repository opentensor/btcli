import asyncio
from typing import Optional, Union

from async_substrate_interface import AsyncExtrinsicReceipt
from bittensor_wallet import Wallet
from rich.prompt import Confirm
from async_substrate_interface.errors import SubstrateRequestException

from bittensor_cli.src.bittensor.balances import Balance
from bittensor_cli.src.bittensor.subtensor_interface import SubtensorInterface
from bittensor_cli.src.bittensor.utils import (
    console,
    err_console,
    print_verbose,
    format_error_message,
    is_valid_bittensor_address_or_public_key,
    print_error,
    unlock_key,
)


async def transfer_extrinsic(
    subtensor: SubtensorInterface,
    wallet: Wallet,
    destination: str,
    amount: Balance,
    era: int = 3,
    transfer_all: bool = False,
    allow_death: bool = False,
    wait_for_inclusion: bool = True,
    wait_for_finalization: bool = False,
    prompt: bool = False,
) -> tuple[bool, Optional[AsyncExtrinsicReceipt]]:
    """Transfers funds from this wallet to the destination public key address.

    :param subtensor: initialized SubtensorInterface object used for transfer
    :param wallet: Bittensor wallet object to make transfer from.
    :param destination: Destination public key address (ss58_address or ed25519) of recipient.
    :param amount: Amount to stake as Bittensor balance.
    :param era: Length (in blocks) for which the transaction should be valid.
    :param transfer_all: Whether to transfer all funds from this wallet to the destination address.
    :param allow_death: Whether to allow for falling below the existential deposit when performing this transfer.
    :param wait_for_inclusion: If set, waits for the extrinsic to enter a block before returning `True`,
                               or returns `False` if the extrinsic fails to enter the block within the timeout.
    :param wait_for_finalization:  If set, waits for the extrinsic to be finalized on the chain before returning
                                   `True`, or returns `False` if the extrinsic fails to be finalized within the timeout.
    :param prompt: If `True`, the call waits for confirmation from the user before proceeding.
    :return: success: Flag is `True` if extrinsic was finalized or included in the block. If we did not wait for
                      finalization / inclusion, the response is `True`, regardless of its inclusion.
    """

    async def get_transfer_fee() -> Balance:
        """
        Calculates the transaction fee for transferring tokens from a wallet to a specified destination address.
        This function simulates the transfer to estimate the associated cost, taking into account the current
        network conditions and transaction complexity.
        """
        call = await subtensor.substrate.compose_call(
            call_module="Balances",
            call_function=call_function,
            call_params=call_params,
        )

        try:
            payment_info = await subtensor.substrate.get_payment_info(
                call=call, keypair=wallet.coldkeypub
            )
        except SubstrateRequestException as e:
            payment_info = {"partial_fee": int(2e7)}  # assume  0.02 Tao
            err_console.print(
                f":cross_mark: [red]Failed to get payment info[/red]:[bold white]\n"
                f"  {format_error_message(e)}[/bold white]\n"
                f"  Defaulting to default transfer fee: {payment_info['partialFee']}"
            )

        return Balance.from_rao(payment_info["partial_fee"])

    async def do_transfer() -> tuple[bool, str, str, AsyncExtrinsicReceipt]:
        """
        Makes transfer from wallet to destination public key address.
        :return: success, block hash, formatted error message
        """
        call = await subtensor.substrate.compose_call(
            call_module="Balances",
            call_function=call_function,
            call_params=call_params,
        )
        extrinsic = await subtensor.substrate.create_signed_extrinsic(
            call=call, keypair=wallet.coldkey, era={"period": era}
        )
        response = await subtensor.substrate.submit_extrinsic(
            extrinsic,
            wait_for_inclusion=wait_for_inclusion,
            wait_for_finalization=wait_for_finalization,
        )
        # We only wait here if we expect finalization.
        if not wait_for_finalization and not wait_for_inclusion:
            return True, "", "", response

        # Otherwise continue with finalization.
        if await response.is_success:
            block_hash_ = response.block_hash
            return True, block_hash_, "", response
        else:
            return (
                False,
                "",
                format_error_message(await response.error_message),
                response,
            )

    # Validate destination address.
    if not is_valid_bittensor_address_or_public_key(destination):
        err_console.print(
            f":cross_mark: [red]Invalid destination SS58 address[/red]:[bold white]\n  {destination}[/bold white]"
        )
        return False, None
    console.print(f"[dark_orange]Initiating transfer on network: {subtensor.network}")

    call_params: dict[str, Optional[Union[str, int]]] = {"dest": destination}
    if transfer_all:
        call_function = "transfer_all"
        if allow_death:
            call_params["keep_alive"] = False
        else:
            call_params["keep_alive"] = True
    else:
        call_params["value"] = amount.rao
        if allow_death:
            call_function = "transfer_allow_death"
        else:
            call_function = "transfer_keep_alive"

    # Check balance.
    with console.status(
        f":satellite: Checking balance and fees on chain [white]{subtensor.network}[/white]",
        spinner="aesthetic",
    ) as status:
        # check existential deposit and fee
        print_verbose("Fetching existential and fee", status)
        block_hash = await subtensor.substrate.get_chain_head()
        account_balance, existential_deposit = await asyncio.gather(
            subtensor.get_balance(
                wallet.coldkeypub.ss58_address, block_hash=block_hash
            ),
            subtensor.get_existential_deposit(block_hash=block_hash),
        )
        fee = await get_transfer_fee()

    if allow_death:
        # Check if the transfer should keep alive the account
        existential_deposit = Balance(0)

    if account_balance < (amount + fee + existential_deposit) and not allow_death:
        err_console.print(
            ":cross_mark: [bold red]Not enough balance[/bold red]:\n\n"
            f"  balance: [bright_cyan]{account_balance}[/bright_cyan]\n"
            f"  amount: [bright_cyan]{amount}[/bright_cyan]\n"
            f"  for fee: [bright_cyan]{fee}[/bright_cyan]\n"
            f"   would bring you under the existential deposit: [bright_cyan]{existential_deposit}[/bright_cyan].\n"
            f"You can try again with `--allow-death`."
        )
        return False, None
    elif account_balance < (amount + fee) and allow_death:
        print_error(
            ":cross_mark: [bold red]Not enough balance[/bold red]:\n\n"
            f"  balance: [bright_red]{account_balance}[/bright_red]\n"
            f"  amount: [bright_red]{amount}[/bright_red]\n"
            f"  for fee: [bright_red]{fee}[/bright_red]"
        )
        return False, None

    # Ask before moving on.
    if prompt:
        hk_owner = await subtensor.get_hotkey_owner(destination, check_exists=False)
        if hk_owner and hk_owner != destination:
            if not Confirm.ask(
                f"The destination appears to be a hotkey, owned by [bright_magenta]{hk_owner}[/bright_magenta]. "
                f"Only proceed if you are absolutely sure that [bright_magenta]{destination}[/bright_magenta] is the "
                f"correct destination.",
                default=False,
            ):
                return False, None
        if not Confirm.ask(
            "Do you want to transfer:[bold white]\n"
            f"  amount: [bright_cyan]{amount if not transfer_all else account_balance}[/bright_cyan]\n"
            f"  from: [light_goldenrod2]{wallet.name}[/light_goldenrod2] : "
            f"[bright_magenta]{wallet.coldkeypub.ss58_address}\n[/bright_magenta]"
            f"  to: [bright_magenta]{destination}[/bright_magenta]\n  for fee: [bright_cyan]{fee}[/bright_cyan]\n"
            f"[bright_yellow]Transferring is not the same as staking. To instead stake, use "
            f"[dark_orange]btcli stake add[/dark_orange] instead[/bright_yellow].\n"
            f"Proceed with transfer?"
        ):
            return False, None

    # Unlock wallet coldkey.
    if not unlock_key(wallet).success:
        return False, None

    with console.status(":satellite: Transferring...", spinner="earth"):
        success, block_hash, err_msg, ext_receipt = await do_transfer()

        if success:
            console.print(":white_heavy_check_mark: [green]Finalized[/green]")
            console.print(f"[green]Block Hash: {block_hash}[/green]")

        else:
            console.print(f":cross_mark: [red]Failed[/red]: {err_msg}")

    if success:
        with console.status(":satellite: Checking Balance...", spinner="aesthetic"):
            new_balance = await subtensor.get_balance(
                wallet.coldkeypub.ss58_address, reuse_block=False
            )
            console.print(
                f"Balance:\n"
                f"  [blue]{account_balance}[/blue] :arrow_right: [green]{new_balance}[/green]"
            )
            return True, ext_receipt

    return False, None
