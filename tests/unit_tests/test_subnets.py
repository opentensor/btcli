"""
Unit tests for subnet-related functions, particularly identity deposit queries.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from bittensor_cli.src.bittensor.balances import Balance
from bittensor_cli.src.commands.subnets.subnets import (
    get_subtensor_constant,
    get_identity_deposit,
)


@pytest.mark.asyncio
async def test_get_subtensor_constant_success():
    """Test successful retrieval of a SubtensorModule constant."""
    mock_subtensor = MagicMock()
    mock_subtensor.substrate = MagicMock()
    
    # Mock runtime initialization
    mock_runtime = MagicMock()
    mock_subtensor.substrate.init_runtime = AsyncMock(return_value=mock_runtime)
    
    # Mock constant retrieval
    mock_constant_result = MagicMock()
    mock_constant_result.value = 1000000000  # 1 TAO in RAO
    mock_subtensor.substrate.get_constant = AsyncMock(return_value=mock_constant_result)
    
    result = await get_subtensor_constant(mock_subtensor, "TestConstant")
    
    assert result == 1000000000
    mock_subtensor.substrate.get_constant.assert_called_once_with(
        module_name="SubtensorModule",
        constant_name="TestConstant",
        block_hash=None,
        runtime=mock_runtime,
    )


@pytest.mark.asyncio
async def test_get_subtensor_constant_with_block_hash():
    """Test constant retrieval with a specific block hash."""
    mock_subtensor = MagicMock()
    mock_subtensor.substrate = MagicMock()
    
    mock_runtime = MagicMock()
    mock_subtensor.substrate.init_runtime = AsyncMock(return_value=mock_runtime)
    
    mock_constant_result = MagicMock()
    mock_constant_result.value = 2000000000
    mock_subtensor.substrate.get_constant = AsyncMock(return_value=mock_constant_result)
    
    block_hash = "0x1234567890abcdef"
    result = await get_subtensor_constant(
        mock_subtensor, "TestConstant", block_hash=block_hash
    )
    
    assert result == 2000000000
    mock_subtensor.substrate.get_constant.assert_called_once_with(
        module_name="SubtensorModule",
        constant_name="TestConstant",
        block_hash=block_hash,
        runtime=mock_runtime,
    )


@pytest.mark.asyncio
async def test_get_identity_deposit_success_first_constant():
    """Test successful retrieval of identity deposit using the first constant name."""
    mock_subtensor = MagicMock()
    mock_subtensor.substrate = MagicMock()
    
    mock_runtime = MagicMock()
    mock_subtensor.substrate.init_runtime = AsyncMock(return_value=mock_runtime)
    
    # Mock successful constant retrieval for SubnetIdentityDeposit
    mock_constant_result = MagicMock()
    mock_constant_result.value = 5000000000  # 5 TAO in RAO
    mock_subtensor.substrate.get_constant = AsyncMock(return_value=mock_constant_result)
    
    # Mock get_subtensor_constant to return the value
    with patch(
        "bittensor_cli.src.commands.subnets.subnets.get_subtensor_constant",
        new_callable=AsyncMock,
    ) as mock_get_constant:
        mock_get_constant.return_value = 5000000000
        
        result = await get_identity_deposit(mock_subtensor)
        
        assert isinstance(result, Balance)
        assert result.rao == 5000000000
        assert result.tao == 5.0


@pytest.mark.asyncio
async def test_get_identity_deposit_tries_multiple_constants():
    """Test that get_identity_deposit tries multiple constant names."""
    mock_subtensor = MagicMock()
    mock_subtensor.substrate = MagicMock()
    
    mock_runtime = MagicMock()
    mock_subtensor.substrate.init_runtime = AsyncMock(return_value=mock_runtime)
    
    # Mock get_subtensor_constant to fail on first attempts, succeed on third
    call_count = 0
    
    async def mock_get_constant(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise Exception("Constant not found")
        return 3000000000  # 3 TAO in RAO
    
    with patch(
        "bittensor_cli.src.commands.subnets.subnets.get_subtensor_constant",
        side_effect=mock_get_constant,
    ):
        result = await get_identity_deposit(mock_subtensor)
        
        assert isinstance(result, Balance)
        assert result.rao == 3000000000
        assert call_count == 3  # Should have tried 3 constants


@pytest.mark.asyncio
async def test_get_identity_deposit_no_constant_found():
    """Test that get_identity_deposit returns 0 when no constant is found."""
    mock_subtensor = MagicMock()
    mock_subtensor.substrate = MagicMock()
    
    mock_runtime = MagicMock()
    mock_subtensor.substrate.init_runtime = AsyncMock(return_value=mock_runtime)
    
    # Mock get_subtensor_constant to always fail
    with patch(
        "bittensor_cli.src.commands.subnets.subnets.get_subtensor_constant",
        side_effect=Exception("Constant not found"),
    ), patch(
        "bittensor_cli.src.commands.subnets.subnets.print_verbose"
    ) as mock_print_verbose:
        result = await get_identity_deposit(mock_subtensor)
        
        assert isinstance(result, Balance)
        assert result.rao == 0
        # Should log a warning
        mock_print_verbose.assert_called()


@pytest.mark.asyncio
async def test_get_identity_deposit_with_block_hash():
    """Test get_identity_deposit with a specific block hash."""
    mock_subtensor = MagicMock()
    mock_subtensor.substrate = MagicMock()
    
    mock_runtime = MagicMock()
    mock_subtensor.substrate.init_runtime = AsyncMock(return_value=mock_runtime)
    
    block_hash = "0xabcdef1234567890"
    
    with patch(
        "bittensor_cli.src.commands.subnets.subnets.get_subtensor_constant",
        new_callable=AsyncMock,
    ) as mock_get_constant:
        mock_get_constant.return_value = 1000000000
        
        result = await get_identity_deposit(mock_subtensor, block_hash=block_hash)
        
        assert isinstance(result, Balance)
        # Verify block_hash was passed through
        mock_get_constant.assert_called()
        # Check that init_runtime was called with block_hash
        mock_subtensor.substrate.init_runtime.assert_called_with(block_hash=block_hash)

