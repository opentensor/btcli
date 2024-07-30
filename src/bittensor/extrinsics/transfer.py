import asyncio
from typing import Union

from bittensor_wallet import Wallet
from rich.prompt import Confirm

from src.subtensor_interface import SubtensorInterface
from src.bittensor.balances import Balance
from src.utils import console, err_console


async def transfer_extrinsic(
    subtensor: SubtensorInterface,
    wallet: Wallet,
    destination: Union[str, bytes],
    amount: Balance,
    wait_for_inclusion: bool = True,
    wait_for_finalization: bool = False,
    keep_alive: bool = True,
    prompt: bool = False,
) -> bool:
    """Transfers funds from this wallet to the destination public key address.

    :param subtensor: SubtensorInterface object used for transfer
    :param wallet: Bittensor wallet object to make transfer from.
    :param destination: Destination public key address (ss58_address or ed25519) of recipient.
    :param amount: Amount to stake as Bittensor balance.
    :param wait_for_inclusion: If set, waits for the extrinsic to enter a block before returning `True`,
                               or returns `False` if the extrinsic fails to enter the block within the timeout.
    :param wait_for_finalization:  If set, waits for the extrinsic to be finalized on the chain before returning
                                   `True`, or returns `False` if the extrinsic fails to be finalized within the timeout.
    :param keep_alive: If set, keeps the account alive by keeping the balance above the existential deposit.
    :param prompt: If `True`, the call waits for confirmation from the user before proceeding.
    :return: success: Flag is `True` if extrinsic was finalized or included in the block. If we did not wait for
                      finalization / inclusion, the response is `True`, regardless of its inclusion.
    """
    # Validate destination address.
    if not is_valid_bittensor_address_or_public_key(destination):  # TODO
        err_console.print(
            f":cross_mark: [red]Invalid destination address[/red]:[bold white]\n  {destination}[/bold white]"
        )
        return False

    if isinstance(destination, bytes):
        # Convert bytes to hex string.
        destination = f"0x{destination.hex()}"

    # Unlock wallet coldkey.
    wallet.unlock_coldkey()

    # Convert to bittensor.Balance
    transfer_balance = amount

    # Check balance.
    with console.status(":satellite: Checking balance and fees..."):
        async with subtensor:
        # check existential deposit and fee
            account_balance, existential_deposit, fee = await asyncio.gather(
                subtensor.get_balance(wallet.coldkey.ss58_address),
                subtensor.get_existential_deposit(),  # TODO
                subtensor.get_transfer_fee(
                    wallet=wallet, dest=destination, value=transfer_balance.rao
                ),  # TODO
            )

    if not keep_alive:
        # Check if the transfer should keep_alive the account
        existential_deposit = Balance(0)

    # Check if we have enough balance.
    if account_balance < (transfer_balance + fee + existential_deposit):
        err_console.print(
            ":cross_mark: [red]Not enough balance[/red]:[bold white]\n"
            f"  balance: {account_balance}\n"
            f"  amount: {transfer_balance}\n"
            f"  for fee: {fee}[/bold white]"
        )
        return False

    # Ask before moving on.
    if prompt:
        if not Confirm.ask(
            "Do you want to transfer:[bold white]\n"
            f"  amount: {transfer_balance}\n"
            f"  from: {wallet.name}:{wallet.coldkey.ss58_address}\n"
            f"  to: {destination}\n  for fee: {fee}[/bold white]"
        ):
            return False

    with console.status(":satellite: Transferring..."):
        async with subtensor:
            success, block_hash, err_msg = await subtensor._do_transfer(  # TODO
                wallet,
                destination,
                transfer_balance,
                wait_for_finalization=wait_for_finalization,
                wait_for_inclusion=wait_for_inclusion,
            )

        if success:
            console.print(":white_heavy_check_mark: [green]Finalized[/green]")
            console.print(f"[green]Block Hash: {block_hash}[/green]")

            explorer_urls = bittensor.utils.get_explorer_url_for_network(  # TODO
                subtensor.network,
                block_hash,
                bittensor.__network_explorer_map__,  # TODO
            )
            if explorer_urls != {} and explorer_urls:
                console.print(
                    f"[green]Opentensor Explorer Link: {explorer_urls.get('opentensor')}[/green]"
                )
                console.print(
                    f"[green]Taostats Explorer Link: {explorer_urls.get('taostats')}[/green]"
                )
        else:
            console.print(f":cross_mark: [red]Failed[/red]: {err_msg}")

    if success:
        with console.status(":satellite: Checking Balance..."):
            async with subtensor:
                new_balance = await subtensor.get_balance(
                    wallet.coldkey.ss58_address, reuse_block=False
                )
            console.print(
                f"Balance:\n  [blue]{account_balance}[/blue] :arrow_right: [green]{new_balance}[/green]"
            )
            return True

    return False
