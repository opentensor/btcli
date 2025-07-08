import pytest
import typer

from bittensor_cli.cli import parse_mnemonic
from unittest.mock import AsyncMock, patch, MagicMock


def test_parse_mnemonic():
    # standard
    assert parse_mnemonic("hello how are you") == "hello how are you"
    # numbered
    assert parse_mnemonic("1-hello 2-how 3-are 4-you") == "hello how are you"
    with pytest.raises(typer.Exit):
        # not starting with 1
        parse_mnemonic("2-hello 3-how 4-are 5-you")
        # duplicate numbers
        parse_mnemonic("1-hello 1-how 2-are 3-you")
        # missing numbers
        parse_mnemonic("1-hello 3-are 4-you")


@pytest.mark.asyncio
async def test_subnet_sets_price_correctly():
    from bittensor_cli.src.bittensor.subtensor_interface import (
        SubtensorInterface,
        DynamicInfo,
    )

    mock_result = {"some": "data"}
    mock_price = 42.0
    mock_dynamic_info = MagicMock()
    mock_dynamic_info.price = None

    with (
        patch.object(
            SubtensorInterface, "query_runtime_api", new_callable=AsyncMock
        ) as mock_query,
        patch.object(
            SubtensorInterface, "get_subnet_price", new_callable=AsyncMock
        ) as mock_price_method,
        patch.object(DynamicInfo, "from_any", return_value=mock_dynamic_info),
    ):
        mock_query.return_value = mock_result
        mock_price_method.return_value = mock_price

        subtensor = SubtensorInterface("finney")
        subnet_info = await subtensor.subnet(netuid=1)

        mock_query.assert_awaited_once_with(
            "SubnetInfoRuntimeApi", "get_dynamic_info", params=[1], block_hash=None
        )
        mock_price_method.assert_awaited_once_with(netuid=1, block_hash=None)
        assert subnet_info.price == mock_price
