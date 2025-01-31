from typing import Optional, TYPE_CHECKING

import rich.prompt
from rich.table import Table

from bittensor_cli.src.bittensor.chain_data import DelegateInfoLite
from bittensor_cli.src.bittensor.utils import console

if TYPE_CHECKING:
    from bittensor_cli.src.bittensor.subtensor_interface import SubtensorInterface


async def select_delegate(subtensor: "SubtensorInterface", netuid: int):
    # Get a list of delegates and sort them by total stake in descending order
    delegates: list[DelegateInfoLite] = (
        await subtensor.get_delegates_by_netuid_light(netuid)
    ).sort(key=lambda x: x.total_stake, reverse=True)

    # Get registered delegates details.
    registered_delegate_info = await subtensor.get_delegate_identities()

    # Create a table to display delegate information
    table = Table(
        show_header=True,
        header_style="bold",
        border_style="rgb(7,54,66)",
        style="rgb(0,43,54)",
    )

    # Add columns to the table with specific styles
    table.add_column("Index", style="rgb(253,246,227)", no_wrap=True)
    table.add_column("Delegate Name", no_wrap=True)
    table.add_column("Hotkey SS58", style="rgb(211,54,130)", no_wrap=True)
    table.add_column("Owner SS58", style="rgb(133,153,0)", no_wrap=True)
    table.add_column("Take", style="rgb(181,137,0)", no_wrap=True)
    table.add_column(
        "Total Stake", style="rgb(38,139,210)", no_wrap=True, justify="right"
    )
    table.add_column(
        "Owner Stake", style="rgb(220,50,47)", no_wrap=True, justify="right"
    )
    # table.add_column("Return per 1000", style="rgb(108,113,196)", no_wrap=True, justify="right")
    # table.add_column("Total Daily Return", style="rgb(42,161,152)", no_wrap=True, justify="right")

    # List to store visible delegates
    visible_delegates = []

    def get_user_input() -> str:
        return rich.prompt.Prompt.ask(
            'Press Enter to scroll, enter a number (1-N) to select, or type "h" for help: ',
            choices=["", "h"] + [str(x) for x in range(1, len(delegates) - 1)],
            show_choices=True,
        )

    # TODO: Add pagination to handle large number of delegates more efficiently
    # Iterate through delegates and display their information

    def loop_selections() -> Optional[int]:
        idx = 0
        selected_idx = None
        while idx < len(delegates):
            if idx < len(delegates):
                delegate = delegates[idx]

                # Add delegate to visible list
                visible_delegates.append(delegate)

                # Add a row to the table with delegate information
                table.add_row(
                    str(idx),
                    registered_delegate_info[delegate.hotkey_ss58].name
                    if delegate.hotkey_ss58 in registered_delegate_info
                    else "",
                    delegate.hotkey_ss58[:5]
                    + "..."
                    + delegate.hotkey_ss58[-5:],  # Show truncated hotkey
                    delegate.owner_ss58[:5]
                    + "..."
                    + delegate.owner_ss58[-5:],  # Show truncated owner address
                    f"{delegate.take:.6f}",
                    f"τ{delegate.total_stake.tao:,.4f}",
                    f"τ{delegate.owner_stake.tao:,.4f}",
                    # f"τ{delegate.return_per_1000.tao:,.4f}",
                    # f"τ{delegate.total_daily_return.tao:,.4f}",
                )

            # Clear console and print updated table
            console.clear()
            console.print(table)

            # Prompt user for input
            user_input: str = get_user_input()

            # Add a help option to display information about each column
            if user_input == "h":
                console.print("\nColumn Information:")
                console.print(
                    "[rgb(253,246,227)]Index:[/rgb(253,246,227)] Position in the list of delegates"
                )
                console.print(
                    "[rgb(211,54,130)]Hotkey SS58:[/rgb(211,54,130)] Truncated public key of the delegate's hotkey"
                )
                console.print(
                    "[rgb(133,153,0)]Owner SS58:[/rgb(133,153,0)] Truncated public key of the delegate's owner"
                )
                console.print(
                    "[rgb(181,137,0)]Take:[/rgb(181,137,0)] Percentage of rewards the delegate takes"
                )
                console.print(
                    "[rgb(38,139,210)]Total Stake:[/rgb(38,139,210)] Total amount staked to this delegate"
                )
                console.print(
                    "[rgb(220,50,47)]Owner Stake:[/rgb(220,50,47)] Amount staked by the delegate owner"
                )
                console.print(
                    "[rgb(108,113,196)]Return per 1000:[/rgb(108,113,196)] Estimated return for 1000 Tao staked"
                )
                console.print(
                    "[rgb(42,161,152)]Total Daily Return:[/rgb(42,161,152)] Estimated total daily return for all stake"
                )
                user_input = get_user_input()

            # If user presses Enter, continue to next delegate
            if user_input and user_input != "h":
                selected_idx = int(user_input)
                break

            if idx < len(delegates):
                idx += 1

        return selected_idx

    # TODO( const ): uncomment for check
    # Add a confirmation step before returning the selected delegate
    # console.print(f"\nSelected delegate: [rgb(211,54,130)]{visible_delegates[selected_idx].hotkey_ss58}[/rgb(211,54,130)]")
    # console.print(f"Take: [rgb(181,137,0)]{visible_delegates[selected_idx].take:.6f}[/rgb(181,137,0)]")
    # console.print(f"Total Stake: [rgb(38,139,210)]{visible_delegates[selected_idx].total_stake}[/rgb(38,139,210)]")

    # confirmation = Prompt.ask("Do you want to proceed with this delegate? (y/n)")
    # if confirmation.lower() != 'yes' and confirmation.lower() != 'y':
    #     return select_delegate( subtensor, netuid )

    # Return the selected delegate
    while True:
        selected_idx_ = loop_selections()
        if selected_idx_ is None:
            if not rich.prompt.Confirm.ask(
                "You've reached the end of the list. You must make a selection. Loop through again?"
            ):
                raise IndexError
            else:
                continue
        else:
            return delegates[selected_idx_]
