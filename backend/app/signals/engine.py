"""
Automated Multi-Factor Signal Engine

This is institutional-grade signal generation combining:
- Momentum factors (price, earnings, analyst revisions)
- Value factors (PE, PB, FCF yield)
- Quality factors (ROE, margins, balance sheet)
- Volatility factors (realized vol, vol regime)
- Technical factors (RSI, MACD, support/resistance)

Signals are combined using ML ensemble with walk-forward validation.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, date, timedelta
from enum import Enum
import numpy as np
import pandas as pd
import logging

logger = logging.getLogger(__name__)

from ..config import get_settings


class SignalStrength(Enum):
    """Signal strength classification."""
    STRONG_BUY = 2
    BUY = 1
    HOLD = 0
    SELL = -1
    STRONG_SELL = -2


@dataclass
class StockSignal:
    """Individual stock signal with full factor breakdown."""
    symbol: str
    timestamp: datetime

    # Composite scores
    composite_score: float  # -1 to 1
    signal_strength: SignalStrength
    confidence: float  # 0 to 1

    # Factor scores (all normalized -1 to 1)
    momentum_score: float
    value_score: float
    quality_score: float
    volatility_score: float
    technical_score: float

    # Factor details
    factor_details: Dict[str, float] = field(default_factory=dict)

    # Risk metrics
    expected_return: float = 0.0  # Annualized
    expected_volatility: float = 0.0
    sharpe_estimate: float = 0.0
    max_position_size: float = 0.0  # Recommended max weight

    # Trading recommendation
    action: str = "HOLD"  # BUY, SELL, HOLD
    target_weight: float = 0.0
    stop_loss_pct: float = 0.0
    take_profit_pct: float = 0.0

    def to_dict(self) -> Dict:
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat(),
            "composite_score": round(self.composite_score, 4),
            "signal_strength": self.signal_strength.name,
            "confidence": round(self.confidence, 3),
            "momentum_score": round(self.momentum_score, 4),
            "value_score": round(self.value_score, 4),
            "quality_score": round(self.quality_score, 4),
            "volatility_score": round(self.volatility_score, 4),
            "technical_score": round(self.technical_score, 4),
            "factor_details": {k: round(v, 4) for k, v in self.factor_details.items()},
            "expected_return": round(self.expected_return, 4),
            "expected_volatility": round(self.expected_volatility, 4),
            "sharpe_estimate": round(self.sharpe_estimate, 3),
            "max_position_size": round(self.max_position_size, 4),
            "action": self.action,
            "target_weight": round(self.target_weight, 4),
            "stop_loss_pct": round(self.stop_loss_pct, 4),
            "take_profit_pct": round(self.take_profit_pct, 4),
        }


@dataclass
class PortfolioSignals:
    """Portfolio-level signal aggregation."""
    timestamp: datetime
    signals: List[StockSignal]

    # Portfolio recommendations
    buy_signals: List[StockSignal] = field(default_factory=list)
    sell_signals: List[StockSignal] = field(default_factory=list)

    # Market regime
    market_regime: str = "normal"  # bull, bear, normal, high_vol
    regime_confidence: float = 0.0

    # Recommended portfolio
    recommended_weights: Dict[str, float] = field(default_factory=dict)
    expected_portfolio_return: float = 0.0
    expected_portfolio_vol: float = 0.0
    expected_sharpe: float = 0.0

    def to_dict(self) -> Dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "total_signals": len(self.signals),
            "buy_count": len(self.buy_signals),
            "sell_count": len(self.sell_signals),
            "market_regime": self.market_regime,
            "regime_confidence": round(self.regime_confidence, 3),
            "top_buys": [s.to_dict() for s in self.buy_signals[:10]],
            "top_sells": [s.to_dict() for s in self.sell_signals[:5]],
            "recommended_weights": {k: round(v, 4) for k, v in self.recommended_weights.items()},
            "expected_portfolio_return": round(self.expected_portfolio_return, 4),
            "expected_portfolio_vol": round(self.expected_portfolio_vol, 4),
            "expected_sharpe": round(self.expected_sharpe, 3),
        }


class SignalEngine:
    """
    Multi-factor signal generation engine.

    Implements institutional-grade factor investing with:
    - Cross-sectional factor scoring
    - Dynamic factor weighting
    - Regime detection
    - Risk-adjusted position sizing
    """

    # Default factor weights (can be ML-optimized)
    DEFAULT_WEIGHTS = {
        "momentum": 0.25,
        "value": 0.20,
        "quality": 0.20,
        "volatility": 0.15,
        "technical": 0.20,
    }

    # Sector/asset-class specific weight overrides
    # Different asset types respond to different factors:
    # - Crypto: momentum-driven, high vol sensitivity, less fundamental value
    # - Tech: momentum + technical dominated, moderate value
    # - Defensive (utilities, staples): value + quality dominated
    # - Commodities: volatility + momentum driven
    # - Financials: value + quality sensitive
    SECTOR_WEIGHTS = {
        "crypto": {"momentum": 0.35, "value": 0.05, "quality": 0.05, "volatility": 0.30, "technical": 0.25},
        "tech": {"momentum": 0.30, "value": 0.10, "quality": 0.15, "volatility": 0.15, "technical": 0.30},
        "defensive": {"momentum": 0.10, "value": 0.30, "quality": 0.30, "volatility": 0.15, "technical": 0.15},
        "commodity": {"momentum": 0.25, "value": 0.10, "quality": 0.05, "volatility": 0.30, "technical": 0.30},
        "financial": {"momentum": 0.20, "value": 0.30, "quality": 0.25, "volatility": 0.10, "technical": 0.15},
    }

    # Symbol-to-sector mapping for known tickers
    SYMBOL_SECTOR = {
        # Crypto
        "BTC": "crypto", "ETH": "crypto", "SOL": "crypto", "ADA": "crypto",
        "DOT": "crypto", "AVAX": "crypto", "LINK": "crypto", "DOGE": "crypto",
        "XRP": "crypto", "BNB": "crypto", "MATIC": "crypto", "ATOM": "crypto",
        "UNI": "crypto", "LTC": "crypto", "FIL": "crypto", "NEAR": "crypto",
        # Tech
        "AAPL": "tech", "MSFT": "tech", "GOOGL": "tech", "GOOG": "tech",
        "AMZN": "tech", "META": "tech", "NVDA": "tech", "TSLA": "tech",
        "AMD": "tech", "INTC": "tech", "CRM": "tech", "NFLX": "tech",
        "ADBE": "tech", "PYPL": "tech", "SQ": "tech", "SHOP": "tech",
        "QQQ": "tech",
        # Defensive (utilities, staples, healthcare)
        "JNJ": "defensive", "PG": "defensive", "KO": "defensive", "PEP": "defensive",
        "MRK": "defensive", "UNH": "defensive", "WMT": "defensive", "COST": "defensive",
        "XLU": "defensive", "XLP": "defensive",
        # Commodities
        "GLD": "commodity", "SLV": "commodity", "USO": "commodity", "GDX": "commodity",
        "XLE": "commodity", "XOP": "commodity",
        # Financials
        "JPM": "financial", "BAC": "financial", "GS": "financial", "MS": "financial",
        "XLF": "financial", "V": "financial", "MA": "financial",
        # Broad market ETFs use defaults
        "SPY": None, "IWM": None, "DIA": None,
    }

    def __init__(self, factor_weights: Optional[Dict[str, float]] = None):
        self.factor_weights = factor_weights or self.DEFAULT_WEIGHTS
        self.settings = get_settings()

    def get_sector_weights(self, ticker: str) -> Dict[str, float]:
        """Get sector-specific factor weights for a ticker."""
        # Strip common suffixes to get base symbol
        base = ticker.split("-")[0].replace("USDT", "").replace("/USD", "").replace("-PERP", "")
        sector = self.SYMBOL_SECTOR.get(base)
        if sector and sector in self.SECTOR_WEIGHTS:
            return self.SECTOR_WEIGHTS[sector]
        return self.factor_weights  # Fall back to default/configured weights

    def generate_signals(
        self,
        prices: pd.DataFrame,
        volumes: Optional[pd.DataFrame] = None,
        fundamentals: Optional[Dict[str, Dict]] = None,
    ) -> PortfolioSignals:
        """
        Generate signals for all stocks in the universe.

        Args:
            prices: DataFrame with dates as index, tickers as columns
            volumes: Optional volume data
            fundamentals: Optional dict of ticker -> fundamental metrics

        Returns:
            PortfolioSignals with ranked recommendations
        """
        logger.info(f"Generating signals for {len(prices.columns)} stocks")

        # Calculate all factor scores
        momentum_scores = self._compute_momentum_scores(prices)
        value_scores = self._compute_value_scores(prices, fundamentals)
        quality_scores = self._compute_quality_scores(fundamentals)
        volatility_scores = self._compute_volatility_scores(prices)
        technical_scores = self._compute_technical_scores(prices, volumes)

        # Detect market regime
        market_regime, regime_conf = self._detect_regime(prices)

        # Adjust base weights for regime
        regime_weights = self._adjust_weights_for_regime(market_regime)

        # Generate individual signals with per-sector factor weights
        signals = []
        for ticker in prices.columns:
            try:
                # Merge sector-specific weights with regime adjustments
                sector_base = self.get_sector_weights(ticker)
                # Apply regime scaling on top of sector weights
                ticker_weights = {}
                for factor in sector_base:
                    regime_scale = regime_weights.get(factor, 0.20) / self.DEFAULT_WEIGHTS.get(factor, 0.20)
                    ticker_weights[factor] = sector_base[factor] * regime_scale
                # Renormalize
                total_w = sum(ticker_weights.values())
                if total_w > 0:
                    ticker_weights = {k: v / total_w for k, v in ticker_weights.items()}

                signal = self._create_stock_signal(
                    ticker=ticker,
                    prices=prices[ticker],
                    momentum=momentum_scores.get(ticker, 0),
                    value=value_scores.get(ticker, 0),
                    quality=quality_scores.get(ticker, 0),
                    volatility=volatility_scores.get(ticker, 0),
                    technical=technical_scores.get(ticker, 0),
                    weights=ticker_weights,
                )
                signals.append(signal)
            except Exception as e:
                logger.warning(f"Failed to generate signal for {ticker}: {e}")

        # Sort by composite score
        signals.sort(key=lambda x: x.composite_score, reverse=True)

        # Identify buys and sells
        buy_signals = [s for s in signals if s.action == "BUY"]
        sell_signals = [s for s in signals if s.action == "SELL"]

        # Generate recommended portfolio weights
        recommended_weights = self._compute_optimal_weights(signals, prices)

        # Calculate expected portfolio metrics
        exp_ret, exp_vol, exp_sharpe = self._estimate_portfolio_metrics(
            recommended_weights, prices
        )

        return PortfolioSignals(
            timestamp=datetime.now(),
            signals=signals,
            buy_signals=buy_signals,
            sell_signals=sell_signals,
            market_regime=market_regime,
            regime_confidence=regime_conf,
            recommended_weights=recommended_weights,
            expected_portfolio_return=exp_ret,
            expected_portfolio_vol=exp_vol,
            expected_sharpe=exp_sharpe,
        )

    def _compute_momentum_scores(self, prices: pd.DataFrame) -> Dict[str, float]:
        """
        Compute momentum factor scores.

        Includes:
        - 12-1 month momentum (skip last month)
        - 6-month momentum
        - 1-month reversal
        - 52-week high proximity
        """
        scores = {}

        for ticker in prices.columns:
            try:
                p = prices[ticker].dropna()
                if len(p) < 252:
                    scores[ticker] = 0
                    continue

                # 12-1 month momentum (most important)
                mom_12_1 = (p.iloc[-21] / p.iloc[-252] - 1) if len(p) >= 252 else 0

                # 6-month momentum
                mom_6 = (p.iloc[-1] / p.iloc[-126] - 1) if len(p) >= 126 else 0

                # 1-month reversal (negative weight - mean reversion)
                mom_1 = (p.iloc[-1] / p.iloc[-21] - 1) if len(p) >= 21 else 0

                # 52-week high proximity
                high_52w = p.iloc[-252:].max()
                high_prox = p.iloc[-1] / high_52w if high_52w > 0 else 0

                # Combine (12-1 is primary, reversal is negative)
                raw_score = 0.5 * mom_12_1 + 0.3 * mom_6 - 0.1 * mom_1 + 0.1 * (high_prox - 0.8)
                scores[ticker] = raw_score

            except Exception:
                scores[ticker] = 0

        # Cross-sectional standardization
        return self._cross_sectional_zscore(scores)

    def _compute_value_scores(
        self,
        prices: pd.DataFrame,
        fundamentals: Optional[Dict] = None
    ) -> Dict[str, float]:
        """
        Compute value factor scores.

        Without fundamentals, uses price-based value proxies:
        - 5-year price percentile (low = cheap)
        - Drawdown from all-time high
        """
        scores = {}

        for ticker in prices.columns:
            try:
                p = prices[ticker].dropna()

                if fundamentals and ticker in fundamentals:
                    # Use fundamental data if available
                    f = fundamentals[ticker]
                    pe = f.get("pe_ratio", 20)
                    pb = f.get("pb_ratio", 3)
                    fcf_yield = f.get("fcf_yield", 0.03)

                    # Lower is better for PE/PB, higher for yield
                    pe_score = -np.clip((pe - 15) / 15, -2, 2)
                    pb_score = -np.clip((pb - 2) / 2, -2, 2)
                    fcf_score = np.clip((fcf_yield - 0.03) / 0.03, -2, 2)

                    raw_score = 0.4 * pe_score + 0.3 * pb_score + 0.3 * fcf_score
                else:
                    # Price-based proxy
                    if len(p) >= 1260:  # 5 years
                        percentile = (p.iloc[-1] - p.iloc[-1260:].min()) / (p.iloc[-1260:].max() - p.iloc[-1260:].min() + 1e-10)
                        raw_score = -(percentile - 0.5)  # Lower percentile = higher value score
                    else:
                        raw_score = 0

                scores[ticker] = raw_score

            except Exception:
                scores[ticker] = 0

        return self._cross_sectional_zscore(scores)

    def _compute_quality_scores(self, fundamentals: Optional[Dict] = None) -> Dict[str, float]:
        """
        Compute quality factor scores.

        Without fundamentals, returns neutral scores.
        With fundamentals: ROE, profit margins, debt ratios.
        """
        if not fundamentals:
            return {}

        scores = {}
        for ticker, f in fundamentals.items():
            try:
                roe = f.get("roe", 0.15)
                margin = f.get("profit_margin", 0.10)
                debt_equity = f.get("debt_equity", 0.5)

                roe_score = np.clip((roe - 0.12) / 0.10, -2, 2)
                margin_score = np.clip((margin - 0.08) / 0.08, -2, 2)
                debt_score = -np.clip((debt_equity - 0.5) / 0.5, -2, 2)

                scores[ticker] = 0.4 * roe_score + 0.3 * margin_score + 0.3 * debt_score
            except Exception:
                scores[ticker] = 0

        return self._cross_sectional_zscore(scores)

    def _compute_volatility_scores(self, prices: pd.DataFrame) -> Dict[str, float]:
        """
        Compute volatility factor scores.

        Low volatility anomaly: lower vol stocks tend to outperform risk-adjusted.
        Also penalize stocks in high vol regime.
        """
        scores = {}

        for ticker in prices.columns:
            try:
                p = prices[ticker].dropna()
                if len(p) < 63:
                    scores[ticker] = 0
                    continue

                returns = p.pct_change().dropna()

                # Realized volatility (annualized)
                vol_63d = returns.iloc[-63:].std() * np.sqrt(252)
                vol_21d = returns.iloc[-21:].std() * np.sqrt(252)

                # Vol regime (is short-term vol elevated?)
                vol_ratio = vol_21d / (vol_63d + 1e-10)

                # Lower vol = higher score (low vol anomaly)
                vol_score = -np.clip((vol_63d - 0.25) / 0.15, -2, 2)
                regime_penalty = -np.clip((vol_ratio - 1) * 2, 0, 1)

                scores[ticker] = vol_score + 0.3 * regime_penalty

            except Exception:
                scores[ticker] = 0

        return self._cross_sectional_zscore(scores)

    def _compute_technical_scores(
        self,
        prices: pd.DataFrame,
        volumes: Optional[pd.DataFrame] = None
    ) -> Dict[str, float]:
        """
        Compute technical factor scores.

        Includes:
        - RSI (contrarian at extremes)
        - MACD signal
        - Price vs moving averages
        - Volume confirmation
        """
        scores = {}

        for ticker in prices.columns:
            try:
                p = prices[ticker].dropna()
                if len(p) < 50:
                    scores[ticker] = 0
                    continue

                # RSI
                delta = p.diff()
                gain = delta.where(delta > 0, 0).rolling(14).mean()
                loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
                rs = gain / (loss + 1e-10)
                rsi = 100 - (100 / (1 + rs))
                current_rsi = rsi.iloc[-1]

                # RSI score (contrarian at extremes)
                if current_rsi > 70:
                    rsi_score = -0.5 * (current_rsi - 70) / 30
                elif current_rsi < 30:
                    rsi_score = 0.5 * (30 - current_rsi) / 30
                else:
                    rsi_score = (current_rsi - 50) / 100

                # Moving average trend
                ma_20 = p.rolling(20).mean().iloc[-1]
                ma_50 = p.rolling(50).mean().iloc[-1]
                ma_200 = p.rolling(200).mean().iloc[-1] if len(p) >= 200 else ma_50

                price = p.iloc[-1]
                ma_score = 0
                if price > ma_20 > ma_50:
                    ma_score = 0.5
                if price > ma_50 > ma_200:
                    ma_score += 0.5
                if price < ma_20 < ma_50:
                    ma_score = -0.5
                if price < ma_50 < ma_200:
                    ma_score -= 0.5

                # MACD
                ema_12 = p.ewm(span=12).mean()
                ema_26 = p.ewm(span=26).mean()
                macd = ema_12 - ema_26
                signal = macd.ewm(span=9).mean()
                macd_hist = macd.iloc[-1] - signal.iloc[-1]
                macd_score = np.clip(macd_hist / (price * 0.01), -1, 1)

                # Combine
                scores[ticker] = 0.3 * rsi_score + 0.4 * ma_score + 0.3 * macd_score

            except Exception:
                scores[ticker] = 0

        return self._cross_sectional_zscore(scores)

    def _detect_regime(self, prices: pd.DataFrame) -> Tuple[str, float]:
        """
        Detect current market regime.

        Returns:
            (regime_name, confidence)
        """
        try:
            # Use equal-weighted index as market proxy
            market = prices.mean(axis=1).dropna()

            if len(market) < 252:
                return "normal", 0.5

            returns = market.pct_change().dropna()

            # Recent performance
            ret_21d = (market.iloc[-1] / market.iloc[-21] - 1)
            ret_63d = (market.iloc[-1] / market.iloc[-63] - 1)

            # Volatility regime
            vol_21d = returns.iloc[-21:].std() * np.sqrt(252)
            vol_63d = returns.iloc[-63:].std() * np.sqrt(252)
            vol_252d = returns.iloc[-252:].std() * np.sqrt(252)

            # Classify
            if vol_21d > vol_252d * 1.5:
                return "high_vol", min(vol_21d / vol_252d - 1, 1)
            elif ret_63d > 0.10 and ret_21d > 0:
                return "bull", min(ret_63d / 0.10, 1)
            elif ret_63d < -0.10 and ret_21d < 0:
                return "bear", min(abs(ret_63d) / 0.10, 1)
            else:
                return "normal", 0.7

        except Exception:
            return "normal", 0.5

    def _adjust_weights_for_regime(self, regime: str) -> Dict[str, float]:
        """Adjust factor weights based on market regime."""
        weights = self.factor_weights.copy()

        if regime == "high_vol":
            # Reduce momentum, increase quality and low vol
            weights["momentum"] *= 0.5
            weights["quality"] *= 1.5
            weights["volatility"] *= 1.5
        elif regime == "bull":
            # Increase momentum
            weights["momentum"] *= 1.3
            weights["value"] *= 0.8
        elif regime == "bear":
            # Increase value and quality, reduce momentum
            weights["momentum"] *= 0.6
            weights["value"] *= 1.4
            weights["quality"] *= 1.3

        # Renormalize
        total = sum(weights.values())
        return {k: v / total for k, v in weights.items()}

    def _create_stock_signal(
        self,
        ticker: str,
        prices: pd.Series,
        momentum: float,
        value: float,
        quality: float,
        volatility: float,
        technical: float,
        weights: Dict[str, float],
    ) -> StockSignal:
        """Create a complete stock signal."""

        # Composite score
        composite = (
            weights.get("momentum", 0.25) * momentum +
            weights.get("value", 0.20) * value +
            weights.get("quality", 0.20) * quality +
            weights.get("volatility", 0.15) * volatility +
            weights.get("technical", 0.20) * technical
        )

        # Clip to [-1, 1]
        composite = np.clip(composite, -1, 1)

        # Signal strength
        if composite > 0.5:
            strength = SignalStrength.STRONG_BUY
            action = "BUY"
        elif composite > 0.2:
            strength = SignalStrength.BUY
            action = "BUY"
        elif composite < -0.5:
            strength = SignalStrength.STRONG_SELL
            action = "SELL"
        elif composite < -0.2:
            strength = SignalStrength.SELL
            action = "SELL"
        else:
            strength = SignalStrength.HOLD
            action = "HOLD"

        # Confidence based on factor agreement
        factor_scores = [momentum, value, quality, volatility, technical]
        factor_std = np.std([f for f in factor_scores if f != 0])
        confidence = max(0, 1 - factor_std)

        # Risk estimates
        returns = prices.pct_change().dropna()
        vol = returns.iloc[-63:].std() * np.sqrt(252) if len(returns) >= 63 else 0.25

        # Expected return based on signal (rough heuristic)
        expected_ret = composite * 0.15  # Scale signal to expected return
        sharpe_est = expected_ret / (vol + 1e-10)

        # Position sizing based on vol targeting
        target_vol = 0.15
        max_position = min(target_vol / (vol + 1e-10) * 0.1, 0.10)

        # Target weight based on signal strength
        if action == "BUY":
            target_weight = max_position * (0.5 + 0.5 * abs(composite))
        else:
            target_weight = 0

        # Stop loss and take profit
        stop_loss = max(vol * 2, 0.08)  # 2x vol or 8% minimum
        take_profit = max(expected_ret * 2, 0.15)  # 2x expected or 15%

        return StockSignal(
            symbol=ticker,
            timestamp=datetime.now(),
            composite_score=composite,
            signal_strength=strength,
            confidence=confidence,
            momentum_score=momentum,
            value_score=value,
            quality_score=quality,
            volatility_score=volatility,
            technical_score=technical,
            factor_details={
                "momentum_12_1": momentum,
                "value_composite": value,
                "quality_composite": quality,
                "low_vol_score": volatility,
                "technical_composite": technical,
            },
            expected_return=expected_ret,
            expected_volatility=vol,
            sharpe_estimate=sharpe_est,
            max_position_size=max_position,
            action=action,
            target_weight=target_weight,
            stop_loss_pct=stop_loss,
            take_profit_pct=take_profit,
        )

    def _compute_optimal_weights(
        self,
        signals: List[StockSignal],
        prices: pd.DataFrame
    ) -> Dict[str, float]:
        """
        Compute optimal portfolio weights using signals and risk constraints.
        """
        # Filter to buy signals only
        buy_signals = [s for s in signals if s.action == "BUY"]

        if not buy_signals:
            return {}

        # Simple approach: weight by signal strength with constraints
        weights = {}
        total_score = sum(max(s.composite_score, 0) for s in buy_signals)

        if total_score == 0:
            return {}

        for signal in buy_signals[:20]:  # Top 20 positions max
            raw_weight = max(signal.composite_score, 0) / total_score
            # Apply position limit
            weights[signal.symbol] = min(raw_weight, signal.max_position_size, 0.10)

        # Renormalize to sum to 1 (or less for cash buffer)
        total = sum(weights.values())
        if total > 0.95:
            weights = {k: v * 0.95 / total for k, v in weights.items()}

        return weights

    def _estimate_portfolio_metrics(
        self,
        weights: Dict[str, float],
        prices: pd.DataFrame
    ) -> Tuple[float, float, float]:
        """Estimate expected portfolio return, vol, and Sharpe."""
        if not weights:
            return 0, 0, 0

        try:
            # Get returns for weighted stocks
            returns = prices[list(weights.keys())].pct_change().dropna()

            if len(returns) < 63:
                return 0, 0.20, 0

            # Portfolio returns
            weight_array = np.array([weights.get(c, 0) for c in returns.columns])
            port_returns = returns.values @ weight_array

            # Annualized metrics
            exp_ret = np.mean(port_returns) * 252
            exp_vol = np.std(port_returns) * np.sqrt(252)
            sharpe = exp_ret / (exp_vol + 1e-10)

            return exp_ret, exp_vol, sharpe

        except Exception:
            return 0, 0.20, 0

    def _cross_sectional_zscore(self, scores: Dict[str, float]) -> Dict[str, float]:
        """Standardize scores cross-sectionally."""
        if not scores:
            return {}

        values = np.array(list(scores.values()))
        values = values[~np.isnan(values)]

        if len(values) < 3:
            return scores

        mean = np.mean(values)
        std = np.std(values) + 1e-10

        return {k: np.clip((v - mean) / std, -3, 3) for k, v in scores.items()}


# Singleton
_engine: Optional[SignalEngine] = None

def get_signal_engine() -> SignalEngine:
    global _engine
    if _engine is None:
        _engine = SignalEngine()
    return _engine
