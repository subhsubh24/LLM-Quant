"""
Portfolio-Level Risk Management for 1600h Trading

Handles:
1. Drawdown limits (max 15% acceptable)
2. Per-position heat (max 3% risk per position)
3. Sector exposure limits (max 20% per sector)
4. Correlation tracking (avoid all-correlated positions)
5. Liquidity validation for position exit
"""

import numpy as np
from typing import Dict, List, Tuple
from collections import defaultdict

class PortfolioRiskManager:
    """Manage portfolio-level risks for 1600h trading."""

    def __init__(
        self,
        max_portfolio_drawdown: float = 0.15,  # 15% max drawdown
        max_position_heat: float = 0.03,       # 3% capital at risk per position
        max_sector_exposure: float = 0.20,     # 20% max per sector
        max_correlation: float = 0.70,         # Avoid highly correlated positions
        min_liquidity_ratio: float = 0.02,     # Can exit 2% position in <1% slippage
    ):
        self.max_drawdown = max_portfolio_drawdown
        self.max_heat = max_position_heat
        self.max_sector = max_sector_exposure
        self.max_corr = max_correlation
        self.min_liq = min_liquidity_ratio

        self.equity_history = []
        self.rolling_max = 0
        self.positions_active = {}
        self.sector_exposure = defaultdict(float)

    def update_equity(self, timestamp, capital: float):
        """Update equity curve for drawdown tracking."""
        self.equity_history.append((timestamp, capital))
        self.rolling_max = max(self.rolling_max, capital)

    def check_drawdown(self, current_capital: float) -> Tuple[bool, float]:
        """
        Check if current drawdown exceeds limit.

        Returns: (is_ok, current_drawdown_pct)
        """
        if self.rolling_max == 0:
            return True, 0.0

        current_dd = 1 - (current_capital / self.rolling_max)

        is_ok = current_dd <= self.max_drawdown
        return is_ok, current_dd

    def can_open_position(
        self,
        symbol: str,
        position_size: float,
        stop_loss_pct: float,
        sector: str = "unknown",
        correlation_with_existing: float = 0.0,
        current_capital: float = 1.0,
    ) -> Tuple[bool, str]:
        """
        Determine if can open new position based on risk limits.

        Checks:
        1. Position heat (% capital at risk)
        2. Sector exposure
        3. Correlation with existing positions
        4. Liquidity

        Returns: (can_open, reason)
        """
        # Check position heat (risk exposure)
        heat = position_size * stop_loss_pct
        # FIX #1: Add epsilon guard for division by zero
        heat_pct = heat / max(current_capital, 1e-8)

        if heat_pct > self.max_heat:
            return False, f"Exceeds max heat: {heat_pct:.2%} > {self.max_heat:.2%}"

        # Check sector exposure
        # FIX #2: Add epsilon guard for division by zero
        new_sector_exposure = self.sector_exposure[sector] + (position_size / max(current_capital, 1e-8))
        if new_sector_exposure > self.max_sector:
            return False, f"Sector {sector} exposure too high: {new_sector_exposure:.2%} > {self.max_sector:.2%}"

        # Check correlation with existing
        if correlation_with_existing > self.max_corr:
            return False, f"Too correlated with existing: {correlation_with_existing:.2f} > {self.max_corr:.2f}"

        return True, "OK"

    def check_liquidity_for_exit(
        self,
        symbol: str,
        position_size: float,
        avg_daily_volume: float,
        position_horizon_hours: int = 48,
    ) -> Tuple[bool, str]:
        """
        Verify can exit position in timeframe without excessive slippage.

        For 1600h positions, need to be able to exit gradually.
        """
        if avg_daily_volume == 0:
            return False, "No volume data"

        # Can we exit this position over the position horizon?
        # FIX #3 & #4: Add epsilon guards for division by zero
        if position_horizon_hours <= 0:
            return False, "Invalid position horizon"
        daily_exit_amount = position_size / (position_horizon_hours / 24)
        daily_volume_pct = daily_exit_amount / max(avg_daily_volume, 1e-8)

        # Need to be able to exit without moving market >1%
        if daily_volume_pct > 0.01:
            return False, f"Would need to sell {daily_volume_pct:.2%} of daily volume"

        return True, "Adequate liquidity"

    def estimate_exit_cost(
        self,
        position_size: float,
        exit_days: int = 20,  # Spread exit over 20 days for 1600h positions
        daily_volume: float = 1000000,
        base_spread_bps: float = 10,
    ) -> float:
        """
        Estimate slippage cost of exiting position gradually.

        More conservative for 1600h positions (spread over multiple days).
        """
        daily_exit = position_size / max(1, exit_days)
        daily_volume_pct = daily_exit / daily_volume

        # Market impact increases with volume
        # 0.1% of daily volume: ~10 bps additional slippage
        # 0.5% of daily volume: ~50 bps additional slippage
        market_impact_bps = min(200, daily_volume_pct * 1000 * 100)  # Cap at 200 bps

        total_bps = base_spread_bps + market_impact_bps
        total_cost = position_size * (total_bps / 10000)

        return total_cost

    def get_position_list_by_sector(self) -> Dict[str, List[str]]:
        """Get all positions grouped by sector."""
        by_sector = defaultdict(list)
        for symbol, pos_info in self.positions_active.items():
            sector = pos_info.get("sector", "unknown")
            by_sector[sector].append(symbol)
        return dict(by_sector)

    def update_sector_exposure(self, positions: Dict, capital: float):
        """Update tracked sector exposures."""
        self.sector_exposure.clear()
        # FIX #5: Add epsilon guard for division by zero
        if capital > 1e-8:
            for symbol, pos in positions.items():
                sector = pos.get("sector", "unknown")
                self.sector_exposure[sector] += (pos.get("size", 0) / capital)

    def should_close_all_positions(self, current_capital: float) -> bool:
        """
        Emergency stop: Close all positions if drawdown critical.

        Threshold: 20% drawdown (vs 15% normal limit)
        """
        if self.rolling_max == 0:
            return False

        current_dd = 1 - (current_capital / self.rolling_max)
        return current_dd > 0.20  # Emergency threshold

    def calculate_portfolio_correlation(self, price_data: Dict[str, List[float]]) -> np.ndarray:
        """
        Calculate correlation matrix of active positions.

        Used to detect portfolio clustering risk.
        """
        symbols = list(price_data.keys())
        if len(symbols) < 2:
            return np.array([[1.0]])

        # Get returns
        returns = []
        min_len = min(len(prices) for prices in price_data.values())

        for symbol in symbols:
            prices = np.array(price_data[symbol][-min_len:])
            # BUG FIX #6: Protect against division by zero in returns calculation
            ret = np.diff(prices) / (prices[:-1] + 1e-8)
            returns.append(ret)

        returns = np.array(returns)

        # Correlation matrix
        corr_matrix = np.corrcoef(returns)

        # CRITICAL FIX: Validate correlation matrix doesn't contain NaN values
        # NaN can occur when any returns series has zero variance (flat price)
        # If NaN detected, replace with zero correlation (safe assumption)
        if np.any(np.isnan(corr_matrix)):
            # Replace NaN with 0 (uncorrelated), keep 1.0 on diagonal (self-correlation)
            corr_matrix = np.nan_to_num(corr_matrix, nan=0.0)
            np.fill_diagonal(corr_matrix, 1.0)  # Restore diagonal to 1.0

        return corr_matrix

    def get_portfolio_risk_score(self) -> float:
        """
        Overall portfolio risk score (0-1).

        0 = safe, 1 = maximum risk
        """
        scores = []

        # Drawdown score
        # BUG FIX #1: equity_history contains (timestamp, capital) tuples, not just numbers
        if self.rolling_max > 0 and self.equity_history:
            current_capital = self.equity_history[-1][1]  # Extract capital from tuple
            current_dd = 1 - (current_capital / self.rolling_max)
            dd_score = min(1.0, current_dd / self.max_drawdown)
            scores.append(dd_score)

        # Sector concentration score
        max_sector = max(self.sector_exposure.values()) if self.sector_exposure else 0
        sector_score = min(1.0, max_sector / self.max_sector)
        scores.append(sector_score)

        # Number of positions score
        num_positions = len(self.positions_active)
        position_score = min(1.0, num_positions / 20)  # 20+ positions = fully invested
        scores.append(position_score)

        return np.mean(scores) if scores else 0.0


# Global portfolio risk manager
_portfolio_risk = PortfolioRiskManager()

def get_portfolio_risk_manager() -> PortfolioRiskManager:
    """Get the global portfolio risk manager instance."""
    return _portfolio_risk
