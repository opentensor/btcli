"""
Unit tests for proxy commands.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from bittensor_cli.src.commands.proxy.add import proxy_add, PROXY_TYPES
from bittensor_cli.src.commands.proxy.remove import proxy_remove, proxy_remove_all
from bittensor_cli.src.commands.proxy.list import proxy_list, proxy_list_for_wallet


class TestProxyTypes:
    """Test that all expected proxy types are defined."""

    def test_proxy_types_defined(self):
        """Verify all expected proxy types are available."""
        expected_types = [
            "Any",
            "NonTransfer",
            "Governance",
            "Staking",
            "Registration",
            "SenateVoting",
            "Transfer",
            "SmallTransfer",
            "RootWeights",
            "ChildKeys",
            "SudoUncheckedSetCode",
        ]
        assert PROXY_TYPES == expected_types


class TestProxyAdd:
    """Tests for proxy_add command."""

    @pytest.mark.asyncio
    async def test_proxy_add_invalid_delegate_address(self):
        """Test that invalid SS58 address is rejected."""
        mock_wallet = MagicMock()
        mock_subtensor = MagicMock()

        with patch(
            "bittensor_cli.src.commands.proxy.add.is_valid_ss58_address",
            return_value=False,
        ):
            result = await proxy_add(
                wallet=mock_wallet,
                subtensor=mock_subtensor,
                delegate="invalid_address",
                proxy_type="Any",
                delay=0,
                prompt=False,
            )

        assert result is False

    @pytest.mark.asyncio
    async def test_proxy_add_invalid_proxy_type(self):
        """Test that invalid proxy type is rejected."""
        mock_wallet = MagicMock()
        mock_subtensor = MagicMock()

        with patch(
            "bittensor_cli.src.commands.proxy.add.is_valid_ss58_address",
            return_value=True,
        ):
            result = await proxy_add(
                wallet=mock_wallet,
                subtensor=mock_subtensor,
                delegate="5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY",
                proxy_type="InvalidType",
                delay=0,
                prompt=False,
            )

        assert result is False

    @pytest.mark.asyncio
    async def test_proxy_add_wallet_unlock_failure(self):
        """Test that failed wallet unlock returns False."""
        mock_wallet = MagicMock()
        mock_subtensor = MagicMock()
        mock_subtensor.network = "finney"
        mock_unlock_result = MagicMock()
        mock_unlock_result.success = False

        with (
            patch(
                "bittensor_cli.src.commands.proxy.add.is_valid_ss58_address",
                return_value=True,
            ),
            patch(
                "bittensor_cli.src.commands.proxy.add.unlock_key",
                return_value=mock_unlock_result,
            ),
        ):
            result = await proxy_add(
                wallet=mock_wallet,
                subtensor=mock_subtensor,
                delegate="5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY",
                proxy_type="Any",
                delay=0,
                prompt=False,
            )

        assert result is False


class TestProxyRemove:
    """Tests for proxy_remove command."""

    @pytest.mark.asyncio
    async def test_proxy_remove_invalid_delegate_address(self):
        """Test that invalid SS58 address is rejected."""
        mock_wallet = MagicMock()
        mock_subtensor = MagicMock()

        with patch(
            "bittensor_cli.src.commands.proxy.remove.is_valid_ss58_address",
            return_value=False,
        ):
            result = await proxy_remove(
                wallet=mock_wallet,
                subtensor=mock_subtensor,
                delegate="invalid_address",
                proxy_type="Any",
                delay=0,
                prompt=False,
            )

        assert result is False

    @pytest.mark.asyncio
    async def test_proxy_remove_invalid_proxy_type(self):
        """Test that invalid proxy type is rejected."""
        mock_wallet = MagicMock()
        mock_subtensor = MagicMock()

        with patch(
            "bittensor_cli.src.commands.proxy.remove.is_valid_ss58_address",
            return_value=True,
        ):
            result = await proxy_remove(
                wallet=mock_wallet,
                subtensor=mock_subtensor,
                delegate="5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY",
                proxy_type="InvalidType",
                delay=0,
                prompt=False,
            )

        assert result is False

    @pytest.mark.asyncio
    async def test_proxy_remove_wallet_unlock_failure(self):
        """Test that failed wallet unlock returns False."""
        mock_wallet = MagicMock()
        mock_subtensor = MagicMock()
        mock_subtensor.network = "finney"
        mock_unlock_result = MagicMock()
        mock_unlock_result.success = False

        with (
            patch(
                "bittensor_cli.src.commands.proxy.remove.is_valid_ss58_address",
                return_value=True,
            ),
            patch(
                "bittensor_cli.src.commands.proxy.remove.unlock_key",
                return_value=mock_unlock_result,
            ),
        ):
            result = await proxy_remove(
                wallet=mock_wallet,
                subtensor=mock_subtensor,
                delegate="5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY",
                proxy_type="Any",
                delay=0,
                prompt=False,
            )

        assert result is False


class TestProxyRemoveAll:
    """Tests for proxy_remove_all command."""

    @pytest.mark.asyncio
    async def test_proxy_remove_all_wallet_unlock_failure(self):
        """Test that failed wallet unlock returns False."""
        mock_wallet = MagicMock()
        mock_subtensor = MagicMock()
        mock_subtensor.network = "finney"
        mock_unlock_result = MagicMock()
        mock_unlock_result.success = False

        with patch(
            "bittensor_cli.src.commands.proxy.remove.unlock_key",
            return_value=mock_unlock_result,
        ):
            result = await proxy_remove_all(
                wallet=mock_wallet,
                subtensor=mock_subtensor,
                prompt=False,
            )

        assert result is False


class TestProxyList:
    """Tests for proxy_list command."""

    @pytest.mark.asyncio
    async def test_proxy_list_invalid_address(self):
        """Test that invalid SS58 address is rejected."""
        mock_subtensor = MagicMock()

        with patch(
            "bittensor_cli.src.commands.proxy.list.is_valid_ss58_address",
            return_value=False,
        ):
            result = await proxy_list(
                subtensor=mock_subtensor,
                address="invalid_address",
            )

        assert result is False

    @pytest.mark.asyncio
    async def test_proxy_list_no_proxies(self):
        """Test listing when no proxies exist."""
        mock_subtensor = MagicMock()
        mock_subtensor.network = "finney"
        mock_subtensor.substrate.query = AsyncMock(return_value=None)

        with patch(
            "bittensor_cli.src.commands.proxy.list.is_valid_ss58_address",
            return_value=True,
        ):
            result = await proxy_list(
                subtensor=mock_subtensor,
                address="5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY",
            )

        assert result is True

    @pytest.mark.asyncio
    async def test_proxy_list_with_proxies(self):
        """Test listing when proxies exist."""
        mock_subtensor = MagicMock()
        mock_subtensor.network = "finney"

        # Mock result with proxy data
        mock_result = MagicMock()
        mock_result.value = (
            [
                {
                    "delegate": "5FHneW46xGXgs5mUiveU4sbTyGBzmstUspZC92UhjJM694ty",
                    "proxy_type": {"Staking": None},
                    "delay": 0,
                }
            ],
            1000000000,  # deposit in rao
        )
        mock_subtensor.substrate.query = AsyncMock(return_value=mock_result)

        with patch(
            "bittensor_cli.src.commands.proxy.list.is_valid_ss58_address",
            return_value=True,
        ):
            result = await proxy_list(
                subtensor=mock_subtensor,
                address="5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY",
            )

        assert result is True

    @pytest.mark.asyncio
    async def test_proxy_list_for_wallet(self):
        """Test listing proxies for wallet's coldkey."""
        mock_wallet = MagicMock()
        mock_wallet.coldkeypub.ss58_address = (
            "5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY"
        )
        mock_subtensor = MagicMock()
        mock_subtensor.network = "finney"
        mock_subtensor.substrate.query = AsyncMock(return_value=None)

        with patch(
            "bittensor_cli.src.commands.proxy.list.is_valid_ss58_address",
            return_value=True,
        ):
            result = await proxy_list_for_wallet(
                wallet=mock_wallet,
                subtensor=mock_subtensor,
            )

        assert result is True
