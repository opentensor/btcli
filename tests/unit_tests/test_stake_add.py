from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bittensor_cli.src.bittensor.balances import Balance
from bittensor_cli.src.commands.stake.add import stake_add


TEST_SS58 = "5FHneW46xGXgs5mUiveU4sbTyGBzmstUspZC92UhjJM694ty"


class MockSubnetInfo:
    def __init__(self, netuid: int, price_tao: float):
        self.netuid = netuid
        self.price = Balance.from_tao(price_tao)
        self.is_dynamic = netuid != 0


@pytest.fixture
def mock_wallet():
    return SimpleNamespace(
        coldkeypub=SimpleNamespace(ss58_address=TEST_SS58),
        path="/tmp",
        name="test_wallet",
    )


@pytest.fixture
def mock_subtensor():
    async def sim_swap_mock(origin_netuid, destination_netuid, amount):
        del origin_netuid, amount
        return SimpleNamespace(
            alpha_amount=Balance.from_tao(1).set_unit(destination_netuid),
            tao_fee=Balance.from_tao(0.1),
        )

    return SimpleNamespace(
        substrate=SimpleNamespace(
            get_chain_head=AsyncMock(return_value="0xabc"),
            compose_call=AsyncMock(return_value=SimpleNamespace()),
        ),
        network="test",
        all_subnets=AsyncMock(return_value=[]),
        get_stake_for_coldkey=AsyncMock(return_value=[]),
        get_balance=AsyncMock(return_value=Balance.from_tao(100)),
        get_extrinsic_fee=AsyncMock(return_value=Balance.from_tao(0.01)),
        sim_swap=AsyncMock(side_effect=sim_swap_mock),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("safe_staking", [False, True])
async def test_stake_add_zero_price_does_not_raise(
    mock_wallet,
    mock_subtensor,
    safe_staking,
):
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
