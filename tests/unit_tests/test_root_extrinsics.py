"""
Unit tests for bittensor_cli/src/bittensor/extrinsics/root.py.

Covers the pure mathematical functions (normalize_max_weight,
convert_weights_and_uids_for_emit, generate_weight_hash) and the
async helper functions (get_current_weights_for_uid, get_limits).
"""

import pytest
from unittest.mock import AsyncMock

from bittensor_cli.src.bittensor.extrinsics.root import (
    normalize_max_weight,
    convert_weights_and_uids_for_emit,
    generate_weight_hash,
    get_current_weights_for_uid,
    get_limits,
)
from .conftest import COLDKEY_SS58 as _SS58

U16_MAX = 65535


# ---------------------------------------------------------------------------
# normalize_max_weight
# ---------------------------------------------------------------------------


class TestNormalizeMaxWeight:
    def test_all_zero_returns_uniform(self):
        result = normalize_max_weight([0.0, 0.0, 0.0, 0.0], limit=0.5)
        assert result == pytest.approx([0.25, 0.25, 0.25, 0.25], abs=1e-6)

    def test_uniform_input_below_limit(self):
        result = normalize_max_weight([1.0, 1.0, 1.0, 1.0], limit=0.5)
        # Each element is 0.25, which is below limit=0.5 → normalized by sum
        assert sum(result) == pytest.approx(1.0, abs=1e-6)
        assert max(result) <= 0.5 + 1e-6

    def test_single_element_returns_one(self):
        # n*limit = 0.5 <= 1 → uniform = 1.0
        result = normalize_max_weight([1.0], limit=0.5)
        assert result == pytest.approx([1.0], abs=1e-6)

    def test_clipping_reduces_max(self):
        # One very large weight, others small
        result = normalize_max_weight([100.0, 1.0, 1.0, 1.0], limit=0.4)
        assert max(result) <= 0.4 + 1e-5
        assert sum(result) == pytest.approx(1.0, abs=1e-5)

    def test_output_sums_to_one(self):
        result = normalize_max_weight([0.1, 0.5, 0.3, 0.8], limit=0.4)
        assert sum(result) == pytest.approx(1.0, abs=1e-5)

    def test_limit_of_one_allows_any_weight(self):
        result = normalize_max_weight([0.2, 0.3, 0.5], limit=1.0)
        assert sum(result) == pytest.approx(1.0, abs=1e-6)


# ---------------------------------------------------------------------------
# convert_weights_and_uids_for_emit
# ---------------------------------------------------------------------------


class TestConvertWeightsAndUidsForEmit:
    def test_empty_input_raises(self):
        # min() on an empty list raises ValueError in the current implementation
        with pytest.raises(ValueError):
            convert_weights_and_uids_for_emit([], [])

    def test_all_zero_weights_returns_empty(self):
        result_uids, result_vals = convert_weights_and_uids_for_emit(
            [0, 1, 2], [0.0, 0.0, 0.0]
        )
        assert result_uids == []
        assert result_vals == []

    def test_mismatched_lengths_raise_value_error(self):
        with pytest.raises(ValueError):
            convert_weights_and_uids_for_emit([0, 1], [0.5, 0.3, 0.2])

    def test_negative_weight_raises_value_error(self):
        with pytest.raises(ValueError):
            convert_weights_and_uids_for_emit([0, 1], [0.5, -0.1])

    def test_normal_case_filters_zeros(self):
        result_uids, _ = convert_weights_and_uids_for_emit([0, 1, 2], [1.0, 0.0, 0.5])
        # uid 1 has weight 0 → filtered
        assert 1 not in result_uids

    def test_max_weight_is_u16_max(self):
        _, result_vals = convert_weights_and_uids_for_emit([0, 1], [1.0, 0.5])
        # The max weight should be U16_MAX
        assert max(result_vals) == U16_MAX

    def test_output_lengths_match(self):
        result_uids, result_vals = convert_weights_and_uids_for_emit(
            [0, 1, 2], [0.3, 0.5, 0.2]
        )
        assert len(result_uids) == len(result_vals)

    def test_uids_preserved_in_output(self):
        result_uids, _ = convert_weights_and_uids_for_emit([5, 10, 15], [1.0, 0.5, 0.25])
        for uid in result_uids:
            assert uid in [5, 10, 15]


# ---------------------------------------------------------------------------
# generate_weight_hash
# ---------------------------------------------------------------------------


class TestGenerateWeightHash:
    def test_returns_0x_prefixed_string(self):
        result = generate_weight_hash(
            address=_SS58,
            netuid=1,
            uids=[0, 1, 2],
            values=[U16_MAX, U16_MAX // 2, U16_MAX // 4],
            version_key=0,
            salt=[1, 2, 3],
        )
        assert isinstance(result, str)
        assert result.startswith("0x")

    def test_returns_64_char_hex_after_prefix(self):
        result = generate_weight_hash(
            address=_SS58,
            netuid=1,
            uids=[0],
            values=[U16_MAX],
            version_key=0,
            salt=[42],
        )
        hex_part = result[2:]  # Remove 0x
        assert len(hex_part) == 64  # Blake2b 32 bytes = 64 hex chars

    def test_deterministic_same_inputs(self):
        kwargs = dict(
            address=_SS58,
            netuid=2,
            uids=[0, 1],
            values=[30000, 35535],
            version_key=1,
            salt=[7, 8],
        )
        hash1 = generate_weight_hash(**kwargs)
        hash2 = generate_weight_hash(**kwargs)
        assert hash1 == hash2

    def test_different_salt_produces_different_hash(self):
        base = dict(address=_SS58, netuid=1, uids=[0], values=[U16_MAX], version_key=0)
        hash1 = generate_weight_hash(**base, salt=[1])
        hash2 = generate_weight_hash(**base, salt=[2])
        assert hash1 != hash2

    def test_different_netuid_produces_different_hash(self):
        base = dict(address=_SS58, uids=[0], values=[U16_MAX], version_key=0, salt=[1])
        hash1 = generate_weight_hash(**base, netuid=1)
        hash2 = generate_weight_hash(**base, netuid=2)
        assert hash1 != hash2


# ---------------------------------------------------------------------------
# get_current_weights_for_uid (async)
# ---------------------------------------------------------------------------


class TestGetCurrentWeightsForUid:
    async def test_returns_weights_for_matching_uid(self, mock_subtensor):
        # Return [(uid, [(dest, raw_weight), ...])]
        mock_subtensor.weights = AsyncMock(return_value=[(5, [(0, 65535), (1, 32767)])])
        result = await get_current_weights_for_uid(
            subtensor=mock_subtensor, netuid=0, uid=5
        )
        assert 0 in result
        assert 1 in result
        assert result[0] == pytest.approx(1.0)
        assert 0.4 < result[1] < 0.6

    async def test_returns_empty_for_nonmatching_uid(self, mock_subtensor):
        mock_subtensor.weights = AsyncMock(return_value=[(3, [(0, 65535)])])
        result = await get_current_weights_for_uid(
            subtensor=mock_subtensor, netuid=0, uid=99
        )
        assert result == {}

    async def test_returns_empty_when_no_weights(self, mock_subtensor):
        mock_subtensor.weights = AsyncMock(return_value=[])
        result = await get_current_weights_for_uid(
            subtensor=mock_subtensor, netuid=0, uid=0
        )
        assert result == {}


# ---------------------------------------------------------------------------
# get_limits (async)
# ---------------------------------------------------------------------------


class TestGetLimits:
    async def test_returns_int_and_float(self, mock_subtensor):
        call_count = [0]

        async def side_effect(param, netuid):
            call_count[0] += 1
            if call_count[0] == 1:
                return "4"  # MinAllowedWeights as string (int-able)
            return "32767"  # MaxWeightsLimit as string

        mock_subtensor.get_hyperparameter = AsyncMock(side_effect=side_effect)
        min_w, max_w = await get_limits(mock_subtensor)
        assert isinstance(min_w, int)
        assert isinstance(max_w, float)
        assert min_w == 4
        assert 0.0 < max_w < 1.0
