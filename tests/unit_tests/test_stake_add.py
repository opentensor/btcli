from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bittensor_cli.src.bittensor.balances import Balance
from bittensor_cli.src.commands.stake.add import stake_add

from tests.unit_tests.conftest import COLDKEY_SS58 as TEST_SS58


class MockSubnetInfo:
    def __init__(self, netuid: int, price_tao: float):
        self.netuid = netuid
        self.price = Balance.from_tao(price_tao)
        self.is_dynamic = netuid != 0


def _sim_swap_side_effect():
    async def sim_swap_mock(origin_netuid, destination_netuid, amount):
        del origin_netuid, amount
        return SimpleNamespace(
            alpha_amount=Balance.from_tao(1).set_unit(destination_netuid),
            tao_fee=Balance.from_tao(0.1),
        )

    return AsyncMock(side_effect=sim_swap_mock)


@pytest.mark.asyncio
@pytest.mark.parametrize("safe_staking", [False, True])
async def test_stake_add_zero_price_does_not_raise(
    mock_wallet,
    mock_subtensor,
    safe_staking,
):
    mock_subtensor.sim_swap = _sim_swap_side_effect()
    mock_subtensor.all_subnets.return_value = [MockSubnetInfo(netuid=427, price_tao=0)]

    with patch(
        "bittensor_cli.src.commands.stake.add.confirm_action", return_value=False
    ):
        await stake_add(
            wallet=mock_wallet,
            subtensor=mock_subtensor,
            netuids=[427],
            stake_all=False,
            amount=10.0,
            prompt=True,
            decline=False,
            quiet=True,
            all_hotkeys=False,
            include_hotkeys=[TEST_SS58],
            exclude_hotkeys=[],
            safe_staking=safe_staking,
            rate_tolerance=0.05,
            allow_partial_stake=True,
            json_output=False,
            era=16,
            mev_protection=False,
            proxy=None,
        )

    assert mock_subtensor.substrate.compose_call.await_count == 1
    composed_call = mock_subtensor.substrate.compose_call.await_args.kwargs
    expected_fn = "add_stake_limit" if safe_staking else "add_stake"
    assert composed_call["call_function"] == expected_fn
    assert mock_subtensor.sim_swap.await_count == 1


@pytest.mark.asyncio
async def test_stake_add_mixed_prices_including_zero_does_not_raise(
    mock_wallet,
    mock_subtensor,
):
    mock_subtensor.sim_swap = _sim_swap_side_effect()
    mock_subtensor.all_subnets.return_value = [
        MockSubnetInfo(netuid=427, price_tao=0),
        MockSubnetInfo(netuid=1, price_tao=2.0),
    ]

    with patch(
        "bittensor_cli.src.commands.stake.add.confirm_action", return_value=False
    ):
        await stake_add(
            wallet=mock_wallet,
            subtensor=mock_subtensor,
            netuids=[427, 1],
            stake_all=False,
            amount=10.0,
            prompt=True,
            decline=False,
            quiet=True,
            all_hotkeys=False,
            include_hotkeys=[TEST_SS58],
            exclude_hotkeys=[],
            safe_staking=True,
            rate_tolerance=0.05,
            allow_partial_stake=True,
            json_output=False,
            era=16,
            mev_protection=False,
            proxy=None,
        )

    assert mock_subtensor.substrate.compose_call.await_count == 2
    assert mock_subtensor.sim_swap.await_count == 2


@pytest.mark.asyncio
async def test_stake_add_announce_only_forwarded(
    mock_wallet,
    mock_subtensor,
):
    """announce_only=True must be threaded through to sign_and_send_extrinsic.

    Regression test for https://github.com/latent-to/btcli/issues/898 — the flag
    was accepted by the CLI but silently dropped before reaching the extrinsic layer.
    """
    mock_subtensor.sim_swap = _sim_swap_side_effect()
    mock_subtensor.all_subnets.return_value = [
        MockSubnetInfo(netuid=1, price_tao=1.0),
    ]
    send_mock = AsyncMock(return_value=(True, "", None))
    mock_subtensor.sign_and_send_extrinsic = send_mock

    with (
        patch("bittensor_cli.src.commands.stake.add.confirm_action", return_value=True),
        patch("bittensor_cli.src.commands.stake.add.print_verbose"),
    ):
        await stake_add(
            wallet=mock_wallet,
            subtensor=mock_subtensor,
            netuids=[1],
            stake_all=False,
            amount=1.0,
            prompt=True,
            decline=False,
            quiet=True,
            all_hotkeys=False,
            include_hotkeys=[TEST_SS58],
            exclude_hotkeys=[],
            safe_staking=False,
            rate_tolerance=0.05,
            allow_partial_stake=True,
            json_output=False,
            era=16,
            mev_protection=False,
            proxy=None,
            announce_only=True,
        )

    assert send_mock.called, "sign_and_send_extrinsic was never invoked"
    _, kwargs = send_mock.call_args
    assert kwargs.get("announce_only") is True, (
        "announce_only=True was not forwarded to sign_and_send_extrinsic"
    )
