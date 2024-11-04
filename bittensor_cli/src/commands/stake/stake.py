import asyncio
import copy
import json
import sqlite3
from contextlib import suppress

from typing import TYPE_CHECKING, Optional, Sequence, Union, cast

from bittensor_wallet import Wallet
from bittensor_wallet.errors import KeyFileError
from rich.prompt import Confirm
from rich.table import Table, Column
import typer


from bittensor_cli.src.bittensor.balances import Balance
from bittensor_cli.src.bittensor.utils import (
    console,
    create_table,
    err_console,
    print_verbose,
    print_error,
    get_coldkey_wallets_for_path,
    get_hotkey_wallets_for_wallet,
    is_valid_ss58_address,
    get_metadata_table,
    update_metadata_table,
    render_tree,
    u16_normalized_float,
    validate_coldkey_presence,
)

if TYPE_CHECKING:
    from bittensor_cli.src.bittensor.subtensor_interface import SubtensorInterface


# Helpers and Extrinsics


async def _get_threshold_amount(
    subtensor: "SubtensorInterface", block_hash: str
) -> Balance:
    mrs = await subtensor.substrate.query(
        module="SubtensorModule",
        storage_function="NominatorMinRequiredStake",
        block_hash=block_hash,
    )
    min_req_stake: Balance = Balance.from_rao(mrs)
    return min_req_stake


async def _check_threshold_amount(
    subtensor: "SubtensorInterface",
    sb: Balance,
    block_hash: str,
    min_req_stake: Optional[Balance] = None,
) -> tuple[bool, Balance]:
    """
    Checks if the new stake balance will be above the minimum required stake threshold.

    :param sb: the balance to check for threshold limits.

    :return: (success, threshold)
            `True` if the staking balance is above the threshold, or `False` if the staking balance is below the
            threshold.
            The threshold balance required to stake.
    """
    if not min_req_stake:
        min_req_stake = await _get_threshold_amount(subtensor, block_hash)

    if min_req_stake > sb:
        return False, min_req_stake
    else:
        return True, min_req_stake


async def add_stake_extrinsic(
    subtensor: "SubtensorInterface",
    wallet: Wallet,
    old_balance: Balance,
    hotkey_ss58: Optional[str] = None,
    amount: Optional[Balance] = None,
    wait_for_inclusion: bool = True,
    wait_for_finalization: bool = False,
    prompt: bool = False,
) -> bool:
    """
    Adds the specified amount of stake to passed hotkey `uid`.

    :param subtensor: the initialized SubtensorInterface object to use
    :param wallet: Bittensor wallet object.
    :param old_balance: the balance prior to the staking
    :param hotkey_ss58: The `ss58` address of the hotkey account to stake to defaults to the wallet's hotkey.
    :param amount: Amount to stake as Bittensor balance, `None` if staking all.
    :param wait_for_inclusion: If set, waits for the extrinsic to enter a block before returning `True`, or returns
                               `False` if the extrinsic fails to enter the block within the timeout.
    :param wait_for_finalization: If set, waits for the extrinsic to be finalized on the chain before returning `True`,
                                  or returns `False` if the extrinsic fails to be finalized within the timeout.
    :param prompt: If `True`, the call waits for confirmation from the user before proceeding.

    :return: success: Flag is `True` if extrinsic was finalized or included in the block. If we did not wait for
                      finalization/inclusion, the response is `True`.
    """

    # Decrypt keys,
    try:
        wallet.unlock_coldkey()
    except KeyFileError:
        err_console.print("Error decrypting coldkey (possibly incorrect password)")
        return False

    # Default to wallet's own hotkey if the value is not passed.
    if hotkey_ss58 is None:
        hotkey_ss58 = wallet.hotkey.ss58_address

    # Flag to indicate if we are using the wallet's own hotkey.
    own_hotkey: bool

    with console.status(
        f":satellite: Syncing with chain: [white]{subtensor}[/white] ...",
        spinner="aesthetic",
    ) as status:
        block_hash = await subtensor.substrate.get_chain_head()
        # Get hotkey owner
        print_verbose("Confirming hotkey owner", status)
        hotkey_owner = await subtensor.get_hotkey_owner(
            hotkey_ss58=hotkey_ss58, block_hash=block_hash
        )
        own_hotkey = wallet.coldkeypub.ss58_address == hotkey_owner
        if not own_hotkey:
            # This is not the wallet's own hotkey, so we are delegating.
            if not await subtensor.is_hotkey_delegate(
                hotkey_ss58, block_hash=block_hash
            ):
                err_console.print(
                    f"Hotkey {hotkey_ss58} is not a delegate on the chain."
                )
                return False

            # Get hotkey take
            hk_result = await subtensor.substrate.query(
                module="SubtensorModule",
                storage_function="Delegates",
                params=[hotkey_ss58],
                block_hash=block_hash,
            )
            hotkey_take = u16_normalized_float(hk_result or 0)
        else:
            hotkey_take = None

        # Get current stake
        print_verbose("Fetching current stake", status)
        old_stake = await subtensor.get_stake_for_coldkey_and_hotkey(
            coldkey_ss58=wallet.coldkeypub.ss58_address,
            hotkey_ss58=hotkey_ss58,
            block_hash=block_hash,
        )

        print_verbose("Fetching existential deposit", status)
        # Grab the existential deposit.
        existential_deposit = await subtensor.get_existential_deposit()

    # Convert to bittensor.Balance
    if amount is None:
        # Stake it all.
        staking_balance = Balance.from_tao(old_balance.tao)
    else:
        staking_balance = Balance.from_tao(amount)

    # Leave existential balance to keep key alive.
    if staking_balance > old_balance - existential_deposit:
        # If we are staking all, we need to leave at least the existential deposit.
        staking_balance = old_balance - existential_deposit
    else:
        staking_balance = staking_balance

    # Check enough to stake.
    if staking_balance > old_balance:
        err_console.print(
            f":cross_mark: [red]Not enough stake[/red]:[bold white]\n"
            f"\tbalance:\t{old_balance}\n"
            f"\tamount:\t{staking_balance}\n"
            f"\tcoldkey:\t{wallet.name}[/bold white]"
        )
        return False

    # If nominating, we need to check if the new stake balance will be above the minimum required stake threshold.
    if not own_hotkey:
        new_stake_balance = old_stake + staking_balance
        print_verbose("Fetching threshold amount")
        is_above_threshold, threshold = await _check_threshold_amount(
            subtensor, new_stake_balance, block_hash
        )
        if not is_above_threshold:
            err_console.print(
                f":cross_mark: [red]New stake balance of {new_stake_balance} is below the minimum required nomination"
                f" stake threshold {threshold}.[/red]"
            )
            return False

    # Ask before moving on.
    if prompt:
        if not own_hotkey:
            # We are delegating.
            if not Confirm.ask(
                f"Do you want to delegate:[bold white]\n"
                f"\tamount: {staking_balance}\n"
                f"\tto: {hotkey_ss58}\n"
                f"\ttake: {hotkey_take}\n[/bold white]"
                f"\towner: {hotkey_owner}\n"
            ):
                return False
        else:
            if not Confirm.ask(
                f"Do you want to stake:[bold white]\n"
                f"\tamount: {staking_balance}\n"
                f"\tto: {wallet.hotkey_str}\n"
                f"\taddress: {hotkey_ss58}[/bold white]\n"
            ):
                return False

    with console.status(
        f":satellite: Staking to: [bold white]{subtensor}[/bold white] ...",
        spinner="earth",
    ):
        call = await subtensor.substrate.compose_call(
            call_module="SubtensorModule",
            call_function="add_stake",
            call_params={"hotkey": hotkey_ss58, "amount_staked": staking_balance.rao},
        )
        staking_response, err_msg = await subtensor.sign_and_send_extrinsic(
            call, wallet, wait_for_inclusion, wait_for_finalization
        )
    if staking_response is True:  # If we successfully staked.
        # We only wait here if we expect finalization.
        if not wait_for_finalization and not wait_for_inclusion:
            return True

        console.print(":white_heavy_check_mark: [green]Finalized[/green]")
        with console.status(
            f":satellite: Checking Balance on: [white]{subtensor}[/white] ..."
        ):
            new_block_hash = await subtensor.substrate.get_chain_head()
            new_balance, new_stake = await asyncio.gather(
                subtensor.get_balance(
                    wallet.coldkeypub.ss58_address, block_hash=new_block_hash
                ),
                subtensor.get_stake_for_coldkey_and_hotkey(
                    coldkey_ss58=wallet.coldkeypub.ss58_address,
                    hotkey_ss58=hotkey_ss58,
                    block_hash=new_block_hash,
                ),
            )

            console.print(
                f"Balance:\n"
                f"\t[blue]{old_balance}[/blue] :arrow_right: "
                f"[green]{new_balance[wallet.coldkeypub.ss58_address]}[/green]"
            )
            console.print(
                f"Stake:\n"
                f"\t[blue]{old_stake}[/blue] :arrow_right: [green]{new_stake}[/green]"
            )
            return True
    else:
        err_console.print(f":cross_mark: [red]Failed[/red]: {err_msg}")
        return False


async def add_stake_multiple_extrinsic(
    subtensor: "SubtensorInterface",
    wallet: Wallet,
    old_balance: Balance,
    hotkey_ss58s: list[str],
    amounts: Optional[list[Balance]] = None,
    wait_for_inclusion: bool = True,
    wait_for_finalization: bool = False,
    prompt: bool = False,
) -> bool:
    """Adds stake to each ``hotkey_ss58`` in the list, using each amount, from a common coldkey.

    :param subtensor: The initialized SubtensorInterface object.
    :param wallet: Bittensor wallet object for the coldkey.
    :param old_balance: The balance of the wallet prior to staking.
    :param hotkey_ss58s: List of hotkeys to stake to.
    :param amounts: List of amounts to stake. If `None`, stake all to the first hotkey.
    :param wait_for_inclusion: If set, waits for the extrinsic to enter a block before returning `True`, or returns
                               `False` if the extrinsic fails to enter the block within the timeout.
    :param wait_for_finalization: If set, waits for the extrinsic to be finalized on the chain before returning `True`,
                                  or returns `False` if the extrinsic fails to be finalized within the timeout.
    :param prompt: If `True`, the call waits for confirmation from the user before proceeding.

    :return: success: `True` if extrinsic was finalized or included in the block. `True` if any wallet was staked. If
                      we did not wait for finalization/inclusion, the response is `True`.
    """

    if len(hotkey_ss58s) == 0:
        return True

    if amounts is not None and len(amounts) != len(hotkey_ss58s):
        raise ValueError("amounts must be a list of the same length as hotkey_ss58s")

    new_amounts: Sequence[Optional[Balance]]
    if amounts is None:
        new_amounts = [None] * len(hotkey_ss58s)
    else:
        new_amounts = [Balance.from_tao(amount) for amount in amounts]
        if sum(amount.tao for amount in new_amounts) == 0:
            # Staking 0 tao
            return True

    # Decrypt coldkey.
    try:
        wallet.unlock_coldkey()
    except KeyFileError:
        err_console.print("Error decrypting coldkey (possibly incorrect password)")
        return False

    with console.status(
        f":satellite: Syncing with chain: [white]{subtensor}[/white] ..."
    ):
        block_hash = await subtensor.substrate.get_chain_head()
        old_stakes = await asyncio.gather(
            *[
                subtensor.get_stake_for_coldkey_and_hotkey(
                    hk, wallet.coldkeypub.ss58_address, block_hash=block_hash
                )
                for hk in hotkey_ss58s
            ]
        )

    # Remove existential balance to keep key alive.
    ## Keys must maintain a balance of at least 1000 rao to stay alive.
    total_staking_rao = sum(
        [amount.rao if amount is not None else 0 for amount in new_amounts]
    )
    if total_staking_rao == 0:
        # Staking all to the first wallet.
        if old_balance.rao > 1000:
            old_balance -= Balance.from_rao(1000)

    elif total_staking_rao < 1000:
        # Staking less than 1000 rao to the wallets.
        pass
    else:
        # Staking more than 1000 rao to the wallets.
        ## Reduce the amount to stake to each wallet to keep the balance above 1000 rao.
        percent_reduction = 1 - (1000 / total_staking_rao)
        new_amounts = [
            Balance.from_tao(amount.tao * percent_reduction)
            for amount in cast(Sequence[Balance], new_amounts)
        ]

    successful_stakes = 0
    for idx, (hotkey_ss58, amount, old_stake) in enumerate(
        zip(hotkey_ss58s, new_amounts, old_stakes)
    ):
        staking_all = False
        # Convert to bittensor.Balance
        if amount is None:
            # Stake it all.
            staking_balance = Balance.from_tao(old_balance.tao)
            staking_all = True
        else:
            # Amounts are cast to balance earlier in the function
            assert isinstance(amount, Balance)
            staking_balance = amount

        # Check enough to stake
        if staking_balance > old_balance:
            err_console.print(
                f":cross_mark: [red]Not enough balance[/red]:"
                f" [green]{old_balance}[/green] to stake: [blue]{staking_balance}[/blue]"
                f" from coldkey: [white]{wallet.name}[/white]"
            )
            continue

        # Ask before moving on.
        if prompt:
            if not Confirm.ask(
                f"Do you want to stake:\n"
                f"\t[bold white]amount: {staking_balance}\n"
                f"\thotkey: {wallet.hotkey_str}[/bold white ]?"
            ):
                continue

        call = await subtensor.substrate.compose_call(
            call_module="SubtensorModule",
            call_function="add_stake",
            call_params={"hotkey": hotkey_ss58, "amount_staked": staking_balance.rao},
        )
        staking_response, err_msg = await subtensor.sign_and_send_extrinsic(
            call, wallet, wait_for_inclusion, wait_for_finalization
        )

        if staking_response is True:  # If we successfully staked.
            # We only wait here if we expect finalization.

            if idx < len(hotkey_ss58s) - 1:
                # Wait for tx rate limit.
                tx_query = await subtensor.substrate.query(
                    module="SubtensorModule",
                    storage_function="TxRateLimit",
                    block_hash=block_hash,
                )
                tx_rate_limit_blocks: int = tx_query
                if tx_rate_limit_blocks > 0:
                    with console.status(
                        f":hourglass: [yellow]Waiting for tx rate limit:"
                        f" [white]{tx_rate_limit_blocks}[/white] blocks[/yellow]"
                    ):
                        await asyncio.sleep(
                            tx_rate_limit_blocks * 12
                        )  # 12 seconds per block

            if not wait_for_finalization and not wait_for_inclusion:
                old_balance -= staking_balance
                successful_stakes += 1
                if staking_all:
                    # If staked all, no need to continue
                    break

                continue

            console.print(":white_heavy_check_mark: [green]Finalized[/green]")

            new_block_hash = await subtensor.substrate.get_chain_head()
            new_stake, new_balance_ = await asyncio.gather(
                subtensor.get_stake_for_coldkey_and_hotkey(
                    coldkey_ss58=wallet.coldkeypub.ss58_address,
                    hotkey_ss58=hotkey_ss58,
                    block_hash=new_block_hash,
                ),
                subtensor.get_balance(
                    wallet.coldkeypub.ss58_address, block_hash=new_block_hash
                ),
            )
            new_balance = new_balance_[wallet.coldkeypub.ss58_address]
            console.print(
                "Stake ({}): [blue]{}[/blue] :arrow_right: [green]{}[/green]".format(
                    hotkey_ss58, old_stake, new_stake
                )
            )
            old_balance = new_balance
            successful_stakes += 1
            if staking_all:
                # If staked all, no need to continue
                break

        else:
            err_console.print(f":cross_mark: [red]Failed[/red]: {err_msg}")
            continue

    if successful_stakes != 0:
        with console.status(
            f":satellite: Checking Balance on: ([white]{subtensor}[/white] ..."
        ):
            new_balance_ = await subtensor.get_balance(
                wallet.coldkeypub.ss58_address, reuse_block=False
            )
            new_balance = new_balance_[wallet.coldkeypub.ss58_address]
        console.print(
            f"Balance: [blue]{old_balance}[/blue] :arrow_right: [green]{new_balance}[/green]"
        )
        return True

    return False


async def unstake_extrinsic(
    subtensor: "SubtensorInterface",
    wallet: Wallet,
    hotkey_ss58: Optional[str] = None,
    amount: Optional[Balance] = None,
    wait_for_inclusion: bool = True,
    wait_for_finalization: bool = False,
    prompt: bool = False,
) -> bool:
    """Removes stake into the wallet coldkey from the specified hotkey ``uid``.

    :param subtensor: the initialized SubtensorInterface object to use
    :param wallet: Bittensor wallet object.
    :param hotkey_ss58: The `ss58` address of the hotkey to unstake from. By default, the wallet hotkey is used.
    :param amount: Amount to stake as Bittensor balance, or `None` is unstaking all
    :param wait_for_inclusion: If set, waits for the extrinsic to enter a block before returning `True`, or returns
                               `False` if the extrinsic fails to enter the block within the timeout.
    :param wait_for_finalization: If set, waits for the extrinsic to be finalized on the chain before returning `True`,
                                  or returns `False` if the extrinsic fails to be finalized within the timeout.
    :param prompt: If `True`, the call waits for confirmation from the user before proceeding.

    :return: success: `True` if extrinsic was finalized or included in the block. If we did not wait for
                      finalization/inclusion, the response is `True`.
    """
    # Decrypt keys,
    try:
        wallet.unlock_coldkey()
    except KeyFileError:
        err_console.print("Error decrypting coldkey (possibly incorrect password)")
        return False

    if hotkey_ss58 is None:
        hotkey_ss58 = wallet.hotkey.ss58_address  # Default to wallet's own hotkey.

    with console.status(
        f":satellite: Syncing with chain: [white]{subtensor}[/white] ...",
        spinner="aesthetic",
    ) as status:
        print_verbose("Fetching balance and stake", status)
        block_hash = await subtensor.substrate.get_chain_head()
        old_balance, old_stake, hotkey_owner = await asyncio.gather(
            subtensor.get_balance(
                wallet.coldkeypub.ss58_address, block_hash=block_hash
            ),
            subtensor.get_stake_for_coldkey_and_hotkey(
                coldkey_ss58=wallet.coldkeypub.ss58_address,
                hotkey_ss58=hotkey_ss58,
                block_hash=block_hash,
            ),
            subtensor.get_hotkey_owner(hotkey_ss58, block_hash),
        )

        own_hotkey: bool = wallet.coldkeypub.ss58_address == hotkey_owner

    # Convert to bittensor.Balance
    if amount is None:
        # Unstake it all.
        unstaking_balance = old_stake
    else:
        unstaking_balance = Balance.from_tao(amount)

    # Check enough to unstake.
    stake_on_uid = old_stake
    if unstaking_balance > stake_on_uid:
        err_console.print(
            f":cross_mark: [red]Not enough stake[/red]: "
            f"[green]{stake_on_uid}[/green] to unstake: "
            f"[blue]{unstaking_balance}[/blue] from hotkey:"
            f" [white]{wallet.hotkey_str}[/white]"
        )
        return False

    print_verbose("Fetching threshold amount")
    # If nomination stake, check threshold.
    if not own_hotkey and not await _check_threshold_amount(
        subtensor=subtensor,
        sb=(stake_on_uid - unstaking_balance),
        block_hash=block_hash,
    ):
        console.print(
            ":warning: [yellow]This action will unstake the entire staked balance![/yellow]"
        )
        unstaking_balance = stake_on_uid

    # Ask before moving on.
    if prompt:
        if not Confirm.ask(
            f"Do you want to unstake:\n"
            f"[bold white]\tamount: {unstaking_balance}\n"
            f"\thotkey: {wallet.hotkey_str}[/bold white ]?"
        ):
            return False

    with console.status(
        f":satellite: Unstaking from chain: [white]{subtensor}[/white] ...",
        spinner="earth",
    ):
        call = await subtensor.substrate.compose_call(
            call_module="SubtensorModule",
            call_function="remove_stake",
            call_params={
                "hotkey": hotkey_ss58,
                "amount_unstaked": unstaking_balance.rao,
            },
        )
        staking_response, err_msg = await subtensor.sign_and_send_extrinsic(
            call, wallet, wait_for_inclusion, wait_for_finalization
        )

    if staking_response is True:  # If we successfully unstaked.
        # We only wait here if we expect finalization.
        if not wait_for_finalization and not wait_for_inclusion:
            return True

        console.print(":white_heavy_check_mark: [green]Finalized[/green]")
        with console.status(
            f":satellite: Checking Balance on: [white]{subtensor}[/white] ..."
        ):
            new_block_hash = await subtensor.substrate.get_chain_head()
            new_balance, new_stake = await asyncio.gather(
                subtensor.get_balance(
                    wallet.coldkeypub.ss58_address, block_hash=new_block_hash
                ),
                subtensor.get_stake_for_coldkey_and_hotkey(
                    hotkey_ss58, wallet.coldkeypub.ss58_address, new_block_hash
                ),
            )
            console.print(
                f"Balance:\n"
                f"  [blue]{old_balance[wallet.coldkeypub.ss58_address]}[/blue] :arrow_right:"
                f" [green]{new_balance[wallet.coldkeypub.ss58_address]}[/green]"
            )
            console.print(
                f"Stake:\n  [blue]{old_stake}[/blue] :arrow_right: [green]{new_stake}[/green]"
            )
            return True
    else:
        err_console.print(f":cross_mark: [red]Failed[/red]: {err_msg}")
        return False


async def unstake_multiple_extrinsic(
    subtensor: "SubtensorInterface",
    wallet: Wallet,
    hotkey_ss58s: list[str],
    amounts: Optional[list[Union[Balance, float]]] = None,
    wait_for_inclusion: bool = True,
    wait_for_finalization: bool = False,
    prompt: bool = False,
) -> bool:
    """
    Removes stake from each `hotkey_ss58` in the list, using each amount, to a common coldkey.

    :param subtensor: the initialized SubtensorInterface object to use
    :param wallet: The wallet with the coldkey to unstake to.
    :param hotkey_ss58s: List of hotkeys to unstake from.
    :param amounts: List of amounts to unstake. If ``None``, unstake all.
    :param wait_for_inclusion: If set, waits for the extrinsic to enter a block before returning `True`, or returns
                              `False` if the extrinsic fails to enter the block within the timeout.
    :param wait_for_finalization: If set, waits for the extrinsic to be finalized on the chain before returning `True`,
                                  or returns `False` if the extrinsic fails to be finalized within the timeout.
    :param prompt: If `True`, the call waits for confirmation from the user before proceeding.

    :return: success: `True` if extrinsic was finalized or included in the block. Flag is `True` if any wallet was
                      unstaked. If we did not wait for finalization/inclusion, the response is `True`.
    """
    if not isinstance(hotkey_ss58s, list) or not all(
        isinstance(hotkey_ss58, str) for hotkey_ss58 in hotkey_ss58s
    ):
        raise TypeError("hotkey_ss58s must be a list of str")

    if len(hotkey_ss58s) == 0:
        return True

    if amounts is not None and len(amounts) != len(hotkey_ss58s):
        raise ValueError("amounts must be a list of the same length as hotkey_ss58s")

    if amounts is not None and not all(
        isinstance(amount, (Balance, float)) for amount in amounts
    ):
        raise TypeError(
            "amounts must be a [list of bittensor.Balance or float] or None"
        )

    new_amounts: Sequence[Optional[Balance]]
    if amounts is None:
        new_amounts = [None] * len(hotkey_ss58s)
    else:
        new_amounts = [
            Balance(amount) if not isinstance(amount, Balance) else amount
            for amount in (amounts or [None] * len(hotkey_ss58s))
        ]
        if sum(amount.tao for amount in new_amounts if amount is not None) == 0:
            return True

    # Unlock coldkey.
    try:
        wallet.unlock_coldkey()
    except KeyFileError:
        err_console.print("Error decrypting coldkey (possibly incorrect password)")
        return False

    with console.status(
        f":satellite: Syncing with chain: [white]{subtensor}[/white] ..."
    ):
        block_hash = await subtensor.substrate.get_chain_head()

        old_balance_ = subtensor.get_balance(
            wallet.coldkeypub.ss58_address, block_hash=block_hash
        )
        old_stakes_ = asyncio.gather(
            *[
                subtensor.get_stake_for_coldkey_and_hotkey(
                    h, wallet.coldkeypub.ss58_address, block_hash
                )
                for h in hotkey_ss58s
            ]
        )
        hotkey_owners_ = asyncio.gather(
            *[subtensor.get_hotkey_owner(h, block_hash) for h in hotkey_ss58s]
        )

        old_balance, old_stakes, hotkey_owners, threshold = await asyncio.gather(
            old_balance_,
            old_stakes_,
            hotkey_owners_,
            _get_threshold_amount(subtensor, block_hash),
        )
        own_hotkeys = [
            wallet.coldkeypub.ss58_address == hotkey_owner
            for hotkey_owner in hotkey_owners
        ]

    successful_unstakes = 0
    for idx, (hotkey_ss58, amount, old_stake, own_hotkey) in enumerate(
        zip(hotkey_ss58s, new_amounts, old_stakes, own_hotkeys)
    ):
        # Covert to bittensor.Balance
        if amount is None:
            # Unstake it all.
            unstaking_balance = old_stake
        else:
            unstaking_balance = amount

        # Check enough to unstake.
        stake_on_uid = old_stake
        if unstaking_balance > stake_on_uid:
            err_console.print(
                f":cross_mark: [red]Not enough stake[/red]:"
                f" [green]{stake_on_uid}[/green] to unstake:"
                f" [blue]{unstaking_balance}[/blue] from hotkey:"
                f" [white]{wallet.hotkey_str}[/white]"
            )
            continue

        # If nomination stake, check threshold.
        if (
            not own_hotkey
            and (
                await _check_threshold_amount(
                    subtensor=subtensor,
                    sb=(stake_on_uid - unstaking_balance),
                    block_hash=block_hash,
                    min_req_stake=threshold,
                )
            )[0]
            is False
        ):
            console.print(
                ":warning: [yellow]This action will unstake the entire staked balance![/yellow]"
            )
            unstaking_balance = stake_on_uid

        # Ask before moving on.
        if prompt:
            if not Confirm.ask(
                f"Do you want to unstake:\n"
                f"[bold white]\tamount: {unstaking_balance}\n"
                f"ss58: {hotkey_ss58}[/bold white ]?"
            ):
                continue

        with console.status(
            f":satellite: Unstaking from chain: [white]{subtensor}[/white] ..."
        ):
            call = await subtensor.substrate.compose_call(
                call_module="SubtensorModule",
                call_function="remove_stake",
                call_params={
                    "hotkey": hotkey_ss58,
                    "amount_unstaked": unstaking_balance.rao,
                },
            )
            staking_response, err_msg = await subtensor.sign_and_send_extrinsic(
                call, wallet, wait_for_inclusion, wait_for_finalization
            )

        if staking_response is True:  # If we successfully unstaked.
            # We only wait here if we expect finalization.

            if idx < len(hotkey_ss58s) - 1:
                # Wait for tx rate limit.
                tx_query = await subtensor.substrate.query(
                    module="SubtensorModule",
                    storage_function="TxRateLimit",
                    block_hash=block_hash,
                )
                tx_rate_limit_blocks: int = tx_query

                # TODO: Handle in-case we have fast blocks
                if tx_rate_limit_blocks > 0:
                    console.print(
                        ":hourglass: [yellow]Waiting for tx rate limit:"
                        f" [white]{tx_rate_limit_blocks}[/white] blocks,"
                        f" estimated time: [white]{tx_rate_limit_blocks * 12} [/white] seconds[/yellow]"
                    )
                    await asyncio.sleep(
                        tx_rate_limit_blocks * 12
                    )  # 12 seconds per block

            if not wait_for_finalization and not wait_for_inclusion:
                successful_unstakes += 1
                continue

            console.print(":white_heavy_check_mark: [green]Finalized[/green]")
            with console.status(
                f":satellite: Checking stake balance on: [white]{subtensor}[/white] ..."
            ):
                new_stake = await subtensor.get_stake_for_coldkey_and_hotkey(
                    coldkey_ss58=wallet.coldkeypub.ss58_address,
                    hotkey_ss58=hotkey_ss58,
                    block_hash=(await subtensor.substrate.get_chain_head()),
                )
                console.print(
                    "Stake ({}): [blue]{}[/blue] :arrow_right: [green]{}[/green]".format(
                        hotkey_ss58, stake_on_uid, new_stake
                    )
                )
                successful_unstakes += 1
        else:
            err_console.print(":cross_mark: [red]Failed[/red]: Unknown Error.")
            continue

    if successful_unstakes != 0:
        with console.status(
            f":satellite: Checking balance on: ([white]{subtensor}[/white] ..."
        ):
            new_balance = await subtensor.get_balance(wallet.coldkeypub.ss58_address)
        console.print(
            f"Balance: [blue]{old_balance[wallet.coldkeypub.ss58_address]}[/blue]"
            f" :arrow_right: [green]{new_balance[wallet.coldkeypub.ss58_address]}[/green]"
        )
        return True

    return False


# Commands


async def show(
    wallet: Wallet,
    subtensor: Optional["SubtensorInterface"],
    all_wallets: bool,
    reuse_last: bool,
    html_output: bool,
    no_cache: bool,
):
    """Show all stake accounts."""

    async def get_stake_accounts(
        wallet_, block_hash: str
    ) -> dict[str, Union[str, Balance, dict[str, Union[str, Balance]]]]:
        """Get stake account details for the given wallet.

        :param wallet_: The wallet object to fetch the stake account details for.

        :return: A dictionary mapping SS58 addresses to their respective stake account details.
        """

        wallet_stake_accounts = {}

        # Get this wallet's coldkey balance.
        cold_balance_, stakes_from_hk, stakes_from_d = await asyncio.gather(
            subtensor.get_balance(
                wallet_.coldkeypub.ss58_address, block_hash=block_hash
            ),
            get_stakes_from_hotkeys(wallet_, block_hash=block_hash),
            get_stakes_from_delegates(wallet_),
        )

        cold_balance = cold_balance_[wallet_.coldkeypub.ss58_address]

        # Populate the stake accounts with local hotkeys data.
        wallet_stake_accounts.update(stakes_from_hk)

        # Populate the stake accounts with delegations data.
        wallet_stake_accounts.update(stakes_from_d)

        return {
            "name": wallet_.name,
            "balance": cold_balance,
            "accounts": wallet_stake_accounts,
        }

    async def get_stakes_from_hotkeys(
        wallet_, block_hash: str
    ) -> dict[str, dict[str, Union[str, Balance]]]:
        """Fetch stakes from hotkeys for the provided wallet.

        :param wallet_: The wallet object to fetch the stakes for.

        :return: A dictionary of stakes related to hotkeys.
        """

        async def get_all_neurons_for_pubkey(hk):
            netuids = await subtensor.get_netuids_for_hotkey(hk, block_hash=block_hash)
            uid_query = await asyncio.gather(
                *[
                    subtensor.substrate.query(
                        module="SubtensorModule",
                        storage_function="Uids",
                        params=[netuid, hk],
                        block_hash=block_hash,
                    )
                    for netuid in netuids
                ]
            )
            uids = [_result for _result in uid_query]
            neurons = await asyncio.gather(
                *[
                    subtensor.neuron_for_uid(uid, net)
                    for (uid, net) in zip(uids, netuids)
                ]
            )
            return neurons

        async def get_emissions_and_stake(hk: str):
            neurons, stake = await asyncio.gather(
                get_all_neurons_for_pubkey(hk),
                subtensor.substrate.query(
                    module="SubtensorModule",
                    storage_function="Stake",
                    params=[hk, wallet_.coldkeypub.ss58_address],
                    block_hash=block_hash,
                ),
            )
            emission_ = sum([n.emission for n in neurons]) if neurons else 0.0
            return emission_, Balance.from_rao(stake) if stake else Balance(0)

        hotkeys = cast(list[Wallet], get_hotkey_wallets_for_wallet(wallet_))
        stakes = {}
        query = await asyncio.gather(
            *[get_emissions_and_stake(hot.hotkey.ss58_address) for hot in hotkeys]
        )
        for hot, (emission, hotkey_stake) in zip(hotkeys, query):
            stakes[hot.hotkey.ss58_address] = {
                "name": hot.hotkey_str,
                "stake": hotkey_stake,
                "rate": emission,
            }
        return stakes

    async def get_stakes_from_delegates(
        wallet_,
    ) -> dict[str, dict[str, Union[str, Balance]]]:
        """Fetch stakes from delegates for the provided wallet.

        :param wallet_: The wallet object to fetch the stakes for.

        :return: A dictionary of stakes related to delegates.
        """
        delegates = await subtensor.get_delegated(
            coldkey_ss58=wallet_.coldkeypub.ss58_address, block_hash=None
        )
        stakes = {}
        for dele, staked in delegates:
            for nom in dele.nominators:
                if nom[0] == wallet_.coldkeypub.ss58_address:
                    delegate_name = (
                        registered_delegate_info[dele.hotkey_ss58].display
                        if dele.hotkey_ss58 in registered_delegate_info
                        else None
                    )
                    stakes[dele.hotkey_ss58] = {
                        "name": delegate_name if delegate_name else dele.hotkey_ss58,
                        "stake": nom[1],
                        "rate": dele.total_daily_return.tao
                        * (nom[1] / dele.total_stake.tao),
                    }
        return stakes

    async def get_all_wallet_accounts(
        block_hash: str,
    ) -> list[dict[str, Union[str, Balance, dict[str, Union[str, Balance]]]]]:
        """Fetch stake accounts for all provided wallets using a ThreadPool.

        :param block_hash: The block hash to fetch the stake accounts for.

        :return: A list of dictionaries, each dictionary containing stake account details for each wallet.
        """

        accounts_ = await asyncio.gather(
            *[get_stake_accounts(w, block_hash=block_hash) for w in wallets]
        )
        return accounts_

    if not reuse_last:
        cast("SubtensorInterface", subtensor)
        if all_wallets:
            wallets = get_coldkey_wallets_for_path(wallet.path)
            valid_wallets, invalid_wallets = validate_coldkey_presence(wallets)
            wallets = valid_wallets
            for invalid_wallet in invalid_wallets:
                print_error(f"No coldkeypub found for wallet: ({invalid_wallet.name})")
        else:
            wallets = [wallet]

        with console.status(
            ":satellite: Retrieving account data...", spinner="aesthetic"
        ):
            block_hash_ = await subtensor.substrate.get_chain_head()
            registered_delegate_info = await subtensor.get_delegate_identities(
                block_hash=block_hash_
            )
            accounts = await get_all_wallet_accounts(block_hash=block_hash_)

        total_stake: float = 0.0
        total_balance: float = 0.0
        total_rate: float = 0.0
        rows = []
        db_rows = []
        for acc in accounts:
            cast(str, acc["name"])
            cast(Balance, acc["balance"])
            rows.append([acc["name"], str(acc["balance"]), "", "", ""])
            db_rows.append(
                [acc["name"], float(acc["balance"]), None, None, None, None, 0]
            )
            total_balance += cast(Balance, acc["balance"]).tao
            for key, value in cast(dict, acc["accounts"]).items():
                if value["name"] and value["name"] != key:
                    account_display_name = f"{value['name']}"
                else:
                    account_display_name = "(~)"
                rows.append(
                    [
                        "",
                        "",
                        account_display_name,
                        key,
                        str(value["stake"]),
                        str(value["rate"]),
                    ]
                )
                db_rows.append(
                    [
                        acc["name"],
                        None,
                        value["name"],
                        float(value["stake"]),
                        float(value["rate"]),
                        key,
                        1,
                    ]
                )
                total_stake += cast(Balance, value["stake"]).tao
                total_rate += float(value["rate"])
        metadata = {
            "total_stake": "\u03c4{:.5f}".format(total_stake),
            "total_balance": "\u03c4{:.5f}".format(total_balance),
            "total_rate": "\u03c4{:.5f}/d".format(total_rate),
            "rows": json.dumps(rows),
        }
        if not no_cache:
            create_table(
                "stakeshow",
                [
                    ("COLDKEY", "TEXT"),
                    ("BALANCE", "REAL"),
                    ("ACCOUNT", "TEXT"),
                    ("STAKE", "REAL"),
                    ("RATE", "REAL"),
                    ("HOTKEY", "TEXT"),
                    ("CHILD", "INTEGER"),
                ],
                db_rows,
            )
            update_metadata_table("stakeshow", metadata)
    else:
        try:
            metadata = get_metadata_table("stakeshow")
            rows = json.loads(metadata["rows"])
        except sqlite3.OperationalError:
            err_console.print(
                "[red]Error[/red] Unable to retrieve table data. This is usually caused by attempting to use "
                "`--reuse-last` before running the command a first time. In rare cases, this could also be due to "
                "a corrupted database. Re-run the command (do not use `--reuse-last`) and see if that resolves your "
                "issue."
            )
            return
    if not html_output:
        table = Table(
            Column("[bold white]Coldkey", style="dark_orange", ratio=1),
            Column(
                "[bold white]Balance",
                metadata["total_balance"],
                style="dark_sea_green",
                ratio=1,
            ),
            Column("[bold white]Account", style="bright_cyan", ratio=3),
            Column("[bold white]Hotkey", ratio=7, no_wrap=True, style="bright_magenta"),
            Column(
                "[bold white]Stake",
                metadata["total_stake"],
                style="light_goldenrod2",
                ratio=1,
            ),
            Column(
                "[bold white]Rate /d",
                metadata["total_rate"],
                style="rgb(42,161,152)",
                ratio=1,
            ),
            title=f"[underline dark_orange]Stake Show[/underline dark_orange]\n[dark_orange]Network: {subtensor.network}\n",
            show_footer=True,
            show_edge=False,
            expand=False,
            border_style="bright_black",
        )

        for i, row in enumerate(rows):
            is_last_row = i + 1 == len(rows)
            table.add_row(*row)

            # If last row or new coldkey starting next
            if is_last_row or (rows[i + 1][0] != ""):
                table.add_row(end_section=True)
        console.print(table)

    else:
        render_tree(
            "stakeshow",
            f"Stakes | Total Balance: {metadata['total_balance']} - Total Stake: {metadata['total_stake']} "
            f"Total Rate: {metadata['total_rate']}",
            [
                {"title": "Coldkey", "field": "COLDKEY"},
                {
                    "title": "Balance",
                    "field": "BALANCE",
                    "formatter": "money",
                    "formatterParams": {"symbol": "τ", "precision": 5},
                },
                {
                    "title": "Account",
                    "field": "ACCOUNT",
                    "width": 425,
                },
                {
                    "title": "Stake",
                    "field": "STAKE",
                    "formatter": "money",
                    "formatterParams": {"symbol": "τ", "precision": 5},
                },
                {
                    "title": "Daily Rate",
                    "field": "RATE",
                    "formatter": "money",
                    "formatterParams": {"symbol": "τ", "precision": 5},
                },
                {
                    "title": "Hotkey",
                    "field": "HOTKEY",
                    "width": 425,
                },
            ],
            0,
        )


async def stake_add(
    wallet: Wallet,
    subtensor: "SubtensorInterface",
    amount: float,
    stake_all: bool,
    max_stake: float,
    include_hotkeys: list[str],
    exclude_hotkeys: list[str],
    all_hotkeys: bool,
    prompt: bool,
    hotkey_ss58: Optional[str] = None,
) -> None:
    """Stake token of amount to hotkey(s)."""

    async def is_hotkey_registered_any(hk: str, bh: str) -> bool:
        return len(await subtensor.get_netuids_for_hotkey(hk, bh)) > 0

    # Get the hotkey_names (if any) and the hotkey_ss58s.
    hotkeys_to_stake_to: list[tuple[Optional[str], str]] = []
    if hotkey_ss58:
        if not is_valid_ss58_address(hotkey_ss58):
            print_error("The entered ss58 address is incorrect")
            typer.Exit()

        # Stake to specific hotkey.
        hotkeys_to_stake_to = [(None, hotkey_ss58)]
    elif all_hotkeys:
        # Stake to all hotkeys.
        all_hotkeys_: list[Wallet] = get_hotkey_wallets_for_wallet(wallet=wallet)
        # Get the hotkeys to exclude. (d)efault to no exclusions.
        # Exclude hotkeys that are specified.
        hotkeys_to_stake_to = [
            (wallet.hotkey_str, wallet.hotkey.ss58_address)
            for wallet in all_hotkeys_
            if wallet.hotkey_str not in exclude_hotkeys
            and wallet.hotkey.ss58_address not in exclude_hotkeys
        ]  # definitely wallets

    elif include_hotkeys:
        print_verbose("Staking to only included hotkeys")
        # Stake to specific hotkeys.
        for hotkey_ss58_or_hotkey_name in include_hotkeys:
            if is_valid_ss58_address(hotkey_ss58_or_hotkey_name):
                # If the hotkey is a valid ss58 address, we add it to the list.
                hotkeys_to_stake_to.append((None, hotkey_ss58_or_hotkey_name))
            else:
                # If the hotkey is not a valid ss58 address, we assume it is a hotkey name.
                #  We then get the hotkey from the wallet and add it to the list.
                wallet_ = Wallet(
                    path=wallet.path,
                    name=wallet.name,
                    hotkey=hotkey_ss58_or_hotkey_name,
                )
                hotkeys_to_stake_to.append(
                    (wallet_.hotkey_str, wallet_.hotkey.ss58_address)
                )
    else:
        # Only config.wallet.hotkey is specified.
        #  so we stake to that single hotkey.
        print_verbose(
            f"Staking to hotkey: ({wallet.hotkey_str}) in wallet: ({wallet.name})"
        )
        assert wallet.hotkey is not None
        hotkey_ss58_or_name = wallet.hotkey.ss58_address
        hotkeys_to_stake_to = [(None, hotkey_ss58_or_name)]

    try:
        # Get coldkey balance
        print_verbose("Fetching coldkey balance")
        wallet_balance_: dict[str, Balance] = await subtensor.get_balance(
            wallet.coldkeypub.ss58_address
        )
        block_hash = subtensor.substrate.last_block_hash
        wallet_balance: Balance = wallet_balance_[wallet.coldkeypub.ss58_address]
        old_balance = copy.copy(wallet_balance)
        final_hotkeys: list[tuple[Optional[str], str]] = []
        final_amounts: list[Union[float, Balance]] = []
        hotkey: tuple[Optional[str], str]  # (hotkey_name (or None), hotkey_ss58)

        print_verbose("Checking if hotkeys are registered")
        registered_ = asyncio.gather(
            *[is_hotkey_registered_any(h[1], block_hash) for h in hotkeys_to_stake_to]
        )
        if max_stake:
            hotkey_stakes_ = asyncio.gather(
                *[
                    subtensor.get_stake_for_coldkey_and_hotkey(
                        hotkey_ss58=h[1],
                        coldkey_ss58=wallet.coldkeypub.ss58_address,
                        block_hash=block_hash,
                    )
                    for h in hotkeys_to_stake_to
                ]
            )
        else:

            async def null():
                return [None] * len(hotkeys_to_stake_to)

            hotkey_stakes_ = null()
        registered: list[bool]
        hotkey_stakes: list[Optional[Balance]]
        registered, hotkey_stakes = await asyncio.gather(registered_, hotkey_stakes_)

        for hotkey, reg, hotkey_stake in zip(
            hotkeys_to_stake_to, registered, hotkey_stakes
        ):
            if not reg:
                # Hotkey is not registered.
                if len(hotkeys_to_stake_to) == 1:
                    # Only one hotkey, error
                    err_console.print(
                        f"[red]Hotkey [bold]{hotkey[1]}[/bold] is not registered. Aborting.[/red]"
                    )
                    raise ValueError
                else:
                    # Otherwise, print warning and skip
                    console.print(
                        f"[yellow]Hotkey [bold]{hotkey[1]}[/bold] is not registered. Skipping.[/yellow]"
                    )
                    continue

            stake_amount_tao: float = amount
            if max_stake:
                stake_amount_tao = max_stake - hotkey_stake.tao

                # If the max_stake is greater than the current wallet balance, stake the entire balance.
                stake_amount_tao = min(stake_amount_tao, wallet_balance.tao)
                if (
                    stake_amount_tao <= 0.00001
                ):  # Threshold because of fees, might create a loop otherwise
                    # Skip hotkey if max_stake is less than current stake.
                    continue
                wallet_balance = Balance.from_tao(wallet_balance.tao - stake_amount_tao)

                if wallet_balance.tao < 0:
                    # No more balance to stake.
                    break

            final_amounts.append(stake_amount_tao)
            final_hotkeys.append(hotkey)  # add both the name and the ss58 address.

        if len(final_hotkeys) == 0:
            # No hotkeys to stake to.
            err_console.print(
                "Not enough balance to stake to any hotkeys or max_stake is less than current stake."
            )
            raise ValueError

        if len(final_hotkeys) == 1:
            # do regular stake
            await add_stake_extrinsic(
                subtensor,
                wallet=wallet,
                old_balance=old_balance,
                hotkey_ss58=final_hotkeys[0][1],
                amount=None if stake_all else final_amounts[0],
                wait_for_inclusion=True,
                prompt=prompt,
            )
        else:
            await add_stake_multiple_extrinsic(
                subtensor,
                wallet=wallet,
                old_balance=old_balance,
                hotkey_ss58s=[hotkey_ss58 for _, hotkey_ss58 in final_hotkeys],
                amounts=None if stake_all else final_amounts,
                wait_for_inclusion=True,
                prompt=prompt,
            )
    except ValueError:
        pass


async def unstake(
    wallet: Wallet,
    subtensor: "SubtensorInterface",
    hotkey_ss58_address: str,
    all_hotkeys: bool,
    include_hotkeys: list[str],
    exclude_hotkeys: list[str],
    amount: float,
    keep_stake: float,
    unstake_all: bool,
    prompt: bool,
):
    """Unstake token of amount from hotkey(s)."""

    # Get the hotkey_names (if any) and the hotkey_ss58s.
    hotkeys_to_unstake_from: list[tuple[Optional[str], str]] = []
    if hotkey_ss58_address:
        print_verbose(f"Unstaking from ss58 ({hotkey_ss58_address})")
        # Unstake to specific hotkey.
        hotkeys_to_unstake_from = [(None, hotkey_ss58_address)]
    elif all_hotkeys:
        print_verbose("Unstaking from all hotkeys")
        # Unstake to all hotkeys.
        all_hotkeys_: list[Wallet] = get_hotkey_wallets_for_wallet(wallet=wallet)
        # Exclude hotkeys that are specified.
        hotkeys_to_unstake_from = [
            (wallet.hotkey_str, wallet.hotkey.ss58_address)
            for wallet in all_hotkeys_
            if wallet.hotkey_str not in exclude_hotkeys
            and wallet.hotkey.ss58_address not in hotkeys_to_unstake_from
        ]  # definitely wallets

    elif include_hotkeys:
        print_verbose("Unstaking from included hotkeys")
        # Unstake to specific hotkeys.
        for hotkey_ss58_or_hotkey_name in include_hotkeys:
            if is_valid_ss58_address(hotkey_ss58_or_hotkey_name):
                # If the hotkey is a valid ss58 address, we add it to the list.
                hotkeys_to_unstake_from.append((None, hotkey_ss58_or_hotkey_name))
            else:
                # If the hotkey is not a valid ss58 address, we assume it is a hotkey name.
                #  We then get the hotkey from the wallet and add it to the list.
                wallet_ = Wallet(
                    name=wallet.name,
                    path=wallet.path,
                    hotkey=hotkey_ss58_or_hotkey_name,
                )
                hotkeys_to_unstake_from.append(
                    (wallet_.hotkey_str, wallet_.hotkey.ss58_address)
                )
    else:
        # Only cli.config.wallet.hotkey is specified.
        #  so we stake to that single hotkey.
        print_verbose(
            f"Unstaking from wallet: ({wallet.name}) from hotkey: ({wallet.hotkey_str})"
        )
        assert wallet.hotkey is not None
        hotkeys_to_unstake_from = [(None, wallet.hotkey.ss58_address)]

    final_hotkeys: list[tuple[str, str]] = []
    final_amounts: list[Union[float, Balance]] = []
    hotkey: tuple[Optional[str], str]  # (hotkey_name (or None), hotkey_ss58)
    with suppress(ValueError):
        with console.status(
            f":satellite:Syncing with chain {subtensor}", spinner="earth"
        ) as status:
            print_verbose("Fetching stake", status)
            block_hash = await subtensor.substrate.get_chain_head()
            hotkey_stakes = await asyncio.gather(
                *[
                    subtensor.get_stake_for_coldkey_and_hotkey(
                        hotkey_ss58=hotkey[1],
                        coldkey_ss58=wallet.coldkeypub.ss58_address,
                        block_hash=block_hash,
                    )
                    for hotkey in hotkeys_to_unstake_from
                ]
            )
        for hotkey, hotkey_stake in zip(hotkeys_to_unstake_from, hotkey_stakes):
            unstake_amount_tao: float = amount

            if unstake_all:
                unstake_amount_tao = hotkey_stake.tao
            if keep_stake:
                # Get the current stake of the hotkey from this coldkey.
                unstake_amount_tao = hotkey_stake.tao - keep_stake
                amount = unstake_amount_tao
                if unstake_amount_tao < 0:
                    # Skip if max_stake is greater than current stake.
                    continue
            else:
                if unstake_amount_tao > hotkey_stake.tao:
                    # Skip if the specified amount is greater than the current stake.
                    continue

            final_amounts.append(unstake_amount_tao)
            final_hotkeys.append(hotkey)  # add both the name and the ss58 address.

        if len(final_hotkeys) == 0:
            # No hotkeys to unstake from.
            err_console.print(
                "Not enough stake to unstake from any hotkeys or max_stake is more than current stake."
            )
            return None

        # Ask to unstake
        if prompt:
            if not Confirm.ask(
                f"Do you want to unstake from the following keys to {wallet.name}:\n"
                + "".join(
                    [
                        f"    [bold white]- {hotkey[0] + ':' if hotkey[0] else ''}{hotkey[1]}: "
                        f"{f'{amount} {Balance.unit}' if amount else 'All'}[/bold white]\n"
                        for hotkey, amount in zip(final_hotkeys, final_amounts)
                    ]
                )
            ):
                return None
        if len(final_hotkeys) == 1:
            # do regular unstake
            await unstake_extrinsic(
                subtensor,
                wallet=wallet,
                hotkey_ss58=final_hotkeys[0][1],
                amount=None if unstake_all else final_amounts[0],
                wait_for_inclusion=True,
                prompt=prompt,
            )
        else:
            await unstake_multiple_extrinsic(
                subtensor,
                wallet=wallet,
                hotkey_ss58s=[hotkey_ss58 for _, hotkey_ss58 in final_hotkeys],
                amounts=None if unstake_all else final_amounts,
                wait_for_inclusion=True,
                prompt=prompt,
            )
