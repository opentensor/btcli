import asyncio
import json
from typing import Optional

from bittensor_wallet import Wallet
from rich.prompt import Confirm, IntPrompt, FloatPrompt
from rich.table import Table
from rich.text import Text
from async_substrate_interface.errors import SubstrateRequestException

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
    unlock_key,
    json_console,
)


async def get_childkey_completion_block(
    subtensor: SubtensorInterface, netuid: int
) -> tuple[int, int]:
    """
    Calculates the block at which the childkey set request will complete
    """
    bh = await subtensor.substrate.get_chain_head()
    blocks_since_last_step_query = subtensor.query(
        "SubtensorModule", "BlocksSinceLastStep", params=[netuid], block_hash=bh
    )
    tempo_query = subtensor.get_hyperparameter(
        param_name="Tempo", netuid=netuid, block_hash=bh
    )
    block_number, blocks_since_last_step, tempo = await asyncio.gather(
        subtensor.substrate.get_block_number(block_hash=bh),
        blocks_since_last_step_query,
        tempo_query,
    )
    cooldown = block_number + 7200
    blocks_left_in_tempo = tempo - blocks_since_last_step
    next_tempo = block_number + blocks_left_in_tempo
    next_epoch_after_cooldown = (cooldown - next_tempo) % (tempo + 1) + cooldown
    return block_number, next_epoch_after_cooldown


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
                f"Do you want to revoke all children hotkeys for hotkey {hotkey} on netuid {netuid}?"
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
    if not (unlock_status := unlock_key(wallet, print_out=False)).success:
        return False, unlock_status.message

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
            return True, f"Successfully {operation.lower()} and Finalized."
        else:
            err_console.print(f":cross_mark: [red]Failed[/red]: {error_message}")
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
    if not (unlock_status := unlock_key(wallet, print_out=False)).success:
        return False, unlock_status.message

    with console.status(
        f":satellite: Setting childkey take on [white]{subtensor.network}[/white] ..."
    ):
        try:
            if 0 <= take <= 0.18:
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
                f"Exception occurred while setting childkey take: {format_error_message(e)}",
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
        childkey_take_ = await subtensor.query(
            module="SubtensorModule",
            storage_function="ChildkeyTake",
            params=[hotkey, netuid],
        )
        if childkey_take_:
            return int(childkey_take_)

    except SubstrateRequestException as e:
        err_console.print(f"Error querying ChildKeys: {format_error_message(e)}")
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
    # TODO rao asks separately for the hotkey from the user, should we do this, or the way we do it now?
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

    async def get_take(child: tuple, netuid__: int) -> float:
        """
        Get the take value for a given subtensor, hotkey, and netuid.

        Arguments:
            child: The hotkey to retrieve the take value for.
            netuid__: the netuid to retrieve the take value for.

        Returns:
            The take value as a float. If the take value is not available, it returns 0.

        """
        child_hotkey = child[1]
        take_u16 = await get_childkey_take(
            subtensor=subtensor, hotkey=child_hotkey, netuid=netuid__
        )
        if take_u16:
            return u16_to_float(take_u16)
        else:
            return 0

    async def _render_table(
        parent_hotkey: str,
        netuid_children_: list[tuple[int, list[tuple[int, str]]]],
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

        if not netuid_children_:
            console.print(table)
            console.print(
                f"[bold red]There are currently no child hotkeys with parent hotkey: "
                f"{wallet.name} | {wallet.hotkey_str} ({parent_hotkey}).[/bold red]"
            )
            return

        # calculate totals per subnet
        total_proportion = 0
        total_stake_weight = 0

        netuid_children_.sort(key=lambda x: x[0])  # Sort by netuid in ascending order
        unique_keys = set(
            [parent_hotkey]
            + [s for _, child_list in netuid_children_ for _, s in child_list]
        )
        hotkey_stake_dict = await subtensor.get_total_stake_for_hotkey(
            *unique_keys,
            netuids=[n[0] for n in netuid_children_],
        )
        parent_total = sum(hotkey_stake_dict[parent_hotkey].values())
        insert_text = (
            " "
            if netuid is None
            else f" on netuids: {', '.join(str(n[0]) for n in netuid_children_)} "
        )
        console.print(
            f"The total stake of parent hotkey '{parent_hotkey}'{insert_text}is {parent_total}."
        )

        for index, (child_netuid, children_) in enumerate(netuid_children_):
            # calculate totals
            total_proportion_per_netuid = 0
            total_stake_weight_per_netuid = 0
            avg_take_per_netuid = 0.0

            hotkey_stake: dict[int, Balance] = hotkey_stake_dict[parent_hotkey]

            children_info = []
            child_takes = await asyncio.gather(
                *[get_take(c, child_netuid) for c in children_]
            )
            for child, child_take in zip(children_, child_takes):
                proportion = child[0]
                child_hotkey = child[1]

                # add to totals
                avg_take_per_netuid += child_take

                converted_proportion = u64_to_float(proportion)

                children_info.append(
                    (
                        converted_proportion,
                        child_hotkey,
                        hotkey_stake_dict[child_hotkey][child_netuid],
                        child_take,
                    )
                )

            children_info.sort(
                key=lambda x: x[0], reverse=True
            )  # sorting by proportion (highest first)

            for proportion_, hotkey, stake, child_take in children_info:
                proportion_percent = proportion_ * 100  # Proportion in percent
                proportion_tao = (
                    hotkey_stake[child_netuid].tao * proportion_
                )  # Proportion in TAO

                total_proportion_per_netuid += proportion_percent

                # Conditionally format text
                proportion_str = f"{proportion_percent:.3f}% ({proportion_tao:.3f}τ)"
                stake_weight = stake.tao + proportion_tao
                total_stake_weight_per_netuid += stake_weight
                take_str = f"{child_take * 100:.3f}%"

                hotkey = Text(hotkey, style="italic red" if proportion_ == 0 else "")
                table.add_row(
                    str(child_netuid),
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
            if len(netuid_children_) > 1:
                table.add_section()

        console.print(table)

    # Core logic for get_children
    if netuid is None:
        # get all netuids
        netuids = await subtensor.get_all_subnet_netuids()
        netuid_children_tuples = []
        for netuid_ in netuids:
            success, children, err_mg = await subtensor.get_children(
                wallet.hotkey.ss58_address, netuid_
            )
            if children:
                netuid_children_tuples.append((netuid_, children))
            if not success:
                err_console.print(
                    f"Failed to get children from subtensor {netuid_}: {err_mg}"
                )
        await _render_table(wallet.hotkey.ss58_address, netuid_children_tuples)
    else:
        success, children, err_mg = await subtensor.get_children(
            wallet.hotkey.ss58_address, netuid
        )
        if not success:
            err_console.print(f"Failed to get children from subtensor: {err_mg}")
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
    prompt: bool = True,
    json_output: bool = False,
):
    """Set children hotkeys."""
    # Validate children SS58 addresses
    # TODO check to see if this should be allowed to be specified by user instead of pulling from wallet
    hotkey = wallet.hotkey.ss58_address
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
    successes = {}
    if netuid is not None:
        success, message = await set_children_extrinsic(
            subtensor=subtensor,
            wallet=wallet,
            netuid=netuid,
            hotkey=hotkey,
            children_with_proportions=children_with_proportions,
            prompt=prompt,
            wait_for_inclusion=wait_for_inclusion,
            wait_for_finalization=wait_for_finalization,
        )
        successes[netuid] = {
            "success": success,
            "error": message,
            "completion_block": None,
            "set_block": None,
        }
        # Result
        if success:
            if wait_for_inclusion and wait_for_finalization:
                current_block, completion_block = await get_childkey_completion_block(
                    subtensor, netuid
                )
                successes[netuid]["completion_block"] = completion_block
                successes[netuid]["set_block"] = current_block
                console.print(
                    f"Your childkey request has been submitted. It will be completed around block {completion_block}. "
                    f"The current block is {current_block}"
                )
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
        for netuid_ in netuids:
            if netuid_ == 0:  # dont include root network
                continue
            console.print(f"Setting children on netuid {netuid_}.")
            success, message = await set_children_extrinsic(
                subtensor=subtensor,
                wallet=wallet,
                netuid=netuid_,
                hotkey=hotkey,
                children_with_proportions=children_with_proportions,
                prompt=prompt,
                wait_for_inclusion=True,
                wait_for_finalization=False,
            )
            current_block, completion_block = await get_childkey_completion_block(
                subtensor, netuid_
            )
            successes[netuid_] = {
                "success": success,
                "error": message,
                "completion_block": completion_block,
                "set_block": current_block,
            }
            console.print(
                f"Your childkey request for netuid {netuid_} has been submitted. It will be completed around "
                f"block {completion_block}. The current block is {current_block}."
            )
        console.print(
            ":white_heavy_check_mark: [green]Sent set children request for all subnets.[/green]"
        )
    if json_output:
        json_console.print(json.dumps(successes))


async def revoke_children(
    wallet: Wallet,
    subtensor: "SubtensorInterface",
    netuid: Optional[int] = None,
    wait_for_inclusion: bool = True,
    wait_for_finalization: bool = True,
    prompt: bool = True,
    json_output: bool = False,
):
    """
    Revokes the children hotkeys associated with a given network identifier (netuid).
    """
    dict_output = {}
    if netuid is not None:
        success, message = await set_children_extrinsic(
            subtensor=subtensor,
            wallet=wallet,
            netuid=netuid,
            hotkey=wallet.hotkey.ss58_address,
            children_with_proportions=[],
            prompt=prompt,
            wait_for_inclusion=wait_for_inclusion,
            wait_for_finalization=wait_for_finalization,
        )
        dict_output[netuid] = {
            "success": success,
            "error": message,
            "set_block": None,
            "completion_block": None,
        }

        # Result
        if success:
            current_block, completion_block = await get_childkey_completion_block(
                subtensor, netuid
            )
            dict_output[netuid]["completion_block"] = completion_block
            dict_output[netuid]["set_block"] = current_block
            console.print(
                f":white_heavy_check_mark: Your childkey revocation request for netuid {netuid} has been submitted. "
                f"It will be completed around block {completion_block}. The current block is {current_block}"
            )
        else:
            console.print(
                f":cross_mark:[red] Unable to revoke children hotkeys.[/red] {message}"
            )
    else:
        # revoke children from ALL netuids
        netuids = await subtensor.get_all_subnet_netuids()
        for netuid_ in netuids:
            if netuid_ == 0:  # dont include root network
                continue
            console.print(f"Revoking children from netuid {netuid_}.")
            success, message = await set_children_extrinsic(
                subtensor=subtensor,
                wallet=wallet,
                netuid=netuid,
                hotkey=wallet.hotkey.ss58_address,
                children_with_proportions=[],
                prompt=prompt,
                wait_for_inclusion=True,
                wait_for_finalization=False,
            )
            dict_output[netuid_] = {
                "success": success,
                "error": message,
                "set_block": None,
                "completion_block": None,
            }
            if success:
                current_block, completion_block = await get_childkey_completion_block(
                    subtensor, netuid_
                )
                dict_output[netuid_]["completion_block"] = completion_block
                dict_output[netuid_]["set_block"] = current_block
                console.print(
                    f":white_heavy_check_mark: Your childkey revocation request for netuid {netuid_} has been "
                    f"submitted. It will be completed around block {completion_block}. The current block "
                    f"is {current_block}"
                )
            else:
                err_console.print(
                    f"Childkey revocation failed for netuid {netuid_}: {message}."
                )
    if json_output:
        json_console.print(json.dumps(dict_output))


async def childkey_take(
    wallet: Wallet,
    subtensor: "SubtensorInterface",
    take: Optional[float],
    hotkey: Optional[str] = None,
    netuid: Optional[int] = None,
    wait_for_inclusion: bool = True,
    wait_for_finalization: bool = True,
    prompt: bool = True,
) -> list[tuple[Optional[int], bool]]:
    """
    Get or Set childkey take.

    Returns:
        List of (netuid, success) for specified netuid (or all) and their success in setting take
    """

    def validate_take_value(take_value: float) -> bool:
        if not (0 <= take_value <= 0.18):
            err_console.print(
                f":cross_mark:[red] Invalid take value: {take_value}[/red]"
            )
            return False
        return True

    async def display_chk_take(ss58, take_netuid) -> float:
        """Print single key take for hotkey and netuid"""
        chk_take = await get_childkey_take(
            subtensor=subtensor, netuid=take_netuid, hotkey=ss58
        )
        if chk_take is None:
            chk_take = 0
        chk_take = u16_to_float(chk_take)
        console.print(
            f"Child take for {ss58} is: {chk_take * 100:.2f}% on netuid {take_netuid}."
        )
        return chk_take

    async def chk_all_subnets(ss58):
        """Aggregate data for childkey take from all subnets"""
        all_netuids = await subtensor.get_all_subnet_netuids()
        takes = []
        for subnet in all_netuids:
            if subnet == 0:
                continue
            curr_take = await get_childkey_take(
                subtensor=subtensor, netuid=subnet, hotkey=ss58
            )
            if curr_take is not None:
                take_value = u16_to_float(curr_take)
                takes.append((subnet, take_value * 100))
        table = Table(
            title=f"Current Child Takes for [bright_magenta]{ss58}[/bright_magenta]"
        )
        table.add_column("Netuid", justify="center", style="cyan")
        table.add_column("Take (%)", justify="right", style="magenta")

        for take_netuid, take_value in takes:
            table.add_row(str(take_netuid), f"{take_value:.2f}%")

        console.print(table)

    async def set_chk_take_subnet(subnet: int, chk_take: float) -> bool:
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
            return True
        else:
            console.print(
                f":cross_mark:[red] Unable to set childkey take.[/red] {message}"
            )
            return False

    # Print childkey take for other user and return (dont offer to change take rate)
    if not hotkey or hotkey == wallet.hotkey.ss58_address:
        hotkey = wallet.hotkey.ss58_address
    if hotkey != wallet.hotkey.ss58_address or not take:
        # display childkey take for other users
        if netuid:
            await display_chk_take(hotkey, netuid)
            if take:
                console.print(
                    f"Hotkey {hotkey} not associated with wallet {wallet.name}."
                )
                return [(netuid, False)]
        else:
            # show child hotkey take on all subnets
            await chk_all_subnets(hotkey)
            if take:
                console.print(
                    f"Hotkey {hotkey} not associated with wallet {wallet.name}."
                )
                return [(netuid, False)]

    # Validate child SS58 addresses
    if not take:
        if not Confirm.ask("Would you like to change the child take?"):
            return [(netuid, False)]
        new_take_value = -1.0
        while not validate_take_value(new_take_value):
            new_take_value = FloatPrompt.ask(
                "Enter the new take value (between 0 and 0.18)"
            )
        take = new_take_value
    else:
        if not validate_take_value(take):
            return [(netuid, False)]

    if netuid:
        return [(netuid, await set_chk_take_subnet(subnet=netuid, chk_take=take))]
    else:
        new_take_netuids = IntPrompt.ask(
            "Enter netuid (leave blank for all)", default=None, show_default=True
        )

        if new_take_netuids:
            return [
                (
                    new_take_netuids,
                    await set_chk_take_subnet(subnet=new_take_netuids, chk_take=take),
                )
            ]

        else:
            netuids = await subtensor.get_all_subnet_netuids()
            output_list = []
            for netuid_ in netuids:
                if netuid_ == 0:
                    continue
                console.print(f"Sending to netuid {netuid_} take of {take * 100:.2f}%")
                result = await set_childkey_take_extrinsic(
                    subtensor=subtensor,
                    wallet=wallet,
                    netuid=netuid_,
                    hotkey=wallet.hotkey.ss58_address,
                    take=take,
                    prompt=prompt,
                    wait_for_inclusion=True,
                    wait_for_finalization=False,
                )
                output_list.append((netuid_, result))
            console.print(
                f":white_heavy_check_mark: [green]Sent childkey take of {take * 100:.2f}% to all subnets.[/green]"
            )
            return output_list
