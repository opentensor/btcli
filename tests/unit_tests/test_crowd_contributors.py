"""
Unit tests for crowd contributors command.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, Mock, patch
from bittensor_cli.src.bittensor.balances import Balance
from bittensor_cli.src.bittensor.chain_data import CrowdloanData
from bittensor_cli.src.commands.crowd.contributors import list_contributors


class TestListContributors:
    """Tests for list_contributors function."""

    @pytest.mark.asyncio
    async def test_list_contributors_success(self):
        """Test successful listing of contributors."""
        # Setup mocks
        mock_subtensor = MagicMock()
        mock_subtensor.network = "finney"

        # Mock crowdloan exists
        mock_crowdloan = CrowdloanData(
            creator="5DjzesT8f6Td8",
            funds_account="5EYCAeX97cWb",
            deposit=Balance.from_tao(10.0),
            min_contribution=Balance.from_tao(0.1),
            cap=Balance.from_tao(30.0),
            raised=Balance.from_tao(30.0),
            end=1000000,
            finalized=False,
            contributors_count=3,
            target_address="5GduHCP9UdBY",
            has_call=False,
            call_details=None,
        )
        mock_subtensor.get_single_crowdloan = AsyncMock(return_value=mock_crowdloan)

        # Mock contributors data from query_map
        # The key structure is ((account_bytes_tuple,),) where account_bytes_tuple is tuple of ints
        mock_contributor1_key = (
            (
                74,
                51,
                88,
                161,
                161,
                215,
                144,
                145,
                231,
                175,
                227,
                146,
                149,
                109,
                220,
                180,
                12,
                58,
                121,
                233,
                152,
                50,
                211,
                15,
                242,
                187,
                103,
                2,
                198,
                131,
                177,
                118,
            ),
        )
        mock_contributor2_key = (
            (
                202,
                66,
                124,
                47,
                131,
                219,
                1,
                26,
                137,
                169,
                17,
                112,
                182,
                39,
                163,
                162,
                72,
                150,
                208,
                58,
                179,
                235,
                238,
                242,
                150,
                177,
                219,
                0,
                2,
                76,
                172,
                171,
            ),
        )
        mock_contributor3_key = (
            (
                224,
                56,
                146,
                238,
                201,
                170,
                157,
                255,
                58,
                77,
                190,
                94,
                17,
                231,
                15,
                217,
                15,
                134,
                147,
                100,
                174,
                45,
                31,
                132,
                21,
                200,
                40,
                185,
                176,
                209,
                247,
                54,
            ),
        )

        mock_contribution1 = MagicMock()
        mock_contribution1.value = 10000000000  # 10 TAO in rao
        mock_contribution2 = MagicMock()
        mock_contribution2.value = 10000000000  # 10 TAO in rao
        mock_contribution3 = MagicMock()
        mock_contribution3.value = 10000000000  # 10 TAO in rao

        # Create async generator for query_map results
        async def mock_query_map_generator():
            yield (mock_contributor1_key, mock_contribution1)
            yield (mock_contributor2_key, mock_contribution2)
            yield (mock_contributor3_key, mock_contribution3)

        # Create a proper async iterable
        class MockQueryMapResult:
            def __aiter__(self):
                return mock_query_map_generator()

        mock_subtensor.substrate.query_map = AsyncMock(
            return_value=MockQueryMapResult()
        )

        # Mock identities
        mock_subtensor.query_identity = AsyncMock(
            side_effect=[
                {"info": {"display": {"Raw": "Alice"}}},  # Contributor 1
                {"info": {"display": {"Raw": "Bob"}}},  # Contributor 2
                {},  # Contributor 3 (no identity)
            ]
        )

        # Execute
        result = await list_contributors(
            subtensor=mock_subtensor,
            crowdloan_id=0,
            verbose=False,
            json_output=False,
        )

        # Verify
        assert result is True
        mock_subtensor.get_single_crowdloan.assert_called_once_with(0)
        mock_subtensor.substrate.query_map.assert_called_once_with(
            module="Crowdloan",
            storage_function="Contributions",
            params=[0],
            fully_exhaust=True,
        )
        assert mock_subtensor.query_identity.call_count == 3

    @pytest.mark.asyncio
    async def test_list_contributors_crowdloan_not_found(self):
        """Test listing contributors when crowdloan doesn't exist."""
        mock_subtensor = MagicMock()
        mock_subtensor.get_single_crowdloan = AsyncMock(return_value=None)

        # Execute
        result = await list_contributors(
            subtensor=mock_subtensor,
            crowdloan_id=999,
            verbose=False,
            json_output=False,
        )

        # Verify
        assert result is False
        mock_subtensor.get_single_crowdloan.assert_called_once_with(999)
        mock_subtensor.substrate.query_map.assert_not_called()

    @pytest.mark.asyncio
    async def test_list_contributors_no_contributors(self):
        """Test listing contributors when there are no contributors."""
        mock_subtensor = MagicMock()
        mock_subtensor.network = "finney"

        mock_crowdloan = CrowdloanData(
            creator="5DjzesT8f6Td8",
            funds_account="5EYCAeX97cWb",
            deposit=Balance.from_tao(10.0),
            min_contribution=Balance.from_tao(0.1),
            cap=Balance.from_tao(100.0),
            raised=Balance.from_tao(10.0),
            end=1000000,
            finalized=False,
            contributors_count=0,
            target_address=None,
            has_call=False,
            call_details=None,
        )
        mock_subtensor.get_single_crowdloan = AsyncMock(return_value=mock_crowdloan)

        # Mock empty contributors data
        async def mock_empty_query_map():
            if False:  # Never yield anything
                yield

        class MockEmptyQueryMapResult:
            def __aiter__(self):
                return mock_empty_query_map()

        mock_subtensor.substrate.query_map = AsyncMock(
            return_value=MockEmptyQueryMapResult()
        )

        # Execute
        result = await list_contributors(
            subtensor=mock_subtensor,
            crowdloan_id=0,
            verbose=False,
            json_output=False,
        )

        # Verify
        assert result is True
        mock_subtensor.query_identity.assert_not_called()

    @pytest.mark.asyncio
    async def test_list_contributors_json_output(self):
        """Test listing contributors with JSON output."""
        mock_subtensor = MagicMock()
        mock_subtensor.network = "finney"

        mock_crowdloan = CrowdloanData(
            creator="5DjzesT8f6Td8",
            funds_account="5EYCAeX97cWb",
            deposit=Balance.from_tao(10.0),
            min_contribution=Balance.from_tao(0.1),
            cap=Balance.from_tao(20.0),
            raised=Balance.from_tao(20.0),
            end=1000000,
            finalized=False,
            contributors_count=2,
            target_address=None,
            has_call=False,
            call_details=None,
        )
        mock_subtensor.get_single_crowdloan = AsyncMock(return_value=mock_crowdloan)

        # Mock contributors data
        mock_contributor1_key = (
            (
                74,
                51,
                88,
                161,
                161,
                215,
                144,
                145,
                231,
                175,
                227,
                146,
                149,
                109,
                220,
                180,
                12,
                58,
                121,
                233,
                152,
                50,
                211,
                15,
                242,
                187,
                103,
                2,
                198,
                131,
                177,
                118,
            ),
        )
        mock_contributor2_key = (
            (
                202,
                66,
                124,
                47,
                131,
                219,
                1,
                26,
                137,
                169,
                17,
                112,
                182,
                39,
                163,
                162,
                72,
                150,
                208,
                58,
                179,
                235,
                238,
                242,
                150,
                177,
                219,
                0,
                2,
                76,
                172,
                171,
            ),
        )

        mock_contribution1 = MagicMock()
        mock_contribution1.value = 10000000000  # 10 TAO
        mock_contribution2 = MagicMock()
        mock_contribution2.value = 10000000000  # 10 TAO

        async def mock_query_map_generator():
            yield (mock_contributor1_key, mock_contribution1)
            yield (mock_contributor2_key, mock_contribution2)

        class MockQueryMapResult:
            def __aiter__(self):
                return mock_query_map_generator()

        mock_subtensor.substrate.query_map = AsyncMock(
            return_value=MockQueryMapResult()
        )
        mock_subtensor.query_identity = AsyncMock(
            side_effect=[
                {"info": {"display": {"Raw": "Alice"}}},
                {"info": {"display": {"Raw": "Bob"}}},
            ]
        )

        # Mock json_console
        with patch(
            "bittensor_cli.src.commands.crowd.contributors.json_console"
        ) as mock_json_console:
            # Execute
            result = await list_contributors(
                subtensor=mock_subtensor,
                crowdloan_id=0,
                verbose=False,
                json_output=True,
            )

            # Verify
            assert result is True
            mock_json_console.print.assert_called_once()
            call_args = mock_json_console.print.call_args[0][0]
            import json

            output_data = json.loads(call_args)
            assert output_data["success"] is True
            assert output_data["data"]["crowdloan_id"] == 0
            assert len(output_data["data"]["contributors"]) == 2
            assert output_data["data"]["total_count"] == 2
            assert output_data["data"]["total_contributed_tao"] == 20.0
            assert output_data["data"]["network"] == "finney"
            # Verify contributors are sorted by rank
            assert output_data["data"]["contributors"][0]["rank"] == 1
            assert output_data["data"]["contributors"][1]["rank"] == 2

    @pytest.mark.asyncio
    async def test_list_contributors_verbose_mode(self):
        """Test listing contributors with verbose mode."""
        mock_subtensor = MagicMock()
        mock_subtensor.network = "finney"

        mock_crowdloan = CrowdloanData(
            creator="5DjzesT8f6Td8",
            funds_account="5EYCAeX97cWb",
            deposit=Balance.from_tao(10.0),
            min_contribution=Balance.from_tao(0.1),
            cap=Balance.from_tao(10.0),
            raised=Balance.from_tao(10.0),
            end=1000000,
            finalized=False,
            contributors_count=1,
            target_address=None,
            has_call=False,
            call_details=None,
        )
        mock_subtensor.get_single_crowdloan = AsyncMock(return_value=mock_crowdloan)

        mock_contributor_key = (
            (
                74,
                51,
                88,
                161,
                161,
                215,
                144,
                145,
                231,
                175,
                227,
                146,
                149,
                109,
                220,
                180,
                12,
                58,
                121,
                233,
                152,
                50,
                211,
                15,
                242,
                187,
                103,
                2,
                198,
                131,
                177,
                118,
            ),
        )
        mock_contribution = MagicMock()
        mock_contribution.value = 10000000000  # 10 TAO

        async def mock_query_map_generator():
            yield (mock_contributor_key, mock_contribution)

        class MockQueryMapResult:
            def __aiter__(self):
                return mock_query_map_generator()

        mock_subtensor.substrate.query_map = AsyncMock(
            return_value=MockQueryMapResult()
        )
        mock_subtensor.query_identity = AsyncMock(return_value={})

        # Execute
        result = await list_contributors(
            subtensor=mock_subtensor,
            crowdloan_id=0,
            verbose=True,
            json_output=False,
        )

        # Verify
        assert result is True
