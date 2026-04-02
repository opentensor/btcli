"""
Unit tests for stake/move.py changes:

  - stake_move_transfer_selection: destination_hotkey pre-filled skips dest prompt
  - stake_move_transfer_selection: destination_hotkey=None triggers dest table prompt
  - stake_move_transfer_selection: no stakes raises ValueError
  - move_stake: interactive_selection=True propagates destination_hotkey to selection call
  - move_stake: interactive_selection=True + ValueError from selection returns (False, "")
"""

import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch, call

from bittensor_cli.src.bittensor.balances import Balance
from bittensor_cli.src.commands.stake.move import (
    stake_move_transfer_selection,
    move_stake,
)

MODULE = "bittensor_cli.src.commands.stake.move"

HOTKEY_A = "5CiQ1cV1MmMwsep7YP37QZKEgBgaVXeSPnETB5JBgwYRoXbP"
HOTKEY_B = "5HGjWAeFDfFCWPsjFQdVV2Msvz2XtMktvgocEZcCj68kUMaw"
COLDKEY = "5FHneW46xGXgs5mUiveU4sbTyGBzmstUspZC92UhjJM694ty"


def _make_stake(hotkey_ss58: str, netuid: int, tao: float):
    s = MagicMock()
    s.hotkey_ss58 = hotkey_ss58
    s.netuid = netuid
    s.stake = Balance.from_tao(tao)
    return s


@pytest.fixture
def wallet():
    w = MagicMock()
    w.coldkeypub.ss58_address = COLDKEY
    return w


@pytest.fixture
def subtensor():
    st = MagicMock()
    st.get_stake_for_coldkey = AsyncMock(
        return_value=[
            _make_stake(HOTKEY_A, 1, 10.0),
            _make_stake(HOTKEY_B, 2, 5.0),
        ]
    )
    st.fetch_coldkey_hotkey_identities = AsyncMock(
        return_value={"hotkeys": {}, "coldkeys": {}}
    )
    st.get_all_subnet_netuids = AsyncMock(return_value=[1, 2])
    return st


# ---------------------------------------------------------------------------
# stake_move_transfer_selection
# ---------------------------------------------------------------------------


class TestStakeMoveTransferSelection:
    @pytest.mark.asyncio
    async def test_no_stakes_raises_value_error(self, wallet, subtensor):
        """With no positive stakes, should raise ValueError."""
        subtensor.get_stake_for_coldkey = AsyncMock(return_value=[])
        with pytest.raises(ValueError):
            await stake_move_transfer_selection(subtensor, wallet)

    @pytest.mark.asyncio
    async def test_destination_hotkey_provided_skips_dest_prompt(
        self, wallet, subtensor
    ):
        """When destination_hotkey is pre-filled, the dest table/prompt is skipped
        and the provided value is returned as-is."""
        prompt_responses = [
            "0",  # origin hotkey index
            "1",  # origin netuid
            "10",  # amount
            "2",  # destination netuid
        ]
        with (
            patch(f"{MODULE}.Prompt.ask", side_effect=prompt_responses),
            patch(f"{MODULE}.console"),
            patch(
                f"{MODULE}.prompt_stake_amount",
                return_value=(Balance.from_tao(10), False),
            ),
        ):
            result = await stake_move_transfer_selection(
                subtensor, wallet, destination_hotkey=HOTKEY_B
            )

        assert result["destination_hotkey"] == HOTKEY_B

    @pytest.mark.asyncio
    async def test_destination_hotkey_none_prompts_for_dest(self, wallet, subtensor):
        """When destination_hotkey is None, the user is prompted to pick one
        from the table and the selected hotkey is returned."""
        prompt_responses = [
            "0",  # origin hotkey index
            "1",  # origin netuid
            "1",  # destination hotkey index (HOTKEY_B is index 1)
            "2",  # destination netuid
        ]
        with (
            patch(f"{MODULE}.Prompt.ask", side_effect=prompt_responses),
            patch(f"{MODULE}.console"),
            patch(
                f"{MODULE}.prompt_stake_amount",
                return_value=(Balance.from_tao(5), False),
            ),
        ):
            result = await stake_move_transfer_selection(subtensor, wallet)

        assert result["destination_hotkey"] == HOTKEY_B

    @pytest.mark.asyncio
    async def test_selection_returns_all_expected_keys(self, wallet, subtensor):
        """Return dict must contain all required keys."""
        prompt_responses = ["0", "1", "2"]
        with (
            patch(f"{MODULE}.Prompt.ask", side_effect=prompt_responses),
            patch(f"{MODULE}.console"),
            patch(
                f"{MODULE}.prompt_stake_amount",
                return_value=(Balance.from_tao(10), False),
            ),
        ):
            result = await stake_move_transfer_selection(
                subtensor, wallet, destination_hotkey=HOTKEY_B
            )

        assert set(result.keys()) == {
            "origin_hotkey",
            "origin_netuid",
            "amount",
            "stake_all",
            "destination_netuid",
            "destination_hotkey",
        }

    @pytest.mark.asyncio
    async def test_origin_hotkey_and_netuid_set_correctly(self, wallet, subtensor):
        """origin_hotkey and origin_netuid in the result match user selection."""
        prompt_responses = [
            "0",  # origin hotkey index → HOTKEY_A
            "1",  # origin netuid
            "2",  # destination netuid
        ]
        with (
            patch(f"{MODULE}.Prompt.ask", side_effect=prompt_responses),
            patch(f"{MODULE}.console"),
            patch(
                f"{MODULE}.prompt_stake_amount",
                return_value=(Balance.from_tao(10), False),
            ),
        ):
            result = await stake_move_transfer_selection(
                subtensor, wallet, destination_hotkey=HOTKEY_B
            )

        assert result["origin_hotkey"] == HOTKEY_A
        assert result["origin_netuid"] == 1


# ---------------------------------------------------------------------------
# move_stake — interactive_selection path
# ---------------------------------------------------------------------------


class TestMoveStakeInteractiveSelection:
    def _make_subtensor(self):
        st = MagicMock()
        st.substrate = MagicMock()
        st.substrate.get_chain_head = AsyncMock(return_value="0xabc")
        st.get_stake = AsyncMock(return_value=Balance.from_tao(0))
        return st

    def _make_wallet(self):
        w = MagicMock()
        w.coldkeypub.ss58_address = COLDKEY
        return w

    @pytest.mark.asyncio
    async def test_interactive_passes_destination_hotkey_to_selection(self):
        """move_stake passes the existing destination_hotkey into
        stake_move_transfer_selection so it is not re-prompted."""
        selection = {
            "origin_hotkey": HOTKEY_A,
            "origin_netuid": 1,
            "amount": 5.0,
            "stake_all": False,
            "destination_netuid": 2,
            "destination_hotkey": HOTKEY_B,
        }
        with patch(
            f"{MODULE}.stake_move_transfer_selection",
            new_callable=AsyncMock,
            return_value=selection,
        ) as mock_sel:
            # Patch the rest of move_stake so it doesn't try to do chain calls
            with patch(f"{MODULE}.get_movement_pricing", new_callable=AsyncMock):
                await move_stake(
                    subtensor=self._make_subtensor(),
                    wallet=self._make_wallet(),
                    origin_netuid=None,
                    origin_hotkey=None,
                    destination_netuid=None,
                    destination_hotkey=HOTKEY_B,
                    amount=None,
                    stake_all=False,
                    era=16,
                    interactive_selection=True,
                    prompt=False,
                    decline=False,
                )

        mock_sel.assert_awaited_once()
        _, kwargs = mock_sel.call_args
        # Third positional arg (or keyword) is destination_hotkey
        args = mock_sel.call_args[0]
        assert args[2] == HOTKEY_B

    @pytest.mark.asyncio
    async def test_interactive_value_error_returns_false(self):
        """If stake_move_transfer_selection raises ValueError,
        move_stake returns (False, '')."""
        with patch(
            f"{MODULE}.stake_move_transfer_selection",
            new_callable=AsyncMock,
            side_effect=ValueError,
        ):
            result = await move_stake(
                subtensor=self._make_subtensor(),
                wallet=self._make_wallet(),
                origin_netuid=None,
                origin_hotkey=None,
                destination_netuid=None,
                destination_hotkey=None,
                amount=None,
                stake_all=False,
                era=16,
                interactive_selection=True,
                prompt=False,
                decline=False,
            )

        assert result == (False, "")

    @pytest.mark.asyncio
    async def test_interactive_selection_values_used_in_stake(self):
        """Values from the selection dict are used downstream (not the original
        None args passed in)."""
        selection = {
            "origin_hotkey": HOTKEY_A,
            "origin_netuid": 1,
            "amount": 7.0,
            "stake_all": False,
            "destination_netuid": 2,
            "destination_hotkey": HOTKEY_B,
        }
        subtensor = self._make_subtensor()

        with (
            patch(
                f"{MODULE}.stake_move_transfer_selection",
                new_callable=AsyncMock,
                return_value=selection,
            ),
            patch(f"{MODULE}.get_movement_pricing", new_callable=AsyncMock),
        ):
            await move_stake(
                subtensor=subtensor,
                wallet=self._make_wallet(),
                origin_netuid=None,
                origin_hotkey=None,
                destination_netuid=None,
                destination_hotkey=None,
                amount=None,
                stake_all=False,
                era=16,
                interactive_selection=True,
                prompt=False,
                decline=False,
            )

        # get_stake should be called with the hotkeys from the selection
        stake_calls = subtensor.get_stake.call_args_list
        hotkeys_queried = {c.kwargs.get("hotkey_ss58") for c in stake_calls}
        assert HOTKEY_A in hotkeys_queried
        assert HOTKEY_B in hotkeys_queried
