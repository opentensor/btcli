"""
Unit tests for crowd create custom call functionality.
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, Mock, patch
from scalecodec import GenericCall

from bittensor_cli.src.commands.crowd.create import validate_and_compose_custom_call


class TestValidateAndComposeCustomCall:
    """Tests for validate_and_compose_custom_call function."""

    @pytest.mark.asyncio
    async def test_invalid_json_args(self):
        """Test that invalid JSON in args is caught."""
        mock_subtensor = MagicMock()
        mock_subtensor.substrate = MagicMock()

        result_call, error_msg = await validate_and_compose_custom_call(
            subtensor=mock_subtensor,
            pallet_name="TestPallet",
            method_name="test_method",
            args_json='{"invalid": json}',
        )

        assert result_call is None
        assert "Invalid JSON" in error_msg

    @pytest.mark.asyncio
    async def test_pallet_not_found(self):
        """Test that missing pallet is detected."""
        mock_subtensor = MagicMock()
        mock_subtensor.substrate = MagicMock()

        # Mock metadata structure
        mock_pallet = MagicMock()
        mock_pallet.name = "OtherPallet"

        mock_metadata = MagicMock()
        mock_metadata.pallets = [mock_pallet]
        mock_metadata.get_metadata_pallet = Mock(
            side_effect=ValueError("Pallet not found")
        )

        mock_runtime = MagicMock()
        mock_runtime.metadata = mock_metadata

        mock_subtensor.substrate.get_chain_head = AsyncMock(return_value="0x1234")
        mock_subtensor.substrate.init_runtime = AsyncMock(return_value=mock_runtime)

        result_call, error_msg = await validate_and_compose_custom_call(
            subtensor=mock_subtensor,
            pallet_name="NonExistentPallet",
            method_name="test_method",
            args_json="{}",
        )

        assert result_call is None
        assert "not found" in error_msg.lower()

    @pytest.mark.asyncio
    async def test_method_not_found(self):
        """Test that missing method is detected."""
        mock_subtensor = MagicMock()
        mock_subtensor.substrate = MagicMock()

        # Mock metadata structure
        mock_call = MagicMock()
        mock_call.name = "other_method"

        mock_pallet = MagicMock()
        mock_pallet.name = "TestPallet"
        mock_pallet.calls = [mock_call]

        mock_metadata = MagicMock()
        mock_metadata.pallets = [mock_pallet]
        mock_metadata.get_metadata_pallet = Mock(return_value=mock_pallet)

        mock_runtime = MagicMock()
        mock_runtime.metadata = mock_metadata

        mock_subtensor.substrate.get_chain_head = AsyncMock(return_value="0x1234")
        mock_subtensor.substrate.init_runtime = AsyncMock(return_value=mock_runtime)

        result_call, error_msg = await validate_and_compose_custom_call(
            subtensor=mock_subtensor,
            pallet_name="TestPallet",
            method_name="non_existent_method",
            args_json="{}",
        )

        assert result_call is None
        assert "not found" in error_msg.lower()

    @pytest.mark.asyncio
    async def test_successful_validation(self):
        """Test successful validation and call composition."""
        mock_subtensor = MagicMock()
        mock_subtensor.substrate = MagicMock()

        # Mock metadata structure
        mock_call = MagicMock()
        mock_call.name = "test_method"
        mock_call.index = 0

        mock_pallet = MagicMock()
        mock_pallet.name = "TestPallet"
        mock_pallet.calls = [mock_call]

        mock_metadata = MagicMock()
        mock_metadata.pallets = [mock_pallet]
        mock_metadata.get_metadata_pallet = Mock(return_value=mock_pallet)

        mock_runtime = MagicMock()
        mock_runtime.metadata = mock_metadata

        # Mock compose_call to return a GenericCall
        mock_generic_call = MagicMock(spec=GenericCall)
        mock_subtensor.substrate.compose_call = AsyncMock(
            return_value=mock_generic_call
        )
        mock_subtensor.substrate.get_chain_head = AsyncMock(return_value="0x1234")
        mock_subtensor.substrate.init_runtime = AsyncMock(return_value=mock_runtime)

        result_call, error_msg = await validate_and_compose_custom_call(
            subtensor=mock_subtensor,
            pallet_name="TestPallet",
            method_name="test_method",
            args_json='{"param1": "value1"}',
        )

        assert result_call is not None
        assert error_msg is None
        mock_subtensor.substrate.compose_call.assert_called_once_with(
            call_module="TestPallet",
            call_function="test_method",
            call_params={"param1": "value1"},
        )

    @pytest.mark.asyncio
    async def test_compose_call_failure(self):
        """Test handling of compose_call failures."""
        mock_subtensor = MagicMock()
        mock_subtensor.substrate = MagicMock()

        # Mock metadata structure
        mock_call = MagicMock()
        mock_call.name = "test_method"

        mock_pallet = MagicMock()
        mock_pallet.name = "TestPallet"
        mock_pallet.calls = [mock_call]

        mock_metadata = MagicMock()
        mock_metadata.pallets = [mock_pallet]
        mock_metadata.get_metadata_pallet = Mock(return_value=mock_pallet)

        mock_runtime = MagicMock()
        mock_runtime.metadata = mock_metadata

        # Mock compose_call to raise an error
        mock_subtensor.substrate.compose_call = AsyncMock(
            side_effect=Exception("Invalid parameter type")
        )
        mock_subtensor.substrate.get_chain_head = AsyncMock(return_value="0x1234")
        mock_subtensor.substrate.init_runtime = AsyncMock(return_value=mock_runtime)

        result_call, error_msg = await validate_and_compose_custom_call(
            subtensor=mock_subtensor,
            pallet_name="TestPallet",
            method_name="test_method",
            args_json='{"param1": "value1"}',
        )

        assert result_call is None
        assert error_msg is not None
        assert "Invalid parameter" in error_msg or "Failed to compose" in error_msg
