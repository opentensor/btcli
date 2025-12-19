"""
Unit tests for subnets register command.
"""

from asyncio import Future

import pytest
from unittest.mock import AsyncMock, MagicMock, Mock, patch
from async_substrate_interface.async_substrate import (
    AsyncExtrinsicReceipt,
    AsyncSubstrateInterface,
)
from async_substrate_interface.utils.storage import StorageKey
from bittensor_wallet import Wallet
from scalecodec import GenericCall

from bittensor_cli.src.commands.subnets.subnets import register
from bittensor_cli.src.bittensor.balances import Balance


@pytest.fixture
def mock_subtensor_base():
    """Base subtensor mock with common async methods."""
    mock = MagicMock()
    mock.substrate.get_chain_head = AsyncMock(return_value="0xabc123")
    mock.subnet_exists = AsyncMock(return_value=True)
    mock.substrate.get_block_number = AsyncMock(return_value=1000)
    mock.query = AsyncMock()
    mock.neuron_for_uid = AsyncMock()
    mock.get_hyperparameter = AsyncMock()
    mock.network = "finney"
    return mock


@pytest.fixture
def mock_wallet():
    """Standard mock wallet."""
    wallet = MagicMock(spec=Wallet)
    wallet.coldkeypub.ss58_address = "5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY"
    return wallet


def create_gather_result(
    registration_allowed=True,
    target_registrations=1,
    registrations_current=0,
    last_adjustment=900,
    adjustment_interval=360,
    current_block=1000,
):
    """Helper to create mock gather result for registration checks."""

    async def mock_result():
        return (
            registration_allowed,
            target_registrations,
            registrations_current,
            last_adjustment,
            adjustment_interval,
            current_block,
        )

    return mock_result()


def create_gather_side_effect(recycle_rao=1000000000, balance_tao=5.0):
    """Helper to create mock gather side effect for multiple calls."""
    call_count = [0]

    async def mock_side_effect(*args, **kwargs):
        call_count[0] += 1
        # First call - registration checks (6 values)
        if call_count[0] == 1:
            return (True, 1, 0, 900, 360, 1000)
        # Second call - balance and recycle (2 values)
        else:
            return (recycle_rao, Balance.from_tao(balance_tao))

    return mock_side_effect


class TestSubnetsRegister:
    """Tests for subnets register command."""

    @pytest.mark.asyncio
    async def test_register_subnet_does_not_exist(
        self, mock_subtensor_base, mock_wallet
    ):
        """Test registration fails when subnet does not exist."""
        mock_subtensor_base.subnet_exists = AsyncMock(return_value=False)

        with patch(
            "bittensor_cli.src.bittensor.utils.err_console"
        ) as mock_err_console:
            result = await register(
                wallet=mock_wallet,
                subtensor=mock_subtensor_base,
                netuid=1,
                era=None,
                json_output=False,
                prompt=False,
            )

            assert result is None
            mock_subtensor_base.subnet_exists.assert_awaited_once_with(
                netuid=1, block_hash="0xabc123"
            )
            mock_err_console.print.assert_called_once()
            assert "does not exist" in str(mock_err_console.print.call_args)

    @pytest.mark.asyncio
    async def test_register_json_output_subnet_not_exist(
        self, mock_subtensor_base, mock_wallet
    ):
        """Test JSON output when subnet does not exist."""
        mock_subtensor_base.subnet_exists = AsyncMock(return_value=False)

        with patch(
            "bittensor_cli.src.commands.subnets.subnets.json_console"
        ) as mock_json_console:
            result = await register(
                wallet=mock_wallet,
                subtensor=mock_subtensor_base,
                netuid=1,
                era=None,
                json_output=True,
                prompt=False,
            )

            assert result is None
            mock_json_console.print_json.assert_called_once()
            call_args = mock_json_console.print_json.call_args
            data = call_args[1]["data"]
            assert data["success"] is False
            assert "does not exist" in data["msg"]
            assert data["extrinsic_identifier"] is None
