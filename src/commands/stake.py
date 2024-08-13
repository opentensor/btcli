import asyncio
from math import floor
from typing import TYPE_CHECKING, Union

from bittensor_wallet import Wallet
from rich.prompt import Confirm
from rich.table import Table, Column
from rich.text import Text
from substrateinterface.exceptions import SubstrateRequestException

from src import Constants
from src.bittensor.balances import Balance
from src.utils import (
    get_delegates_details_from_github,
    get_hotkey_wallets_for_wallet,
    get_coldkey_wallets_for_path,
    console,
    err_console,
    is_valid_ss58_address,
    float_to_u64,
)

if TYPE_CHECKING:
    from src.subtensor_interface import SubtensorInterface


# Helpers and Extrinsics


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
    all_revoked = all(prop == 0.0 for prop, _ in children_with_proportions)

    operation = "Revoke all children hotkeys" if all_revoked else "Set children hotkeys"

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

    with console.status(
        f":satellite: {operation} on [white]{subtensor.network}[/white] ..."
    ):
        normalized_children = (
            prepare_child_proportions(children_with_proportions)
            if not all_revoked
            else children_with_proportions
        )
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


def prepare_child_proportions(children_with_proportions):
    """
    Convert proportions to u64 and normalize
    """
    children_u64 = [
        (float_to_u64(prop), child) for prop, child in children_with_proportions
    ]
    normalized_children = normalize_children_and_proportions(children_u64)
    return normalized_children


def normalize_children_and_proportions(
    children: list[tuple[int, str]],
) -> list[tuple[int, str]]:
    """
    Normalizes the proportions of children so that they sum to u64::MAX.
    """
    total = sum(prop for prop, _ in children)
    u64_max = 2**64 - 1
    normalized_children = [
        (int(floor(prop * (u64_max - 1) / total)), child) for prop, child in children
    ]
    sum_norm = sum(prop for prop, _ in normalized_children)

    # if the sum is more, subtract the excess from the first child
    if sum_norm > u64_max:
        if abs(sum_norm - u64_max) > 10:
            raise ValueError(
                "The sum of normalized proportions is out of the acceptable range."
            )
        normalized_children[0] = (
            normalized_children[0][0] - (sum_norm - (u64_max - 1)),
            normalized_children[0][1],
        )

    return normalized_children

# Commands


async def show(wallet: Wallet, subtensor: "SubtensorInterface", all_wallets: bool):
    """Show all stake accounts."""
    if all_wallets:
        wallets = get_coldkey_wallets_for_path(wallet.path)
    else:
        wallets = [wallet]

    registered_delegate_info = await get_delegates_details_from_github(
        Constants.delegates_detail_url
    )

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
            get_stakes_from_delegates(wallet_, block_hash=block_hash),
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

        hotkeys = get_hotkey_wallets_for_wallet(wallet_)
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
        wallet_, block_hash: str
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

    with console.status(":satellite:Retrieving account data..."):
        async with subtensor:
            block_hash_ = await subtensor.substrate.get_chain_head()
            accounts = await get_all_wallet_accounts(block_hash=block_hash_)

    await subtensor.substrate.close()

    total_stake = 0
    total_balance = 0
    total_rate = 0
    for acc in accounts:
        total_balance += acc["balance"].tao
        for key, value in acc["accounts"].items():
            total_stake += value["stake"].tao
            total_rate += float(value["rate"])
    table = Table(
        Column(
            "[overline white]Coldkey", footer_style="overline white", style="bold white"
        ),
        Column(
            "[overline white]Balance",
            "\u03c4{:.5f}".format(total_balance),
            footer_style="overline white",
            style="green",
        ),
        Column("[overline white]Account", footer_style="overline white", style="blue"),
        Column(
            "[overline white]Stake",
            "\u03c4{:.5f}".format(total_stake),
            footer_style="overline white",
            style="green",
        ),
        Column(
            "[overline white]Rate",
            "\u03c4{:.5f}/d".format(total_rate),
            footer_style="overline white",
            style="green",
        ),
        show_footer=True,
        pad_edge=False,
        box=None,
        expand=False,
    )
    for acc in accounts:
        table.add_row(acc["name"], acc["balance"], "", "")
        for key, value in acc["accounts"].items():
            table.add_row(
                "", "", value["name"], value["stake"], str(value["rate"]) + "/d"
            )
    console.print(table)


# class StakeCommand:
#
#
#     @staticmethod
#     def run(cli: "bittensor.cli"):
#         r"""Stake token of amount to hotkey(s)."""
#         try:
#             config = cli.config.copy()
#             subtensor: "bittensor.subtensor" = bittensor.subtensor(
#                 config=config, log_verbose=False
#             )
#             StakeCommand._run(cli, subtensor)
#         finally:
#             if "subtensor" in locals():
#                 subtensor.close()
#                 bittensor.logging.debug("closing subtensor connection")
#
#     @staticmethod
#     def _run(cli: "bittensor.cli", subtensor: "bittensor.subtensor"):
#         r"""Stake token of amount to hotkey(s)."""
#         config = cli.config.copy()
#         wallet = bittensor.wallet(config=config)
#
#         # Get the hotkey_names (if any) and the hotkey_ss58s.
#         hotkeys_to_stake_to: List[Tuple[Optional[str], str]] = []
#         if config.get("all_hotkeys"):
#             # Stake to all hotkeys.
#             all_hotkeys: List[bittensor.wallet] = get_hotkey_wallets_for_wallet(
#                 wallet=wallet
#             )
#             # Get the hotkeys to exclude. (d)efault to no exclusions.
#             hotkeys_to_exclude: List[str] = cli.config.get("hotkeys", d=[])
#             # Exclude hotkeys that are specified.
#             hotkeys_to_stake_to = [
#                 (wallet.hotkey_str, wallet.hotkey.ss58_address)
#                 for wallet in all_hotkeys
#                 if wallet.hotkey_str not in hotkeys_to_exclude
#             ]  # definitely wallets
#
#         elif config.get("hotkeys"):
#             # Stake to specific hotkeys.
#             for hotkey_ss58_or_hotkey_name in config.get("hotkeys"):
#                 if bittensor.utils.is_valid_ss58_address(hotkey_ss58_or_hotkey_name):
#                     # If the hotkey is a valid ss58 address, we add it to the list.
#                     hotkeys_to_stake_to.append((None, hotkey_ss58_or_hotkey_name))
#                 else:
#                     # If the hotkey is not a valid ss58 address, we assume it is a hotkey name.
#                     #  We then get the hotkey from the wallet and add it to the list.
#                     wallet_ = bittensor.wallet(
#                         config=config, hotkey=hotkey_ss58_or_hotkey_name
#                     )
#                     hotkeys_to_stake_to.append(
#                         (wallet_.hotkey_str, wallet_.hotkey.ss58_address)
#                     )
#         elif config.wallet.get("hotkey"):
#             # Only config.wallet.hotkey is specified.
#             #  so we stake to that single hotkey.
#             hotkey_ss58_or_name = config.wallet.get("hotkey")
#             if bittensor.utils.is_valid_ss58_address(hotkey_ss58_or_name):
#                 hotkeys_to_stake_to = [(None, hotkey_ss58_or_name)]
#             else:
#                 # Hotkey is not a valid ss58 address, so we assume it is a hotkey name.
#                 wallet_ = bittensor.wallet(config=config, hotkey=hotkey_ss58_or_name)
#                 hotkeys_to_stake_to = [
#                     (wallet_.hotkey_str, wallet_.hotkey.ss58_address)
#                 ]
#         else:
#             # Only config.wallet.hotkey is specified.
#             #  so we stake to that single hotkey.
#             assert config.wallet.hotkey is not None
#             hotkeys_to_stake_to = [
#                 (None, bittensor.wallet(config=config).hotkey.ss58_address)
#             ]
#
#         # Get coldkey balance
#         wallet_balance: Balance = subtensor.get_balance(wallet.coldkeypub.ss58_address)
#         final_hotkeys: List[Tuple[str, str]] = []
#         final_amounts: List[Union[float, Balance]] = []
#         for hotkey in tqdm(hotkeys_to_stake_to):
#             hotkey: Tuple[Optional[str], str]  # (hotkey_name (or None), hotkey_ss58)
#             if not subtensor.is_hotkey_registered_any(hotkey_ss58=hotkey[1]):
#                 # Hotkey is not registered.
#                 if len(hotkeys_to_stake_to) == 1:
#                     # Only one hotkey, error
#                     bittensor.__console__.print(
#                         f"[red]Hotkey [bold]{hotkey[1]}[/bold] is not registered. Aborting.[/red]"
#                     )
#                     return None
#                 else:
#                     # Otherwise, print warning and skip
#                     bittensor.__console__.print(
#                         f"[yellow]Hotkey [bold]{hotkey[1]}[/bold] is not registered. Skipping.[/yellow]"
#                     )
#                     continue
#
#             stake_amount_tao: float = config.get("amount")
#             if config.get("max_stake"):
#                 # Get the current stake of the hotkey from this coldkey.
#                 hotkey_stake: Balance = subtensor.get_stake_for_coldkey_and_hotkey(
#                     hotkey_ss58=hotkey[1], coldkey_ss58=wallet.coldkeypub.ss58_address
#                 )
#                 stake_amount_tao: float = config.get("max_stake") - hotkey_stake.tao
#
#                 # If the max_stake is greater than the current wallet balance, stake the entire balance.
#                 stake_amount_tao: float = min(stake_amount_tao, wallet_balance.tao)
#                 if (
#                     stake_amount_tao <= 0.00001
#                 ):  # Threshold because of fees, might create a loop otherwise
#                     # Skip hotkey if max_stake is less than current stake.
#                     continue
#                 wallet_balance = Balance.from_tao(wallet_balance.tao - stake_amount_tao)
#
#                 if wallet_balance.tao < 0:
#                     # No more balance to stake.
#                     break
#
#             final_amounts.append(stake_amount_tao)
#             final_hotkeys.append(hotkey)  # add both the name and the ss58 address.
#
#         if len(final_hotkeys) == 0:
#             # No hotkeys to stake to.
#             bittensor.__console__.print(
#                 "Not enough balance to stake to any hotkeys or max_stake is less than current stake."
#             )
#             return None
#
#         # Ask to stake
#         if not config.no_prompt:
#             if not Confirm.ask(
#                 f"Do you want to stake to the following keys from {wallet.name}:\n"
#                 + "".join(
#                     [
#                         f"    [bold white]- {hotkey[0] + ':' if hotkey[0] else ''}{hotkey[1]}: {f'{amount} {bittensor.__tao_symbol__}' if amount else 'All'}[/bold white]\n"
#                         for hotkey, amount in zip(final_hotkeys, final_amounts)
#                     ]
#                 )
#             ):
#                 return None
#
#         if len(final_hotkeys) == 1:
#             # do regular stake
#             return subtensor.add_stake(
#                 wallet=wallet,
#                 hotkey_ss58=final_hotkeys[0][1],
#                 amount=None if config.get("stake_all") else final_amounts[0],
#                 wait_for_inclusion=True,
#                 prompt=not config.no_prompt,
#             )
#
#         subtensor.add_stake_multiple(
#             wallet=wallet,
#             hotkey_ss58s=[hotkey_ss58 for _, hotkey_ss58 in final_hotkeys],
#             amounts=None if config.get("stake_all") else final_amounts,
#             wait_for_inclusion=True,
#             prompt=False,
#         )
#
#     @classmethod
#     def check_config(cls, config: "bittensor.config"):
#         if not config.is_set("wallet.name") and not config.no_prompt:
#             wallet_name = Prompt.ask("Enter wallet name", default=defaults.wallet.name)
#             config.wallet.name = str(wallet_name)
#
#         if (
#             not config.is_set("wallet.hotkey")
#             and not config.no_prompt
#             and not config.wallet.get("all_hotkeys")
#             and not config.wallet.get("hotkeys")
#         ):
#             hotkey = Prompt.ask("Enter hotkey name", default=defaults.wallet.hotkey)
#             config.wallet.hotkey = str(hotkey)
#
#         # Get amount.
#         if (
#             not config.get("amount")
#             and not config.get("stake_all")
#             and not config.get("max_stake")
#         ):
#             if not Confirm.ask(
#                 "Stake all Tao from account: [bold]'{}'[/bold]?".format(
#                     config.wallet.get("name", defaults.wallet.name)
#                 )
#             ):
#                 amount = Prompt.ask("Enter Tao amount to stake")
#                 try:
#                     config.amount = float(amount)
#                 except ValueError:
#                     console.print(
#                         ":cross_mark:[red]Invalid Tao amount[/red] [bold white]{}[/bold white]".format(
#                             amount
#                         )
#                     )
#                     sys.exit()
#             else:
#                 config.stake_all = True
#
#     @classmethod
#     def add_args(cls, parser: argparse.ArgumentParser):
#         stake_parser = parser.add_parser(
#             "add", help="""Add stake to your hotkey accounts from your coldkey."""
#         )
#         stake_parser.add_argument("--all", dest="stake_all", action="store_true")
#         stake_parser.add_argument("--uid", dest="uid", type=int, required=False)
#         stake_parser.add_argument("--amount", dest="amount", type=float, required=False)
#         stake_parser.add_argument(
#             "--max_stake",
#             dest="max_stake",
#             type=float,
#             required=False,
#             action="store",
#             default=None,
#             help="""Specify the maximum amount of Tao to have staked in each hotkey.""",
#         )
#         stake_parser.add_argument(
#             "--hotkeys",
#             "--exclude_hotkeys",
#             "--wallet.hotkeys",
#             "--wallet.exclude_hotkeys",
#             required=False,
#             action="store",
#             default=[],
#             type=str,
#             nargs="*",
#             help="""Specify the hotkeys by name or ss58 address. (e.g. hk1 hk2 hk3)""",
#         )
#         stake_parser.add_argument(
#             "--all_hotkeys",
#             "--wallet.all_hotkeys",
#             required=False,
#             action="store_true",
#             default=False,
#             help="""To specify all hotkeys. Specifying hotkeys will exclude them from this all.""",
#         )
#         bittensor.wallet.add_args(stake_parser)
#         bittensor.subtensor.add_args(stake_parser)


async def get_children(wallet: Wallet, subtensor: "SubtensorInterface", netuid: int):

    async def get_total_stake_for_child_hk(child: tuple):
        child_hotkey = child[1]
        _result = await subtensor.substrate.query(
            module="SubtensorModule",
            storage_function="TotalHotkeyStake",
            params=[child_hotkey],
            reuse_block_hash=True,
        )
        return (
            Balance.from_rao(_result.value)
            if getattr(_result, "value", None)
            else Balance(0)
        )

    async def render_table(
        hk: str,
        children: list[tuple[int, str]],
        nuid: int,
        prompt: bool = True
    ):
        # Initialize Rich table for pretty printing
        table = Table(
            Column("Index", style="cyan", no_wrap=True, justify="right"),
            Column("ChildHotkey", style="cyan", no_wrap=True),
            Column("Proportion", style="cyan", no_wrap=True, justify="right"),
            Column("Total Stake", style="cyan", no_wrap=True, justify="right"),
            show_header=True,
            header_style="bold magenta",
            border_style="green",
            style="green",
        )

        if not children:
            console.print(table)
            console.print(
                f"There are currently no child hotkeys on subnet {netuid} with ParentHotKey {hk}."
            )
            if prompt:
                command = f"btcli stake set_children --children <child_hotkey> --hotkey <parent_hotkey> --netuid {netuid} --proportion <float>"
                console.print(
                    f"To add a child hotkey you can run the command: [white]{command}[/white]"
                )
            return

        console.print("ParentHotKey:", style="cyan", no_wrap=True)
        console.print(hk)

        # calculate totals
        total_proportion = 0
        total_stake = 0

        children_info = []
        child_stakes = await asyncio.gather(
            *[get_total_stake_for_child_hk(c) for c in children]
        )
        for child, child_stake in zip(children, child_stakes):
            proportion = child[0]
            child_hotkey = child[1]

            # add to totals
            total_proportion += proportion
            total_stake += child_stake

            children_info.append((proportion, child_hotkey, child_stake))

        children_info.sort(
            key=lambda x: x[0], reverse=True
        )  # sorting by proportion (highest first)

        # add the children info to the table
        for i, (proportion, hotkey, stake) in enumerate(children_info, 1):
            proportion_str = Text(
                str(proportion), style="red" if proportion == 0 else ""
            )
            hotkey = Text(hotkey, style="red" if proportion == 0 else "")
            table.add_row(
                str(i),
                hotkey,
                proportion_str,
                str(stake),
            )

        # add totals row
        table.add_row("", "Total", str(total_proportion), str(total_stake), "")
        console.print(table)

    async with subtensor:
        err, children = await subtensor.get_children(wallet.hotkey, netuid)
        if err:
            err_console.print(f"Failed to get children from subtensor. {children[0]}")
        if not children:
            console.print("[yellow]No children found.[/yellow]")

        await render_table(wallet.hotkey, children, netuid)

    await subtensor.substrate.close()

    return children


async def set_children(
    wallet: Wallet,
    subtensor: "SubtensorInterface",
    netuid: int,
    children: list[str],
    proportions: list[float],
):
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

    async with subtensor:
        success, message = await set_children_extrinsic(
            subtensor=subtensor,
            wallet=wallet,
            netuid=netuid,
            hotkey=wallet.hotkey.ss58_address,
            children_with_proportions=children_with_proportions,
            prompt=True,
        )
    await subtensor.substrate.close()
    # Result
    if success:
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
    wait_for_finalization: bool = False,
):
    """
    Revokes the children hotkeys associated with a given network identifier (netuid).

    Parameters:
    - wallet: An instance of the Wallet class representing the user's wallet.
    - subtensor: An instance of the SubtensorInterface class.
    - netuid: An integer representing the network identifier.
    - wait_for_inclusion: A boolean indicating whether to wait for the transaction to be included in a block. Defaults to True.
    - wait_for_finalization: A boolean indicating whether to wait for the transaction to be finalized. Defaults to False.

    Returns:
    None

    Example:
    >>> wallet = Wallet()
    >>> subtensor = SubtensorInterface()
    >>> revoke_children(wallet, subtensor, 12345, wait_for_inclusion=True)
    """
    # print table with diff prompts
    status, current_children = await subtensor.get_children(wallet.hotkey.ss58_address, netuid)
    # Validate children SS58 addresses
    for child in current_children:
        if not is_valid_ss58_address(child):
            err_console.print(f":cross_mark:[red] Invalid SS58 address: {child}[/red]")
            return

    # Prepare children with zero proportions
    children_with_zero_proportions = [(0.0, child[1]) for child in current_children]

    async with subtensor:
        success, message = await set_children_extrinsic(
            subtensor=subtensor,
            wallet=wallet,
            netuid=netuid,
            hotkey=wallet.hotkey.ss58_address,
            children_with_proportions=children_with_zero_proportions,
            prompt=True,
        )
    await subtensor.substrate.close()
    # Result
    if success:
        if wait_for_finalization and wait_for_inclusion:
            await get_children(wallet, subtensor, netuid)
        console.print(":white_heavy_check_mark: [green]Revoked children hotkeys.[/green]")
    else:
        console.print(
            f":cross_mark:[red] Unable to revoke children hotkeys.[/red] {message}"
        )
