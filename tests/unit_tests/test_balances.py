"""
Unit tests for the Balance class in bittensor_cli/src/bittensor/balances.py.

All tests are synchronous and require no mocks — Balance is a pure value object.
"""

import pytest

from bittensor_cli.src.bittensor.balances import Balance, fixed_to_float
from bittensor_cli.src import UNITS


RAO_PER_TAO = 1_000_000_000  # 10^9


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestBalanceConstruction:
    def test_int_stores_as_rao(self):
        b = Balance(RAO_PER_TAO)
        assert b.rao == RAO_PER_TAO

    def test_zero_int(self):
        b = Balance(0)
        assert b.rao == 0

    def test_float_converts_tao_to_rao(self):
        b = Balance(1.0)
        assert b.rao == RAO_PER_TAO

    def test_float_half_tao(self):
        b = Balance(0.5)
        assert b.rao == RAO_PER_TAO // 2

    def test_invalid_type_raises_type_error(self):
        with pytest.raises(TypeError):
            Balance("1")

    def test_invalid_type_none_raises_type_error(self):
        with pytest.raises(TypeError):
            Balance(None)

    def test_large_int(self):
        b = Balance(10 * RAO_PER_TAO)
        assert b.rao == 10 * RAO_PER_TAO


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------


class TestBalanceProperties:
    def test_tao_property_one_tao(self):
        b = Balance(RAO_PER_TAO)
        assert b.tao == pytest.approx(1.0)

    def test_tao_property_zero(self):
        b = Balance(0)
        assert b.tao == 0.0

    def test_int_conversion(self):
        b = Balance(42)
        assert int(b) == 42

    def test_float_conversion(self):
        b = Balance(RAO_PER_TAO)
        assert float(b) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Factory methods
# ---------------------------------------------------------------------------


class TestBalanceFactories:
    def test_from_rao(self):
        b = Balance.from_rao(RAO_PER_TAO)
        assert b.rao == RAO_PER_TAO

    def test_from_tao(self):
        b = Balance.from_tao(1.0)
        assert b.rao == RAO_PER_TAO

    def test_from_float(self):
        b = Balance.from_float(2.0)
        assert b.rao == 2 * RAO_PER_TAO

    def test_from_tao_and_from_float_agree(self):
        assert Balance.from_tao(3.5).rao == Balance.from_float(3.5).rao

    def test_from_rao_zero(self):
        b = Balance.from_rao(0)
        assert b.rao == 0


# ---------------------------------------------------------------------------
# Arithmetic
# ---------------------------------------------------------------------------


class TestBalanceArithmetic:
    def test_add_two_balances(self):
        a = Balance.from_tao(1.0)
        b = Balance.from_tao(2.0)
        assert (a + b).rao == 3 * RAO_PER_TAO

    def test_add_int(self):
        a = Balance.from_tao(1.0)
        result = a + RAO_PER_TAO
        assert result.rao == 2 * RAO_PER_TAO

    def test_radd_int(self):
        a = Balance.from_tao(1.0)
        result = RAO_PER_TAO + a
        assert result.rao == 2 * RAO_PER_TAO

    def test_add_unsupported_raises(self):
        with pytest.raises(NotImplementedError):
            Balance.from_tao(1.0) + "x"

    def test_sub_two_balances(self):
        a = Balance.from_tao(3.0)
        b = Balance.from_tao(1.0)
        assert (a - b).rao == 2 * RAO_PER_TAO

    def test_sub_int(self):
        a = Balance.from_tao(2.0)
        result = a - RAO_PER_TAO
        assert result.rao == RAO_PER_TAO

    def test_rsub_int(self):
        b = Balance.from_tao(1.0)
        result = 2 * RAO_PER_TAO - b
        assert result.rao == RAO_PER_TAO

    def test_mul_balance(self):
        a = Balance.from_rao(4)
        b = Balance.from_rao(3)
        assert (a * b).rao == 12  # 4*3 rao

    def test_mul_int(self):
        a = Balance.from_tao(2.0)
        result = a * 3
        assert result.rao == 6 * RAO_PER_TAO

    def test_rmul_int(self):
        a = Balance.from_tao(2.0)
        result = 3 * a
        assert result.rao == 6 * RAO_PER_TAO

    def test_mul_unsupported_raises(self):
        with pytest.raises(NotImplementedError):
            Balance.from_tao(1.0) * "x"

    def test_truediv_by_int(self):
        a = Balance.from_tao(6.0)
        result = a / 3
        assert result.rao == 2 * RAO_PER_TAO

    def test_rtruediv_int(self):
        a = Balance.from_rao(4)
        result = 12 / a
        assert result.rao == 3  # 12 // 4 rao

    def test_floordiv_by_int(self):
        a = Balance.from_rao(7)
        result = a // 2
        assert result.rao == 3  # 7 // 2 rao

    def test_rfloordiv_int(self):
        a = Balance.from_rao(3)
        result = 10 // a
        assert result.rao == 3  # 10 // 3 rao


# ---------------------------------------------------------------------------
# Unary operators
# ---------------------------------------------------------------------------


class TestBalanceUnary:
    def test_neg(self):
        b = Balance.from_tao(1.0)
        assert (-b).rao == -RAO_PER_TAO

    def test_pos(self):
        b = Balance.from_tao(1.0)
        assert (+b).rao == RAO_PER_TAO

    def test_abs_positive(self):
        b = Balance.from_rao(5)
        assert abs(b).rao == 5

    def test_abs_negative(self):
        b = Balance.from_rao(-5)
        assert abs(b).rao == 5


# ---------------------------------------------------------------------------
# Comparisons
# ---------------------------------------------------------------------------


class TestBalanceComparisons:
    def test_eq_same_balance(self):
        a = Balance.from_tao(1.0)
        b = Balance.from_tao(1.0)
        assert a == b

    def test_eq_different_balance(self):
        a = Balance.from_tao(1.0)
        b = Balance.from_tao(2.0)
        assert not (a == b)

    def test_eq_none_returns_false(self):
        b = Balance.from_tao(1.0)
        assert (b == None) is False  # noqa: E711

    def test_ne(self):
        a = Balance.from_tao(1.0)
        b = Balance.from_tao(2.0)
        assert a != b

    def test_gt_true(self):
        a = Balance.from_tao(2.0)
        b = Balance.from_tao(1.0)
        assert a > b

    def test_gt_false(self):
        a = Balance.from_tao(1.0)
        b = Balance.from_tao(2.0)
        assert not (a > b)

    def test_lt_true(self):
        a = Balance.from_tao(1.0)
        b = Balance.from_tao(2.0)
        assert a < b

    def test_le_equal(self):
        a = Balance.from_tao(1.0)
        b = Balance.from_tao(1.0)
        assert a <= b

    def test_le_less(self):
        a = Balance.from_tao(0.5)
        b = Balance.from_tao(1.0)
        assert a <= b

    def test_ge_equal(self):
        a = Balance.from_tao(1.0)
        b = Balance.from_tao(1.0)
        assert a >= b

    def test_ge_greater(self):
        a = Balance.from_tao(2.0)
        b = Balance.from_tao(1.0)
        assert a >= b

    def test_eq_with_int_rao(self):
        b = Balance.from_tao(1.0)
        assert b == RAO_PER_TAO


# ---------------------------------------------------------------------------
# Boolean
# ---------------------------------------------------------------------------


class TestBalanceBool:
    def test_zero_is_falsy(self):
        assert not Balance(0)

    def test_nonzero_is_truthy(self):
        assert Balance(1)

    def test_negative_is_truthy(self):
        assert Balance.from_rao(-1)


# ---------------------------------------------------------------------------
# String representation
# ---------------------------------------------------------------------------


class TestBalanceStr:
    def test_str_contains_tao_symbol(self):
        b = Balance.from_tao(1.0)
        s = str(b)
        # Default unit is lowercase τ (chr(0x03C4)), not the uppercase UNITS[0] Τ
        assert chr(0x03C4) in s

    def test_str_contains_value(self):
        b = Balance.from_tao(1.0)
        s = str(b)
        assert "1" in s

    def test_str_with_non_default_unit(self):
        b = Balance.from_tao(1.0)
        b.set_unit(1)  # Alpha unit
        s = str(b)
        assert UNITS[1] in s


# ---------------------------------------------------------------------------
# to_dict
# ---------------------------------------------------------------------------


class TestBalanceToDict:
    def test_to_dict_keys(self):
        b = Balance.from_tao(1.0)
        d = b.to_dict()
        assert set(d.keys()) == {"rao", "tao"}

    def test_to_dict_rao_is_int(self):
        b = Balance.from_tao(1.0)
        assert isinstance(b.to_dict()["rao"], int)

    def test_to_dict_tao_is_float(self):
        b = Balance.from_tao(1.0)
        assert isinstance(b.to_dict()["tao"], float)

    def test_to_dict_values(self):
        b = Balance.from_tao(2.0)
        d = b.to_dict()
        assert d["rao"] == 2 * RAO_PER_TAO
        assert d["tao"] == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# get_unit / set_unit
# ---------------------------------------------------------------------------


class TestBalanceUnit:
    def test_get_unit_netuid_0_is_tau(self):
        assert Balance.get_unit(0) == UNITS[0]

    def test_get_unit_netuid_1_is_alpha(self):
        assert Balance.get_unit(1) == UNITS[1]

    def test_get_unit_within_range(self):
        for i in range(len(UNITS)):
            assert Balance.get_unit(i) == UNITS[i]

    def test_get_unit_beyond_units_length(self):
        # Should compute a combined unit string for netuids >= len(UNITS)
        unit = Balance.get_unit(len(UNITS))
        assert isinstance(unit, str)
        assert len(unit) > 0

    def test_set_unit_mutates_and_returns_self(self):
        b = Balance.from_tao(1.0)
        result = b.set_unit(2)
        assert result is b
        assert b.unit == UNITS[2]

    def test_set_unit_zero(self):
        b = Balance.from_tao(1.0)
        b.set_unit(0)
        assert b.unit == UNITS[0]


# ---------------------------------------------------------------------------
# fixed_to_float
# ---------------------------------------------------------------------------


class TestFixedToFloat:
    def test_zero_fixed(self):
        result = fixed_to_float({"bits": 0})
        assert result == pytest.approx(0.0)

    def test_one_integer_part(self):
        # 1.0 in U64F64: integer_part=1, fractional_part=0
        # bits = 1 << 64
        bits = 1 << 64
        result = fixed_to_float({"bits": bits})
        assert result == pytest.approx(1.0)

    def test_half_fractional(self):
        # 0.5 in U64F64: integer_part=0, fractional_part=2^63
        bits = 1 << 63
        result = fixed_to_float({"bits": bits})
        assert result == pytest.approx(0.5)

    def test_one_and_half(self):
        # 1.5: integer_part bits=1<<64, fractional=1<<63
        bits = (1 << 64) + (1 << 63)
        result = fixed_to_float({"bits": bits})
        assert result == pytest.approx(1.5)
