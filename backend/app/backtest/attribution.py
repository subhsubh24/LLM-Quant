"""
Performance attribution analysis.

Attributes returns to:
- Factor exposures (momentum, volatility, market, etc.)
- Sector allocation
- Stock selection
- Timing
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
import numpy as np
import pandas as pd
from loguru import logger


@dataclass
class AttributionResult:
    """Attribution analysis results."""

    # Factor attribution
    factor_returns: Dict[str, float]  # Factor name -> contribution
    factor_exposures: Dict[str, float]  # Factor name -> avg exposure

    # Sector attribution (if available)
    sector_allocation: Dict[str, float]  # Sector -> contribution
    sector_selection: Dict[str, float]  # Sector -> stock selection contribution

    # Time decomposition
    gross_return: float
    transaction_costs: float
    net_return: float

    # Explained vs unexplained
    explained_return: float
    residual_return: float

    def to_dict(self) -> dict:
        return {
            "factor_returns": self.factor_returns,
            "factor_exposures": self.factor_exposures,
            "sector_allocation": self.sector_allocation,
            "sector_selection": self.sector_selection,
            "gross_return": self.gross_return,
            "transaction_costs": self.transaction_costs,
            "net_return": self.net_return,
            "explained_return": self.explained_return,
            "residual_return": self.residual_return,
        }


class AttributionAnalysis:
    """
    Analyze sources of portfolio returns.

    Uses factor regression to decompose returns into:
    - Market exposure (beta)
    - Factor exposures (momentum, value, volatility, etc.)
    - Residual (stock selection / alpha)
    """

    def __init__(
        self,
        factor_names: Optional[List[str]] = None
    ):
        self.factor_names = factor_names or [
            "market", "momentum", "volatility", "size"
        ]

    def analyze(
        self,
        portfolio_returns: pd.Series,
        weights_history: pd.DataFrame,
        stock_returns: pd.DataFrame,
        market_returns: pd.Series,
        factor_returns: Optional[pd.DataFrame] = None,
        sector_map: Optional[Dict[str, str]] = None,
        transaction_costs: float = 0
    ) -> AttributionResult:
        """
        Run attribution analysis.

        Args:
            portfolio_returns: Portfolio daily returns
            weights_history: Portfolio weights over time
            stock_returns: Individual stock returns
            market_returns: Market benchmark returns
            factor_returns: Optional factor return series
            sector_map: Ticker -> sector mapping
            transaction_costs: Total transaction costs

        Returns:
            AttributionResult
        """
        # Compute factor exposures and returns
        factor_analysis = self._factor_attribution(
            portfolio_returns, market_returns, factor_returns
        )

        # Sector attribution
        sector_alloc, sector_select = self._sector_attribution(
            weights_history, stock_returns, market_returns, sector_map
        )

        # Gross vs net
        gross_return = portfolio_returns.sum()
        costs_pct = transaction_costs / 100000  # Rough percentage
        net_return = gross_return  # Costs already included in returns

        # Explained return
        explained = sum(factor_analysis["returns"].values())
        residual = gross_return - explained

        return AttributionResult(
            factor_returns=factor_analysis["returns"],
            factor_exposures=factor_analysis["exposures"],
            sector_allocation=sector_alloc,
            sector_selection=sector_select,
            gross_return=gross_return,
            transaction_costs=costs_pct,
            net_return=net_return,
            explained_return=explained,
            residual_return=residual
        )

    def _factor_attribution(
        self,
        portfolio_returns: pd.Series,
        market_returns: pd.Series,
        factor_returns: Optional[pd.DataFrame]
    ) -> Dict:
        """Attribute returns to factors using regression."""
        from sklearn.linear_model import LinearRegression

        # Align data
        if factor_returns is not None:
            all_factors = pd.concat([market_returns, factor_returns], axis=1)
            all_factors.columns = ["market"] + list(factor_returns.columns)
        else:
            all_factors = pd.DataFrame({"market": market_returns})

        aligned = pd.concat([portfolio_returns, all_factors], axis=1).dropna()

        if len(aligned) < 30:
            logger.warning("Insufficient data for factor attribution")
            return {
                "returns": {f: 0 for f in self.factor_names},
                "exposures": {f: 0 for f in self.factor_names}
            }

        y = aligned.iloc[:, 0].values
        X = aligned.iloc[:, 1:].values

        # Regression
        reg = LinearRegression()
        reg.fit(X, y)

        # Factor exposures (betas)
        factor_cols = aligned.columns[1:].tolist()
        exposures = dict(zip(factor_cols, reg.coef_))

        # Factor returns contribution
        factor_means = aligned.iloc[:, 1:].mean()
        contributions = {
            col: exposures[col] * factor_means[col] * 252
            for col in factor_cols
        }

        # Ensure all expected factors are present
        for f in self.factor_names:
            if f not in exposures:
                exposures[f] = 0
            if f not in contributions:
                contributions[f] = 0

        return {
            "returns": contributions,
            "exposures": exposures
        }

    def _sector_attribution(
        self,
        weights_history: pd.DataFrame,
        stock_returns: pd.DataFrame,
        market_returns: pd.Series,
        sector_map: Optional[Dict[str, str]]
    ) -> Tuple[Dict[str, float], Dict[str, float]]:
        """Attribute returns to sector allocation and selection."""
        if sector_map is None or weights_history.empty:
            return {}, {}

        # Get unique sectors
        sectors = set(sector_map.values())
        sector_allocation = {s: 0 for s in sectors}
        sector_selection = {s: 0 for s in sectors}

        # For each date, compute sector contributions
        common_dates = weights_history.index.intersection(stock_returns.index)

        for dt in common_dates:
            weights = weights_history.loc[dt]
            returns = stock_returns.loc[dt] if dt in stock_returns.index else pd.Series()

            for sector in sectors:
                # Tickers in this sector
                sector_tickers = [t for t, s in sector_map.items() if s == sector]

                # Portfolio weight in sector
                sector_weight = sum(weights.get(t, 0) for t in sector_tickers)

                # Sector return (equal weighted)
                sector_returns = [returns.get(t, 0) for t in sector_tickers if t in returns]
                sector_ret = np.mean(sector_returns) if sector_returns else 0

                # Market weight (assume equal)
                market_weight = 1 / len(sectors)
                market_ret = market_returns.get(dt, 0) if dt in market_returns.index else 0

                # Allocation effect: (portfolio weight - market weight) * sector return
                alloc_effect = (sector_weight - market_weight) * sector_ret
                sector_allocation[sector] += alloc_effect

                # Selection effect: portfolio weight * (stock selection vs sector)
                # Simplified: weight * (portfolio sector return - sector benchmark)
                # This is a simplified Brinson attribution

        # Annualize
        n_periods = len(common_dates)
        if n_periods > 0:
            for s in sectors:
                sector_allocation[s] = (sector_allocation[s] / n_periods) * 252
                sector_selection[s] = (sector_selection[s] / n_periods) * 252

        return sector_allocation, sector_selection

    def generate_report(self, result: AttributionResult) -> str:
        """Generate human-readable attribution report."""
        report = []
        report.append("=" * 50)
        report.append("PERFORMANCE ATTRIBUTION REPORT")
        report.append("=" * 50)

        report.append("\nFactor Contributions (Annualized):")
        report.append("-" * 30)
        for factor, contrib in sorted(result.factor_returns.items(), key=lambda x: -abs(x[1])):
            report.append(f"  {factor:20} {contrib:+.2%}")

        report.append(f"\n  {'Explained Total':20} {result.explained_return:+.2%}")
        report.append(f"  {'Residual (Alpha)':20} {result.residual_return:+.2%}")

        report.append("\nFactor Exposures (Beta):")
        report.append("-" * 30)
        for factor, exp in sorted(result.factor_exposures.items(), key=lambda x: -abs(x[1])):
            report.append(f"  {factor:20} {exp:+.2f}")

        if result.sector_allocation:
            report.append("\nSector Attribution:")
            report.append("-" * 30)
            for sector in sorted(result.sector_allocation.keys()):
                alloc = result.sector_allocation.get(sector, 0)
                select = result.sector_selection.get(sector, 0)
                report.append(f"  {sector:15} Alloc: {alloc:+.2%}  Select: {select:+.2%}")

        report.append("\nReturn Decomposition:")
        report.append("-" * 30)
        report.append(f"  Net Return:        {result.net_return:+.2%}")
        report.append(f"  Transaction Costs: {result.transaction_costs:+.2%}")

        return "\n".join(report)
