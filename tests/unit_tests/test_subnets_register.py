"""
Unit tests for subnets register command.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, Mock, patch
from bittensor_wallet import Wallet

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
    current_block=1000
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
    async def test_register_subnet_does_not_exist(self, mock_subtensor_base, mock_wallet):
        """Test registration fails when subnet does not exist."""
        mock_subtensor_base.subnet_exists = AsyncMock(return_value=False)

        with patch("bittensor_cli.src.commands.subnets.subnets.err_console") as mock_err_console:
            result = await register(
                wallet=mock_wallet,
                subtensor=mock_subtensor_base,
                netuid=1,
                era=None,
                json_output=False,
                prompt=False,
            )

            assert result is None
            mock_subtensor_base.subnet_exists.assert_awaited_once_with(netuid=1, block_hash="0xabc123")
            mock_err_console.print.assert_called_once()
            assert "does not exist" in str(mock_err_console.print.call_args)

    @pytest.mark.asyncio
    async def test_register_registration_not_allowed(self, mock_subtensor_base, mock_wallet):
        """Test registration fails when registration is not allowed."""
        with patch("bittensor_cli.src.commands.subnets.subnets.asyncio.gather") as mock_gather:
            mock_gather.return_value = create_gather_result(registration_allowed=False)

            with patch("bittensor_cli.src.commands.subnets.subnets.err_console") as mock_err_console:
                result = await register(
                    wallet=mock_wallet,
                    subtensor=mock_subtensor_base,
                    netuid=1,
                    era=None,
                    json_output=False,
                    prompt=False,
                )

                assert result is None
                mock_err_console.print.assert_called_once()
                assert "not allowed" in str(mock_err_console.print.call_args)

    @pytest.mark.asyncio
    async def test_register_registration_full(self, mock_subtensor_base, mock_wallet):
        """Test registration fails when registration is full for the interval."""
        # registrations_this_interval >= target * 3
        # next_adjustment_block = 900 + 360 = 1260, remaining = 1260 - 1000 = 260
        with patch("bittensor_cli.src.commands.subnets.subnets.asyncio.gather") as mock_gather:
            mock_gather.return_value = create_gather_result(registrations_current=3)

            with patch("bittensor_cli.src.commands.subnets.subnets.err_console") as mock_err_console:
                result = await register(
                    wallet=mock_wallet,
                    subtensor=mock_subtensor_base,
                    netuid=1,
                    era=None,
                    json_output=False,
                    prompt=False,
                )

                assert result is None
                mock_err_console.print.assert_called_once()
                call_str = str(mock_err_console.print.call_args)
                assert "full" in call_str
                assert "260 blocks" in call_str  # remaining_blocks = (900+360) - 1000 = 260

    @pytest.mark.asyncio
    async def test_register_insufficient_balance(self, mock_subtensor_base, mock_wallet):
        """Test registration fails when balance is insufficient."""
        with patch("bittensor_cli.src.commands.subnets.subnets.asyncio.gather") as mock_gather:
            mock_gather.side_effect = create_gather_side_effect(recycle_rao=10000000000, balance_tao=5.0)

            with patch("bittensor_cli.src.commands.subnets.subnets.err_console") as mock_err_console:
                result = await register(
                    wallet=mock_wallet,
                    subtensor=mock_subtensor_base,
                    netuid=1,
                    era=None,
                    json_output=False,
                    prompt=False,
                )

                assert result is None
                mock_err_console.print.assert_called_once()
                assert "Insufficient balance" in str(mock_err_console.print.call_args)

    @pytest.mark.asyncio
    async def test_register_success_netuid_0(self, mock_subtensor_base, mock_wallet):
        """Test successful registration to netuid 0 (root network)."""
        with (
            patch("bittensor_cli.src.commands.subnets.subnets.asyncio.gather") as mock_gather,
            patch("bittensor_cli.src.commands.subnets.subnets.root_register_extrinsic") as mock_root_register,
            patch("bittensor_cli.src.commands.subnets.subnets.err_console") as mock_err_console,
        ):
            mock_gather.side_effect = create_gather_side_effect()
            mock_root_register.return_value = (True, "Success", "0x123")

            result = await register(
                wallet=mock_wallet,
                subtensor=mock_subtensor_base,
                netuid=0,
                era=None,
                json_output=False,
                prompt=False,
            )

            # Verify root_register_extrinsic was called with correct parameters
            mock_root_register.assert_awaited_once()
            call_args = mock_root_register.call_args
            assert call_args[1]["wallet"] == mock_wallet
            assert call_args[1]["proxy"] is None
            
            # Verify no errors were printed (success case)
            mock_err_console.print.assert_not_called()


    @pytest.mark.asyncio
    async def test_register_with_proxy(self, mock_subtensor_base, mock_wallet):
        """Test registration with proxy address."""
        proxy_address = "5FHneW46xGXgs5mUiveU4sbTyGBzmstUspZC92UhjJM694ty"
        
        with (
            patch("bittensor_cli.src.commands.subnets.subnets.asyncio.gather") as mock_gather,
            patch("bittensor_cli.src.commands.subnets.subnets.burned_register_extrinsic") as mock_burned_register,
            patch("bittensor_cli.src.commands.subnets.subnets.err_console") as mock_err_console,
        ):
            mock_gather.side_effect = create_gather_side_effect()
            mock_burned_register.return_value = (True, "Success", "0x789")

            result = await register(
                wallet=mock_wallet,
                subtensor=mock_subtensor_base,
                netuid=1,
                era=None,
                json_output=False,
                prompt=False,
                proxy=proxy_address,
            )

            # Verify burned_register_extrinsic was called with correct proxy
            mock_burned_register.assert_awaited_once()
            call_args = mock_burned_register.call_args
            assert call_args[1]["proxy"] == proxy_address
            
            # Verify no errors were printed (success case)
            mock_err_console.print.assert_not_called()

    @pytest.mark.asyncio
    async def test_register_json_output_subnet_not_exist(self, mock_subtensor_base, mock_wallet):
        """Test JSON output when subnet does not exist."""
        mock_subtensor_base.subnet_exists = AsyncMock(return_value=False)

        with patch("bittensor_cli.src.commands.subnets.subnets.json_console") as mock_json_console:
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

    @pytest.mark.asyncio
    async def test_register_json_output_success(self, mock_subtensor_base, mock_wallet):
        """Test JSON output on successful registration."""
        with (
            patch("bittensor_cli.src.commands.subnets.subnets.asyncio.gather") as mock_gather,
            patch("bittensor_cli.src.commands.subnets.subnets.burned_register_extrinsic") as mock_burned_register,
            patch("bittensor_cli.src.commands.subnets.subnets.json_console") as mock_json_console,
        ):
            mock_gather.side_effect = create_gather_side_effect()
            mock_burned_register.return_value = (True, "Registration successful", "0xabc")

            result = await register(
                wallet=mock_wallet,
                subtensor=mock_subtensor_base,
                netuid=1,
                era=None,
                json_output=True,
                prompt=False,
            )

            mock_json_console.print.assert_called_once()
            call_str = str(mock_json_console.print.call_args)
            assert "success" in call_str
            assert "0xabc" in call_str

    @pytest.mark.asyncio
    async def test_register_user_cancels_prompt(self, mock_subtensor_base, mock_wallet):
        """Test registration when user cancels the confirmation prompt."""
        with (
            patch("bittensor_cli.src.commands.subnets.subnets.asyncio.gather") as mock_gather,
            patch("bittensor_cli.src.commands.subnets.subnets.Confirm") as mock_confirm,
            patch("bittensor_cli.src.commands.subnets.subnets.get_hotkey_pub_ss58") as mock_get_hotkey,
            patch("bittensor_cli.src.commands.subnets.subnets.burned_register_extrinsic") as mock_burned_register,
        ):
            mock_gather.side_effect = create_gather_side_effect()
            mock_confirm.ask.return_value = False  # User cancels
            mock_get_hotkey.return_value = "5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY"

            result = await register(
                wallet=mock_wallet,
                subtensor=mock_subtensor_base,
                netuid=1,
                era=None,
                json_output=False,
                prompt=True,
            )

            # User cancelled, so burned_register should not be called
            mock_burned_register.assert_not_awaited()
            mock_confirm.ask.assert_called_once()
