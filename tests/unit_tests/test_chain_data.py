"""
Unit tests for bittensor_cli/src/bittensor/chain_data.py.

Focuses on the _fix_decoded() class methods and the DynamicInfo price/slippage
math — the areas most likely to cause silent data corruption or crashes in
production when chain data has unexpected values.
"""

import pytest

from bittensor_cli.src.bittensor.chain_data import (
    DynamicInfo,
    StakeInfo,
    NeuronInfo,
)
from bittensor_cli.src.bittensor.balances import Balance

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# 32-byte account id tuple used to stand in for owner_hotkey / owner_coldkey.
# bytes(tuple(range(32))) is valid input to decode_account_id.
_ACCOUNT_ID = tuple(range(32))

# A fixed-point dict as returned by the chain for moving_price (value ≈ 1.0).
# fixed_to_float reads fixed["bits"]; bits = 2**32 ≈ 1.0 in Q32.32 format.
_MOVING_PRICE_ONE = {"bits": 2**32}
_MOVING_PRICE_ZERO = {"bits": 0}

TAO = 1_000_000_000  # 1 TAO in rao


def _make_dynamic_decoded(
    netuid: int = 1,
    alpha_in_rao: int = 100 * TAO,
    tao_in_rao: int = 50 * TAO,
    symbol: bytes = b"SN",
    subnet_name: bytes = b"TestNet",
    subnet_identity=None,
) -> dict:
    """Construct a minimal decoded dict that mirrors what the chain returns."""
    return {
        "netuid": netuid,
        "token_symbol": list(symbol),
        "subnet_name": list(subnet_name),
        "owner_hotkey": _ACCOUNT_ID,
        "owner_coldkey": _ACCOUNT_ID,
        "emission": 0,
        "alpha_in": alpha_in_rao,
        "alpha_out": 0,
        "tao_in": tao_in_rao,
        "alpha_out_emission": 0,
        "alpha_in_emission": 0,
        "subnet_volume": 0,
        "tao_in_emission": 0,
        "pending_alpha_emission": 0,
        "pending_root_emission": 0,
        "tempo": 100,
        "last_step": 500,
        "blocks_since_last_step": 50,
        "network_registered_at": 1000,
        "moving_price": _MOVING_PRICE_ONE,
        "subnet_identity": subnet_identity,
    }


def _make_stake_decoded(
    netuid: int = 1,
    stake_rao: int = 10 * TAO,
) -> dict:
    """Construct a minimal decoded dict for StakeInfo."""
    return {
        "hotkey": _ACCOUNT_ID,
        "coldkey": _ACCOUNT_ID,
        "netuid": netuid,
        "stake": stake_rao,
        "locked": 0,
        "emission": 0,
        "tao_emission": 0,
        "drain": 0,
        "is_registered": True,
    }


def _make_neuron_decoded(emission_rao: int = 1_000_000_000) -> dict:
    """Construct a minimal decoded dict for NeuronInfo."""
    return {
        "hotkey": _ACCOUNT_ID,
        "coldkey": _ACCOUNT_ID,
        "uid": 0,
        "netuid": 1,
        "active": 1,
        "stake": [(_ACCOUNT_ID, emission_rao)],
        "rank": 0,
        "emission": emission_rao,
        "incentive": 0,
        "consensus": 0,
        "trust": 0,
        "validator_trust": 0,
        "dividends": 0,
        "last_update": 0,
        "validator_permit": False,
        "weights": [(0, 65535)],
        "bonds": [(0, 65535)],
        "pruning_score": 0,
        "axon_info": {
            "version": 0,
            "ip": 0,
            "port": 0,
            "ip_type": 4,
            "placeholder1": 0,
            "placeholder2": 0,
            "protocol": 4,
        },
    }


# ---------------------------------------------------------------------------
# DynamicInfo._fix_decoded
# ---------------------------------------------------------------------------


class TestDynamicInfoFixDecoded:
    def test_normal_case_returns_dynamic_info(self):
        """Standard decoding should return a DynamicInfo with correct fields."""
        decoded = _make_dynamic_decoded(
            netuid=1, alpha_in_rao=100 * TAO, tao_in_rao=50 * TAO
        )
        info = DynamicInfo._fix_decoded(decoded)
        assert isinstance(info, DynamicInfo)
        assert info.netuid == 1
        assert info.is_dynamic is True

    def test_netuid_zero_is_not_dynamic(self):
        """netuid=0 must set is_dynamic=False and price=1.0."""
        decoded = _make_dynamic_decoded(netuid=0, alpha_in_rao=100 * TAO, tao_in_rao=0)
        info = DynamicInfo._fix_decoded(decoded)
        assert info.is_dynamic is False
        assert info.price.tao == pytest.approx(1.0)

    def test_alpha_in_zero_price_defaults_to_one(self):
        """alpha_in=0 must not cause ZeroDivisionError; price must be 1.0."""
        decoded = _make_dynamic_decoded(netuid=1, alpha_in_rao=0, tao_in_rao=50 * TAO)
        info = DynamicInfo._fix_decoded(decoded)
        # The guard `if alpha_in.tao > 0 else Balance.from_tao(1)` must fire.
        assert info.price.tao == pytest.approx(1.0)

    def test_price_calculation_correct(self):
        """price = tao_in / alpha_in — verify the ratio is computed correctly."""
        tao_in = 50 * TAO
        alpha_in = 100 * TAO
        decoded = _make_dynamic_decoded(
            netuid=1, alpha_in_rao=alpha_in, tao_in_rao=tao_in
        )
        info = DynamicInfo._fix_decoded(decoded)
        expected = Balance.from_rao(tao_in).tao / Balance.from_rao(alpha_in).tao
        assert info.price.tao == pytest.approx(expected, rel=1e-6)

    def test_k_is_tao_rao_times_alpha_rao(self):
        """k = tao_in.rao * alpha_in.rao."""
        decoded = _make_dynamic_decoded(
            netuid=1, alpha_in_rao=100 * TAO, tao_in_rao=50 * TAO
        )
        info = DynamicInfo._fix_decoded(decoded)
        assert info.k == (50 * TAO) * (100 * TAO)

    def test_symbol_and_name_decoded_from_bytes(self):
        """token_symbol and subnet_name are decoded from byte lists."""
        decoded = _make_dynamic_decoded(symbol=b"TEST", subnet_name=b"MySubnet")
        info = DynamicInfo._fix_decoded(decoded)
        assert info.symbol == "TEST"
        assert info.subnet_name == "MySubnet"

    def test_subnet_identity_none_when_absent(self):
        """subnet_identity field is None when not present in decoded dict."""
        decoded = _make_dynamic_decoded()
        info = DynamicInfo._fix_decoded(decoded)
        assert info.subnet_identity is None

    def test_balances_have_correct_units(self):
        """alpha_in and alpha_out should be in subnet unit; tao_in in TAO unit."""
        decoded = _make_dynamic_decoded(netuid=3, alpha_in_rao=100 * TAO)
        info = DynamicInfo._fix_decoded(decoded)
        # alpha_in unit is set to netuid (3); tao_in unit is 0 (TAO)
        assert info.alpha_in.unit == Balance.get_unit(3)
        assert info.tao_in.unit == Balance.get_unit(0)


# ---------------------------------------------------------------------------
# DynamicInfo.tao_to_alpha / alpha_to_tao
# ---------------------------------------------------------------------------


class TestDynamicInfoConversions:
    def _make_info(
        self, alpha_in_rao=100 * TAO, tao_in_rao=50 * TAO, netuid=1
    ) -> DynamicInfo:
        return DynamicInfo._fix_decoded(
            _make_dynamic_decoded(
                netuid=netuid, alpha_in_rao=alpha_in_rao, tao_in_rao=tao_in_rao
            )
        )

    def test_tao_to_alpha_converts_at_price(self):
        """tao_to_alpha should return tao / price alpha."""
        info = self._make_info(alpha_in_rao=100 * TAO, tao_in_rao=50 * TAO)
        # price = 50/100 = 0.5 TAO/alpha  → 1 TAO should give 2 alpha
        result = info.tao_to_alpha(Balance.from_tao(1.0))
        assert result.tao == pytest.approx(2.0, rel=1e-6)

    def test_tao_to_alpha_zero_price_returns_zero(self):
        """With price=0 guard, tao_to_alpha should return 0 without dividing by zero."""
        # Force price to 0 by direct construction (not via _fix_decoded, which guards it)
        decoded = _make_dynamic_decoded(
            netuid=1, alpha_in_rao=100 * TAO, tao_in_rao=50 * TAO
        )
        info = DynamicInfo._fix_decoded(decoded)
        info.price = Balance.from_tao(0)
        result = info.tao_to_alpha(Balance.from_tao(1.0))
        assert result.tao == 0.0

    def test_alpha_to_tao_converts_at_price(self):
        """alpha_to_tao should return alpha * price."""
        info = self._make_info(alpha_in_rao=100 * TAO, tao_in_rao=50 * TAO)
        # price = 0.5 TAO/alpha → 10 alpha = 5 TAO
        result = info.alpha_to_tao(Balance.from_tao(10.0))
        assert result.tao == pytest.approx(5.0, rel=1e-6)

    def test_netuid_zero_tao_to_alpha_is_identity(self):
        """For netuid 0 (non-dynamic), price=1.0 so tao_to_alpha is a 1:1 conversion."""
        info = self._make_info(netuid=0, alpha_in_rao=0, tao_in_rao=0)
        result = info.tao_to_alpha(Balance.from_tao(5.0))
        assert result.tao == pytest.approx(5.0, rel=1e-6)


# ---------------------------------------------------------------------------
# DynamicInfo.tao_to_alpha_with_slippage
# ---------------------------------------------------------------------------


class TestTaoToAlphaWithSlippage:
    def _make_dynamic_info(self) -> DynamicInfo:
        # tao_in=50, alpha_in=100 → price=0.5, k=5000*TAO²
        return DynamicInfo._fix_decoded(
            _make_dynamic_decoded(netuid=1, alpha_in_rao=100 * TAO, tao_in_rao=50 * TAO)
        )

    def test_returns_three_tuple(self):
        info = self._make_dynamic_info()
        result = info.tao_to_alpha_with_slippage(Balance.from_tao(1.0))
        assert len(result) == 3

    def test_alpha_returned_is_positive(self):
        info = self._make_dynamic_info()
        alpha_returned, slippage, pct = info.tao_to_alpha_with_slippage(
            Balance.from_tao(1.0)
        )
        assert alpha_returned.tao > 0

    def test_slippage_is_non_negative(self):
        info = self._make_dynamic_info()
        alpha_returned, slippage, pct = info.tao_to_alpha_with_slippage(
            Balance.from_tao(1.0)
        )
        assert slippage.tao >= 0

    def test_slippage_pct_between_0_and_100(self):
        info = self._make_dynamic_info()
        _, _, pct = info.tao_to_alpha_with_slippage(Balance.from_tao(1.0))
        assert 0.0 <= pct <= 100.0

    def test_small_amount_has_low_slippage(self):
        """A tiny stake relative to pool size should produce near-zero slippage."""
        info = self._make_dynamic_info()
        _, _, pct = info.tao_to_alpha_with_slippage(Balance.from_rao(1))  # 1 rao
        assert pct < 0.01

    def test_non_dynamic_subnet_no_slippage(self):
        """For netuid=0 (non-dynamic), slippage must always be 0."""
        info = DynamicInfo._fix_decoded(
            _make_dynamic_decoded(netuid=0, alpha_in_rao=0, tao_in_rao=0)
        )
        alpha_returned, slippage, pct = info.tao_to_alpha_with_slippage(
            Balance.from_tao(5.0)
        )
        assert slippage.tao == pytest.approx(0.0)
        assert pct == pytest.approx(0.0)

    def test_large_stake_has_high_slippage(self):
        """Staking more than the pool size should produce significant slippage."""
        info = self._make_dynamic_info()
        # Stake 50x the pool size
        _, _, pct = info.tao_to_alpha_with_slippage(Balance.from_tao(50 * 50.0))
        assert pct > 50.0


# ---------------------------------------------------------------------------
# DynamicInfo.alpha_to_tao_with_slippage
# ---------------------------------------------------------------------------


class TestAlphaToTaoWithSlippage:
    def _make_dynamic_info(self) -> DynamicInfo:
        return DynamicInfo._fix_decoded(
            _make_dynamic_decoded(netuid=1, alpha_in_rao=100 * TAO, tao_in_rao=50 * TAO)
        )

    def test_returns_three_tuple(self):
        info = self._make_dynamic_info()
        result = info.alpha_to_tao_with_slippage(Balance.from_tao(1.0))
        assert len(result) == 3

    def test_tao_returned_is_positive(self):
        info = self._make_dynamic_info()
        tao_returned, slippage, pct = info.alpha_to_tao_with_slippage(
            Balance.from_tao(1.0)
        )
        assert tao_returned.tao > 0

    def test_slippage_pct_between_0_and_100(self):
        info = self._make_dynamic_info()
        _, _, pct = info.alpha_to_tao_with_slippage(Balance.from_tao(1.0))
        assert 0.0 <= pct <= 100.0

    def test_non_dynamic_subnet_no_slippage(self):
        """For netuid=0 (non-dynamic), slippage must be 0."""
        info = DynamicInfo._fix_decoded(
            _make_dynamic_decoded(netuid=0, alpha_in_rao=0, tao_in_rao=0)
        )
        tao_returned, slippage, pct = info.alpha_to_tao_with_slippage(
            Balance.from_tao(5.0)
        )
        assert slippage.tao == pytest.approx(0.0)
        assert pct == pytest.approx(0.0)

    def test_small_unstake_low_slippage(self):
        """Tiny unstake relative to pool should have near-zero slippage."""
        info = self._make_dynamic_info()
        _, _, pct = info.alpha_to_tao_with_slippage(Balance.from_rao(1))
        assert pct < 0.01


# ---------------------------------------------------------------------------
# StakeInfo._fix_decoded
# ---------------------------------------------------------------------------


class TestStakeInfoFixDecoded:
    def test_normal_decode(self):
        """StakeInfo decodes correctly from a standard decoded dict."""
        decoded = _make_stake_decoded(netuid=1, stake_rao=10 * TAO)
        info = StakeInfo._fix_decoded(decoded)
        assert isinstance(info, StakeInfo)
        assert info.netuid == 1
        assert info.stake.tao == pytest.approx(10.0)
        assert info.is_registered is True

    def test_stake_unit_matches_netuid(self):
        """stake Balance unit should be set to the netuid."""
        decoded = _make_stake_decoded(netuid=5, stake_rao=1 * TAO)
        info = StakeInfo._fix_decoded(decoded)
        assert info.stake.unit == Balance.get_unit(5)

    def test_tao_emission_unit_is_not_netuid_unit(self):
        """tao_emission is constructed without .set_unit(), so it keeps the
        default Balance unit (lowercase τ, chr(0x03C4)), NOT the netuid unit."""
        decoded = _make_stake_decoded(netuid=3)
        info = StakeInfo._fix_decoded(decoded)
        # Default unit is lowercase τ; the netuid 3 unit would be something else.
        assert info.tao_emission.unit == chr(0x03C4)
        assert info.tao_emission.unit != Balance.get_unit(3)

    def test_zero_stake(self):
        """A stake of 0 rao should decode to a zero Balance."""
        decoded = _make_stake_decoded(stake_rao=0)
        info = StakeInfo._fix_decoded(decoded)
        assert info.stake.rao == 0

    def test_list_from_any_decodes_multiple(self):
        """list_from_any should decode a list of stake dicts."""
        decoded_list = [
            _make_stake_decoded(netuid=i, stake_rao=i * TAO) for i in range(3)
        ]
        infos = StakeInfo.list_from_any(decoded_list)
        assert len(infos) == 3
        for i, info in enumerate(infos):
            assert info.netuid == i
            assert info.stake.tao == pytest.approx(float(i))


# ---------------------------------------------------------------------------
# NeuronInfo._fix_decoded
# ---------------------------------------------------------------------------


class TestNeuronInfoFixDecoded:
    def test_normal_decode(self):
        """NeuronInfo decodes correctly from a standard decoded dict."""
        decoded = _make_neuron_decoded(emission_rao=TAO)
        info = NeuronInfo._fix_decoded(decoded)
        assert isinstance(info, NeuronInfo)
        assert info.uid == 0
        assert info.netuid == 1
        assert info.is_null is False

    def test_emission_converted_from_rao_to_float(self):
        """emission field should be rao/1e9 (i.e. in tao units)."""
        decoded = _make_neuron_decoded(emission_rao=TAO)  # 1 TAO
        info = NeuronInfo._fix_decoded(decoded)
        assert info.emission == pytest.approx(1.0)

    def test_weights_list_decoded(self):
        """weights should be a list of [uid, weight] pairs."""
        decoded = _make_neuron_decoded()
        info = NeuronInfo._fix_decoded(decoded)
        assert isinstance(info.weights, list)
        assert info.weights == [[0, 65535]]

    def test_bonds_list_decoded(self):
        """bonds should be a list of [uid, value] pairs."""
        decoded = _make_neuron_decoded()
        info = NeuronInfo._fix_decoded(decoded)
        assert isinstance(info.bonds, list)

    def test_rank_normalized(self):
        """rank must be u16-normalized float in [0, 1]."""
        decoded = _make_neuron_decoded()
        decoded["rank"] = 32767  # ~0.5
        info = NeuronInfo._fix_decoded(decoded)
        assert 0.0 <= info.rank <= 1.0

    def test_get_null_neuron(self):
        """get_null_neuron() should return a NeuronInfo with is_null=True."""
        null = NeuronInfo.get_null_neuron()
        assert null.is_null is True
        assert null.uid == 0
        assert null.stake.rao == 0

    def test_stake_dict_populated_from_stake_list(self):
        """stake_dict should contain the decoded coldkey → Balance mapping."""
        decoded = _make_neuron_decoded(emission_rao=5 * TAO)
        info = NeuronInfo._fix_decoded(decoded)
        assert isinstance(info.stake_dict, dict)
        # One entry from _ACCOUNT_ID → 5 TAO
        assert len(info.stake_dict) == 1
