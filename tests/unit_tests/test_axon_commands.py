"""
Unit tests for axon commands (reset and set).
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, Mock, patch
from bittensor_wallet import Wallet

from bittensor_cli.src.bittensor.extrinsics.serving import (
    reset_axon_extrinsic,
    set_axon_extrinsic,
    ip_to_int,
)


class TestIpToInt:
    """Tests for IP address to integer conversion."""

    def test_ipv4_conversion(self):
        """Test IPv4 address conversion."""
        assert ip_to_int("0.0.0.0") == 0
        assert ip_to_int("127.0.0.1") == 2130706433
        assert ip_to_int("192.168.1.1") == 3232235777
        assert ip_to_int("255.255.255.255") == 4294967295

    def test_ipv6_conversion(self):
        """Test IPv6 address conversion."""
        # IPv6 loopback
        result = ip_to_int("::1")
        assert result == 1
        
        # IPv6 address
        result = ip_to_int("2001:db8::1")
        assert result > 0

    def test_invalid_ip_raises_error(self):
        """Test that invalid IP addresses raise errors."""
        with pytest.raises(Exception):
            ip_to_int("invalid.ip.address")
        
        with pytest.raises(Exception):
            ip_to_int("256.256.256.256")


class TestResetAxonExtrinsic:
    """Tests for reset_axon_extrinsic function."""

    @pytest.mark.asyncio
    async def test_reset_axon_success(self):
        """Test successful axon reset."""
        # Setup mocks
        mock_subtensor = MagicMock()
        mock_subtensor.substrate.compose_call = AsyncMock(return_value="mock_call")
        mock_response = MagicMock()
        mock_response.is_success = AsyncMock(return_value=True)
        mock_response.get_extrinsic_identifier = AsyncMock(return_value="0x123")
        mock_subtensor.sign_and_send_extrinsic = AsyncMock(
            return_value=(True, "", mock_response)
        )
        
        mock_wallet = MagicMock(spec=Wallet)
        mock_wallet.hotkey.ss58_address = "5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY"
        
        with (
            patch("bittensor_cli.src.bittensor.extrinsics.serving.unlock_key") as mock_unlock,
            patch("bittensor_cli.src.bittensor.extrinsics.serving.print_extrinsic_id", new_callable=AsyncMock),
        ):
            mock_unlock.return_value = MagicMock(success=True)
            
            # Execute
            success, message = await reset_axon_extrinsic(
                subtensor=mock_subtensor,
                wallet=mock_wallet,
                netuid=1,
                prompt=False,
                wait_for_inclusion=True,
                wait_for_finalization=False,
            )
            
            # Verify
            assert success is True
            assert "successfully" in message.lower()
            
            # Verify compose_call was called with correct parameters
            mock_subtensor.substrate.compose_call.assert_called_once()
            call_args = mock_subtensor.substrate.compose_call.call_args
            assert call_args[1]["call_module"] == "SubtensorModule"
            assert call_args[1]["call_function"] == "serve_axon"
            assert call_args[1]["call_params"]["netuid"] == 1
            assert call_args[1]["call_params"]["ip"] == 0  # 0.0.0.0 as int
            assert call_args[1]["call_params"]["port"] == 0
            assert call_args[1]["call_params"]["ip_type"] == 4

    @pytest.mark.asyncio
    async def test_reset_axon_unlock_failure(self):
        """Test axon reset when hotkey unlock fails."""
        mock_subtensor = MagicMock()
        mock_wallet = MagicMock(spec=Wallet)
        
        with patch("bittensor_cli.src.bittensor.extrinsics.serving.unlock_key") as mock_unlock:
            mock_unlock.return_value = MagicMock(success=False)
            
            success, message = await reset_axon_extrinsic(
                subtensor=mock_subtensor,
                wallet=mock_wallet,
                netuid=1,
                prompt=False,
            )
            
            assert success is False
            assert "unlock" in message.lower()

    @pytest.mark.asyncio
    async def test_reset_axon_user_cancellation(self):
        """Test axon reset when user cancels prompt."""
        mock_subtensor = MagicMock()
        mock_wallet = MagicMock(spec=Wallet)
        mock_wallet.hotkey.ss58_address = "5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY"
        
        with (
            patch("bittensor_cli.src.bittensor.extrinsics.serving.unlock_key") as mock_unlock,
            patch("bittensor_cli.src.bittensor.extrinsics.serving.Confirm") as mock_confirm,
        ):
            mock_unlock.return_value = MagicMock(success=True)
            mock_confirm.ask.return_value = False
            
            success, message = await reset_axon_extrinsic(
                subtensor=mock_subtensor,
                wallet=mock_wallet,
                netuid=1,
                prompt=True,
            )
            
            assert success is False
            assert "cancelled" in message.lower()

    @pytest.mark.asyncio
    async def test_reset_axon_extrinsic_failure(self):
        """Test axon reset when extrinsic submission fails."""
        mock_subtensor = MagicMock()
        mock_subtensor.substrate.compose_call = AsyncMock(return_value="mock_call")
        mock_subtensor.sign_and_send_extrinsic = AsyncMock(
            return_value=(False, "Network error", None)
        )
        
        mock_wallet = MagicMock(spec=Wallet)
        mock_wallet.hotkey.ss58_address = "5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY"
        
        with patch("bittensor_cli.src.bittensor.extrinsics.serving.unlock_key") as mock_unlock:
            mock_unlock.return_value = MagicMock(success=True)
            
            success, message = await reset_axon_extrinsic(
                subtensor=mock_subtensor,
                wallet=mock_wallet,
                netuid=1,
                prompt=False,
            )
            
            assert success is False
            assert "Network error" in message


class TestSetAxonExtrinsic:
    """Tests for set_axon_extrinsic function."""

    @pytest.mark.asyncio
    async def test_set_axon_success(self):
        """Test successful axon set."""
        mock_subtensor = MagicMock()
        mock_subtensor.substrate.compose_call = AsyncMock(return_value="mock_call")
        mock_response = MagicMock()
        mock_response.is_success = AsyncMock(return_value=True)
        mock_response.get_extrinsic_identifier = AsyncMock(return_value="0x123")
        mock_subtensor.sign_and_send_extrinsic = AsyncMock(
            return_value=(True, "", mock_response)
        )
        
        mock_wallet = MagicMock(spec=Wallet)
        mock_wallet.hotkey.ss58_address = "5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY"
        
        with (
            patch("bittensor_cli.src.bittensor.extrinsics.serving.unlock_key") as mock_unlock,
            patch("bittensor_cli.src.bittensor.extrinsics.serving.print_extrinsic_id", new_callable=AsyncMock),
        ):
            mock_unlock.return_value = MagicMock(success=True)
            
            success, message = await set_axon_extrinsic(
                subtensor=mock_subtensor,
                wallet=mock_wallet,
                netuid=1,
                ip="192.168.1.100",
                port=8091,
                ip_type=4,
                protocol=4,
                prompt=False,
                wait_for_inclusion=True,
                wait_for_finalization=False,
            )
            
            assert success is True
            assert "successfully" in message.lower()
            assert "192.168.1.100:8091" in message
            
            # Verify compose_call was called with correct parameters
            mock_subtensor.substrate.compose_call.assert_called_once()
            call_args = mock_subtensor.substrate.compose_call.call_args
            assert call_args[1]["call_module"] == "SubtensorModule"
            assert call_args[1]["call_function"] == "serve_axon"
            assert call_args[1]["call_params"]["netuid"] == 1
            assert call_args[1]["call_params"]["port"] == 8091
            assert call_args[1]["call_params"]["ip_type"] == 4
            assert call_args[1]["call_params"]["protocol"] == 4

    @pytest.mark.asyncio
    async def test_set_axon_invalid_port(self):
        """Test axon set with invalid port number."""
        mock_subtensor = MagicMock()
        mock_wallet = MagicMock(spec=Wallet)
        
        # Test port too high
        success, message = await set_axon_extrinsic(
            subtensor=mock_subtensor,
            wallet=mock_wallet,
            netuid=1,
            ip="192.168.1.100",
            port=70000,
            prompt=False,
        )
        
        assert success is False
        assert "Invalid port" in message
        
        # Test negative port
        success, message = await set_axon_extrinsic(
            subtensor=mock_subtensor,
            wallet=mock_wallet,
            netuid=1,
            ip="192.168.1.100",
            port=-1,
            prompt=False,
        )
        
        assert success is False
        assert "Invalid port" in message

    @pytest.mark.asyncio
    async def test_set_axon_invalid_ip(self):
        """Test axon set with invalid IP address."""
        mock_subtensor = MagicMock()
        mock_wallet = MagicMock(spec=Wallet)
        
        success, message = await set_axon_extrinsic(
            subtensor=mock_subtensor,
            wallet=mock_wallet,
            netuid=1,
            ip="invalid.ip.address",
            port=8091,
            prompt=False,
        )
        
        assert success is False
        assert "Invalid IP" in message

    @pytest.mark.asyncio
    async def test_set_axon_unlock_failure(self):
        """Test axon set when hotkey unlock fails."""
        mock_subtensor = MagicMock()
        mock_wallet = MagicMock(spec=Wallet)
        
        with patch("bittensor_cli.src.bittensor.extrinsics.serving.unlock_key") as mock_unlock:
            mock_unlock.return_value = MagicMock(success=False)
            
            success, message = await set_axon_extrinsic(
                subtensor=mock_subtensor,
                wallet=mock_wallet,
                netuid=1,
                ip="192.168.1.100",
                port=8091,
                prompt=False,
            )
            
            assert success is False
            assert "unlock" in message.lower()

    @pytest.mark.asyncio
    async def test_set_axon_user_cancellation(self):
        """Test axon set when user cancels prompt."""
        mock_subtensor = MagicMock()
        mock_wallet = MagicMock(spec=Wallet)
        mock_wallet.hotkey.ss58_address = "5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY"
        
        with (
            patch("bittensor_cli.src.bittensor.extrinsics.serving.unlock_key") as mock_unlock,
            patch("bittensor_cli.src.bittensor.extrinsics.serving.Confirm") as mock_confirm,
        ):
            mock_unlock.return_value = MagicMock(success=True)
            mock_confirm.ask.return_value = False
            
            success, message = await set_axon_extrinsic(
                subtensor=mock_subtensor,
                wallet=mock_wallet,
                netuid=1,
                ip="192.168.1.100",
                port=8091,
                prompt=True,
            )
            
            assert success is False
            assert "cancelled" in message.lower()

    @pytest.mark.asyncio
    async def test_set_axon_with_ipv6(self):
        """Test axon set with IPv6 address."""
        mock_subtensor = MagicMock()
        mock_subtensor.substrate.compose_call = AsyncMock(return_value="mock_call")
        mock_response = MagicMock()
        mock_response.is_success = AsyncMock(return_value=True)
        mock_response.get_extrinsic_identifier = AsyncMock(return_value="0x123")
        mock_subtensor.sign_and_send_extrinsic = AsyncMock(
            return_value=(True, "", mock_response)
        )
        
        mock_wallet = MagicMock(spec=Wallet)
        mock_wallet.hotkey.ss58_address = "5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY"
        
        with (
            patch("bittensor_cli.src.bittensor.extrinsics.serving.unlock_key") as mock_unlock,
            patch("bittensor_cli.src.bittensor.extrinsics.serving.print_extrinsic_id", new_callable=AsyncMock),
        ):
            mock_unlock.return_value = MagicMock(success=True)
            
            success, message = await set_axon_extrinsic(
                subtensor=mock_subtensor,
                wallet=mock_wallet,
                netuid=1,
                ip="2001:db8::1",
                port=8091,
                ip_type=6,
                protocol=4,
                prompt=False,
            )
            
            assert success is True
            
            # Verify ip_type was set to 6
            call_args = mock_subtensor.substrate.compose_call.call_args
            assert call_args[1]["call_params"]["ip_type"] == 6

    @pytest.mark.asyncio
    async def test_set_axon_exception_handling(self):
        """Test axon set handles exceptions gracefully."""
        mock_subtensor = MagicMock()
        mock_subtensor.substrate.compose_call = AsyncMock(
            side_effect=Exception("Unexpected error")
        )
        
        mock_wallet = MagicMock(spec=Wallet)
        mock_wallet.hotkey.ss58_address = "5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY"
        
        with patch("bittensor_cli.src.bittensor.extrinsics.serving.unlock_key") as mock_unlock:
            mock_unlock.return_value = MagicMock(success=True)
            
            success, message = await set_axon_extrinsic(
                subtensor=mock_subtensor,
                wallet=mock_wallet,
                netuid=1,
                ip="192.168.1.100",
                port=8091,
                prompt=False,
            )
            
            assert success is False
            assert len(message) > 0


class TestAxonCLICommands:
    """Tests for CLI command handlers."""

    @patch("bittensor_cli.cli.serving")
    def test_axon_reset_command_handler(self, mock_serving):
        """Test axon reset CLI command handler."""
        from bittensor_cli.cli import CLIManager
        
        cli_manager = CLIManager()
        mock_serving.reset_axon_extrinsic = AsyncMock(
            return_value=(True, "Success")
        )
        
        with (
            patch.object(cli_manager, "verbosity_handler"),
            patch.object(cli_manager, "wallet_ask") as mock_wallet_ask,
            patch.object(cli_manager, "initialize_chain") as mock_init_chain,
            patch.object(cli_manager, "_run_command") as mock_run_command,
        ):
            mock_wallet = Mock()
            mock_wallet_ask.return_value = mock_wallet
            mock_subtensor = Mock()
            mock_init_chain.return_value = mock_subtensor
            
            cli_manager.axon_reset(
                netuid=1,
                wallet_name="test_wallet",
                wallet_path="/tmp/test",
                wallet_hotkey="test_hotkey",
                network=None,
                prompt=False,
                wait_for_inclusion=True,
                wait_for_finalization=False,
                quiet=False,
                verbose=False,
            )
            
            # Verify wallet_ask was called correctly
            mock_wallet_ask.assert_called_once()
            
            # Verify _run_command was called
            mock_run_command.assert_called_once()

    @patch("bittensor_cli.cli.serving")
    def test_axon_set_command_handler(self, mock_serving):
        """Test axon set CLI command handler."""
        from bittensor_cli.cli import CLIManager
        
        cli_manager = CLIManager()
        mock_serving.set_axon_extrinsic = AsyncMock(
            return_value=(True, "Success")
        )
        
        with (
            patch.object(cli_manager, "verbosity_handler"),
            patch.object(cli_manager, "wallet_ask") as mock_wallet_ask,
            patch.object(cli_manager, "initialize_chain") as mock_init_chain,
            patch.object(cli_manager, "_run_command") as mock_run_command,
        ):
            mock_wallet = Mock()
            mock_wallet_ask.return_value = mock_wallet
            mock_subtensor = Mock()
            mock_init_chain.return_value = mock_subtensor
            
            cli_manager.axon_set(
                netuid=1,
                ip="192.168.1.100",
                port=8091,
                ip_type=4,
                protocol=4,
                wallet_name="test_wallet",
                wallet_path="/tmp/test",
                wallet_hotkey="test_hotkey",
                network=None,
                prompt=False,
                wait_for_inclusion=True,
                wait_for_finalization=False,
                quiet=False,
                verbose=False,
            )
            
            # Verify wallet_ask was called correctly
            mock_wallet_ask.assert_called_once()
            
            # Verify _run_command was called
            mock_run_command.assert_called_once()
