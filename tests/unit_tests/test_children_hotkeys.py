"""Unit tests for children_hotkeys bug fixes."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bittensor_cli.src.commands.stake.children_hotkeys import (
    get_children,
    prepare_child_proportions,
    revoke_children,
    set_children,
)
from .conftest import HOTKEY_SS58, DEST_SS58, ALT_HOTKEY_SS58, _make_successful_receipt

PATCH_UNLOCK = patch(
    "bittensor_cli.src.commands.stake.children_hotkeys.unlock_key",
    side_effect=lambda *a, **k: SimpleNamespace(success=True, message=""),
)
PATCH_HOTKEY = patch(
    "bittensor_cli.src.commands.stake.children_hotkeys.get_hotkey_pub_ss58",
    return_value=HOTKEY_SS58,
)
PATCH_PRINT_EXT = patch(
    "bittensor_cli.src.commands.stake.children_hotkeys.print_extrinsic_id",
    new_callable=AsyncMock,
)


def _success_receipt():
    r = _make_successful_receipt()
    return (True, "Included.", r)


# -- Bug #1: revoke_children all-netuids passed None instead of netuid_ ------


@pytest.mark.asyncio
async def test_revoke_all_netuids_passes_each_netuid(mock_wallet, mock_subtensor):
    mock_subtensor.get_all_subnet_netuids = AsyncMock(return_value=[0, 1, 2])
    mock_subtensor.sign_and_send_extrinsic = AsyncMock(return_value=_success_receipt())
    mock_subtensor.query = AsyncMock(return_value=100)
    mock_subtensor.get_hyperparameter = AsyncMock(return_value=360)

    with PATCH_UNLOCK, PATCH_HOTKEY, PATCH_PRINT_EXT:
        await revoke_children(
            wallet=mock_wallet,
            subtensor=mock_subtensor,
            netuid=None,
            prompt=False,
            wait_for_inclusion=True,
            wait_for_finalization=False,
        )

    netuids_sent = [
        c.kwargs.get("call_params", c[1].get("call_params", {})).get("netuid")
        for c in mock_subtensor.substrate.compose_call.call_args_list
    ]
    assert None not in netuids_sent, f"None passed as netuid: {netuids_sent}"
    assert set(netuids_sent) == {1, 2}


# -- Bug #2: set_children proportions > 1.0 must be rejected -----------------


@pytest.mark.asyncio
async def test_set_children_rejects_proportions_over_one(mock_wallet, mock_subtensor):
    with PATCH_HOTKEY:
        await set_children(
            wallet=mock_wallet,
            subtensor=mock_subtensor,
            children=[DEST_SS58, ALT_HOTKEY_SS58],
            proportions=[0.6, 0.5],
            netuid=1,
            prompt=False,
        )
    mock_subtensor.substrate.compose_call.assert_not_called()


@pytest.mark.asyncio
async def test_set_children_valid_proportions_proceeds(mock_wallet, mock_subtensor):
    mock_subtensor.sign_and_send_extrinsic = AsyncMock(return_value=_success_receipt())
    mock_subtensor.query = AsyncMock(return_value=100)
    mock_subtensor.get_hyperparameter = AsyncMock(return_value=360)

    with PATCH_UNLOCK, PATCH_HOTKEY, PATCH_PRINT_EXT:
        await set_children(
            wallet=mock_wallet,
            subtensor=mock_subtensor,
            children=[DEST_SS58],
            proportions=[0.5],
            netuid=1,
            prompt=False,
        )
    mock_subtensor.substrate.compose_call.assert_called()


# -- Bug #3: get_children all-netuids returned None instead of data -----------


@pytest.mark.asyncio
async def test_get_children_all_netuids_returns_data(mock_wallet, mock_subtensor):
    children_data = [(9223372036854775808, DEST_SS58)]

    async def _get_children(hotkey, netuid):
        if netuid == 0:
            return (True, [], "")
        return (True, children_data, "")

    mock_subtensor.get_all_subnet_netuids = AsyncMock(return_value=[0, 1])
    mock_subtensor.get_children = AsyncMock(side_effect=_get_children)
    mock_subtensor.get_total_stake_for_hotkey = AsyncMock(
        return_value={
            HOTKEY_SS58: {1: MagicMock(tao=100.0)},
            DEST_SS58: {1: MagicMock(tao=50.0)},
        }
    )

    with (
        PATCH_HOTKEY,
        patch(
            "bittensor_cli.src.commands.stake.children_hotkeys.get_childkey_take",
            new_callable=AsyncMock,
            return_value=0,
        ),
    ):
        result = await get_children(
            wallet=mock_wallet,
            subtensor=mock_subtensor,
            netuid=None,
        )

    assert result is not None
    assert len(result) == 1
    assert result[0][0] == 1  # netuid


@pytest.mark.asyncio
async def test_get_children_single_netuid_returns_list(mock_wallet, mock_subtensor):
    mock_subtensor.get_children = AsyncMock(return_value=(True, [], ""))

    with PATCH_HOTKEY:
        result = await get_children(
            wallet=mock_wallet,
            subtensor=mock_subtensor,
            netuid=1,
        )
    assert result == []


# -- prepare_child_proportions ------------------------------------------------


def test_prepare_child_proportions():
    result = prepare_child_proportions([(0.3, DEST_SS58), (0.7, ALT_HOTKEY_SS58)])
    assert len(result) == 2
    assert sum(p for p, _ in result) <= 2**64 - 1
