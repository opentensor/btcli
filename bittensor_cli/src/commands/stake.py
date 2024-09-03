import asyncio
import copy
import json
import sqlite3
from contextlib import suppress

from typing import TYPE_CHECKING, Optional, Sequence, Union, cast

from bittensor_wallet import Wallet
from rich.prompt import Confirm, Prompt
from rich.table import Table, Column
from rich.text import Text
from substrateinterface.exceptions import SubstrateRequestException

from bittensor_cli.src import Constants
from bittensor_cli.src.bittensor.balances import Balance
from bittensor_cli.src.bittensor.utils import (
    console,
    create_table,
    err_console,
    float_to_u64,
    get_coldkey_wallets_for_path,
    get_delegates_details_from_github,
    get_hotkey_wallets_for_wallet,
    is_valid_ss58_address,
    get_metadata_table,
    update_metadata_table,
    render_tree,
    u16_normalized_float,
    float_to_u16,
    u16_to_float,
    u64_to_float,
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
    min_req_stake: Balance = Balance.from_rao(mrs.decode())
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


async def _get_hotkey_owner(
    subtensor: "SubtensorInterface", hotkey_ss58: str, block_hash: str
) -> Optional[str]:
    hk_owner_query = await subtensor.substrate.query(
        module="SubtensorModule",
        storage_function="Owner",
        params=[hotkey_ss58],
        block_hash=block_hash,
    )
    hotkey_owner = (
        val
        if (
            (val := getattr(hk_owner_query, "value", None))
            and await subtensor.does_hotkey_exist(val, block_hash=block_hash)
        )
        else None
    )
    return hotkey_owner


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
    wallet.unlock_coldkey()

    # Default to wallet's own hotkey if the value is not passed.
    if hotkey_ss58 is None:
        hotkey_ss58 = wallet.hotkey.ss58_address

    # Flag to indicate if we are using the wallet's own hotkey.
    own_hotkey: bool

    with console.status(
        f":satellite: Syncing with chain: [white]{subtensor}[/white] ..."
    ):
        block_hash = await subtensor.substrate.get_chain_head()
        # Get hotkey owner
        hotkey_owner = await _get_hotkey_owner(
            subtensor, hotkey_ss58=hotkey_ss58, block_hash=block_hash
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
            hotkey_take = u16_normalized_float(getattr(hk_result, "value", 0))

        # Get current stake
        old_stake = await subtensor.get_stake_for_coldkey_and_hotkey(
            coldkey_ss58=wallet.coldkeypub.ss58_address,
            hotkey_ss58=hotkey_ss58,
            block_hash=block_hash,
        )

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
                f"\tto: {wallet.hotkey_str}\n"
                f"\ttake: {hotkey_take}\n"
                f"\towner: {hotkey_owner}[/bold white]"
            ):
                return False
        else:
            if not Confirm.ask(
                f"Do you want to stake:[bold white]\n"
                f"\tamount: {staking_balance}\n"
                f"\tto: {wallet.hotkey_str}[/bold white]"
            ):
                return False

    with console.status(
        f":satellite: Staking to: [bold white]{subtensor}[/bold white] ..."
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
        new_amounts = amounts
        if sum(amount.tao for amount in amounts) == 0:
            # Staking 0 tao
            return True

    # Decrypt coldkey.
    wallet.unlock_coldkey()

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
                tx_rate_limit_blocks: int = getattr(tx_query, "value", 0)
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
    wallet.unlock_coldkey()

    if hotkey_ss58 is None:
        hotkey_ss58 = wallet.hotkey.ss58_address  # Default to wallet's own hotkey.

    with console.status(
        f":satellite: Syncing with chain: [white]{subtensor}[/white] ..."
    ):
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
            _get_hotkey_owner(subtensor, hotkey_ss58, block_hash),
        )

        own_hotkey: bool = wallet.coldkeypub.ss58_address == hotkey_owner

    # Convert to bittensor.Balance
    if amount is None:
        # Unstake it all.
        unstaking_balance = old_stake
    else:
        unstaking_balance = amount

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
        f":satellite: Unstaking from chain: [white]{subtensor}[/white] ..."
    ):
        unstaking_balance = Balance.from_tao(unstaking_balance)
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
        new_amounts = amounts
        if sum(amount.tao for amount in cast(Sequence[Balance], new_amounts)) == 0:
            # Staking 0 tao
            return True

    # Unlock coldkey.
    wallet.unlock_coldkey()

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
            *[_get_hotkey_owner(subtensor, h, block_hash) for h in hotkey_ss58s]
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
                f"\thotkey: {wallet.hotkey_str}[/bold white ]?"
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
                tx_rate_limit_blocks: int = getattr(tx_query, "value", 0)
                if tx_rate_limit_blocks > 0:
                    console.print(
                        ":hourglass: [yellow]Waiting for tx rate limit:"
                        " [white]{tx_rate_limit_blocks}[/white] blocks[/yellow]"
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


async def set_children_extrinsic(
    subtensor: "SubtensorInterface",
    wallet: Wallet,
    hotkey: str,
    netuid: int,
    children_with_proportions: list[tuple[float, str]],
    wait_for_inclusion: bool = True,
    wait_for_finalization: bool = False,
    prompt: bool = False,
) -> tuple[bool, str]:
    """
    Sets children hotkeys with proportions assigned from the parent.

    :param: subtensor: Subtensor endpoint to use.
    :param: wallet: Bittensor wallet object.
    :param: hotkey: Parent hotkey.
    :param: children_with_proportions: Children hotkeys.
    :param: netuid: Unique identifier of for the subnet.
    :param: wait_for_inclusion: If set, waits for the extrinsic to enter a block before returning `True`, or returns
                                `False` if the extrinsic fails to enter the block within the timeout.
    :param: wait_for_finalization: If set, waits for the extrinsic to be finalized on the chain before returning `
                                   `True`, or returns `False` if the extrinsic fails to be finalized within the timeout.
    :param: prompt: If `True`, the call waits for confirmation from the user before proceeding.

    :return: A tuple containing a success flag and an optional error message.
    """
    # Check if all children are being revoked
    all_revoked = len(children_with_proportions) == 0

    operation = "Revoking all child hotkeys" if all_revoked else "Setting child hotkeys"

    # Ask before moving on.
    if prompt:
        if all_revoked:
            if not Confirm.ask(
                f"Do you want to revoke all children hotkeys for hotkey {hotkey}?"
            ):
                return False, "Operation Cancelled"
        else:
            if not Confirm.ask(
                "Do you want to set children hotkeys:\n[bold white]{}[/bold white]?".format(
                    "\n".join(
                        f"  {child[1]}: {child[0]}"
                        for child in children_with_proportions
                    )
                )
            ):
                return False, "Operation Cancelled"

    # Decrypt coldkey.
    wallet.unlock_coldkey()

    with console.status(
        f":satellite: {operation} on [white]{subtensor.network}[/white] ..."
    ):
        if not all_revoked:
            normalized_children = prepare_child_proportions(children_with_proportions)
        else:
            normalized_children = []

        call = await subtensor.substrate.compose_call(
            call_module="SubtensorModule",
            call_function="set_children",
            call_params={
                "hotkey": hotkey,
                "children": normalized_children,
                "netuid": netuid,
            },
        )
        success, error_message = await subtensor.sign_and_send_extrinsic(
            call, wallet, wait_for_inclusion, wait_for_finalization
        )

        if not wait_for_finalization and not wait_for_inclusion:
            return (
                True,
                f"Not waiting for finalization or inclusion. {operation} initiated.",
            )

        if success:
            console.print(":white_heavy_check_mark: [green]Finalized[/green]")
            # bittensor.logging.success(
            #     prefix=operation,
            #     suffix="<green>Finalized: </green>" + str(success),
            # )
            return True, f"Successfully {operation.lower()} and Finalized."
        else:
            err_console.print(f":cross_mark: [red]Failed[/red]: {error_message}")
            # bittensor.logging.warning(
            #     prefix=operation,
            #     suffix="<red>Failed: </red>" + str(error_message),
            # )
            return False, error_message


async def set_childkey_take_extrinsic(
    subtensor: "SubtensorInterface",
    wallet: Wallet,
    hotkey: str,
    netuid: int,
    take: float,
    wait_for_inclusion: bool = True,
    wait_for_finalization: bool = False,
    prompt: bool = True,
) -> tuple[bool, str]:
    """
    Sets childkey take.

    :param: subtensor: Subtensor endpoint to use.
    :param: wallet: Bittensor wallet object.
    :param: hotkey: Child hotkey.
    :param: take: Childkey Take value.
    :param: netuid: Unique identifier of for the subnet.
    :param: wait_for_inclusion: If set, waits for the extrinsic to enter a block before returning `True`, or returns
                                `False` if the extrinsic fails to enter the block within the timeout.
    :param: wait_for_finalization: If set, waits for the extrinsic to be finalized on the chain before returning `
                                   `True`, or returns `False` if the extrinsic fails to be finalized within the timeout.
    :param: prompt: If `True`, the call waits for confirmation from the user before proceeding.

    :return: A tuple containing a success flag and an optional error message.
    """

    # Ask before moving on.
    if prompt:
        if not Confirm.ask(
            f"Do you want to set childkey take to: [bold white]{take * 100}%[/bold white]?"
        ):
            return False, "Operation Cancelled"

    # Decrypt coldkey.
    wallet.unlock_coldkey()

    with console.status(
        f":satellite: Setting childkey take on [white]{subtensor.network}[/white] ..."
    ):
        try:
            if 0 < take <= 0.18:
                take_u16 = float_to_u16(take)
            else:
                return False, "Invalid take value"

            call = await subtensor.substrate.compose_call(
                call_module="SubtensorModule",
                call_function="set_childkey_take",
                call_params={
                    "hotkey": hotkey,
                    "take": take_u16,
                    "netuid": netuid,
                },
            )
            success, error_message = await subtensor.sign_and_send_extrinsic(
                call, wallet, wait_for_inclusion, wait_for_finalization
            )

            if not wait_for_finalization and not wait_for_inclusion:
                return (
                    True,
                    "Not waiting for finalization or inclusion. Set childkey take initiated.",
                )

            if success:
                console.print(":white_heavy_check_mark: [green]Finalized[/green]")
                # bittensor.logging.success(
                #     prefix="Setting childkey take",
                #     suffix="<green>Finalized: </green>" + str(success),
                # )
                return True, "Successfully set childkey take and Finalized."
            else:
                console.print(f":cross_mark: [red]Failed[/red]: {error_message}")
                # bittensor.logging.warning(
                #     prefix="Setting childkey take",
                #     suffix="<red>Failed: </red>" + str(error_message),
                # )
                return False, error_message

        except Exception as e:
            return False, f"Exception occurred while setting childkey take: {str(e)}"


async def get_childkey_take(subtensor, hotkey: str, netuid: int) -> Optional[int]:
    """
    Get the childkey take of a hotkey on a specific network.
    Args:
    - hotkey (str): The hotkey to search for.
    - netuid (int): The netuid to search for.

    Returns:
    - Optional[float]: The value of the "ChildkeyTake" if found, or None if any error occurs.
    """
    try:
        childkey_take_ = await subtensor.substrate.query(
            module="SubtensorModule",
            storage_function="ChildkeyTake",
            params=[hotkey, netuid],
        )
        if childkey_take_:
            return int(childkey_take_.value)

    except SubstrateRequestException as e:
        err_console.print(f"Error querying ChildKeys: {e}")
        return None


def prepare_child_proportions(children_with_proportions):
    """
    Convert proportions to u64 and normalize, ensuring total does not exceed u64 max.
    """
    children_u64 = [
        (float_to_u64(proportion), child)
        for proportion, child in children_with_proportions
    ]
    total = sum(proportion for proportion, _ in children_u64)

    if total > (2 ** 64 - 1):
        excess = total - (2 ** 64 - 1)
        if excess > (2 ** 64 * 0.01):  # Example threshold of 1% of u64 max
            raise ValueError("Excess is too great to normalize proportions")
        largest_child_index = max(
            range(len(children_u64)), key=lambda i: children_u64[i][0]
        )
        children_u64[largest_child_index] = (
            children_u64[largest_child_index][0] - excess,
            children_u64[largest_child_index][1],
        )

    return children_u64


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
            uids = [getattr(_result, "value", None) for _result in uid_query]
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
            return emission_, Balance.from_rao(stake.value) if getattr(
                stake, "value", None
            ) else Balance(0)

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
                        registered_delegate_info[dele.hotkey_ss58].name
                        if dele.hotkey_ss58 in registered_delegate_info
                        else dele.hotkey_ss58
                    )
                    stakes[dele.hotkey_ss58] = {
                        "name": delegate_name,
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
        else:
            wallets = [wallet]

        registered_delegate_info = await get_delegates_details_from_github(
            Constants.delegates_detail_url
        )

        with console.status(":satellite:Retrieving account data..."):
            block_hash_ = await subtensor.substrate.get_chain_head()
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
                rows.append(
                    [
                        "",
                        "",
                        value["name"],
                        str(value["stake"]),
                        str(value["rate"]),
                        key,
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
        table_width = console.width - 20
        table = Table(
            Column(
                "[bold white]Coldkey",
                style="dark_orange",
            ),
            Column(
                "[bold white]Balance",
                metadata["total_balance"],
                style="dark_sea_green",
            ),
            Column("[bold white]Account", style="bright_cyan"),
            Column(
                "[bold white]Stake",
                metadata["total_stake"],
                style="light_goldenrod2",
            ),
            Column(
                "[bold white]Rate /d",
                metadata["total_rate"],
                style="rgb(42,161,152)",
            ),
            Column(
                "[bold white]Hotkey",
                style="bright_magenta",
            ),
            title="[underline dark_orange]Stake Show",
            show_footer=True,
            show_edge=False,
            expand=False,
            width=table_width,
            border_style="bright_black",
        )
        for row in rows:
            table.add_row(*row)
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
) -> None:
    """Stake token of amount to hotkey(s)."""

    async def is_hotkey_registered_any(hk: str, bh: str) -> bool:
        return len(await subtensor.get_netuids_for_hotkey(hk, bh)) > 0

    # Get the hotkey_names (if any) and the hotkey_ss58s.
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
        assert wallet.hotkey is not None
        hotkey_ss58_or_name = wallet.hotkey.ss58_address
        hotkeys_to_stake_to = [(None, hotkey_ss58_or_name)]

    try:
        # Get coldkey balance
        wallet_balance_: dict[str, Balance] = await subtensor.get_balance(
            wallet.coldkeypub.ss58_address
        )
        block_hash = subtensor.substrate.last_block_hash
        wallet_balance: Balance = wallet_balance_[wallet.coldkeypub.ss58_address]
        old_balance = copy.copy(wallet_balance)
        final_hotkeys: list[tuple[Optional[str], str]] = []
        final_amounts: list[Union[float, Balance]] = []
        hotkey: tuple[Optional[str], str]  # (hotkey_name (or None), hotkey_ss58)
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

        # Ask to stake
        if prompt:
            if not Confirm.ask(
                f"Do you want to stake to the following keys from {wallet.name}:\n"
                + "".join(
                    [
                        f"    [bold white]- {hotkey[0] + ':' if hotkey[0] else ''}{hotkey[1]}: "
                        f"{f'{amount} {Balance.unit}' if amount else 'All'}[/bold white]\n"
                        for hotkey, amount in zip(final_hotkeys, final_amounts)
                    ]
                )
            ):
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
                prompt=False,
            )
        else:
            await add_stake_multiple_extrinsic(
                subtensor,
                wallet=wallet,
                old_balance=old_balance,
                hotkey_ss58s=[hotkey_ss58 for _, hotkey_ss58 in final_hotkeys],
                amounts=None if stake_all else final_amounts,
                wait_for_inclusion=True,
                prompt=False,
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
    max_stake: float,
    unstake_all: bool,
    prompt: bool,
):
    """Unstake token of amount from hotkey(s)."""

    # Get the hotkey_names (if any) and the hotkey_ss58s.
    hotkeys_to_unstake_from: list[tuple[Optional[str], str]] = []
    if hotkey_ss58_address:
        # Stake to specific hotkey.
        hotkeys_to_unstake_from = [(None, hotkey_ss58_address)]
    elif all_hotkeys:
        # Stake to all hotkeys.
        all_hotkeys_: list[Wallet] = get_hotkey_wallets_for_wallet(wallet=wallet)
        # Exclude hotkeys that are specified.
        hotkeys_to_unstake_from = [
            (wallet.hotkey_str, wallet.hotkey.ss58_address)
            for wallet in all_hotkeys_
            if wallet.hotkey_str not in exclude_hotkeys
        ]  # definitely wallets

    elif include_hotkeys:
        # Stake to specific hotkeys.
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
        assert wallet.hotkey is not None
        hotkeys_to_unstake_from = [(None, wallet.hotkey.ss58_address)]

    final_hotkeys: list[tuple[str, str]] = []
    final_amounts: list[Union[float, Balance]] = []
    hotkey: tuple[Optional[str], str]  # (hotkey_name (or None), hotkey_ss58)
    with suppress(ValueError):
        with console.status(f":satellite:Syncing with chain {subtensor}"):
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
            if max_stake:
                # Get the current stake of the hotkey from this coldkey.
                unstake_amount_tao = hotkey_stake.tao - max_stake
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


async def get_children(wallet: Wallet, subtensor: "SubtensorInterface", netuid: Optional[int] = None):
    async def get_total_stake_for_hk(hotkey: str, parent: bool = False):
        _result = await subtensor.substrate.query(
            module="SubtensorModule",
            storage_function="TotalHotkeyStake",
            params=[hotkey],
            reuse_block_hash=True,
        )
        stake = Balance.from_rao(_result.value) if getattr(_result, "value", None) else Balance(0)
        if parent:
            console.print(
                f"\nYour Hotkey: {hotkey}  |  ", style="cyan", end="", no_wrap=True
            )
            console.print(f"Total Stake: {stake}τ")

        return stake

    async def get_take(child: tuple) -> float:
        """
        Get the take value for a given subtensor, hotkey, and netuid.

        @param child: The hotkey to retrieve the take value for.

        @return: The take value as a float. If the take value is not available, it returns 0.

        """
        child_hotkey = child[1]
        take_u16 = await get_childkey_take(
            subtensor=subtensor, hotkey=child_hotkey, netuid=netuid
        )
        if take_u16:
            return u16_to_float(take_u16)
        else:
            return 0

    async def _render_table(
            hk: str, children_: list[tuple[int, str]], prompt: bool = True, netuid: int = None,
    ):
        # Initialize Rich table for pretty printing
        table = Table(
            show_header=True,
            header_style="bold magenta",
            border_style="blue",
            style="dim",
        )

        # Add columns to the table with specific styles
        table.add_column("Index", style="bold yellow", no_wrap=True, justify="center")
        table.add_column("Child Hotkey", style="bold green")
        table.add_column("Proportion", style="bold cyan", no_wrap=True, justify="right")
        table.add_column(
            "Childkey Take", style="bold blue", no_wrap=True, justify="right"
        )
        table.add_column(
            "Current Stake Weight", style="bold red", no_wrap=True, justify="right"
        )

        if not children_:
            console.print(table)
            console.print(
                f"[bold red]There are currently no child hotkeys on subnet {netuid} with Parent HotKey {hk}.[/bold red]"
            )
            if prompt:
                command = (
                    f"`btcli stake child set --children <child_hotkey> --hotkey <parent_hotkey> "
                    f"--netuid {netuid} --proportions <float>`"
                )
                console.print(
                    f"[bold cyan]To add a child hotkey you can run the command: [white]{command}[/white][/bold cyan]"
                )
            return

        # calculate totals
        total_proportion = 0
        total_stake = 0
        total_stake_weight = 0
        avg_take = 0

        hotkey_stake_dict = await subtensor.get_total_stake_for_hotkey(hk)
        hotkey_stake = hotkey_stake_dict.get(hk, Balance(0))

        children_info = []
        child_stakes = await asyncio.gather(
            *[get_total_stake_for_hk(c[1]) for c in children_]
        )
        child_takes = await asyncio.gather(*[get_take(c) for c in children_])
        for child, child_stake, child_take in zip(children_, child_stakes, child_takes):
            proportion = child[0]
            child_hotkey = child[1]

            # add to totals
            avg_take += child_take
            total_stake += child_stake

            proportion = u64_to_float(proportion)

            children_info.append((proportion, child_hotkey, child_stake, child_take))

        children_info.sort(
            key=lambda x: x[0], reverse=True
        )  # sorting by proportion (highest first)

        console.print(f"\nChildren for netuid: {netuid} ", style="cyan")

        # add the children info to the table
        for idx, (proportion, hotkey, stake, child_take) in enumerate(children_info, 1):
            proportion_percent = proportion * 100  # Proportion in percent
            proportion_tao = hotkey_stake.tao * proportion  # Proportion in TAO

            total_proportion += proportion_percent

            # Conditionally format text
            proportion_str = f"{proportion_percent:.3f}% ({proportion_tao:.3f}τ)"
            stake_weight = stake.tao + proportion_tao
            total_stake_weight += stake_weight
            take_str = f"{child_take * 100:.3f}%"

            hotkey = Text(hotkey, style="italic red" if proportion == 0 else "")
            table.add_row(
                str(idx),
                hotkey,
                proportion_str,
                take_str,
                str(f"{stake_weight:.3f}"),
            )

        avg_take = avg_take / len(children_info)

        # add totals row
        table.add_row(
            "",
            "[dim]Total[/dim]",
            f"[dim]{total_proportion:.3f}%[/dim]",
            f"[dim](avg) {avg_take * 100:.3f}%[/dim]",
            f"[dim]{total_stake_weight:.3f}τ[/dim]",
            style="dim",
        )
        console.print(table)

    if netuid is None:
        # get all netuids
        netuids = await subtensor.get_all_subnet_netuids()
        await get_total_stake_for_hk(wallet.hotkey.ss58_address, True)
        for netuid in netuids:
            success, children, err_mg = await subtensor.get_children(
                wallet.hotkey.ss58_address, netuid
            )
            if children:
                await _render_table(wallet.hotkey.ss58_address, children, False, netuid)
            if not success:
                err_console.print(f"Failed to get children from subtensor {netuid}: {err_mg}")

    else:
        success, children, err_mg = await subtensor.get_children(
            wallet.hotkey.ss58_address, netuid
        )
        if not success:
            err_console.print(f"Failed to get children from subtensor: {err_mg}")
        await get_total_stake_for_hk(wallet.hotkey.ss58_address, True)
        await _render_table(wallet.hotkey.ss58_address, children, True, netuid)

    return children


async def set_children(
    wallet: Wallet,
    subtensor: "SubtensorInterface",
    netuid: int,
    children: list[str],
    proportions: list[float],
    wait_for_inclusion: bool = True,
    wait_for_finalization: bool = True,
):
    """Set children hotkeys."""
    # Validate children SS58 addresses
    for child in children:
        if not is_valid_ss58_address(child):
            err_console.print(f":cross_mark:[red] Invalid SS58 address: {child}[/red]")
            return

    total_proposed = sum(proportions)
    if total_proposed > 1:
        raise ValueError(
            f"Invalid proportion: The sum of all proportions cannot be greater than 1. "
            f"Proposed sum of proportions is {total_proposed}."
        )

    children_with_proportions = list(zip(proportions, children))
    success, message = await set_children_extrinsic(
        subtensor=subtensor,
        wallet=wallet,
        netuid=netuid,
        hotkey=wallet.hotkey.ss58_address,
        children_with_proportions=children_with_proportions,
        prompt=True,
        wait_for_inclusion=wait_for_inclusion,
        wait_for_finalization=wait_for_finalization,
    )
    # Result
    if success:
        if wait_for_inclusion and wait_for_finalization:
            console.print("New Status:")
            await get_children(wallet, subtensor, netuid)
        console.print(":white_heavy_check_mark: [green]Set children hotkeys.[/green]")
    else:
        console.print(
            f":cross_mark:[red] Unable to set children hotkeys.[/red] {message}"
        )


async def revoke_children(
    wallet: Wallet,
    subtensor: "SubtensorInterface",
    netuid: int,
    wait_for_inclusion: bool = True,
    wait_for_finalization: bool = True,
):
    """
    Revokes the children hotkeys associated with a given network identifier (netuid).
    """

    success, message = await set_children_extrinsic(
        subtensor=subtensor,
        wallet=wallet,
        netuid=netuid,
        hotkey=wallet.hotkey.ss58_address,
        children_with_proportions=[],
        prompt=True,
        wait_for_inclusion=wait_for_inclusion,
        wait_for_finalization=wait_for_finalization,
    )

    # Result
    if success:
        if wait_for_finalization and wait_for_inclusion:
            await get_children(wallet, subtensor, netuid)
        console.print(
            ":white_heavy_check_mark: [green]Revoked children hotkeys.[/green]"
        )
    else:
        console.print(
            f":cross_mark:[red] Unable to revoke children hotkeys.[/red] {message}"
        )


async def childkey_take(
    wallet: Wallet,
    subtensor: "SubtensorInterface",
    netuid: int,
    take: Optional[float],
    wait_for_inclusion: bool = True,
    wait_for_finalization: bool = True,
    prompt: bool = True,
):
    """Get or Set childkey take."""

    def validate_take_value(take_value: float) -> bool:
        if not (0 <= take_value <= 0.18):
            err_console.print(
                f":cross_mark:[red] Invalid take value: {take_value}[/red]"
            )
            return False
        return True

    # Validate child SS58 addresses
    if not take:
        # print current Take, ask if change
        curr_take = await get_childkey_take(
            subtensor=subtensor, netuid=netuid, hotkey=wallet.hotkey.ss58_address
        )
        take = u16_to_float(curr_take)
        console.print(f"Current child take is: {take * 100:.2f}%")

        if not Confirm.ask("Would you like to change the child take?"):
            return
        new_take_str = Prompt.ask("Enter the new take value (between 0 and 0.18): ")
        try:
            new_take_value = float(new_take_str)
            if not validate_take_value(new_take_value):
                return
        except ValueError:
            err_console.print(
                ":cross_mark:[red] Invalid input. Please enter a number between 0 and 0.18.[/red]"
            )
            return
        take = new_take_value
    else:
        if not validate_take_value(take):
            return

    success, message = await set_childkey_take_extrinsic(
        subtensor=subtensor,
        wallet=wallet,
        netuid=netuid,
        hotkey=wallet.hotkey.ss58_address,
        take=take,
        prompt=prompt,
        wait_for_inclusion=wait_for_inclusion,
        wait_for_finalization=wait_for_finalization,
    )
    # Result
    if success:
        console.print(":white_heavy_check_mark: [green]Set childkey take.[/green]")
        console.print(
            f"The childkey take for {wallet.hotkey.ss58_address} is now set to {take * 100:.3f}%."
        )
    else:
        console.print(f":cross_mark:[red] Unable to set childkey take.[/red] {message}")
