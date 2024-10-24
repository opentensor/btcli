import asyncio
import copy
import json
import sqlite3
from contextlib import suppress
from functools import partial

from typing import TYPE_CHECKING, Optional, Sequence, Union, cast

from bittensor_wallet import Wallet
from bittensor_wallet.errors import KeyFileError
from rich.prompt import Confirm, FloatPrompt, Prompt
from rich.table import Table, Column
import typer
from substrateinterface.exceptions import SubstrateRequestException

from bittensor_cli.src.bittensor.balances import Balance
from bittensor_cli.src.bittensor.chain_data import StakeInfo
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
    format_error_message,
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
async def stake_add(
    wallet: Wallet,
    subtensor: "SubtensorInterface",
    netuid: Optional[int],
    stake_all: bool,
    amount: float,
    delegate: bool,
    prompt: bool,
    max_stake: float,
    all_hotkeys: bool,
    include_hotkeys: list[str],
    exclude_hotkeys: list[str],
):
    """

    Args:
        wallet: wallet object
        subtensor: SubtensorInterface object
        netuid: the netuid to stake to (None indicates all subnets)
        stake_all: whether to stake all available balance
        amount: specified amount of balance to stake
        delegate: whether to delegate stake, currently unused
        prompt: whether to prompt the user
        max_stake: maximum amount to stake (used in combination with stake_all), currently unused
        all_hotkeys: whether to stake all hotkeys
        include_hotkeys: list of hotkeys to include in staking process (if not specifying `--all`)
        exclude_hotkeys: list of hotkeys to exclude in staking (if specifying `--all`)

    Returns:

    """
    netuids = (
        [netuid] if netuid is not None else await subtensor.get_all_subnet_netuids()
    )
    # Init the table.
    table = Table(
        title="[white]Staking operation from Coldkey SS58[/white]: "
        f"[bold dark_green]{wallet.coldkeypub.ss58_address}[/bold dark_green]\n",
        width=console.width - 5,
        safe_box=True,
        padding=(0, 1),
        collapse_padding=False,
        pad_edge=True,
        expand=True,
        show_header=True,
        show_footer=True,
        show_edge=False,
        show_lines=False,
        leading=0,
        style="none",
        row_styles=None,
        header_style="bold",
        footer_style="bold",
        border_style="rgb(7,54,66)",
        title_style="bold magenta",
        title_justify="center",
        highlight=False,
    )

    # Determine the amount we are staking.
    rows = []
    stake_amount_balance = []
    current_stake_balances = []
    current_wallet_balance_ = await subtensor.get_balance(
        wallet.coldkeypub.ss58_address
    )
    current_wallet_balance = current_wallet_balance_[
        wallet.coldkeypub.ss58_address
    ].set_unit(0)
    remaining_wallet_balance = current_wallet_balance
    max_slippage = 0.0

    hotkeys_to_stake_to: list[tuple[Optional[str], str]] = []
    if all_hotkeys:
        # Stake to all hotkeys.
        all_hotkeys_: list[Wallet] = get_hotkey_wallets_for_wallet(wallet=wallet)
        # Get the hotkeys to exclude. (d)efault to no exclusions.
        # Exclude hotkeys that are specified.
        hotkeys_to_stake_to = [
            (wallet.hotkey_str, wallet.hotkey.ss58_address)
            for wallet in all_hotkeys_
            if wallet.hotkey_str not in exclude_hotkeys
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

    starting_chain_head = await subtensor.substrate.get_chain_head()
    all_dynamic_info, initial_stake_balances = await asyncio.gather(
        asyncio.gather(
            *[
                subtensor.get_subnet_dynamic_info(x, starting_chain_head)
                for x in netuids
            ]
        ),
        subtensor.multi_get_stake_for_coldkey_and_hotkey_on_netuid(
            hotkey_ss58s=[x[1] for x in hotkeys_to_stake_to],
            coldkey_ss58=wallet.coldkeypub.ss58_address,
            netuids=netuids,
            block_hash=starting_chain_head,
        ),
    )
    for hk_name, hk_ss58 in hotkeys_to_stake_to:
        if not is_valid_ss58_address(hk_ss58):
            print_error(
                f"The entered hotkey ss58 address is incorrect: {hk_name} | {hk_ss58}"
            )
            return False
    for hotkey in hotkeys_to_stake_to:
        for netuid, dynamic_info in zip(netuids, all_dynamic_info):
            # Check that the subnet exists.
            if not dynamic_info:
                err_console.print(f"Subnet with netuid: {netuid} does not exist.")
                continue
            current_stake_balances.append(initial_stake_balances[hotkey[1]][netuid])

            # Get the amount.
            amount_to_stake_as_balance = Balance(0)
            if amount:
                amount_to_stake_as_balance = Balance.from_tao(amount)
            elif stake_all:
                amount_to_stake_as_balance = current_wallet_balance / len(netuids)
            elif not amount and not max_stake:
                if Confirm.ask(f"Stake all: [bold]{remaining_wallet_balance}[/bold]?"):
                    amount_to_stake_as_balance = remaining_wallet_balance
                else:
                    try:
                        amount = FloatPrompt.ask(
                            f"Enter amount to stake in {Balance.get_unit(0)} to subnet: {netuid}"
                        )
                        amount_to_stake_as_balance = Balance.from_tao(amount)
                    except ValueError:
                        err_console.print(
                            f":cross_mark:[red]Invalid amount: {amount}[/red]"
                        )
                        return False
            stake_amount_balance.append(amount_to_stake_as_balance)

            # Check enough to stake.
            amount_to_stake_as_balance.set_unit(0)
            if amount_to_stake_as_balance > remaining_wallet_balance:
                err_console.print(
                    f"[red]Not enough stake[/red]:[bold white]\n wallet balance:{remaining_wallet_balance} < "
                    f"staking amount: {amount_to_stake_as_balance}[/bold white]"
                )
                return False
            remaining_wallet_balance -= amount_to_stake_as_balance

            # Slippage warning
            received_amount, slippage = dynamic_info.tao_to_alpha_with_slippage(
                amount_to_stake_as_balance
            )
            if dynamic_info.is_dynamic:
                slippage_pct_float = (
                    100 * float(slippage) / float(slippage + received_amount)
                    if slippage + received_amount != 0
                    else 0
                )
                slippage_pct = f"{slippage_pct_float:.4f} %"
            else:
                slippage_pct_float = 0
                slippage_pct = "N/A"
            max_slippage = max(slippage_pct_float, max_slippage)
            rows.append(
                (
                    str(netuid),
                    # f"{staking_address_ss58[:3]}...{staking_address_ss58[-3:]}",
                    f"{hotkey}",
                    str(amount_to_stake_as_balance),
                    str(1 / float(dynamic_info.price))
                    + f" {Balance.get_unit(netuid)}/{Balance.get_unit(0)} ",
                    str(received_amount.set_unit(netuid)),
                    str(slippage_pct),
                )
            )
    table.add_column("Netuid", justify="center", style="grey89")
    table.add_column("Hotkey", justify="center", style="light_salmon3")
    table.add_column(
        f"Amount ({Balance.get_unit(0)})", justify="center", style="dark_sea_green"
    )
    table.add_column(
        f"Rate (per {Balance.get_unit(0)})",
        justify="center",
        style="light_goldenrod2",
    )
    table.add_column(
        "Received",
        justify="center",
        style="light_slate_blue",
    )
    table.add_column("Slippage", justify="center", style="rgb(220,50,47)")
    for row in rows:
        table.add_row(*row)
    console.print(table)
    message = ""
    if max_slippage > 5:
        message += "-------------------------------------------------------------------------------------------------------------------\n"
        message += f"[bold][yellow]WARNING:[/yellow]\tThe slippage on one of your operations is high: [bold red]{max_slippage} %[/bold red], this may result in a loss of funds.[/bold] \n"
        message += "-------------------------------------------------------------------------------------------------------------------\n"
        console.print(message)
    console.print(
        """
[bold white]Description[/bold white]:
The table displays information about the stake operation you are about to perform.
The columns are as follows:
    - [bold white]Netuid[/bold white]: The netuid of the subnet you are staking to.
    - [bold white]Hotkey[/bold white]: The ss58 address of the hotkey you are staking to. 
    - [bold white]Amount[/bold white]: The TAO you are staking into this subnet onto this hotkey.
    - [bold white]Rate[/bold white]: The rate of exchange between your TAO and the subnet's stake.
    - [bold white]Received[/bold white]: The amount of stake you will receive on this subnet after slippage.
    - [bold white]Slippage[/bold white]: The slippage percentage of the stake operation. (0% if the subnet is not dynamic i.e. root).
"""
    )
    if prompt:
        if not Confirm.ask("Would you like to continue?"):
            return False

    async def send_extrinsic(
        netuid_i, amount_, current, staking_address_ss58, status=None
    ):
        err_out = partial(print_error, status=status)
        failure_prelude = (
            f":cross_mark: [red]Failed[/red] to stake {amount} on Netuid {netuid_i}"
        )
        call = await subtensor.substrate.compose_call(
            call_module="SubtensorModule",
            call_function="add_stake",
            call_params={
                "hotkey": staking_address_ss58,
                "netuid": netuid_i,
                "amount_staked": amount_.rao,
            },
        )
        extrinsic = await subtensor.substrate.create_signed_extrinsic(
            call=call, keypair=wallet.coldkey
        )
        try:
            response = await subtensor.substrate.submit_extrinsic(
                extrinsic, wait_for_inclusion=True, wait_for_finalization=False
            )
        except SubstrateRequestException as e:
            err_out(
                f"\n{failure_prelude} with error: {format_error_message(e, subtensor.substrate)}"
            )
            return
        if not prompt:  # TODO verbose?
            console.print(
                f":white_heavy_check_mark: [green]Submitted {amount_} to {netuid_i}[/green]"
            )
        else:
            await response.process_events()
            if not await response.is_success:
                err_out(
                    f"\n{failure_prelude} with error: {format_error_message(await response.error_message, subtensor.substrate)}"
                )
            else:
                new_balance_, new_stake_ = await asyncio.gather(
                    subtensor.get_balance(wallet.coldkeypub.ss58_address),
                    subtensor.get_stake_for_coldkey_and_hotkey_on_netuid(
                        coldkey_ss58=wallet.coldkeypub.ss58_address,
                        hotkey_ss58=staking_address_ss58,
                        netuid=netuid_i,
                    ),
                )
                new_balance = new_balance_[wallet.coldkeypub.ss58_address]
                new_stake = new_stake_.set_unit(netuid_i)
                console.print(
                    f"Balance:\n  [blue]{current_wallet_balance}[/blue] :arrow_right: [green]{new_balance}[/green]"
                )
                console.print(
                    f"Subnet: {netuid_i} Stake:\n  [blue]{current}[/blue] :arrow_right: [green]{new_stake}[/green]"
                )

    # Perform staking operation.
    wallet.unlock_coldkey()
    extrinsics_coroutines = [
        send_extrinsic(ni, am, curr, staking_address)
        for i, (ni, am, curr) in enumerate(
            zip(netuids, stake_amount_balance, current_stake_balances)
        )
        for _, staking_address in hotkeys_to_stake_to
    ]
    if len(extrinsics_coroutines) == 1:
        with console.status(
            f"\n:satellite: Staking on netuid(s): {netuids} ..."
        ) as status:
            await extrinsics_coroutines[0]
    else:
        with console.status(":satellite: Checking transaction rate limit ..."):
            tx_rate_limit_blocks = await subtensor.substrate.query(
                module="SubtensorModule", storage_function="TxRateLimit"
            )
        netuid_hk_pairs = [(ni, hk) for ni in netuids for hk in hotkeys_to_stake_to]
        for item, kp in zip(extrinsics_coroutines, netuid_hk_pairs):
            ni, hk = kp
            with console.status(
                f"\n:satellite: Staking on netuid {ni} with hotkey {hk}... ..."
            ):
                await item
                if tx_rate_limit_blocks > 0:
                    with console.status(
                        f":hourglass: [yellow]Waiting for tx rate limit:"
                        f" [white]{tx_rate_limit_blocks}[/white] blocks[/yellow]"
                    ):
                        await asyncio.sleep(
                            tx_rate_limit_blocks * 12
                        )  # 12 sec per block


async def unstake(
    wallet: Wallet,
    subtensor: "SubtensorInterface",
    hotkey_ss58_address: str,
    netuid: Optional[int],
    all_hotkeys: bool,
    include_hotkeys: list[str],
    exclude_hotkeys: list[str],
    amount: float,
    keep_stake: float,
    unstake_all: bool,
    prompt: bool,
):
    """Unstake token of amount from hotkey(s)."""
    netuids = (
        [int(netuid)] if netuid is not None else await subtensor.get_all_subnet_netuids()
    )
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

    # Get old staking balance.
    table = Table(
        title=f"[white]Unstake operation to Coldkey SS58: [bold dark_green]{wallet.coldkeypub.ss58_address}[/bold dark_green]\n",
        width=console.width - 5,
        safe_box=True,
        padding=(0, 1),
        collapse_padding=False,
        pad_edge=True,
        expand=True,
        show_header=True,
        show_footer=True,
        show_edge=False,
        show_lines=False,
        leading=0,
        style="none",
        row_styles=None,
        header_style="bold",
        footer_style="bold",
        border_style="rgb(7,54,66)",
        title_style="bold magenta",
        title_justify="center",
        highlight=False,
    )
    rows = []
    unstake_amount_balance = []
    current_stake_balances = []
    total_received_amount = Balance.from_tao(0)
    current_wallet_balance: Balance = (
        await subtensor.get_balance(wallet.coldkeypub.ss58_address)
    )[wallet.coldkeypub.ss58_address]
    max_float_slippage = 0
    non_zero_netuids = []
    # TODO gather this all
    for hotkey in hotkeys_to_unstake_from:
        staking_address_name, staking_address_ss58 = hotkey
        for netuid in netuids:
            # Check that the subnet exists.
            dynamic_info = await subtensor.get_subnet_dynamic_info(netuid)
            if dynamic_info is None:
                console.print(f"[red]Subnet: {netuid} does not exist.[/red]")
                return False

            current_stake_balance: Balance = (
                await subtensor.get_stake_for_coldkey_and_hotkey_on_netuid(
                    coldkey_ss58=wallet.coldkeypub.ss58_address,
                    hotkey_ss58=hotkey_ss58_address,
                    netuid=netuid,
                )
            )
            if current_stake_balance.tao == 0:
                continue
            non_zero_netuids.append(netuid)
            current_stake_balances.append(current_stake_balance)

            # Determine the amount we are staking.
            if amount:
                amount_to_unstake_as_balance = Balance.from_tao(amount)
            elif unstake_all:
                amount_to_unstake_as_balance = current_stake_balance
            else:  # TODO max_stake
                if Confirm.ask(
                    f"Unstake all: [bold]{current_stake_balance}[/bold]"
                    f" from [bold]{staking_address_name}[/bold] on netuid: {netuid}?"
                ):
                    amount_to_unstake_as_balance = current_stake_balance
                else:
                    try:
                        # TODO improve this
                        amount = float(
                            Prompt.ask(
                                f"Enter amount to unstake in {Balance.get_unit(netuid)} from subnet: {netuid}"
                            )
                        )
                        amount_to_unstake_as_balance = Balance.from_tao(amount)
                    except ValueError:
                        err_console.print(
                            ":cross_mark:[red]Invalid amount Please use `--amount` with `--no-prompt`.[/red]"
                        )
                        return False
            unstake_amount_balance.append(amount_to_unstake_as_balance)

            # Check enough to stake.
            amount_to_unstake_as_balance.set_unit(netuid)
            if amount_to_unstake_as_balance > current_stake_balance:
                err_console.print(
                    f"[red]Not enough stake to remove[/red]:[bold white]\n stake balance:{current_stake_balance}"
                    f" < unstaking amount: {amount_to_unstake_as_balance}[/bold white]"
                )
                return False

            received_amount, slippage = dynamic_info.alpha_to_tao_with_slippage(
                amount_to_unstake_as_balance
            )
            total_received_amount += received_amount
            if dynamic_info.is_dynamic:
                slippage_pct_float = (
                    100 * float(slippage) / float(slippage + received_amount)
                    if slippage + received_amount != 0
                    else 0
                )
                slippage_pct = f"{slippage_pct_float:.4f} %"
            else:
                slippage_pct_float = 0
                slippage_pct = f"{slippage_pct_float}%"
            max_float_slippage = max(max_float_slippage, slippage_pct_float)

            rows.append(
                (
                    str(netuid),
                    # f"{staking_address_ss58[:3]}...{staking_address_ss58[-3:]}",
                    f"{staking_address_ss58}",
                    str(amount_to_unstake_as_balance),
                    str(float(dynamic_info.price))
                    + f"({Balance.get_unit(0)}/{Balance.get_unit(netuid)})",
                    str(received_amount),
                    str(slippage_pct),
                )
            )

    table.add_column("Netuid", justify="center", style="grey89")
    table.add_column("Hotkey", justify="center", style="light_salmon3")
    table.add_column(
        f"Amount ({Balance.get_unit(1)})", justify="center", style="dark_sea_green"
    )
    table.add_column(
        f"Rate ({Balance.get_unit(0)}/{Balance.get_unit(1)})",
        justify="center",
        style="light_goldenrod2",
    )
    table.add_column(
        f"Recieved ({Balance.get_unit(0)})",
        justify="center",
        style="light_slate_blue",
        footer=f"{total_received_amount}",
    )
    table.add_column("Slippage", justify="center", style="rgb(220,50,47)")
    for row in rows:
        table.add_row(*row)
    console.print(table)
    message = ""
    if max_float_slippage > 5:
        message += f"-------------------------------------------------------------------------------------------------------------------\n"
        message += f"[bold][yellow]WARNING:[/yellow]\tThe slippage on one of your operations is high: [bold red]{max_float_slippage} %[/bold red], this may result in a loss of funds.[/bold] \n"
        message += f"-------------------------------------------------------------------------------------------------------------------\n"
        console.print(message)
    if prompt:
        if not Confirm.ask("Would you like to continue?"):
            return False
    console.print(
        """
[bold white]Description[/bold white]:
The table displays information about the stake remove operation you are about to perform.
The columns are as follows:
    - [bold white]Netuid[/bold white]: The netuid of the subnet you are unstaking from.
    - [bold white]Hotkey[/bold white]: The ss58 address of the hotkey you are unstaking from. 
    - [bold white]Amount[/bold white]: The stake amount you are removing from this key.
    - [bold white]Rate[/bold white]: The rate of exchange between TAO and the subnet's stake.
    - [bold white]Received[/bold white]: The amount of free balance TAO you will receive on this subnet after slippage.
    - [bold white]Slippage[/bold white]: The slippage percentage of the unstake operation. (0% if the subnet is not dynamic i.e. root).
"""
    )

    # Perform staking operation.
    wallet.unlock_coldkey()
    with console.status(
        f"\n:satellite: Unstaking {amount_to_unstake_as_balance} from {staking_address_name} on netuid: {netuid} ..."
    ):
        for netuid_i, amount, current in list(
            zip(non_zero_netuids, unstake_amount_balance, current_stake_balances)
        ):
            call = await subtensor.substrate.compose_call(
                call_module="SubtensorModule",
                call_function="remove_stake",
                call_params={
                    "hotkey": hotkey_ss58_address,
                    "netuid": netuid_i,
                    "amount_unstaked": amount.rao,
                },
            )
            extrinsic = await subtensor.substrate.create_signed_extrinsic(
                call=call, keypair=wallet.coldkey
            )
            response = await subtensor.substrate.submit_extrinsic(
                extrinsic, wait_for_inclusion=True, wait_for_finalization=False
            )
            if not prompt:
                console.print(":white_heavy_check_mark: [green]Sent[/green]")
            else:
                await response.process_events()
                if not await response.is_success:
                    err_console.print(
                        f":cross_mark: [red]Failed[/red] with error: "
                        f"{format_error_message(response.error_message, subtensor.substrate)}"
                    )
                else:
                    new_balance_ = await subtensor.get_balance(
                        wallet.coldkeypub.ss58_address
                    )
                    new_balance = new_balance_[wallet.coldkeypub.ss58_address]
                    new_stake = (
                        await subtensor.get_stake_for_coldkey_and_hotkey_on_netuid(
                            coldkey_ss58=wallet.coldkeypub.ss58_address,
                            hotkey_ss58=hotkey_ss58_address,
                            netuid=netuid_i,
                        )
                    ).set_unit(netuid_i)
                    console.print(
                        f"Balance:\n  [blue]{current_wallet_balance}[/blue] :arrow_right: [green]{new_balance}[/green]"
                    )
                    console.print(
                        f"Subnet: {netuid_i} Stake:\n  [blue]{current}[/blue] :arrow_right: [green]{new_stake}[/green]"
                    )


async def stake_list(wallet: Wallet, subtensor: "SubtensorInterface"):
    sub_stakes = (
        await subtensor.get_stake_info_for_coldkeys(
            coldkey_ss58_list=[wallet.coldkeypub.ss58_address]
        )
    )[wallet.coldkeypub.ss58_address]

    # Get registered delegates details.
    registered_delegate_info = await subtensor.get_delegate_identities()

    # Token pricing info.
    dynamic_info = await subtensor.get_all_subnet_dynamic_info()
    emission_drain_tempo = int(
        await subtensor.substrate.query("SubtensorModule", "HotkeyEmissionTempo")
    )
    balance = (await subtensor.get_balance(wallet.coldkeypub.ss58_address))[
        wallet.coldkeypub.ss58_address
    ]

    # Iterate over substakes and aggregate them by hotkey.
    hotkeys_to_substakes: dict[str, list[StakeInfo]] = {}

    def table_substakes(hotkey_: str, substakes: list[StakeInfo]):
        # Create table structure.
        name = (
            f"{registered_delegate_info[hotkey_].display} ({hotkey_})"
            if hotkey_ in registered_delegate_info
            else hotkey_
        )
        rows = []
        total_global_tao = Balance(0)
        total_tao_value = Balance(0)
        for substake_ in substakes:
            netuid = substake_.netuid
            pool = dynamic_info[netuid]
            symbol = f"{Balance.get_unit(netuid)}"
            # TODO: what is this price var for?
            price = (
                "{:.4f}{}".format(
                    pool.price.__float__(), f" τ/{Balance.get_unit(netuid)}\u200e"
                )
                if pool.is_dynamic
                else (f" 1.0000 τ/{symbol} ")
            )
            alpha_value = Balance.from_rao(int(substake_.stake.rao)).set_unit(netuid)
            locked_value = Balance.from_rao(int(substake_.locked.rao)).set_unit(netuid)
            tao_value = pool.alpha_to_tao(alpha_value)
            total_tao_value += tao_value
            swapped_tao_value, slippage = pool.alpha_to_tao_with_slippage(
                substake_.stake
            )
            if pool.is_dynamic:
                slippage_percentage_ = (
                    100 * float(slippage) / float(slippage + swapped_tao_value)
                    if slippage + swapped_tao_value != 0
                    else 0
                )
                slippage_percentage = (
                    f"[dark_red]{slippage_percentage_:.3f}%[/dark_red]"
                )
            else:
                slippage_percentage = "0.000%"
            tao_locked = pool.tao_in
            issuance = pool.alpha_out if pool.is_dynamic else tao_locked
            per_block_emission = substake_.emission.tao / (
                (emission_drain_tempo / pool.tempo) * pool.tempo
            )
            if alpha_value.tao > 0.00009:
                if issuance.tao != 0:
                    alpha_ownership = "{:.4f}".format(
                        (alpha_value.tao / issuance.tao) * 100
                    )
                    tao_ownership = Balance.from_tao(
                        (alpha_value.tao / issuance.tao) * tao_locked.tao
                    )
                    total_global_tao += tao_ownership
                else:
                    # TODO what's this var for?
                    alpha_ownership = "0.0000"
                    tao_ownership = "0.0000"
                rows.append(
                    [
                        str(netuid),  # Number
                        symbol,  # Symbol
                        # f"[medium_purple]{tao_ownership}[/medium_purple] ([light_salmon3]{ alpha_ownership }[/light_salmon3][white]%[/white])", # Tao ownership.
                        f"[medium_purple]{tao_ownership}[/medium_purple]",  # Tao ownership.
                        # f"[dark_sea_green]{ alpha_value }", # Alpha value
                        f"{substake_.stake.tao:,.4f} {symbol}",
                        f"{pool.price.tao:.4f} τ/{symbol}",
                        f"[light_slate_blue]{tao_value}[/light_slate_blue]",  # Tao equiv
                        f"[cadet_blue]{swapped_tao_value}[/cadet_blue] ({slippage_percentage})",  # Swap amount.
                        # f"[light_salmon3]{ alpha_ownership }%[/light_salmon3]",  # Ownership.
                        "[bold cadet_blue]YES[/bold cadet_blue]"
                        if substake_.is_registered
                        else "[dark_red]NO[/dark_red]",
                        # Registered.
                        str(Balance.from_tao(per_block_emission).set_unit(netuid))
                        if substake_.is_registered
                        else "[dark_red]N/A[/dark_red]",  # emission per block.
                        f"[light_slate_blue]{locked_value}[/light_slate_blue]",  # Locked value
                    ]
                )
        # table = Table(show_footer=True, pad_edge=False, box=None, expand=False, title=f"{name}")
        table = Table(
            title=f"[white]hotkey:[/white] [light_salmon3]{name}[/light_salmon3]\n",
            width=console.width - 5,
            safe_box=True,
            padding=(0, 1),
            collapse_padding=False,
            pad_edge=True,
            expand=True,
            show_header=True,
            show_footer=True,
            show_edge=False,
            show_lines=False,
            leading=0,
            style="none",
            row_styles=None,
            header_style="bold",
            footer_style="bold",
            border_style="rgb(7,54,66)",
            title_style="bold magenta",
            title_justify="center",
            highlight=False,
        )
        table.add_column("[white]Netuid", footer_style="overline white", style="grey89")
        table.add_column(
            "[white]Symbol",
            footer_style="white",
            style="light_goldenrod1",
            justify="right",
            width=5,
            no_wrap=True,
        )
        table.add_column(
            f"[white]TAO({Balance.unit})",
            style="aquamarine3",
            justify="right",
            footer=f"{total_global_tao}",
        )
        table.add_column(
            f"[white]Stake({Balance.get_unit(1)})",
            footer_style="overline white",
            style="green",
            justify="right",
        )
        table.add_column(
            f"[white]Rate({Balance.unit}/{Balance.get_unit(1)})",
            footer_style="white",
            style="light_goldenrod2",
            justify="center",
        )
        table.add_column(
            f"[white]Value({Balance.get_unit(1)} x {Balance.unit}/{Balance.get_unit(1)})",
            footer_style="overline white",
            style="blue",
            justify="right",
            footer=f"{total_tao_value}",
        )
        table.add_column(
            f"[white]Swap({Balance.get_unit(1)}) -> {Balance.unit}",
            footer_style="overline white",
            style="white",
            justify="right",
        )
        # table.add_column(f"[white]Control({bittensor.Balance.get_unit(1)})", style="aquamarine3", justify="right")
        table.add_column("[white]Registered", style="red", justify="right")
        table.add_column(
            f"[white]Emission({Balance.get_unit(1)}/block)",
            style="aquamarine3",
            justify="right",
        )
        table.add_column(
            f"[white]Locked({Balance.get_unit(1)})",
            footer_style="overline white",
            style="green",
            justify="right",
        )
        for row in rows:
            table.add_row(*row)
        console.print(table)
        return total_global_tao, total_tao_value

    for substake in sub_stakes:
        hotkey = substake.hotkey_ss58
        if substake.stake.rao == 0:
            continue
        if hotkey not in hotkeys_to_substakes:
            hotkeys_to_substakes[hotkey] = []
        hotkeys_to_substakes[hotkey].append(substake)

    # Iterate over each hotkey and make a table
    all_hotkeys_total_global_tao = Balance(0)
    all_hotkeys_total_tao_value = Balance(0)
    for hotkey in hotkeys_to_substakes.keys():
        stake, value = table_substakes(hotkey, hotkeys_to_substakes[hotkey])
        all_hotkeys_total_global_tao += stake
        all_hotkeys_total_tao_value += value

    console.print("\n\n")
    console.print(
        f"Wallet:\n"
        f"  Coldkey SS58: [bold dark_green]{wallet.coldkeypub.ss58_address}[/bold dark_green]\n"
        f"  Free Balance: [aquamarine3]{balance}[/aquamarine3]\n"
        f"  Total TAO ({Balance.unit}): [aquamarine3]{all_hotkeys_total_global_tao}[/aquamarine3]\n"
        f"  Total Value ({Balance.unit}): [aquamarine3]{all_hotkeys_total_tao_value}[/aquamarine3]"
    )
    console.print(
        """
[bold white]Description[/bold white]:
Each table displays information about your coldkey's staking accounts with a hotkey. 
The header of the table displays the hotkey and the footer displays the total stake and total value of all your staking accounts. 
The columns of the table are as follows:
    - [bold white]Netuid[/bold white]: The unique identifier for the subnet (its index).
    - [bold white]Symbol[/bold white]: The symbol representing the subnet stake's unit.
    - [bold white]TAO[/bold white]: The hotkey's TAO balance on this subnet. This is this hotkey's proportion of total TAO staked into the subnet divided by the hotkey's share of outstanding stake.
    - [bold white]Stake[/bold white]: The hotkey's stake balance in subnets staking unit.
    - [bold white]Rate[/bold white]: The rate of exchange between the subnet's staking unit and the subnet's TAO.
    - [bold white]Value[/bold white]: The price of the hotkey's stake in TAO computed via the exchange rate.
    - [bold white]Swap[/bold white]: The amount of TAO received when unstaking all of the hotkey's stake (with slippage).
    - [bold white]Registered[/bold white]: Whether the hotkey is registered on this subnet.
    - [bold white]Emission[/bold white]: If registered, the emission (in stake) attained by this hotkey on this subnet per block.
    - [bold white]Locked[/bold white]: The total amount of stake locked (not able to be unstaked).
"""
    )


async def move_stake(
    subtensor: "SubtensorInterface",
    wallet: Wallet,
    origin_netuid: int,
    destination_netuid: int,
    destination_hotkey: str,
    amount: float,
    stake_all: bool,
    prompt: bool = True,
):
    origin_hotkey_ss58 = wallet.hotkey.ss58_address
    # Get the wallet stake balances.
    origin_stake_balance: Balance = (
        await subtensor.get_stake_for_coldkey_and_hotkey_on_netuid(
            coldkey_ss58=wallet.coldkeypub.ss58_address,
            hotkey_ss58=origin_hotkey_ss58,
            netuid=origin_netuid,
        )
    ).set_unit(origin_netuid)

    destination_stake_balance: Balance = (
        await subtensor.get_stake_for_coldkey_and_hotkey_on_netuid(
            coldkey_ss58=wallet.coldkeypub.ss58_address,
            hotkey_ss58=destination_hotkey,
            netuid=destination_netuid,
        )
    ).set_unit(destination_netuid)

    # Determine the amount we are moving.
    amount_to_move_as_balance = None
    if amount:
        amount_to_move_as_balance = Balance.from_tao(amount)
    elif stake_all:
        amount_to_move_as_balance = origin_stake_balance
    else:  # max_stake
        # TODO improve this
        if Confirm.ask(f"Move all: [bold]{origin_stake_balance}[/bold]?"):
            amount_to_move_as_balance = origin_stake_balance
        else:
            try:
                amount = float(
                    Prompt.ask(
                        f"Enter amount to move in {Balance.get_unit(origin_netuid)}"
                    )
                )
                amount_to_move_as_balance = Balance.from_tao(amount)
            except ValueError:
                err_console.print(f":cross_mark:[red]Invalid amount: {amount}[/red]")
                return False

    # Check enough to move.
    amount_to_move_as_balance.set_unit(origin_netuid)
    if amount_to_move_as_balance > origin_stake_balance:
        err_console.print(
            f"[red]Not enough stake[/red]:[bold white]\n stake balance:{origin_stake_balance} < moving amount: {amount_to_move_as_balance}[/bold white]"
        )
        return False

    # Slippage warning
    if prompt:
        if origin_netuid == destination_netuid:
            received_amount_destination = amount_to_move_as_balance
            slippage_pct_float = 0
            slippage_pct = f"{slippage_pct_float}%"
            price = Balance.from_tao(1).set_unit(origin_netuid)
            price_str = (
                str(float(price.tao))
                + f"{Balance.get_unit(origin_netuid)}/{Balance.get_unit(origin_netuid)}"
            )
        else:
            dynamic_origin, dynamic_destination = await asyncio.gather(
                subtensor.get_subnet_dynamic_info(origin_netuid),
                subtensor.get_subnet_dynamic_info(destination_netuid),
            )
            price = float(dynamic_origin.price) * 1 / float(dynamic_destination.price)
            received_amount_tao, slippage = dynamic_origin.alpha_to_tao_with_slippage(
                amount_to_move_as_balance
            )
            received_amount_destination, slippage = (
                dynamic_destination.tao_to_alpha_with_slippage(received_amount_tao)
            )
            received_amount_destination.set_unit(destination_netuid)
            slippage_pct_float = (
                100 * float(slippage) / float(slippage + received_amount_destination)
                if slippage + received_amount_destination != 0
                else 0
            )
            slippage_pct = f"{slippage_pct_float:.4f} %"
            price_str = (
                str(float(price))
                + f"{Balance.get_unit(destination_netuid)}/{Balance.get_unit(origin_netuid)}"
            )

        table = Table(
            title="[white]Move Stake",
            width=console.width - 5,
            safe_box=True,
            padding=(0, 1),
            collapse_padding=False,
            pad_edge=True,
            expand=True,
            show_header=True,
            show_footer=True,
            show_edge=False,
            show_lines=False,
            leading=0,
            style="none",
            row_styles=None,
            header_style="bold",
            footer_style="bold",
            border_style="rgb(7,54,66)",
            title_style="bold magenta",
            title_justify="center",
            highlight=False,
        )
        table.add_column("origin netuid", justify="center", style="rgb(133,153,0)")
        table.add_column("origin hotkey", justify="center", style="rgb(38,139,210)")
        table.add_column("dest netuid", justify="center", style="rgb(133,153,0)")
        table.add_column("dest hotkey", justify="center", style="rgb(38,139,210)")
        table.add_column(
            f"amount ({Balance.get_unit(origin_netuid)})",
            justify="center",
            style="rgb(38,139,210)",
        )
        table.add_column(
            f"rate ({Balance.get_unit(destination_netuid)}/{Balance.get_unit(origin_netuid)})",
            justify="center",
            style="rgb(42,161,152)",
        )
        table.add_column(
            f"received ({Balance.get_unit(destination_netuid)})",
            justify="center",
            style="rgb(220,50,47)",
        )
        table.add_column("slippage", justify="center", style="rgb(181,137,0)")

        table.add_row(
            f"{Balance.get_unit(origin_netuid)}({origin_netuid})",
            f"{origin_hotkey_ss58[:3]}...{origin_hotkey_ss58[-3:]}",
            # TODO f-strings
            Balance.get_unit(destination_netuid) + "(" + str(destination_netuid) + ")",
            f"{destination_hotkey[:3]}...{destination_hotkey[-3:]}",
            str(amount_to_move_as_balance),
            price_str,
            str(received_amount_destination.set_unit(destination_netuid)),
            str(slippage_pct),
        )

        console.print(table)
        message = ""
        if slippage_pct_float > 5:
            message += "\t-------------------------------------------------------------------------------------------------------------------\n"
            message += f"\t[bold][yellow]WARNING:[/yellow]\tSlippage is high: [bold red]{slippage_pct}[/bold red], this may result in a loss of funds.[/bold] \n"
            message += "\t-------------------------------------------------------------------------------------------------------------------\n"
            console.print(message)
        if not Confirm.ask("Would you like to continue?"):
            return True

    # Perform staking operation.
    wallet.unlock_coldkey()
    with console.status(
        f"\n:satellite: Moving {amount_to_move_as_balance} from {origin_hotkey_ss58} on netuid: {origin_netuid} to "
        f"{destination_hotkey} on netuid: {destination_netuid} ..."
    ):
        call = await subtensor.substrate.compose_call(
            call_module="SubtensorModule",
            call_function="move_stake",
            call_params={
                "origin_hotkey": origin_hotkey_ss58,
                "origin_netuid": origin_netuid,
                "destination_hotkey": destination_hotkey,
                "destination_netuid": destination_netuid,
                "amount_moved": amount_to_move_as_balance.rao,
            },
        )
        extrinsic = await subtensor.substrate.create_signed_extrinsic(
            call=call, keypair=wallet.coldkey
        )
        response = await subtensor.substrate.submit_extrinsic(
            extrinsic, wait_for_inclusion=True, wait_for_finalization=False
        )
        if not prompt:
            console.print(":white_heavy_check_mark: [green]Sent[/green]")
            return True
        else:
            await response.process_events()
            if not await response.is_success:
                err_console.print(
                    f":cross_mark: [red]Failed[/red] with error:"
                    f" {format_error_message(response.error_message, subtensor.substrate)}"
                )
                return
            else:
                new_origin_stake_balance: Balance = (
                    await subtensor.get_stake_for_coldkey_and_hotkey_on_netuid(
                        coldkey_ss58=wallet.coldkeypub.ss58_address,
                        hotkey_ss58=origin_hotkey_ss58,
                        netuid=origin_netuid,
                    )
                ).set_unit(origin_netuid)
                new_destination_stake_balance: Balance = (
                    await subtensor.get_stake_for_coldkey_and_hotkey_on_netuid(
                        coldkey_ss58=wallet.coldkeypub.ss58_address,
                        hotkey_ss58=destination_hotkey,
                        netuid=destination_netuid,
                    )
                ).set_unit(destination_netuid)
                console.print(
                    f"Origin Stake:\n  [blue]{origin_stake_balance}[/blue] :arrow_right: "
                    f"[green]{new_origin_stake_balance}[/green]"
                )
                console.print(
                    f"Destination Stake:\n  [blue]{destination_stake_balance}[/blue] :arrow_right: "
                    f"[green]{new_destination_stake_balance}[/green]"
                )
                return
