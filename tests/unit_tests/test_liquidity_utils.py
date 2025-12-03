"""Unit tests for liquidity utility functions."""
import math
import pytest
from bittensor_cli.src.bittensor.balances import Balance
from bittensor_cli.src.commands.liquidity.utils import (
    calculate_max_liquidity_from_balances,
    calculate_alpha_from_tao,
    calculate_tao_from_alpha,
)


class TestLiquidityCalculations:
    """Test the new liquidity calculation helper functions."""

    def test_calculate_max_liquidity_only_alpha_needed(self):
        """Test when current price is below the range (only Alpha needed)."""
        tao_balance = Balance.from_tao(100.0)
        alpha_balance = Balance.from_tao(50.0)
        current_price = Balance.from_tao(1.0)  # Below range
        price_low = Balance.from_tao(2.0)
        price_high = Balance.from_tao(3.0)

        max_liquidity, max_tao, max_alpha = calculate_max_liquidity_from_balances(
            tao_balance, alpha_balance, current_price, price_low, price_high
        )

        # When price is below range, only Alpha is needed
        assert max_tao.rao == 0, "No TAO should be needed when price is below range"
        assert max_alpha.rao == alpha_balance.rao, "All available Alpha should be used"
        assert max_liquidity.rao > 0, "Liquidity should be calculated"

    def test_calculate_max_liquidity_only_tao_needed(self):
        """Test when current price is above the range (only TAO needed)."""
        tao_balance = Balance.from_tao(100.0)
        alpha_balance = Balance.from_tao(50.0)
        current_price = Balance.from_tao(5.0)  # Above range
        price_low = Balance.from_tao(2.0)
        price_high = Balance.from_tao(3.0)

        max_liquidity, max_tao, max_alpha = calculate_max_liquidity_from_balances(
            tao_balance, alpha_balance, current_price, price_low, price_high
        )

        # When price is above range, only TAO is needed
        assert max_tao.rao == tao_balance.rao, "All available TAO should be used"
        assert max_alpha.rao == 0, "No Alpha should be needed when price is above range"
        assert max_liquidity.rao > 0, "Liquidity should be calculated"

    def test_calculate_max_liquidity_both_needed(self):
        """Test when current price is within the range (both TAO and Alpha needed)."""
        tao_balance = Balance.from_tao(100.0)
        alpha_balance = Balance.from_tao(50.0)
        current_price = Balance.from_tao(2.5)  # Within range
        price_low = Balance.from_tao(2.0)
        price_high = Balance.from_tao(3.0)

        max_liquidity, max_tao, max_alpha = calculate_max_liquidity_from_balances(
            tao_balance, alpha_balance, current_price, price_low, price_high
        )

        # When price is within range, both are needed
        assert max_tao.rao > 0, "TAO should be needed when price is within range"
        assert max_alpha.rao > 0, "Alpha should be needed when price is within range"
        assert max_liquidity.rao > 0, "Liquidity should be calculated"
        # Should not exceed available balances
        assert max_tao.rao <= tao_balance.rao, "TAO needed should not exceed balance"
        assert max_alpha.rao <= alpha_balance.rao, "Alpha needed should not exceed balance"

    def test_calculate_alpha_from_tao_within_range(self):
        """Test calculating Alpha amount from TAO when price is within range."""
        tao_amount = Balance.from_tao(10.0)
        current_price = Balance.from_tao(2.5)
        price_low = Balance.from_tao(2.0)
        price_high = Balance.from_tao(3.0)

        alpha_needed = calculate_alpha_from_tao(
            tao_amount, current_price, price_low, price_high
        )

        assert alpha_needed.rao > 0, "Alpha should be needed for TAO within range"

    def test_calculate_alpha_from_tao_below_range(self):
        """Test that no Alpha is calculated when price is below range."""
        tao_amount = Balance.from_tao(10.0)
        current_price = Balance.from_tao(1.0)  # Below range
        price_low = Balance.from_tao(2.0)
        price_high = Balance.from_tao(3.0)

        alpha_needed = calculate_alpha_from_tao(
            tao_amount, current_price, price_low, price_high
        )

        assert alpha_needed.rao == 0, "No Alpha needed when price is below range"

    def test_calculate_alpha_from_tao_above_range(self):
        """Test that no Alpha is needed when price is above range."""
        tao_amount = Balance.from_tao(10.0)
        current_price = Balance.from_tao(5.0)  # Above range
        price_low = Balance.from_tao(2.0)
        price_high = Balance.from_tao(3.0)

        alpha_needed = calculate_alpha_from_tao(
            tao_amount, current_price, price_low, price_high
        )

        assert alpha_needed.rao == 0, "No Alpha needed when price is above range"

    def test_calculate_tao_from_alpha_within_range(self):
        """Test calculating TAO amount from Alpha when price is within range."""
        alpha_amount = Balance.from_tao(10.0)
        current_price = Balance.from_tao(2.5)
        price_low = Balance.from_tao(2.0)
        price_high = Balance.from_tao(3.0)

        tao_needed = calculate_tao_from_alpha(
            alpha_amount, current_price, price_low, price_high
        )

        assert tao_needed.rao > 0, "TAO should be needed for Alpha within range"

    def test_calculate_tao_from_alpha_below_range(self):
        """Test that no TAO is needed when price is below range."""
        alpha_amount = Balance.from_tao(10.0)
        current_price = Balance.from_tao(1.0)  # Below range
        price_low = Balance.from_tao(2.0)
        price_high = Balance.from_tao(3.0)

        tao_needed = calculate_tao_from_alpha(
            alpha_amount, current_price, price_low, price_high
        )

        assert tao_needed.rao == 0, "No TAO needed when price is below range"

    def test_calculate_tao_from_alpha_above_range(self):
        """Test that no TAO is calculated when price is above range."""
        alpha_amount = Balance.from_tao(10.0)
        current_price = Balance.from_tao(5.0)  # Above range
        price_low = Balance.from_tao(2.0)
        price_high = Balance.from_tao(3.0)

        tao_needed = calculate_tao_from_alpha(
            alpha_amount, current_price, price_low, price_high
        )

        assert tao_needed.rao == 0, "No TAO calculated when price is above range"

    def test_reciprocal_calculation(self):
        """Test that TAO->Alpha->TAO conversion is consistent."""
        tao_amount = Balance.from_tao(10.0)
        current_price = Balance.from_tao(2.5)
        price_low = Balance.from_tao(2.0)
        price_high = Balance.from_tao(3.0)

        # Calculate Alpha from TAO
        alpha_needed = calculate_alpha_from_tao(
            tao_amount, current_price, price_low, price_high
        )

        # Calculate TAO back from Alpha
        tao_back = calculate_tao_from_alpha(
            alpha_needed, current_price, price_low, price_high
        )

        # Should be approximately equal (within rounding error)
        assert abs(tao_back.rao - tao_amount.rao) < 1000, \
            "Reciprocal calculation should yield similar result"
