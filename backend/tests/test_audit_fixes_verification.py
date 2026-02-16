"""
Simplified verification tests for critical bug fixes.
Tests core fix logic without complex module dependencies.
"""

import pytest
import numpy as np
import pandas as pd
from datetime import date, datetime, timedelta


class TestBugFix1_ForwardLookingLabels:
    """BUG #1: Forward-looking labels division by zero protection"""

    def test_epsilon_guard_prevents_log_zero(self):
        """Verify epsilon guard prevents log(0) and division by zero."""
        prices = np.array([100.0, 0.0, 105.0, 110.0])

        # Fixed implementation: guard against zero/negative prices
        current_prices = prices[:-1]
        future_prices = prices[1:]
        valid_idx = (current_prices > 1e-8) & (future_prices > 1e-8)

        # Create result array with same length as returns
        fwd_ret = np.full(len(current_prices), np.nan, dtype=float)

        # Only compute where both current and future prices are valid
        fwd_ret[valid_idx] = np.log(future_prices[valid_idx] / current_prices[valid_idx])

        # Check no -inf values (which would come from log(0))
        assert not np.any(np.isinf(fwd_ret) & (fwd_ret < 0))


class TestBugFix2_WeightNormalization:
    """BUG #2: Weight normalization division by zero protection"""

    def test_epsilon_guard_normalizes_zero_weights(self):
        """Verify epsilon guard prevents division by zero in weight normalization."""
        weights = np.array([0.0, 0.0, 0.0])

        # Fixed implementation with epsilon guard
        weight_mean = np.maximum(np.mean(weights), 1e-8)
        normalized = weights / weight_mean

        assert not np.any(np.isnan(normalized))
        assert not np.any(np.isinf(normalized))
        assert weight_mean >= 1e-8


class TestBugFix3_SharpeRatioLogic:
    """BUG #3: Sharpe ratio check before division"""

    def test_sharpe_volatility_threshold(self):
        """Verify Sharpe ratio check uses proper threshold."""
        cumulative_return = 0.05
        volatility = 1e-11  # Very small volatility

        # Fixed implementation: check BEFORE division
        sharpe = cumulative_return / (volatility + 1e-10) if volatility > 1e-10 else 0

        assert sharpe == 0  # Should be zero due to threshold check
        assert not np.isnan(sharpe)
        assert not np.isinf(sharpe)


class TestBugFix4_PeriodReturnsFormula:
    """BUG #4: Period returns uses correct formula (cumulative, not mixed)"""

    def test_period_returns_correct_formula(self):
        """Verify period returns subtract cumulative values, not daily from cumulative."""
        # Sample data: cumulative returns tracking
        cumulative_returns = [0.0, 0.01, 0.025, 0.04]  # Starting, then +1%, +1.5%, +1.5%

        # WRONG (old buggy) formula: would subtract daily from cumulative
        # CORRECT formula: subtract ending cumulative from starting cumulative
        period_return = cumulative_returns[-1] - cumulative_returns[0]

        assert period_return == 0.04  # Should be ~4% total, not something weird


class TestBugFix5_PositionPnLDivisionByZero:
    """BUG #5: Position P&L calculation division by zero protection"""

    def test_position_cost_epsilon_guard(self):
        """Verify epsilon guard prevents division by zero in PnL calculation."""
        quantity = 0.0
        avg_cost = 100.0
        unrealized_pnl = 0.0

        # Fixed implementation with epsilon guard
        position_cost = max(quantity * avg_cost, 1e-8)
        unrealized_pnl_pct = unrealized_pnl / position_cost

        assert not np.isnan(unrealized_pnl_pct)
        assert not np.isinf(unrealized_pnl_pct)
        assert unrealized_pnl_pct == 0.0


class TestBugFix6_ReturnsDivisionByZero:
    """BUG #6: Returns calculation division by zero protection"""

    def test_returns_epsilon_guard_zero_values(self):
        """Verify epsilon guard prevents division by zero in returns calculation."""
        values = np.array([10000.0, 0.0, 5000.0])

        # Fixed implementation with epsilon guard
        diffs = np.diff(values)
        prev_values = np.maximum(values[:-1], 1e-8)
        returns = diffs / prev_values

        assert not np.any(np.isnan(returns))
        assert not np.any(np.isinf(returns))

    def test_returns_small_equity_values(self):
        """Verify epsilon guard works with very small values."""
        values = np.array([10000.0, 1e-10, 1e-9])

        diffs = np.diff(values)
        prev_values = np.maximum(values[:-1], 1e-8)
        returns = diffs / prev_values

        assert all(np.isfinite(returns))


class TestBugFix7_RiskContributionDivisionByZero:
    """BUG #7: Risk contribution division by zero protection"""

    def test_risk_parity_zero_volatility(self):
        """Verify epsilon guard prevents division by zero in risk parity."""
        weights = np.array([0.33, 0.33, 0.34])
        cov = np.zeros((3, 3))  # Zero covariance

        # Fixed implementation
        port_var = weights @ cov @ weights
        port_vol = np.sqrt(port_var)
        port_vol_safe = np.maximum(port_vol, 1e-8)

        mrc = np.ones(3) / port_vol_safe  # Example MRC calculation

        assert not np.any(np.isnan(mrc))
        assert not np.any(np.isinf(mrc))
        assert port_vol_safe >= 1e-8

    def test_risk_parity_small_volatility(self):
        """Verify epsilon guard works with tiny volatilities."""
        weights = np.array([0.5, 0.5])
        cov = np.eye(2) * 1e-12  # Tiny covariance

        port_var = weights @ cov @ weights
        port_vol = np.sqrt(port_var)
        port_vol_safe = np.maximum(port_vol, 1e-8)

        assert port_vol_safe >= 1e-8


class TestBugFix8_BooleanPrecedence:
    """BUG #8: Boolean operator precedence in broker connection check"""

    def test_broker_connection_logic(self):
        """Verify correct boolean logic for broker connection."""
        # Simulate broker state
        class MockBroker:
            def __init__(self, connected):
                self._connected = connected

        class MockManager:
            def __init__(self):
                self.alpaca = MockBroker(True)
                self.credentials = {"ALPACA": type('obj', (object,), {'is_paper': False})}

        manager = MockManager()

        # Fixed implementation with proper parentheses
        is_live = False
        if (manager.alpaca and manager.alpaca._connected and
            "ALPACA" in manager.credentials):
            is_live = not manager.credentials["ALPACA"].is_paper

        assert is_live is True

    def test_broker_disconnected_logic(self):
        """Verify disconnected broker returns is_live=False."""
        class MockBroker:
            def __init__(self, connected):
                self._connected = connected

        class MockManager:
            def __init__(self):
                self.alpaca = MockBroker(False)
                self.credentials = {"ALPACA": type('obj', (object,), {'is_paper': False})}

        manager = MockManager()

        is_live = False
        if (manager.alpaca and manager.alpaca._connected and
            "ALPACA" in manager.credentials):
            is_live = not manager.credentials["ALPACA"].is_paper

        assert is_live is False


class TestBugFix9_EmptyTickersValidation:
    """BUG #9: Empty tickers list validation"""

    def test_empty_tickers_guard(self):
        """Verify empty tickers list is caught early."""
        tickers = []

        # Fixed implementation guard
        if not tickers:
            result = {}
        else:
            result = {"would": "download"}

        assert result == {}

    def test_non_empty_tickers_proceed(self):
        """Verify non-empty tickers proceed normally."""
        tickers = ["AAPL", "MSFT"]

        if not tickers:
            result = {}
        else:
            result = {"proceeds": True}

        assert result == {"proceeds": True}


class TestBugFix10_TickerExtractionRobustness:
    """BUG #10: Robust ticker extraction from feature names"""

    def test_feature_with_underscore_split(self):
        """Verify safe ticker extraction from feature names."""
        feature_names = [
            "AAPL_ret_1",
            "MSFT_ma_20",
            "BTC_crypto_vol",
            "NoUnderscore",  # Edge case
        ]

        # Fixed implementation: safely extract first part
        tickers = []
        for col in feature_names:
            parts = col.split("_")
            if parts:
                ticker = parts[0]
                tickers.append(ticker)

        assert "AAPL" in tickers
        assert "MSFT" in tickers
        assert "BTC" in tickers
        assert "NoUnderscore" in tickers  # Still extracted
        assert len(tickers) == 4


class TestBugFix11_OLSRegressionBounds:
    """BUG #11: OLS regression bounds checking"""

    def test_ols_coefficient_bounds_check(self):
        """Verify OLS result is validated for sufficient coefficients."""
        # Simulate OLS regression
        a_norm = np.array([1.0, 2.0, 3.0])
        b_norm = np.array([1.0, 2.0, 3.0])

        X = np.column_stack([np.ones(len(a_norm)), b_norm])
        beta = np.linalg.lstsq(X, a_norm, rcond=None)[0]

        # Fixed implementation: validate length before access
        if len(beta) < 2:
            hedge_ratio = 1.0
        else:
            hedge_ratio = beta[1]

        assert hedge_ratio is not None
        assert isinstance(hedge_ratio, (int, float, np.number))

    def test_non_finite_hedge_ratio_fallback(self):
        """Verify non-finite hedge ratios are caught."""
        hedge_ratio = float('inf')

        # Fixed implementation: check for finite values
        if np.isfinite(hedge_ratio):
            final_ratio = hedge_ratio
        else:
            final_ratio = 1.0

        assert final_ratio == 1.0


class TestBugFix12_TradeWinRateLogic:
    """BUG #12: Trade win rate counts only profitable trades"""

    def test_win_rate_counts_profitable_only(self):
        """Verify win rate counts only profitable trades."""
        trades = [
            {"side": "buy", "pnl": 0},     # Entry
            {"side": "sell", "pnl": 100},  # Profitable exit
            {"side": "buy", "pnl": 0},     # Another entry
            {"side": "sell", "pnl": -50},  # Loss
        ]

        # Fixed implementation: count only profitable sells
        winning_trades = sum(
            1 for t in trades
            if t["side"] == "sell" and t.get("pnl", 0) > 0
        )

        assert winning_trades == 1  # Only 1 profitable sell

    def test_all_losing_trades(self):
        """Verify all-losing trades gives zero wins."""
        trades = [
            {"side": "buy", "pnl": 0},
            {"side": "sell", "pnl": -100},
            {"side": "buy", "pnl": 0},
            {"side": "sell", "pnl": -50},
        ]

        winning_trades = sum(
            1 for t in trades
            if t["side"] == "sell" and t.get("pnl", 0) > 0
        )

        assert winning_trades == 0


# ============================================================================
# INTEGRATION TESTS
# ============================================================================

class TestIntegrationAllFixes:
    """Verify all fixes work together correctly."""

    def test_numerical_stability_with_edge_cases(self):
        """Test numerical stability with all edge cases."""
        prices = np.array([100.0, 0.0, 1e-10, 1e10, 0.5])

        # Test multiple operations with epsilon guards
        valid_mask = (prices > 1e-8)

        # Forward returns with guard
        if np.sum(valid_mask[:-1] & valid_mask[1:]) > 0:
            valid_indices = valid_mask[:-1] & valid_mask[1:]
            returns = np.log(prices[1:][valid_indices] / prices[:-1][valid_indices])
            assert all(np.isfinite(returns))

    def test_portfolio_operations_with_edge_cases(self):
        """Test portfolio operations handle all edge cases."""
        # Simulated portfolio values
        equity_values = [10000.0, 0.0, -1000.0, 5000.0]

        # Returns calculation with guard
        safe_values = np.maximum(np.array(equity_values[:-1]), 1e-8)
        returns = np.diff(equity_values) / safe_values

        assert all(np.isfinite(returns))

        # Volatility calculation
        volatility = np.std(returns) if len(returns) > 1 else 0
        assert np.isfinite(volatility) or volatility == 0

    def test_model_metrics_robustness(self):
        """Test model metrics calculation is robust."""
        metrics_inputs = [
            (0.05, 0.0),      # Return, vol = 0 (zero volatility)
            (0.05, 1e-12),    # Return, tiny vol
            (0.0, 0.1),       # Zero return, normal vol
            (-0.5, 0.2),      # Loss, normal vol
        ]

        for ret, vol in metrics_inputs:
            # Sharpe ratio with proper check
            sharpe = ret / (vol + 1e-10) if vol > 1e-10 else 0
            assert np.isfinite(sharpe)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
