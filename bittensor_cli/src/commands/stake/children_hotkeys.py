import asyncio
from typing import Optional

from bittensor_wallet import Wallet
from bittensor_wallet.errors import KeyFileError
from rich.prompt import Confirm, Prompt, IntPrompt
from rich.table import Table
from rich.text import Text
from substrateinterface.exceptions import SubstrateRequestException

from bittensor_cli.src.bittensor.balances import Balance
from bittensor_cli.src.bittensor.subtensor_interface import SubtensorInterface
from bittensor_cli.src.bittensor.utils import (
    console,
    err_console,
    float_to_u16,
    float_to_u64,
    u16_to_float,
    u64_to_float,
    is_valid_ss58_address,
    format_error_message,
)


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
    try:
        wallet.unlock_coldkey()
    except KeyFileError:
        return False, "There was an error unlocking your coldkey."

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
            if wait_for_inclusion:
                console.print(":white_heavy_check_mark: [green]Included[/green]")
            if wait_for_finalization:
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
    try:
        wallet.unlock_coldkey()
    except KeyFileError:
        return False, "There was an error unlocking your coldkey."

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
                if wait_for_inclusion:
                    console.print(":white_heavy_check_mark: [green]Included[/green]")
                if wait_for_finalization:
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

        except SubstrateRequestException as e:
            return (
                False,
                f"Exception occurred while setting childkey take: {format_error_message(e, subtensor.substrate)}",
            )


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
        err_console.print(
            f"Error querying ChildKeys: {format_error_message(e, subtensor.substrate)}"
        )
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

    if total > (2**64 - 1):
        excess = total - (2**64 - 1)
        if excess > (2**64 * 0.01):  # Example threshold of 1% of u64 max
            raise ValueError("Excess is too great to normalize proportions")
        largest_child_index = max(
            range(len(children_u64)), key=lambda i: children_u64[i][0]
        )
        children_u64[largest_child_index] = (
            children_u64[largest_child_index][0] - excess,
            children_u64[largest_child_index][1],
        )

    return children_u64


async def get_children(
    wallet: Wallet, subtensor: "SubtensorInterface", netuid: Optional[int] = None
):
    """
    Retrieves the child hotkeys for the specified wallet.

    Args:
    - wallet: The wallet object containing the hotkey information.
        Type: Wallet
    - subtensor: Interface to interact with the subtensor network.
        Type: SubtensorInterface
    - netuid: Optional subnet identifier. If not provided, retrieves data for all subnets.
        Type: Optional[int]

    Returns:
    - If netuid is specified, returns the list of child hotkeys for the given netuid.
        Type: List[tuple[int, str]]
    - If netuid is not specified, generates and prints a summary table of all child hotkeys across all subnets.
    """

    async def get_total_stake_for_hk(hotkey: str, parent: bool = False):
        """
        Fetches and displays the total stake for a specified hotkey from the Subtensor blockchain network.
        If `parent` is True, it prints the hotkey and its corresponding stake.

        Parameters:
        - hotkey (str): The hotkey for which the stake needs to be fetched.
        - parent (bool, optional): A flag to indicate whether the hotkey is the parent key. Defaults to False.

        Returns:
        - Balance: The total stake associated with the specified hotkey.
        """
        _result = await subtensor.substrate.query(
            module="SubtensorModule",
            storage_function="TotalHotkeyStake",
            params=[hotkey],
            reuse_block_hash=True,
        )
        stake = (
            Balance.from_rao(_result.value)
            if getattr(_result, "value", None)
            else Balance(0)
        )
        if parent:
            console.print(
                f"\nYour Hotkey: [bright_magenta]{hotkey}[/bright_magenta]  |  Total Stake: [dark_orange]{stake}t[/dark_orange]\n",
                end="",
                no_wrap=True,
            )

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
        parent_hotkey: str,
        netuid_children_tuples: list[tuple[int, list[tuple[int, str]]]],
    ):
        """
        Retrieves and renders children hotkeys and their details for a given parent hotkey.
        """
        # Initialize Rich table for pretty printing
        table = Table(
            header_style="bold white",
            border_style="bright_black",
            style="dim",
        )

        # Add columns to the table with specific styles
        table.add_column("Netuid", style="dark_orange", no_wrap=True, justify="center")
        table.add_column("Child Hotkey", style="bold bright_magenta")
        table.add_column("Proportion", style="bold cyan", no_wrap=True, justify="right")
        table.add_column(
            "Childkey Take", style="light_goldenrod2", no_wrap=True, justify="right"
        )
        table.add_column(
            "Current Stake Weight", style="bold red", no_wrap=True, justify="right"
        )

        if not netuid_children_tuples:
            console.print(table)
            console.print(
                f"[bold red]There are currently no child hotkeys with parent hotkey: {wallet.name} ({parent_hotkey}).[/bold red]"
            )
            return

        # calculate totals per subnet
        total_proportion = 0
        total_stake_weight = 0

        netuid_children_tuples.sort(
            key=lambda x: x[0]
        )  # Sort by netuid in ascending order

        for index, (netuid, children_) in enumerate(netuid_children_tuples):
            # calculate totals
            total_proportion_per_netuid = 0
            total_stake_weight_per_netuid = 0
            avg_take_per_netuid = 0

            hotkey_stake_dict = await subtensor.get_total_stake_for_hotkey(
                parent_hotkey
            )
            hotkey_stake = hotkey_stake_dict.get(parent_hotkey, Balance(0))

            children_info = []
            child_stakes = await asyncio.gather(
                *[get_total_stake_for_hk(c[1]) for c in children_]
            )
            child_takes = await asyncio.gather(*[get_take(c) for c in children_])
            for child, child_stake, child_take in zip(
                children_, child_stakes, child_takes
            ):
                proportion = child[0]
                child_hotkey = child[1]

                # add to totals
                avg_take_per_netuid += child_take

                proportion = u64_to_float(proportion)

                children_info.append(
                    (proportion, child_hotkey, child_stake, child_take)
                )

            children_info.sort(
                key=lambda x: x[0], reverse=True
            )  # sorting by proportion (highest first)

            for proportion, hotkey, stake, child_take in children_info:
                proportion_percent = proportion * 100  # Proportion in percent
                proportion_tao = hotkey_stake.tao * proportion  # Proportion in TAO

                total_proportion_per_netuid += proportion_percent

                # Conditionally format text
                proportion_str = f"{proportion_percent:.3f}% ({proportion_tao:.3f}τ)"
                stake_weight = stake.tao + proportion_tao
                total_stake_weight_per_netuid += stake_weight
                take_str = f"{child_take * 100:.3f}%"

                hotkey = Text(hotkey, style="italic red" if proportion == 0 else "")
                table.add_row(
                    str(netuid),
                    hotkey,
                    proportion_str,
                    take_str,
                    str(f"{stake_weight:.3f}"),
                )

            avg_take_per_netuid = avg_take_per_netuid / len(children_info)

            # add totals row for this netuid
            table.add_row(
                "",
                "[dim]Total[/dim]",
                f"[dim]{total_proportion_per_netuid:.3f}%[/dim]",
                f"[dim](avg) {avg_take_per_netuid * 100:.3f}%[/dim]",
                f"[dim]{total_stake_weight_per_netuid:.3f}τ[/dim]",
                style="dim",
            )

            # add to grand totals
            total_proportion += total_proportion_per_netuid
            total_stake_weight += total_stake_weight_per_netuid

            # Add a dividing line if there are more than one netuid
            if len(netuid_children_tuples) > 1:
                table.add_section()

        console.print(table)

    # Core logic for get_children
    if netuid is None:
        # get all netuids
        netuids = await subtensor.get_all_subnet_netuids()
        await get_total_stake_for_hk(wallet.hotkey.ss58_address, True)
        netuid_children_tuples = []
        for netuid in netuids:
            success, children, err_mg = await subtensor.get_children(
                wallet.hotkey.ss58_address, netuid
            )
            if children:
                netuid_children_tuples.append((netuid, children))
            if not success:
                err_console.print(
                    f"Failed to get children from subtensor {netuid}: {err_mg}"
                )
        await _render_table(wallet.hotkey.ss58_address, netuid_children_tuples)
    else:
        success, children, err_mg = await subtensor.get_children(
            wallet.hotkey.ss58_address, netuid
        )
        if not success:
            err_console.print(f"Failed to get children from subtensor: {err_mg}")
        await get_total_stake_for_hk(wallet.hotkey.ss58_address, True)
        if children:
            netuid_children_tuples = [(netuid, children)]
            await _render_table(wallet.hotkey.ss58_address, netuid_children_tuples)

        return children


async def set_children(
    wallet: Wallet,
    subtensor: "SubtensorInterface",
    children: list[str],
    proportions: list[float],
    netuid: Optional[int] = None,
    wait_for_inclusion: bool = True,
    wait_for_finalization: bool = True,
):
    """Set children hotkeys."""
    # Validate children SS58 addresses
    for child in children:
        if not is_valid_ss58_address(child):
            err_console.print(f":cross_mark:[red] Invalid SS58 address: {child}[/red]")
            return
        if child == wallet.hotkey.ss58_address:
            err_console.print(":cross_mark:[red] Cannot set yourself as a child.[/red]")
            return

    total_proposed = sum(proportions)
    if total_proposed > 1:
        raise ValueError(
            f"Invalid proportion: The sum of all proportions cannot be greater than 1. "
            f"Proposed sum of proportions is {total_proposed}."
        )

    children_with_proportions = list(zip(proportions, children))
    if netuid:
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
            console.print(
                ":white_heavy_check_mark: [green]Set children hotkeys.[/green]"
            )
        else:
            console.print(
                f":cross_mark:[red] Unable to set children hotkeys.[/red] {message}"
            )
    else:
        # set children on all subnets that parent is registered on
        netuids = await subtensor.get_all_subnet_netuids()
        for netuid in netuids:
            if netuid == 0:  # dont include root network
                continue
            console.print(f"Setting children on netuid {netuid}.")
            await set_children_extrinsic(
                subtensor=subtensor,
                wallet=wallet,
                netuid=netuid,
                hotkey=wallet.hotkey.ss58_address,
                children_with_proportions=children_with_proportions,
                prompt=False,
                wait_for_inclusion=True,
                wait_for_finalization=False,
            )
        console.print(
            ":white_heavy_check_mark: [green]Sent set children request for all subnets.[/green]"
        )


async def revoke_children(
    wallet: Wallet,
    subtensor: "SubtensorInterface",
    netuid: Optional[int] = None,
    wait_for_inclusion: bool = True,
    wait_for_finalization: bool = True,
):
    """
    Revokes the children hotkeys associated with a given network identifier (netuid).
    """
    if netuid:
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
    else:
        # revoke children from ALL netuids
        netuids = await subtensor.get_all_subnet_netuids()
        for netuid in netuids:
            if netuid == 0:  # dont include root network
                continue
            console.print(f"Revoking children from netuid {netuid}.")
            await set_children_extrinsic(
                subtensor=subtensor,
                wallet=wallet,
                netuid=netuid,
                hotkey=wallet.hotkey.ss58_address,
                children_with_proportions=[],
                prompt=False,
                wait_for_inclusion=True,
                wait_for_finalization=False,
            )
        console.print(
            ":white_heavy_check_mark: [green]Sent revoke children command. Finalization may take a few minutes.[/green]"
        )


async def childkey_take(
    wallet: Wallet,
    subtensor: "SubtensorInterface",
    take: Optional[float],
    hotkey: Optional[str] = None,
    netuid: Optional[int] = None,
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

    def print_all_takes(takes: list[tuple[int, float]], ss58: str):
        """Print table with netuids and Takes"""
        table = Table(
            title=f"Current Child Takes for [bright_magenta]{ss58}[/bright_magenta]"
        )
        table.add_column("Netuid", justify="center", style="cyan")
        table.add_column("Take (%)", justify="right", style="magenta")

        for netuid, take_value in takes:
            table.add_row(str(netuid), f"{take_value:.2f}%")

        console.print(table)

    async def display_chk_take(ss58, netuid):
        """Print single key take for hotkey and netuid"""
        chk_take = await get_childkey_take(
            subtensor=subtensor, netuid=netuid, hotkey=ss58
        )
        chk_take = u16_to_float(chk_take)
        console.print(
            f"Child take for {ss58} is: {chk_take * 100:.2f}% on netuid {netuid}."
        )

    async def chk_all_subnets(ss58):
        """Aggregate data for childkey take from all subnets"""
        netuids = await subtensor.get_all_subnet_netuids()
        takes = []
        for subnet in netuids:
            if subnet == 0:
                continue
            curr_take = await get_childkey_take(
                subtensor=subtensor, netuid=subnet, hotkey=ss58
            )
            if curr_take is not None:
                take_value = u16_to_float(curr_take)
                takes.append((subnet, take_value * 100))

        print_all_takes(takes, ss58)

    async def set_chk_take_subnet(subnet, chk_take):
        """Set the childkey take for a single subnet"""
        success, message = await set_childkey_take_extrinsic(
            subtensor=subtensor,
            wallet=wallet,
            netuid=subnet,
            hotkey=wallet.hotkey.ss58_address,
            take=chk_take,
            prompt=prompt,
            wait_for_inclusion=wait_for_inclusion,
            wait_for_finalization=wait_for_finalization,
        )
        # Result
        if success:
            console.print(":white_heavy_check_mark: [green]Set childkey take.[/green]")
            console.print(
                f"The childkey take for {wallet.hotkey.ss58_address} is now set to {take * 100:.2f}%."
            )
        else:
            console.print(
                f":cross_mark:[red] Unable to set childkey take.[/red] {message}"
            )

    # Print childkey take for other user and return (dont offer to change take rate)
    if hotkey and hotkey != wallet.hotkey.ss58_address:
        # display childkey take for other users
        if netuid:
            await display_chk_take(hotkey, netuid)
            if take:
                console.print(
                    f"Hotkey {hotkey} not associated with wallet {wallet.name}."
                )
            return
        else:
            # show childhotkey take on all subnets
            await chk_all_subnets(hotkey)
            if take:
                console.print(
                    f"Hotkey {hotkey} not associated with wallet {wallet.name}."
                )
            return

    # Validate child SS58 addresses
    if not take:
        # print current Take, ask if change
        if netuid:
            await display_chk_take(wallet.hotkey.ss58_address, netuid)
        else:
            # print take from all netuids
            await chk_all_subnets(wallet.hotkey.ss58_address)

        if not Confirm.ask("Would you like to change the child take?"):
            return
        new_take_str = Prompt.ask("Enter the new take value (between 0 and 0.18)")
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

    if netuid:
        await set_chk_take_subnet(subnet=netuid, chk_take=take)
        return
    else:
        new_take_netuids = IntPrompt.ask(
            "Enter netuid (leave blank for all)", default=None, show_default=True
        )

        if new_take_netuids:
            await set_chk_take_subnet(subnet=new_take_netuids, chk_take=take)
            return

        else:
            netuids = await subtensor.get_all_subnet_netuids()
            for netuid in netuids:
                if netuid == 0:
                    continue
                console.print(f"Sending to netuid {netuid} take of {take * 100:.2f}%")
                await set_childkey_take_extrinsic(
                    subtensor=subtensor,
                    wallet=wallet,
                    netuid=netuid,
                    hotkey=wallet.hotkey.ss58_address,
                    take=take,
                    prompt=False,
                    wait_for_inclusion=True,
                    wait_for_finalization=False,
                )
            console.print(
                f":white_heavy_check_mark: [green]Sent childkey take of {take * 100:.2f}% to all subnets.[/green]"
            )
