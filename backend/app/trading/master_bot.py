"""
Master Quant Bot - Institutional-Grade Autonomous Trading System

A PhD-level quantitative trading system that employs:

MACHINE LEARNING:
- Deep Q-Network (DQN) with prioritized experience replay
- Proximal Policy Optimization (PPO) for continuous improvement
- LSTM/Transformer for price prediction
- Variational Autoencoder for regime detection
- Ensemble methods with confidence-weighted voting

STATISTICAL ANALYSIS:
- Bayesian inference for parameter uncertainty
- Hidden Markov Models (3-state regime detection)
- GARCH(1,1) / EGARCH for volatility forecasting
- Student-t Copulas for tail dependency
- Extreme Value Theory for tail risk (VaR/CVaR)
- Multi-factor alpha models (Fama-French 6-factor)

PORTFOLIO OPTIMIZATION:
- Black-Litterman model with investor views
- CVaR optimization for tail risk management
- Risk Parity allocation
- Maximum Diversification portfolio
- Kelly Criterion position sizing

BACKTESTING:
- Walk-forward optimization (prevents overfitting)
- Monte Carlo simulation
- Bootstrap confidence intervals

This bot trades across ALL asset classes:
- Stock/ETF Options (SPY, QQQ, AAPL, etc.)
- Crypto Perpetuals (BTC-PERP, ETH-PERP)
- Crypto Options (BTC/ETH calls/puts)
- Commodities (GLD, SLV, USO options)

PAPER TRADING / EDUCATIONAL purposes only.

Academic References:
- Mnih et al. (2015) - DQN
- Schulman et al. (2017) - PPO
- Hamilton (1989) - HMM
- Bollerslev (1986) - GARCH
- Black & Litterman (1992) - Portfolio Optimization
- McNeil et al. (2005) - Extreme Value Theory
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional, Tuple, Any
import numpy as np

from .options_bot import (
    OptionsQuantBot,
    OptionsMode,
    OptionsPosition,
    OptionsTrade,
    CryptoDerivativePosition,
    IVAnalysis,
    create_options_bot,
)
from .quant_bot import is_market_open, get_market_status
from .ml_models import (
    DQN,
    PPOAgent,
    LSTM,
    TransformerPredictor,
    MarketRegimeVAE,
    EnsemblePredictor,
    Experience,
    create_dqn_agent,
    create_ppo_agent,
)
from .quant_analytics import (
    BayesianEstimator,
    GaussianHMM,
    GARCH,
    StudentTCopula,
    ExtremeValueAnalyzer,
    FactorModel,
    PortfolioOptimizer,
    SignalGenerator,
    WalkForwardOptimizer,
    create_analytics_suite,
)
from .activity_logger import (
    get_activity_logger,
    EventType,
    EventSubtype,
    Severity,
)
from .backtester import (
    get_model_pretrainer,
    get_alpha_manager,
    get_data_downloader,
    get_backtester,
    ModelPreTrainer,
    AlphaSourceManager,
    CHECKPOINT_DIR,
)

logger = logging.getLogger(__name__)


class AssetClass(Enum):
    """Asset classes the bot can trade."""
    STOCK_OPTIONS = "stock_options"
    ETF_OPTIONS = "etf_options"
    COMMODITY_OPTIONS = "commodity_options"
    CRYPTO_PERPETUAL = "crypto_perpetual"
    CRYPTO_OPTIONS = "crypto_options"
    CRYPTO_SPOT = "crypto_spot"  # Direct crypto spot trading


class MarketRegime(Enum):
    """Market regimes detected by HMM/VAE."""
    BULL_MARKET = "bull_market"           # Risk-on, trending up
    BEAR_MARKET = "bear_market"           # Risk-off, trending down
    HIGH_VOLATILITY = "high_volatility"   # Crisis/stress
    LOW_VOLATILITY = "low_volatility"     # Calm/consolidation
    RANGE_BOUND = "range_bound"           # Sideways


@dataclass
class MLPrediction:
    """Unified ML prediction with confidence."""
    action: int  # 0=sell, 1=hold, 2=buy
    action_name: str
    confidence: float
    dqn_q_value: float
    ppo_prob: float
    lstm_pred: float
    transformer_pred: float
    regime: str
    regime_confidence: float
    ensemble_agreement: float
    factors: Dict[str, float]


@dataclass
class RiskMetrics:
    """Comprehensive risk metrics."""
    var_95: float
    var_99: float
    cvar_95: float
    cvar_99: float
    volatility_forecast: float
    tail_index: float
    max_drawdown: float
    sharpe_ratio: float
    sharpe_std_error: float
    correlation_to_market: float


@dataclass
class Opportunity:
    """A scored trading opportunity with ML enhancements."""
    symbol: str
    asset_class: AssetClass
    strategy: str
    expected_return: float
    max_profit: float
    max_loss: float
    probability_of_profit: float
    risk_reward_ratio: float
    iv_rank: float
    score: float
    rationale: str

    # ML-enhanced fields
    ml_prediction: Optional[MLPrediction] = None
    risk_metrics: Optional[RiskMetrics] = None
    factor_alpha: float = 0.0
    regime_alignment: float = 0.0
    bayesian_confidence: float = 0.0

    def to_dict(self) -> Dict:
        result = {
            "symbol": self.symbol,
            "asset_class": self.asset_class.value,
            "strategy": self.strategy,
            "expected_return": round(self.expected_return, 2),
            "max_profit": round(self.max_profit, 2),
            "max_loss": round(self.max_loss, 2),
            "probability_of_profit": round(self.probability_of_profit * 100, 1),
            "risk_reward_ratio": round(self.risk_reward_ratio, 2),
            "iv_rank": round(self.iv_rank, 1),
            "score": round(self.score, 2),
            "rationale": self.rationale,
            "factor_alpha": round(self.factor_alpha, 4),
            "regime_alignment": round(self.regime_alignment, 2),
            "bayesian_confidence": round(self.bayesian_confidence, 2),
        }

        if self.ml_prediction:
            result["ml_prediction"] = {
                "action": self.ml_prediction.action_name,
                "confidence": round(self.ml_prediction.confidence, 2),
                "regime": self.ml_prediction.regime,
                "ensemble_agreement": round(self.ml_prediction.ensemble_agreement, 2),
            }

        if self.risk_metrics:
            result["risk_metrics"] = {
                "var_95": round(self.risk_metrics.var_95, 4),
                "cvar_95": round(self.risk_metrics.cvar_95, 4),
                "volatility_forecast": round(self.risk_metrics.volatility_forecast, 4),
                "sharpe_ratio": round(self.risk_metrics.sharpe_ratio, 2),
            }

        return result


class QuantAnalyticsEngine:
    """
    Core analytics engine combining all statistical and ML models.

    This engine provides institutional-grade analysis:
    - Real-time regime detection
    - Forward-looking volatility estimates
    - Tail risk quantification
    - Factor-based alpha signals
    - Optimal portfolio construction
    """

    # State dimensions for RL agents
    STATE_DIM = 64  # Features: prices, returns, vol, positions, greeks, sentiment
    ACTION_DIM = 5  # hold, buy_small, buy_large, sell_small, sell_large

    def __init__(self, lookback_days: int = 252):
        self.lookback_days = lookback_days

        # Initialize ML models
        self.dqn = create_dqn_agent(
            state_dim=self.STATE_DIM,
            action_dim=self.ACTION_DIM,
            hidden_dims=[512, 256, 128],
            lr=0.0001,
        )

        self.ppo = create_ppo_agent(
            state_dim=self.STATE_DIM,
            action_dim=self.ACTION_DIM,
            hidden_dims=[256, 256],
        )

        self.lstm = LSTM(input_dim=16, hidden_dim=128)
        self.transformer = TransformerPredictor(
            input_dim=16,
            d_model=64,
            n_heads=4,
            n_layers=3,
        )
        self.regime_vae = MarketRegimeVAE(input_dim=32, latent_dim=8)

        # Initialize statistical models
        self.bayesian = BayesianEstimator(n_samples=5000)
        self.hmm = GaussianHMM(n_states=3, n_iter=100)
        self.garch = GARCH(p=1, q=1, model_type="garch")
        self.egarch = GARCH(p=1, q=1, model_type="egarch")
        self.copula = StudentTCopula(df=5)
        self.evt = ExtremeValueAnalyzer(threshold_quantile=0.95)
        self.factor_model = FactorModel(factors=["market", "size", "value", "momentum", "volatility", "quality"])
        self.signal_generator = SignalGenerator()
        self.walk_forward = WalkForwardOptimizer(
            in_sample_periods=252,
            out_of_sample_periods=63,
            n_windows=4,
        )

        # Price/return history for models
        self.price_history: Dict[str, np.ndarray] = {}
        self.return_history: Dict[str, np.ndarray] = {}

        # Fitted model states
        self.hmm_fitted = False
        self.garch_fitted = False

        # Training metrics
        self.training_step = 0
        self.cumulative_reward = 0.0
        self.episode_rewards: List[float] = []

        logger.info("QuantAnalyticsEngine initialized with full ML/stats suite")

    def update_price_history(self, symbol: str, prices: np.ndarray):
        """Update price history for a symbol."""
        self.price_history[symbol] = prices
        if len(prices) > 1:
            self.return_history[symbol] = np.diff(prices) / prices[:-1]

    def _construct_state(self, symbol: str, additional_features: Optional[Dict] = None) -> np.ndarray:
        """
        Construct state vector for RL agents.

        Features (64 dims):
        - Price features: returns, log returns, normalized price (10)
        - Volatility features: realized vol, GARCH forecast, vol ratio (10)
        - Technical features: RSI, MACD, Bollinger, momentum (15)
        - Position features: current exposure, PnL, Greeks (10)
        - Market features: VIX, correlation, beta (10)
        - Regime features: HMM state probs, VAE latent (9)
        """
        state = np.zeros(self.STATE_DIM)

        if symbol in self.return_history:
            returns = self.return_history[symbol]

            # Price features (0-9)
            if len(returns) >= 20:
                state[0] = returns[-1]  # Last return
                state[1] = np.mean(returns[-5:])  # 5-day mean
                state[2] = np.mean(returns[-20:])  # 20-day mean
                state[3] = np.std(returns[-20:]) * np.sqrt(252)  # Annualized vol
                state[4] = np.sum(returns[-5:])  # 5-day cumulative
                state[5] = np.sum(returns[-20:])  # 20-day cumulative
                state[6] = (returns[-1] - np.mean(returns[-20:])) / (np.std(returns[-20:]) + 1e-8)  # Z-score
                state[7] = np.percentile(returns, 95) if len(returns) >= 100 else 0  # 95th percentile
                state[8] = np.percentile(returns, 5) if len(returns) >= 100 else 0  # 5th percentile
                state[9] = np.corrcoef(returns[-20:], np.arange(20))[0, 1] if len(returns) >= 20 else 0  # Trend

            # Volatility features (10-19)
            if len(returns) >= 60:
                state[10] = np.std(returns[-5:]) * np.sqrt(252)
                state[11] = np.std(returns[-20:]) * np.sqrt(252)
                state[12] = np.std(returns[-60:]) * np.sqrt(252)
                state[13] = state[10] / (state[12] + 1e-8)  # Vol ratio

                # GARCH forecast (if fitted)
                if self.garch_fitted:
                    try:
                        forecast = self.garch.forecast(returns[-60:], horizon=5)
                        state[14] = forecast.current_vol
                        state[15] = np.mean(forecast.forecast_vol)
                    except Exception:
                        pass

            # Technical features (20-34)
            prices = self.price_history.get(symbol, np.array([]))
            if len(prices) >= 20:
                # RSI
                gains = np.where(returns[-14:] > 0, returns[-14:], 0)
                losses = np.where(returns[-14:] < 0, -returns[-14:], 0)
                avg_gain = np.mean(gains)
                avg_loss = np.mean(losses)
                rs = avg_gain / (avg_loss + 1e-8)
                state[20] = 100 - 100 / (1 + rs)  # RSI

                # Bollinger Bands
                ma20 = np.mean(prices[-20:])
                std20 = np.std(prices[-20:])
                state[21] = (prices[-1] - ma20) / (2 * std20 + 1e-8)  # BB position

                # Momentum
                state[22] = prices[-1] / prices[-5] - 1  # 5-day momentum
                state[23] = prices[-1] / prices[-20] - 1  # 20-day momentum

                if len(prices) >= 60:
                    state[24] = prices[-1] / prices[-60] - 1  # 60-day momentum

        # Add additional features if provided
        if additional_features:
            # Position features (35-44)
            state[35] = additional_features.get("position_size", 0)
            state[36] = additional_features.get("unrealized_pnl", 0)
            state[37] = additional_features.get("delta", 0)
            state[38] = additional_features.get("gamma", 0)
            state[39] = additional_features.get("theta", 0)
            state[40] = additional_features.get("vega", 0)

            # Market features (45-54)
            state[45] = additional_features.get("vix", 18) / 100
            state[46] = additional_features.get("market_return", 0)
            state[47] = additional_features.get("sector_return", 0)

        # Regime features (55-63)
        if symbol in self.return_history and len(self.return_history[symbol]) >= 30:
            returns = self.return_history[symbol][-30:]
            try:
                regime_id, regime_probs, latent = self.regime_vae.detect_regime(
                    returns.reshape(1, -1)[:, :32] if len(returns) >= 32 else np.pad(returns, (0, 32 - len(returns))).reshape(1, -1)
                )
                state[55:59] = regime_probs
                state[59:63] = latent[:4] if len(latent) >= 4 else latent
            except Exception:
                pass

        return state

    def get_ml_prediction(
        self,
        symbol: str,
        additional_features: Optional[Dict] = None,
    ) -> MLPrediction:
        """
        Get unified ML prediction from all models.

        Combines:
        - DQN Q-values
        - PPO policy distribution
        - LSTM return prediction
        - Transformer attention-based prediction
        - VAE regime detection
        - Factor model alpha
        """
        state = self._construct_state(symbol, additional_features)

        # DQN prediction
        dqn_action = self.dqn.select_action(state, training=False)
        dqn_q_values = self.dqn._forward(state.reshape(1, -1), self.dqn.q_network)
        dqn_q = float(np.max(dqn_q_values))

        # PPO prediction
        ppo_action, ppo_log_prob, ppo_value = self.ppo.select_action(state)
        ppo_probs = self.ppo._forward_actor(state.reshape(1, -1)).flatten()

        # LSTM prediction (if we have history)
        lstm_pred = 0.0
        if symbol in self.return_history and len(self.return_history[symbol]) >= 60:
            try:
                self.lstm.reset_state()
                returns = np.array(self.return_history[symbol][-60:]).flatten()
                # Reshape for LSTM: (seq_len, features)
                lstm_input = returns.reshape(-1, 1)
                lstm_input = np.pad(lstm_input, ((0, 0), (0, 15)), mode='constant')
                lstm_out = self.lstm.forward(lstm_input)
                lstm_pred = float(lstm_out[0, -1, 0])
            except Exception as e:
                logger.debug(f"LSTM prediction failed for {symbol}: {e}")

        # Transformer prediction
        transformer_pred = 0.0
        if symbol in self.return_history and len(self.return_history[symbol]) >= 60:
            try:
                returns = np.array(self.return_history[symbol][-60:]).flatten()
                transformer_input = returns.reshape(-1, 1)
                transformer_input = np.pad(transformer_input, ((0, 0), (0, 15)), mode='constant')
                transformer_pred = self.transformer.predict(transformer_input)
            except Exception as e:
                logger.debug(f"Transformer prediction failed for {symbol}: {e}")

        # Regime detection
        regime = "Unknown"
        regime_confidence = 0.5
        if symbol in self.return_history and len(self.return_history[symbol]) >= 32:
            try:
                returns = self.return_history[symbol][-32:]
                regime_id, regime_probs, _ = self.regime_vae.detect_regime(returns.reshape(1, -1))
                regime = self.regime_vae.get_regime_name(regime_id)
                regime_confidence = float(np.max(regime_probs))
            except Exception:
                pass

        # Factor analysis
        factors = {}
        if symbol in self.return_history and len(self.return_history[symbol]) >= 60:
            try:
                returns = self.return_history[symbol][-60:]
                factor_exposures = self.factor_model.fit(returns)
                factors = factor_exposures.betas
                factors["alpha"] = factor_exposures.alpha
            except Exception:
                pass

        # Ensemble voting
        action_votes = np.zeros(3)  # sell, hold, buy

        # Map 5-action space to 3-action for voting
        dqn_vote = 0 if dqn_action in [0, 1] else (2 if dqn_action in [3, 4] else 1)
        ppo_vote = 0 if ppo_action in [0, 1] else (2 if ppo_action in [3, 4] else 1)
        lstm_vote = 2 if lstm_pred > 0.005 else (0 if lstm_pred < -0.005 else 1)
        transformer_vote = 2 if transformer_pred > 0.005 else (0 if transformer_pred < -0.005 else 1)

        weights = [0.30, 0.25, 0.20, 0.25]  # DQN, PPO, LSTM, Transformer
        for vote, weight in zip([dqn_vote, ppo_vote, lstm_vote, transformer_vote], weights):
            action_votes[vote] += weight

        final_action = int(np.argmax(action_votes))
        action_names = ["sell", "hold", "buy"]
        confidence = float(action_votes[final_action])

        # Ensemble agreement (how much models agree)
        agreement = (action_votes[final_action] - 0.25) / 0.75  # Normalize from 0.25-1.0 to 0-1

        return MLPrediction(
            action=final_action,
            action_name=action_names[final_action],
            confidence=confidence,
            dqn_q_value=dqn_q,
            ppo_prob=float(ppo_probs[ppo_action]),
            lstm_pred=lstm_pred,
            transformer_pred=transformer_pred,
            regime=regime,
            regime_confidence=regime_confidence,
            ensemble_agreement=agreement,
            factors=factors,
        )

    def compute_risk_metrics(self, symbol: str) -> RiskMetrics:
        """
        Compute comprehensive risk metrics using EVT, GARCH, and Bayesian methods.
        """
        if symbol not in self.return_history or len(self.return_history[symbol]) < 60:
            return RiskMetrics(
                var_95=0.02, var_99=0.03, cvar_95=0.03, cvar_99=0.05,
                volatility_forecast=0.20, tail_index=3.0, max_drawdown=0.10,
                sharpe_ratio=0.0, sharpe_std_error=0.5, correlation_to_market=0.5
            )

        returns = self.return_history[symbol]
        losses = -returns  # Convert to losses

        # EVT analysis
        evt_analysis = self.evt.analyze(losses[losses > 0] if np.any(losses > 0) else np.abs(losses))

        # GARCH volatility forecast
        vol_forecast = 0.20
        try:
            garch_forecast = self.garch.forecast(returns[-60:], horizon=5)
            vol_forecast = float(np.mean(garch_forecast.forecast_vol))
            self.garch_fitted = True
        except Exception:
            vol_forecast = float(np.std(returns) * np.sqrt(252))

        # Bayesian Sharpe ratio with uncertainty
        sharpe_mean, sharpe_std, _ = self.bayesian.estimate_sharpe_ratio(returns[-252:] if len(returns) >= 252 else returns)

        # Max drawdown
        cumulative = np.cumprod(1 + returns)
        running_max = np.maximum.accumulate(cumulative)
        drawdowns = (cumulative - running_max) / running_max
        max_dd = float(-np.min(drawdowns))

        # Correlation to market (using first principal component as proxy)
        market_proxy = np.mean([self.return_history.get(s, returns)[:len(returns)]
                                for s in list(self.return_history.keys())[:5]], axis=0)
        if len(market_proxy) == len(returns):
            corr = np.corrcoef(returns, market_proxy)[0, 1]
        else:
            corr = 0.5

        return RiskMetrics(
            var_95=float(evt_analysis.var_95) if evt_analysis.var_95 else np.percentile(losses, 95),
            var_99=float(evt_analysis.var_99) if evt_analysis.var_99 else np.percentile(losses, 99),
            cvar_95=float(evt_analysis.expected_shortfall_95) if evt_analysis.expected_shortfall_95 else np.mean(losses[losses > np.percentile(losses, 95)]) if np.any(losses > np.percentile(losses, 95)) else 0,
            cvar_99=float(evt_analysis.expected_shortfall_99) if evt_analysis.expected_shortfall_99 else np.mean(losses[losses > np.percentile(losses, 99)]) if np.any(losses > np.percentile(losses, 99)) else 0,
            volatility_forecast=vol_forecast,
            tail_index=float(1 / evt_analysis.shape_xi) if evt_analysis.shape_xi > 0 else 3.0,
            max_drawdown=max_dd,
            sharpe_ratio=sharpe_mean,
            sharpe_std_error=sharpe_std,
            correlation_to_market=float(corr) if not np.isnan(corr) else 0.5,
        )

    def optimize_portfolio(
        self,
        symbols: List[str],
        method: str = "black_litterman",
        views: Optional[Dict[str, float]] = None,
    ) -> Dict[str, float]:
        """
        Optimize portfolio allocation across assets.

        Methods:
        - mean_variance: Classic Markowitz
        - black_litterman: With investor views
        - risk_parity: Equal risk contribution
        - cvar: Minimize tail risk
        - max_diversification: Maximum diversification ratio
        """
        # Construct return matrix
        min_len = min(len(self.return_history.get(s, [])) for s in symbols)
        if min_len < 60:
            # Equal weight if insufficient data
            return {s: 1.0 / len(symbols) for s in symbols}

        returns_matrix = np.column_stack([
            self.return_history[s][-min_len:] for s in symbols
        ])

        optimizer = PortfolioOptimizer(returns_matrix, asset_names=symbols)

        if method == "black_litterman" and views:
            result = optimizer.black_litterman(views)
        elif method == "risk_parity":
            result = optimizer.risk_parity()
        elif method == "cvar":
            result = optimizer.cvar_optimization()
        elif method == "max_diversification":
            result = optimizer.maximum_diversification()
        else:
            result = optimizer.mean_variance()

        return dict(zip(symbols, result.weights))

    def train_rl_step(self, state: np.ndarray, action: int, reward: float,
                      next_state: np.ndarray, done: bool):
        """Train RL agents with new experience."""
        # Store experience in DQN buffer
        self.dqn.replay_buffer.push(Experience(state, action, reward, next_state, done))

        # Train DQN
        if len(self.dqn.replay_buffer) >= 64:
            loss = self.dqn.train_step(batch_size=64)

        # Store PPO transition
        _, log_prob, value = self.ppo.select_action(state)
        self.ppo.store_transition(state, action, reward, value, log_prob, done)

        # Train PPO periodically
        if done or len(self.ppo.states) >= 2048:
            next_value = self.ppo._forward_critic(next_state.reshape(1, -1)).flatten()[0]
            self.ppo.train(next_value, n_epochs=10)

        self.training_step += 1
        self.cumulative_reward += reward

        if done:
            self.episode_rewards.append(self.cumulative_reward)
            self.cumulative_reward = 0.0

    def detect_regime_hmm(self, returns: np.ndarray) -> Tuple[int, np.ndarray]:
        """Detect regime using HMM."""
        if len(returns) < 60:
            return 1, np.array([0.33, 0.34, 0.33])

        try:
            self.hmm.fit(returns[-252:] if len(returns) >= 252 else returns)
            self.hmm_fitted = True
            state = self.hmm.get_state(returns[-30:])
            return state.current_state, state.state_probs
        except Exception:
            return 1, np.array([0.33, 0.34, 0.33])


class MasterQuantBot:
    """
    Institutional-Grade Autonomous Trading Bot

    Employs PhD-level quantitative methods including:
    - Deep Reinforcement Learning (DQN, PPO)
    - Statistical Regime Detection (HMM, VAE)
    - Advanced Risk Modeling (GARCH, EVT, Copulas)
    - Portfolio Optimization (Black-Litterman, CVaR)
    - Factor-Based Alpha Generation

    One button to start, then it runs autonomously while continuously
    learning and improving from market data.
    """

    # Full universe of tradeable assets
    STOCK_OPTIONS = [
        "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "AMD",
        "NFLX", "CRM", "INTC", "PYPL", "SQ", "COIN", "V", "MA", "JPM", "BAC",
    ]

    ETF_OPTIONS = [
        "SPY", "QQQ", "IWM", "DIA", "XLK", "XLF", "XLE", "XLV", "XLU", "XLI",
    ]

    COMMODITY_OPTIONS = [
        "GLD", "SLV", "GDX", "USO", "UNG", "WEAT", "CORN",
    ]

    # Binance Futures USDT-M Perpetuals (verified available on Binance)
    # Symbol format: "XXX-PERP" -> converted to "XXXUSDT" for Binance API
    CRYPTO_PERPETUALS = [
        # Tier 1 - Blue Chips (highest liquidity)
        "BTC-PERP", "ETH-PERP", "BNB-PERP", "SOL-PERP", "XRP-PERP",
        # Tier 2 - Major Alts (all verified on Binance Futures)
        "DOGE-PERP", "ADA-PERP", "AVAX-PERP", "LINK-PERP", "DOT-PERP",
        "MATIC-PERP", "LTC-PERP", "ATOM-PERP", "UNI-PERP", "ETC-PERP",
        "FIL-PERP", "NEAR-PERP", "APT-PERP", "ARB-PERP", "OP-PERP",
        # Tier 3 - DeFi & L2s (verified on Binance Futures)
        "INJ-PERP", "SUI-PERP", "SEI-PERP", "TIA-PERP", "FTM-PERP",
        "AAVE-PERP", "MKR-PERP", "LDO-PERP", "CRV-PERP", "SNX-PERP",
        "COMP-PERP", "DYDX-PERP", "GMX-PERP", "GRT-PERP", "IMX-PERP",
        # Tier 4 - AI & Storage (verified on Binance Futures)
        "FET-PERP", "RNDR-PERP", "AR-PERP", "THETA-PERP", "STX-PERP",
        # Tier 5 - Memes (verified, use smaller sizes due to volatility)
        "PEPE-PERP", "SHIB-PERP", "FLOKI-PERP", "BONK-PERP", "WIF-PERP",
        "MEME-PERP", "ORDI-PERP",
        # Tier 6 - Recent Listings (verified on Binance Futures)
        "JTO-PERP", "PYTH-PERP", "JUP-PERP", "STRK-PERP", "W-PERP",
        "ENA-PERP", "ONDO-PERP", "PENDLE-PERP", "NOT-PERP", "WLD-PERP",
    ]

    # Crypto options - for paper trading all work; live trading limited to BTC/ETH
    CRYPTO_OPTIONS = [
        "BTC", "ETH", "SOL", "BNB", "XRP", "AVAX", "LINK", "DOGE",
        "ADA", "DOT", "MATIC", "LTC",
    ]

    # Crypto spot trading - direct buy/sell (works on Binance.US)
    CRYPTO_SPOT = [
        # Blue chips - always liquid
        "BTC", "ETH", "SOL", "BNB", "XRP",
        # Major alts
        "AVAX", "LINK", "DOGE", "ADA", "DOT", "MATIC", "LTC", "ATOM",
        # DeFi & emerging
        "UNI", "AAVE", "MKR", "CRV", "FET", "RNDR", "INJ", "SUI",
    ]

    def __init__(
        self,
        initial_capital: float = 100000.0,
        mode: str = "balanced",
    ):
        self.initial_capital = initial_capital
        self.mode = OptionsMode(mode)
        self.is_running = False
        self._task: Optional[asyncio.Task] = None

        # Core trading engine
        self.engine = create_options_bot(capital=initial_capital, mode=mode)

        # ML/Stats Analytics Engine
        self.analytics = QuantAnalyticsEngine(lookback_days=252)

        # Market state (now ML-detected)
        self.market_regime = MarketRegime.RANGE_BOUND
        self.regime_confidence = 0.5
        self.vix_level = 18.0

        # Opportunity tracking
        self.opportunities: List[Opportunity] = []
        self.last_full_scan: Optional[datetime] = None

        # Dynamic allocation (optimized via portfolio optimization)
        # Total allocation can exceed 100% since positions use leverage/margin
        self.allocation_limits = {
            AssetClass.STOCK_OPTIONS: 0.25,
            AssetClass.ETF_OPTIONS: 0.25,
            AssetClass.COMMODITY_OPTIONS: 0.10,
            AssetClass.CRYPTO_PERPETUAL: 0.15,
            AssetClass.CRYPTO_OPTIONS: 0.10,
            AssetClass.CRYPTO_SPOT: 0.15,  # Direct crypto spot buys
        }

        self.current_allocations: Dict[AssetClass, float] = {
            ac: 0.0 for ac in AssetClass
        }

        # Performance tracking
        self.daily_pnl: List[Tuple[datetime, float]] = []
        self.trade_history: List[Dict] = []

        # RL training state
        self.last_state: Optional[np.ndarray] = None
        self.last_action: Optional[int] = None
        self.episode_reward = 0.0

        # Commentary for UI
        self.commentary: List[Dict] = []

        # Live trading integration
        self.live_trading_enabled = False
        self.broker_manager = None  # Set via enable_live_trading endpoint

        # Activity logger for comprehensive event tracking
        self.activity_logger = get_activity_logger()

        # Funding rate cache: {symbol: (rate, timestamp)}
        self._funding_rate_cache: Dict[str, Tuple[float, datetime]] = {}
        self._funding_rate_cache_ttl = timedelta(minutes=30)

        # Pre-training integration - CRITICAL for intelligent trading
        self.model_pretrainer = get_model_pretrainer()
        self.alpha_manager = get_alpha_manager()
        self.models_trained = False
        self.training_required = True  # Require training before live trading

        # Try to load pre-trained models
        if self.model_pretrainer.load_checkpoints():
            meets_req, reason = self.model_pretrainer.meets_training_requirements()
            self.models_trained = meets_req
            if meets_req:
                logger.info("✅ Pre-trained models loaded successfully!")
                # Sync DQN epsilon from loaded checkpoint
                self.analytics.dqn.epsilon = self.model_pretrainer.dqn.epsilon
            else:
                logger.warning(f"⚠️ Models loaded but: {reason}")
        else:
            logger.warning("⚠️ No pre-trained models found - training required before trading")

        # Initialize with some synthetic price history for models
        self._initialize_price_history()

        logger.info(f"MasterQuantBot initialized: ${initial_capital:,.0f}, mode={mode}")
        self._add_commentary(
            f"🧠 MASTER QUANT BOT INITIALIZED: ${initial_capital:,.0f} capital | "
            f"ML Models: DQN, PPO, LSTM, Transformer, HMM, GARCH | "
            f"Mode: {mode}",
            "system"
        )

    def _initialize_price_history(self):
        """Initialize price history tracking - NO synthetic data, requires REAL data."""
        # Flag to track if real data has been loaded
        self._real_data_loaded = False

        # NO SYNTHETIC DATA - ML models will wait for real data
        logger.info("Price history initialized - waiting for REAL market data (no synthetic fallback)")

    async def _load_real_market_data(self):
        """Load real historical data from Binance (crypto) and Alpaca (stocks)."""
        if self._real_data_loaded:
            return

        total_loaded = 0

        # ============ CRYPTO DATA FROM BINANCE ============
        try:
            from ..data.binance_data import get_binance_fetcher

            fetcher = get_binance_fetcher()

            # Crypto symbols to fetch real data for (verified on Binance.US)
            crypto_symbols = [
                "BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX",
                "LINK", "DOT", "MATIC", "LTC", "ATOM", "UNI", "FET",
                "AAVE", "MKR", "CRV", "NEAR", "APT", "ARB", "OP", "SUI",
            ]

            self._add_commentary(
                "📊 Fetching REAL crypto data from Binance.US...",
                "system"
            )

            data = await fetcher.get_multi_symbol_data(crypto_symbols, days=252, interval="1d")

            crypto_loaded = 0
            for symbol, (prices, returns) in data.items():
                if len(prices) >= 60:
                    # Update both the base symbol and perpetual version
                    self.analytics.update_price_history(symbol, prices)
                    self.analytics.update_price_history(f"{symbol}-PERP", prices)
                    crypto_loaded += 1

            if crypto_loaded > 0:
                self._add_commentary(
                    f"✅ Loaded {crypto_loaded} crypto symbols from Binance.US",
                    "system"
                )
                logger.info(f"Loaded real Binance data for {crypto_loaded} crypto symbols")
                total_loaded += crypto_loaded

        except Exception as e:
            logger.warning(f"Failed to load Binance crypto data: {e}")
            self._add_commentary(
                f"⚠️ Binance fetch failed: {str(e)[:40]}",
                "system"
            )

        # ============ STOCK DATA FROM ALPACA ============
        try:
            from ..data.alpaca_data import get_alpaca_fetcher

            alpaca = get_alpaca_fetcher()

            if alpaca.has_keys:
                # Stock/ETF symbols to fetch
                stock_symbols = [
                    # ETFs (most important for regime detection)
                    "SPY", "QQQ", "IWM", "DIA",
                    # Major stocks
                    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA",
                    # Commodities ETFs
                    "GLD", "SLV", "USO",
                    # Financials
                    "JPM", "BAC", "GS",
                    # High vol
                    "AMD", "COIN",
                ]

                self._add_commentary(
                    "📈 Fetching REAL stock data from Alpaca...",
                    "system"
                )

                stock_data = await alpaca.get_multi_symbol_data(stock_symbols, days=252)

                stock_loaded = 0
                for symbol, (prices, returns) in stock_data.items():
                    if len(prices) >= 60:
                        self.analytics.update_price_history(symbol, prices)
                        stock_loaded += 1

                if stock_loaded > 0:
                    self._add_commentary(
                        f"✅ Loaded {stock_loaded} stock symbols from Alpaca",
                        "system"
                    )
                    logger.info(f"Loaded real Alpaca data for {stock_loaded} stock symbols")
                    total_loaded += stock_loaded
            else:
                self._add_commentary(
                    "❌ Alpaca API keys not configured - stock data UNAVAILABLE",
                    "system"
                )

        except Exception as e:
            logger.warning(f"Failed to load Alpaca stock data: {e}")
            self._add_commentary(
                f"❌ Alpaca fetch failed: {str(e)[:40]}",
                "system"
            )

        # ============ SUMMARY ============
        if total_loaded > 0:
            self._real_data_loaded = True
            self._add_commentary(
                f"🎯 ML Training Data: {total_loaded} symbols with REAL market data",
                "system"
            )
        else:
            self._add_commentary(
                "❌ NO REAL DATA LOADED - ML predictions may be unreliable! Check broker connections.",
                "system"
            )
            logger.error("No real market data loaded - synthetic fallback DISABLED")

    async def _update_live_prices(self):
        """Update price history with latest live data from Binance."""
        try:
            from ..data.binance_data import get_binance_fetcher

            fetcher = get_binance_fetcher()

            # Update prices for actively traded symbols
            active_symbols = list(set(
                [pos.symbol.replace("-PERP", "").split("-")[0]
                 for pos in self.engine.crypto_positions.values()]
            ))

            # Also update top crypto symbols
            top_cryptos = ["BTC", "ETH", "SOL", "BNB", "XRP"]
            symbols_to_update = list(set(active_symbols + top_cryptos))

            for symbol in symbols_to_update[:10]:  # Limit to 10 to avoid rate limits
                try:
                    price = await fetcher.get_price(symbol)
                    if price:
                        # Append to existing price history
                        key = symbol if symbol in self.analytics.price_history else f"{symbol}-PERP"
                        if key in self.analytics.price_history:
                            prices = self.analytics.price_history[key]
                            # Append new price
                            new_prices = np.append(prices, price)
                            # Keep last 500 prices
                            if len(new_prices) > 500:
                                new_prices = new_prices[-500:]
                            self.analytics.update_price_history(key, new_prices)
                except Exception:
                    pass  # Silently skip failed updates

        except Exception as e:
            logger.debug(f"Live price update failed: {e}")

    # ===================
    # MARKET ANALYSIS (ML-Enhanced)
    # ===================

    async def _assess_market_regime(self):
        """Assess market regime using HMM and VAE."""
        # Use SPY as market proxy
        if "SPY" in self.analytics.return_history:
            spy_returns = self.analytics.return_history["SPY"]

            # HMM regime detection
            hmm_state, hmm_probs = self.analytics.detect_regime_hmm(spy_returns)

            # VAE regime detection
            vae_regime, vae_probs = 1, np.array([0.25, 0.25, 0.25, 0.25])  # Default
            if len(spy_returns) >= 32:
                try:
                    vae_regime, vae_probs, _ = self.analytics.regime_vae.detect_regime(
                        spy_returns[-32:].reshape(1, -1)
                    )
                except Exception as e:
                    logger.debug(f"VAE regime detection failed: {e}")

            # Combine HMM and VAE
            combined_confidence = (np.max(hmm_probs) + np.max(vae_probs)) / 2

            # Calculate VIX from actual SPY volatility (annualized)
            # HMM state provides regime context: 0=low vol, 1=medium, 2=high vol
            actual_vol = float(np.std(spy_returns[-20:]) * np.sqrt(252) * 100) if len(spy_returns) >= 20 else 18
            # VIX typically ranges 10-40, with SPY vol * 100 being a good proxy
            self.vix_level = max(10, min(50, actual_vol + hmm_state * 2))

            if self.vix_level > 25:
                self.market_regime = MarketRegime.HIGH_VOLATILITY
                regime_str = "HIGH VOLATILITY"
            elif self.vix_level < 14:
                self.market_regime = MarketRegime.LOW_VOLATILITY
                regime_str = "LOW VOLATILITY"
            elif vae_regime == 0:
                self.market_regime = MarketRegime.BULL_MARKET
                regime_str = "BULL MARKET"
            elif vae_regime == 1:
                self.market_regime = MarketRegime.BEAR_MARKET
                regime_str = "BEAR MARKET"
            else:
                self.market_regime = MarketRegime.RANGE_BOUND
                regime_str = "RANGE BOUND"

            self.regime_confidence = combined_confidence

            self._add_commentary(
                f"🤖 ML Regime Detection: {regime_str} | "
                f"VIX: {self.vix_level:.1f} | "
                f"HMM State: {hmm_state} (conf: {np.max(hmm_probs):.0%}) | "
                f"VAE Regime: {self.analytics.regime_vae.get_regime_name(vae_regime)}",
                "analysis"
            )
        else:
            # No SPY data - try to use BTC volatility as market proxy
            if "BTC" in self.analytics.return_history:
                btc_returns = self.analytics.return_history["BTC"]
                if len(btc_returns) >= 20:
                    btc_vol = float(np.std(btc_returns[-20:]) * np.sqrt(365) * 100)
                    # BTC vol is typically 2-3x stock vol, so scale down
                    self.vix_level = max(10, min(50, btc_vol / 3))
                else:
                    self.vix_level = 18  # Default if no data
            else:
                self.vix_level = 18  # Default
            self.market_regime = MarketRegime.RANGE_BOUND

    # ===================
    # OPPORTUNITY SCANNING (ML-Enhanced)
    # ===================

    async def _scan_all_markets(self) -> List[Opportunity]:
        """Scan markets with ML-enhanced scoring, respecting market hours."""
        opportunities = []

        # Check if US stock market is open
        market_open = is_market_open()
        market_status = get_market_status()

        if market_open:
            self._add_commentary(
                "🔍 Market OPEN - Scanning ALL markets with ML analytics...",
                "scan"
            )

            # 1. Scan Stock Options with ML
            stock_opps = await self._scan_stock_options()
            opportunities.extend(stock_opps)

            # 2. Scan ETF Options
            etf_opps = await self._scan_etf_options()
            opportunities.extend(etf_opps)

            # 3. Scan Commodity Options
            commodity_opps = await self._scan_commodity_options()
            opportunities.extend(commodity_opps)
        else:
            self._add_commentary(
                f"🌙 Market CLOSED ({market_status['message']}) - CRYPTO ONLY mode active",
                "scan"
            )

        # Crypto markets are 24/7 - always scan
        # 4. Scan Crypto Perpetuals
        crypto_perp_opps = await self._scan_crypto_perpetuals()
        opportunities.extend(crypto_perp_opps)

        # 5. Scan Crypto Options
        crypto_opt_opps = await self._scan_crypto_options()
        opportunities.extend(crypto_opt_opps)

        # 6. Scan Crypto Spot (direct buy/sell)
        crypto_spot_opps = await self._scan_crypto_spot()
        opportunities.extend(crypto_spot_opps)

        # Re-rank using ML composite score
        for opp in opportunities:
            opp.score = self._compute_ml_score(opp)

        # Sort by ML-enhanced score
        opportunities.sort(key=lambda x: x.score, reverse=True)

        self._add_commentary(
            f"✅ ML Scan complete: {len(opportunities)} opportunities | "
            f"Top: {opportunities[0].symbol if opportunities else 'N/A'} "
            f"(Score: {opportunities[0].score:.1f})" if opportunities else "",
            "scan"
        )

        self.opportunities = opportunities
        self.last_full_scan = datetime.now()

        # Log scan completion to activity logger
        await self.activity_logger.log_scan(
            subtype=EventSubtype.SCAN_COMPLETE,
            message=f"Market scan complete: {len(opportunities)} opportunities found",
            details={
                "market_open": market_open,
                "total_opportunities": len(opportunities),
                "by_asset_class": {
                    "stock_options": len([o for o in opportunities if o.asset_class == AssetClass.STOCK_OPTIONS]),
                    "etf_options": len([o for o in opportunities if o.asset_class == AssetClass.ETF_OPTIONS]),
                    "commodity_options": len([o for o in opportunities if o.asset_class == AssetClass.COMMODITY_OPTIONS]),
                    "crypto_perpetual": len([o for o in opportunities if o.asset_class == AssetClass.CRYPTO_PERPETUAL]),
                    "crypto_options": len([o for o in opportunities if o.asset_class == AssetClass.CRYPTO_OPTIONS]),
                    "crypto_spot": len([o for o in opportunities if o.asset_class == AssetClass.CRYPTO_SPOT]),
                },
                "top_opportunity": opportunities[0].symbol if opportunities else None,
                "market_regime": self.market_regime.value,
                "vix_level": self.vix_level,
            }
        )

        return opportunities

    def _compute_ml_score(self, opp: Opportunity) -> float:
        """Compute ML-enhanced opportunity score."""
        base_score = opp.score

        # Get ML prediction
        ml_pred = self.analytics.get_ml_prediction(opp.symbol)
        opp.ml_prediction = ml_pred

        # Get risk metrics
        risk = self.analytics.compute_risk_metrics(opp.symbol)
        opp.risk_metrics = risk

        # Factor alpha
        opp.factor_alpha = ml_pred.factors.get("alpha", 0)

        # Regime alignment (does strategy match regime?)
        regime_alignment = self._compute_regime_alignment(opp)
        opp.regime_alignment = regime_alignment

        # Bayesian confidence
        opp.bayesian_confidence = ml_pred.confidence * ml_pred.ensemble_agreement

        # Composite score
        ml_score = (
            base_score * 0.30 +                           # Traditional score
            ml_pred.confidence * 100 * 0.20 +             # ML confidence
            ml_pred.ensemble_agreement * 50 * 0.15 +      # Model agreement
            regime_alignment * 30 * 0.15 +                # Regime fit
            (1 - risk.var_95) * 50 * 0.10 +              # Lower VaR is better
            risk.sharpe_ratio * 10 * 0.10                 # Expected risk-adjusted return
        )

        # Boost if ML says buy/sell aligns with strategy
        if ml_pred.action == 2 and "Long" in opp.strategy:  # Buy signal + Long strategy
            ml_score *= 1.15
        elif ml_pred.action == 0 and "Short" in opp.strategy:  # Sell signal + Short strategy
            ml_score *= 1.15

        return ml_score

    def _compute_regime_alignment(self, opp: Opportunity) -> float:
        """Compute how well opportunity aligns with current regime."""
        alignment = 0.5  # Neutral

        if self.market_regime == MarketRegime.HIGH_VOLATILITY:
            # Prefer premium selling
            if "Iron Condor" in opp.strategy or "Sell" in opp.strategy:
                alignment = 0.9
            elif "Straddle" in opp.strategy and "Long" not in opp.strategy:
                alignment = 0.8
        elif self.market_regime == MarketRegime.LOW_VOLATILITY:
            # Prefer premium buying
            if "Long" in opp.strategy or "Buy" in opp.strategy:
                alignment = 0.85
        elif self.market_regime == MarketRegime.BULL_MARKET:
            # Prefer bullish strategies
            if "Long" in opp.strategy or "Call" in opp.strategy:
                alignment = 0.9
        elif self.market_regime == MarketRegime.BEAR_MARKET:
            # Prefer bearish strategies
            if "Short" in opp.strategy or "Put" in opp.strategy:
                alignment = 0.9

        return alignment

    async def _scan_stock_options(self) -> List[Opportunity]:
        """Scan stock options with ML enhancement."""
        opportunities = []

        for symbol in self.STOCK_OPTIONS[:10]:
            iv_analysis = await self.engine._analyze_iv(symbol)
            self.engine.iv_cache[symbol] = iv_analysis

            opp = self._score_options_opportunity(
                symbol, iv_analysis, AssetClass.STOCK_OPTIONS
            )
            if opp and opp.score > 40:
                opportunities.append(opp)

        return opportunities

    async def _scan_etf_options(self) -> List[Opportunity]:
        """Scan ETF options with ML enhancement."""
        opportunities = []

        for symbol in self.ETF_OPTIONS:
            iv_analysis = await self.engine._analyze_iv(symbol)
            self.engine.iv_cache[symbol] = iv_analysis

            opp = self._score_options_opportunity(
                symbol, iv_analysis, AssetClass.ETF_OPTIONS
            )
            if opp and opp.score > 40:
                opportunities.append(opp)

        return opportunities

    async def _scan_commodity_options(self) -> List[Opportunity]:
        """Scan commodity options."""
        opportunities = []

        for symbol in self.COMMODITY_OPTIONS:
            iv_analysis = await self.engine._analyze_iv(symbol)
            self.engine.iv_cache[symbol] = iv_analysis

            opp = self._score_options_opportunity(
                symbol, iv_analysis, AssetClass.COMMODITY_OPTIONS
            )
            if opp and opp.score > 35:
                opportunities.append(opp)

        return opportunities

    async def _scan_crypto_perpetuals(self) -> List[Opportunity]:
        """Scan crypto perpetuals with ML enhancement."""
        opportunities = []

        for symbol in self.CRYPTO_PERPETUALS:
            opp = await self._score_crypto_perpetual(symbol)
            # Lower threshold (30) to capture more opportunities in range-bound markets
            if opp and opp.score > 30:
                opportunities.append(opp)

        return opportunities

    async def _scan_crypto_options(self) -> List[Opportunity]:
        """Scan crypto options."""
        opportunities = []

        for base_asset in self.CRYPTO_OPTIONS:
            call_opp = await self._score_crypto_option(base_asset, "call")
            # Lower threshold (35) for more opportunity capture
            if call_opp and call_opp.score > 35:
                opportunities.append(call_opp)

            put_opp = await self._score_crypto_option(base_asset, "put")
            if put_opp and put_opp.score > 35:
                opportunities.append(put_opp)

        return opportunities

    async def _scan_crypto_spot(self) -> List[Opportunity]:
        """Scan crypto spot market for buy/sell opportunities."""
        opportunities = []

        for symbol in self.CRYPTO_SPOT:
            opp = await self._score_crypto_spot(symbol)
            # Lower threshold (30) for spot - we want more activity
            if opp and opp.score > 30:
                opportunities.append(opp)

        return opportunities

    async def _score_crypto_spot(self, symbol: str) -> Optional[Opportunity]:
        """Score crypto spot opportunity using ML signals."""
        try:
            # Get ML prediction
            ml_pred = self.analytics.get_ml_prediction(symbol)

            # Determine direction based on ML
            if ml_pred.action == 2:  # Buy signal
                strategy = "Spot Long"
                direction = "bullish"
            elif ml_pred.action == 0:  # Sell signal
                strategy = "Spot Short"  # Or just don't buy
                direction = "bearish"
            else:
                # Hold signal - still create opportunity but lower score
                strategy = "Spot Long"
                direction = "neutral"

            # Get risk metrics
            risk = self.analytics.compute_risk_metrics(symbol)

            # Score based on ML confidence and risk metrics
            base_score = ml_pred.confidence * 100

            # Adjust for regime
            if self.market_regime == MarketRegime.BULL_MARKET and direction == "bullish":
                base_score *= 1.2
            elif self.market_regime == MarketRegime.BEAR_MARKET and direction == "bearish":
                base_score *= 1.1

            # Penalize high volatility for spot (we prefer stable entries)
            if risk.volatility_forecast > 0.5:
                base_score *= 0.8

            # Estimate P&L
            position_size = self.initial_capital * 0.02  # 2% position
            expected_return = ml_pred.lstm_pred * 100 if ml_pred.lstm_pred else 5
            max_profit = position_size * 0.10  # 10% upside
            max_loss = position_size * 0.05   # 5% stop loss

            return Opportunity(
                symbol=symbol,
                asset_class=AssetClass.CRYPTO_SPOT,
                strategy=strategy,
                score=base_score,
                expected_return=expected_return,
                probability_of_profit=ml_pred.confidence,
                risk_reward_ratio=max_profit / max_loss if max_loss > 0 else 2.0,
                iv_rank=50,  # N/A for spot, use neutral value
                max_profit=max_profit,
                max_loss=max_loss,
                rationale=f"ML Signal: {ml_pred.action_name} (conf: {ml_pred.confidence:.1%}) | "
                         f"Regime: {ml_pred.regime}",
            )
        except Exception as e:
            logger.debug(f"Error scoring {symbol} spot: {e}")
            return None

    # ===================
    # OPPORTUNITY SCORING
    # ===================

    def _score_options_opportunity(
        self,
        symbol: str,
        iv_analysis: IVAnalysis,
        asset_class: AssetClass
    ) -> Optional[Opportunity]:
        """Score options opportunity with traditional + ML metrics."""
        # Determine strategy based on IV and regime
        if iv_analysis.iv_rank > 50 or self.market_regime == MarketRegime.HIGH_VOLATILITY:
            strategy = "Iron Condor"
            expected_return = 25 + iv_analysis.iv_rank * 0.3
            probability = 0.70 + (iv_analysis.iv_rank - 50) * 0.002
            max_profit = 200 + iv_analysis.iv_rank * 3
            max_loss = 500
            rationale = f"High IV Rank ({iv_analysis.iv_rank:.0f}%) - premium selling"
        elif iv_analysis.iv_rank < 25:
            strategy = "Long Straddle"
            expected_return = 15 + (25 - iv_analysis.iv_rank) * 0.5
            probability = 0.45
            max_profit = 1000
            max_loss = 300
            rationale = f"Low IV Rank ({iv_analysis.iv_rank:.0f}%) - cheap premium"
        else:
            strategy = "Vertical Spread"
            expected_return = 20
            probability = 0.55
            max_profit = 300
            max_loss = 200
            rationale = f"Moderate IV ({iv_analysis.iv_rank:.0f}%) - directional"

        risk_reward = max_profit / max_loss if max_loss > 0 else 0

        # Base score
        score = (
            expected_return * 0.3 +
            probability * 100 * 0.25 +
            iv_analysis.iv_rank * 0.2 +
            risk_reward * 10 * 0.15 +
            (30 if asset_class == AssetClass.ETF_OPTIONS else 20) * 0.1
        )

        return Opportunity(
            symbol=symbol,
            asset_class=asset_class,
            strategy=strategy,
            expected_return=expected_return,
            max_profit=max_profit,
            max_loss=max_loss,
            probability_of_profit=probability,
            risk_reward_ratio=risk_reward,
            iv_rank=iv_analysis.iv_rank,
            score=score,
            rationale=rationale,
        )

    async def _fetch_funding_rate(self, symbol: str) -> float:
        """
        Fetch real funding rate from Binance Futures API.

        Falls back to a neutral estimate on failure. Caches results
        for 30 minutes to avoid excessive API calls.
        """
        base = symbol.split("-")[0].replace("USDT", "").replace("/USD", "")
        cache_key = base

        # Check cache
        if cache_key in self._funding_rate_cache:
            rate, ts = self._funding_rate_cache[cache_key]
            if datetime.now() - ts < self._funding_rate_cache_ttl:
                return rate

        try:
            import httpx
            binance_symbol = f"{base}USDT"
            url = f"https://fapi.binance.com/fapi/v1/fundingRate?symbol={binance_symbol}&limit=1"

            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    data = resp.json()
                    if data and len(data) > 0:
                        rate = float(data[0]["fundingRate"])
                        self._funding_rate_cache[cache_key] = (rate, datetime.now())
                        return rate
        except Exception as e:
            logger.debug(f"Funding rate API failed for {symbol}: {e}")

        # Fallback: neutral funding rate (typical average ~0.01% per 8h)
        fallback = 0.0001
        self._funding_rate_cache[cache_key] = (fallback, datetime.now())
        return fallback

    async def _score_crypto_perpetual(self, symbol: str) -> Optional[Opportunity]:
        """Score crypto perpetual with ML enhancement."""
        base = symbol.split("-")[0]
        price = await self.engine._get_crypto_price(symbol)

        # Skip if no valid price (no synthetic fallback)
        if price <= 0:
            logger.debug(f"Skipping {symbol} - no live price available")
            return None

        # Get ML prediction for crypto
        ml_pred = self.analytics.get_ml_prediction(symbol)

        funding_rate = await self._fetch_funding_rate(symbol)

        if ml_pred.action == 0:  # Sell signal
            strategy = "Short Perpetual"
            side = "short"
            expected_return = 40 * ml_pred.confidence
            probability = 0.55 + ml_pred.ensemble_agreement * 0.15
            rationale = f"ML Sell signal (conf: {ml_pred.confidence:.0%}) | Regime: {ml_pred.regime}"
        elif ml_pred.action == 2:  # Buy signal
            strategy = "Long Perpetual"
            expected_return = 40 * ml_pred.confidence
            probability = 0.55 + ml_pred.ensemble_agreement * 0.15
            rationale = f"ML Buy signal (conf: {ml_pred.confidence:.0%}) | Regime: {ml_pred.regime}"
        else:
            strategy = "Long Perpetual"
            expected_return = 15
            probability = 0.50
            rationale = f"Neutral ML signal | Funding: {funding_rate*100:.3f}%"

        max_profit = price * 0.10
        max_loss = price * 0.05
        risk_reward = max_profit / max_loss if max_loss > 0 else 2.0

        score = (
            expected_return * 0.30 +
            probability * 100 * 0.25 +
            ml_pred.confidence * 50 * 0.25 +
            risk_reward * 15 * 0.20
        )

        return Opportunity(
            symbol=symbol,
            asset_class=AssetClass.CRYPTO_PERPETUAL,
            strategy=strategy,
            expected_return=expected_return,
            max_profit=max_profit,
            max_loss=max_loss,
            probability_of_profit=probability,
            risk_reward_ratio=risk_reward,
            iv_rank=65,
            score=score,
            rationale=rationale,
        )

    async def _score_crypto_option(self, base_asset: str, option_type: str) -> Optional[Opportunity]:
        """Score crypto option opportunity."""
        symbol = f"{base_asset}-OPT"
        price = await self.engine._get_crypto_price(symbol)

        # Skip if no valid price (no synthetic fallback)
        if price <= 0:
            logger.debug(f"Skipping {symbol} - no live price available")
            return None

        iv = 0.65 + np.random.uniform(-0.1, 0.2)

        if iv > 0.70:
            strategy = f"Sell {base_asset} {option_type.title()}"
            expected_return = 35
            probability = 0.65
            max_profit = price * 0.05
            max_loss = price * 0.15
            rationale = f"High crypto IV ({iv*100:.0f}%) - selling premium"
        else:
            strategy = f"Buy {base_asset} {option_type.title()}"
            expected_return = 25
            probability = 0.40
            max_profit = price * 0.20
            max_loss = price * 0.03
            rationale = f"Lower crypto IV ({iv*100:.0f}%) - directional"

        risk_reward = max_profit / max_loss if max_loss > 0 else 0

        score = (
            expected_return * 0.3 +
            probability * 100 * 0.25 +
            iv * 100 * 0.2 +
            risk_reward * 10 * 0.15 +
            15 * 0.1
        )

        return Opportunity(
            symbol=f"{base_asset}-{option_type.upper()}",
            asset_class=AssetClass.CRYPTO_OPTIONS,
            strategy=strategy,
            expected_return=expected_return,
            max_profit=max_profit,
            max_loss=max_loss,
            probability_of_profit=probability,
            risk_reward_ratio=risk_reward,
            iv_rank=iv * 100,
            score=score,
            rationale=rationale,
        )

    # ===================
    # TRADE EXECUTION (RL-Enhanced)
    # ===================

    async def _execute_best_opportunities(self):
        """Execute opportunities using RL-informed decisions.

        IMPORTANT: This now requires trained models before executing trades.
        No more "exploration bypass" - we don't trade with random weights.
        """
        if not self.opportunities:
            return

        # CRITICAL: Check if models are trained before allowing trades
        if self.training_required and not self.models_trained:
            meets_req, reason = self.model_pretrainer.meets_training_requirements()
            if not meets_req:
                self._add_commentary(
                    f"⏸️ Trading paused - models not trained: {reason}. "
                    f"Run training pipeline first!",
                    "system"
                )
                return
            else:
                self.models_trained = True
                self._add_commentary(
                    "✅ Models trained - enabling intelligent trading",
                    "system"
                )

        executed = 0
        max_new_positions = 3

        for opp in self.opportunities[:10]:
            if executed >= max_new_positions:
                break

            # Check allocation limit
            current_alloc = self.current_allocations.get(opp.asset_class, 0)
            limit = self.allocation_limits.get(opp.asset_class, 0.20)

            if current_alloc >= limit:
                continue

            if self._has_position(opp.symbol):
                continue

            # Construct state for ML prediction
            state = self.analytics._construct_state(opp.symbol, {
                "position_size": 0,
                "vix": self.vix_level,
            })

            # Get ensemble prediction from PRE-TRAINED models
            ml_prediction = self.model_pretrainer.predict(state)
            action = ml_prediction["action"]
            confidence = ml_prediction["confidence"]

            # Get alpha signals (sentiment, on-chain, fear/greed)
            try:
                alpha_signal = await self.alpha_manager.get_combined_alpha(opp.symbol)
                alpha_boost = alpha_signal.get("combined_signal", 0) * 10  # -10 to +10
            except Exception:
                alpha_boost = 0

            # INTELLIGENT TRADING DECISION (no more random exploration bypass!)
            # Criteria for execution:
            # 1. ML prediction is BUY (action=2) or SELL (action=0), not HOLD (action=1)
            # 2. ML confidence > 60%
            # 3. Opportunity score >= 35 (from traditional analysis)
            # 4. Optional: alpha sources support the trade

            ml_agrees = action != 1  # Not hold
            score_threshold = self._get_dynamic_score_threshold()
            conf_threshold = self._get_dynamic_confidence_threshold()
            ml_confident = confidence >= conf_threshold
            score_sufficient = opp.score >= score_threshold
            alpha_supports = (
                (action == 2 and alpha_boost > 0) or  # Buy + bullish alpha
                (action == 0 and alpha_boost < 0) or  # Sell + bearish alpha
                abs(alpha_boost) < 3  # Neutral alpha doesn't block
            )

            # Adjusted score with alpha
            adjusted_score = opp.score + alpha_boost

            # Execute only with proper ML support (NO RANDOM TRADING!)
            should_execute = (
                ml_agrees and
                ml_confident and
                score_sufficient and
                alpha_supports
            )

            if should_execute:
                success = await self._execute_opportunity(opp)

                if success:
                    executed += 1
                    position_size = opp.max_loss / self.initial_capital
                    self.current_allocations[opp.asset_class] = current_alloc + position_size

                    # Store state for continued RL training (online learning)
                    self.last_state = state
                    self.last_action = action

                    # Log the intelligent decision
                    self._add_commentary(
                        f"🎯 ML-INFORMED TRADE: {opp.symbol} | "
                        f"Action: {'BUY' if action == 2 else 'SELL'} | "
                        f"Confidence: {confidence:.1%} | "
                        f"Score: {adjusted_score:.1f} (alpha: {alpha_boost:+.1f})",
                        "execution"
                    )
            else:
                # Log rejection reason for transparency
                if not ml_agrees:
                    rejection = "ML says HOLD"
                elif not ml_confident:
                    rejection = f"Low confidence ({confidence:.1%} < {conf_threshold:.0%})"
                elif not score_sufficient:
                    rejection = f"Score too low ({opp.score:.1f} < {score_threshold:.0f})"
                else:
                    rejection = "Alpha signal conflicts"

                logger.debug(f"Rejected {opp.symbol}: {rejection}")

        if executed > 0:
            self._add_commentary(
                f"📈 Executed {executed} intelligent trades | "
                f"DQN Epsilon: {self.analytics.dqn.epsilon:.3f} | "
                f"Models: {'TRAINED ✅' if self.models_trained else 'UNTRAINED ❌'}",
                "execution"
            )
        else:
            # Log why no trades executed (for debugging)
            top_opps = self.opportunities[:3] if self.opportunities else []
            if top_opps:
                rejection_reasons = []
                for opp in top_opps:
                    reason = f"{opp.symbol}: Score {opp.score:.1f}"
                    if opp.ml_prediction and opp.ml_prediction.action == 1:
                        reason += " (ML: HOLD)"
                    rejection_reasons.append(reason)
                self._add_commentary(
                    f"⏸️ No trades executed. Top opportunities: {', '.join(rejection_reasons)}",
                    "scan"
                )

    def _get_dynamic_score_threshold(self) -> float:
        """
        Regime-adjusted score threshold for trade execution.

        Instead of a fixed score >= 35, adapts to market conditions:
        - High volatility: very selective (50) — only high-conviction trades
        - Bear market: cautious (45) — tighter filter
        - Range-bound: default (35) — normal selectivity
        - Bull market: more aggressive (30) — capture momentum
        - Low volatility: slightly aggressive (28) — more opportunities
        """
        thresholds = {
            MarketRegime.HIGH_VOLATILITY: 50,
            MarketRegime.BEAR_MARKET: 45,
            MarketRegime.RANGE_BOUND: 35,
            MarketRegime.BULL_MARKET: 30,
            MarketRegime.LOW_VOLATILITY: 28,
        }
        return thresholds.get(self.market_regime, 35)

    def _get_dynamic_confidence_threshold(self) -> float:
        """
        Regime-adjusted ML confidence threshold.

        Higher bar in dangerous regimes, lower in favorable ones.
        """
        thresholds = {
            MarketRegime.HIGH_VOLATILITY: 0.75,
            MarketRegime.BEAR_MARKET: 0.70,
            MarketRegime.RANGE_BOUND: 0.60,
            MarketRegime.BULL_MARKET: 0.55,
            MarketRegime.LOW_VOLATILITY: 0.50,
        }
        return thresholds.get(self.market_regime, 0.60)

    def _vol_adjusted_size(self, symbol: str, base_pct: float, max_usd: float,
                              leverage: float = 1.0) -> float:
        """
        Compute volatility-adjusted position size.

        Instead of fixed % of cash, targets a fixed dollar-risk per position
        by scaling inversely with the asset's volatility.

        Higher vol → smaller position, Lower vol → larger position.
        This normalizes the risk contribution of each trade.

        Args:
            symbol: Asset symbol
            base_pct: Base position size as fraction of cash (e.g. 0.05)
            max_usd: Hard dollar cap
            leverage: Position leverage multiplier
        """
        base_size = self.engine.cash * base_pct

        # Get asset volatility from return history
        base_symbol = symbol.split("-")[0].replace("USDT", "").replace("/USD", "")
        vol_annual = 0.40  # Default: 40% annualized

        for sym, returns in self.analytics.return_history.items():
            if base_symbol in sym and len(returns) >= 20:
                vol_annual = float(np.std(returns[-60:]) * np.sqrt(252))
                break

        # Target volatility: 20% annualized (moderate risk)
        # Scale: position shrinks when asset vol > target, grows when below
        target_vol = 0.20
        vol_scalar = target_vol / max(vol_annual, 0.05)  # Floor at 5% vol
        vol_scalar = np.clip(vol_scalar, 0.25, 2.0)  # Don't go below 25% or above 200% of base

        # Account for leverage (higher leverage → smaller base position)
        leverage_adj = 1.0 / max(leverage, 1.0)

        adjusted_size = base_size * vol_scalar * leverage_adj
        return min(adjusted_size, max_usd)

    async def _execute_opportunity(self, opp: Opportunity) -> bool:
        """Execute a single opportunity."""
        try:
            # CRITICAL: Check market hours for stock/ETF/commodity options
            if opp.asset_class in [AssetClass.STOCK_OPTIONS, AssetClass.ETF_OPTIONS, AssetClass.COMMODITY_OPTIONS]:
                if not is_market_open():
                    self._add_commentary(
                        f"⛔ BLOCKED: Cannot execute {opp.symbol} - market is CLOSED",
                        "execution"
                    )
                    return False

            # If live trading is enabled, execute on real exchanges
            if self.live_trading_enabled and self.broker_manager:
                live_success = await self._execute_live_trade(opp)
                if live_success:
                    self._record_trade(opp, f"live_{opp.asset_class.value}")
                    return True
                # Fall through to paper trading if live fails

            # Paper trading execution
            if opp.asset_class in [AssetClass.STOCK_OPTIONS, AssetClass.ETF_OPTIONS, AssetClass.COMMODITY_OPTIONS]:
                iv_analysis = self.engine.iv_cache.get(opp.symbol)
                if not iv_analysis:
                    return False

                signal = self.engine._generate_signal(opp.symbol, iv_analysis)
                if signal:
                    await self.engine._execute_signal(opp.symbol, signal, iv_analysis)
                    self._record_trade(opp, "options")
                    return True

            elif opp.asset_class == AssetClass.CRYPTO_PERPETUAL:
                side = "long" if "Long" in opp.strategy else "short"
                perp_size = self._vol_adjusted_size(opp.symbol, base_pct=0.05, max_usd=5000, leverage=2.0)
                position = await self.engine.open_crypto_perpetual(
                    symbol=opp.symbol,
                    side=side,
                    size_usd=perp_size,
                    leverage=2.0,
                )
                if position:
                    trade_id = self._record_trade(opp, "crypto_perpetual", position.entry_price, position.size)
                    position.trade_id = trade_id
                    position.opened_at = datetime.now()
                return position is not None

            elif opp.asset_class == AssetClass.CRYPTO_OPTIONS:
                base = opp.symbol.split("-")[0]
                opt_type = "call" if "CALL" in opp.symbol or "Call" in opp.strategy else "put"
                is_buy = "Buy" in opp.strategy

                price = await self.engine._get_crypto_price(f"{base}-OPT")
                strike = round(price * (1.05 if opt_type == "call" else 0.95), -2)

                opt_size = self._vol_adjusted_size(opp.symbol, base_pct=0.03, max_usd=3000)
                position = await self.engine.open_crypto_option(
                    base_asset=base,
                    option_type=opt_type,
                    strike=strike,
                    expiry_days=30,
                    size_usd=opt_size,
                    is_buy=is_buy,
                )
                if position:
                    trade_id = self._record_trade(opp, "crypto_option", position.entry_price, position.size)
                    position.trade_id = trade_id
                    position.opened_at = datetime.now()
                return position is not None

            elif opp.asset_class == AssetClass.CRYPTO_SPOT:
                # Crypto spot buy/sell
                side = "buy" if "Long" in opp.strategy else "sell"
                size_usd = self._vol_adjusted_size(opp.symbol, base_pct=0.02, max_usd=2000)

                position = await self.engine.open_crypto_spot(
                    symbol=opp.symbol,
                    side=side,
                    size_usd=size_usd,
                )
                if position:
                    trade_id = self._record_trade(opp, "crypto_spot", position.entry_price, position.size)
                    position.trade_id = trade_id
                    position.opened_at = datetime.now()
                return position is not None

        except Exception as e:
            logger.error(f"Failed to execute {opp.symbol}: {e}")
            return False

        return False

    def _record_trade(self, opp: Opportunity, trade_type: str, price: float = 0, size: float = 0) -> str:
        """Record trade for RL training and analysis with LLM summary. Returns trade_id."""
        from ..llm.analyst import get_quant_analyst

        trade_id = str(uuid.uuid4())[:8]
        side = "long" if "Long" in opp.strategy or "Buy" in opp.strategy or "Call" in opp.strategy else "short"

        # Use explicit checks for price/size to avoid falsy 0 issues
        if price > 0:
            trade_price = price
        elif opp.max_profit and opp.max_profit > 0:
            trade_price = opp.max_profit / 100
        else:
            trade_price = 0

        trade_size = size if size > 0 else min(5000, self.initial_capital * 0.05)

        # Build comprehensive trade record with full details
        trade_record = {
            "id": trade_id,
            "timestamp": datetime.now().isoformat(),
            "symbol": opp.symbol,
            "asset_class": opp.asset_class.value,
            "type": trade_type,
            "strategy": opp.strategy,
            "side": side,
            # Entry details (keep both 'price' and 'entry_price' for frontend compatibility)
            "price": trade_price,  # Legacy field for frontend
            "entry_price": trade_price,
            "size": trade_size,
            # Exit details (populated when position closes)
            "status": "open",  # open, closed, stopped, target_hit
            "exit_price": None,
            "exit_timestamp": None,
            "close_reason": None,
            # P&L tracking
            "realized_pnl": None,
            "realized_pnl_pct": None,
            "duration_minutes": None,
            # ML/Analysis context
            "score": round(opp.score, 1),
            "ml_confidence": opp.ml_prediction.confidence if opp.ml_prediction else 0,
            "iv_rank": opp.iv_rank,
            "regime": self.market_regime.value,
            "rationale": opp.rationale,
            "live_executed": self.live_trading_enabled,
            "llm_summary": "",  # Will be populated async
        }

        # Generate LLM summary asynchronously (non-blocking)
        async def generate_summary():
            try:
                analyst = get_quant_analyst()
                summary = await analyst.generate_trade_summary(trade_record)
                trade_record["llm_summary"] = summary
            except Exception as e:
                logger.debug(f"LLM summary generation failed: {e}")
                trade_record["llm_summary"] = f"{opp.strategy} - {opp.rationale[:80] if opp.rationale else 'ML signal'}"

        # Schedule async summary generation
        asyncio.create_task(generate_summary())

        self.trade_history.append(trade_record)

        # Log trade to activity logger (async, non-blocking)
        async def log_trade_activity():
            await self.activity_logger.log_trade(
                subtype=EventSubtype.SUBMIT,
                symbol=opp.symbol,
                asset_class=opp.asset_class.value,
                message=f"Trade executed: {side.upper()} {opp.symbol} via {trade_type}",
                broker="live" if self.live_trading_enabled else "paper",
                value=trade_size,
                details={
                    "trade_id": trade_id,
                    "strategy": opp.strategy,
                    "entry_price": trade_price,
                    "size": trade_size,
                    "score": opp.score,
                    "ml_confidence": opp.ml_prediction.confidence if opp.ml_prediction else 0,
                    "iv_rank": opp.iv_rank,
                    "regime": self.market_regime.value,
                    "rationale": opp.rationale[:200] if opp.rationale else None,
                }
            )

        asyncio.create_task(log_trade_activity())

        return trade_id

    def _update_trade_closed(
        self,
        trade_id: str,
        exit_price: float,
        realized_pnl: float,
        close_reason: str,
    ):
        """Update a trade record when position is closed."""
        for trade in self.trade_history:
            if trade.get("id") == trade_id:
                now = datetime.now()
                entry_time = datetime.fromisoformat(trade["timestamp"])
                duration_minutes = (now - entry_time).total_seconds() / 60

                trade["status"] = "closed"
                trade["exit_price"] = round(exit_price, 4)
                trade["exit_timestamp"] = now.isoformat()
                trade["close_reason"] = close_reason
                trade["realized_pnl"] = round(realized_pnl, 2)
                trade["realized_pnl_pct"] = round(realized_pnl / trade["size"] * 100, 2) if trade["size"] else 0
                trade["duration_minutes"] = round(duration_minutes, 1)

                # Log trade close to activity logger
                async def log_close():
                    emoji = "profit" if realized_pnl >= 0 else "loss"
                    await self.activity_logger.log_trade(
                        subtype=EventSubtype.FILL,
                        symbol=trade["symbol"],
                        asset_class=trade["asset_class"],
                        message=f"Trade closed: {trade['symbol']} {close_reason} | P&L: ${realized_pnl:+,.2f}",
                        broker="live" if trade["live_executed"] else "paper",
                        value=realized_pnl,
                        details={
                            "trade_id": trade_id,
                            "entry_price": trade["entry_price"],
                            "exit_price": exit_price,
                            "realized_pnl": realized_pnl,
                            "realized_pnl_pct": trade["realized_pnl_pct"],
                            "duration_minutes": duration_minutes,
                            "close_reason": close_reason,
                        }
                    )

                asyncio.create_task(log_close())
                break

    def get_trade_log(self, limit: int = 50) -> List[Dict]:
        """Get formatted trade log for display."""
        return sorted(
            self.trade_history[-limit:],
            key=lambda x: x.get("timestamp", ""),
            reverse=True
        )

    async def _execute_live_trade(self, opp: Opportunity) -> bool:
        """Execute a trade on live exchanges via broker manager."""
        if not self.live_trading_enabled or not self.broker_manager:
            return False

        try:
            symbol = opp.symbol
            side = "buy" if "Long" in opp.strategy or "Buy" in opp.strategy or "Call" in opp.strategy else "sell"
            position_size = min(5000, self.initial_capital * 0.05)  # 5% max per position

            if opp.asset_class in [AssetClass.STOCK_OPTIONS, AssetClass.ETF_OPTIONS, AssetClass.COMMODITY_OPTIONS]:
                # CRITICAL: Double-check market hours for stock-based assets
                if not is_market_open():
                    self._add_commentary(
                        f"⛔ LIVE BLOCKED: {opp.symbol} - stock market CLOSED",
                        "execution"
                    )
                    return False
                # For options, we trade the underlying for now
                # TODO: Integrate with options broker when available
                underlying = symbol.replace("-CALL", "").replace("-PUT", "").split("-")[0]
                if self.broker_manager.alpaca and self.broker_manager.alpaca._connected:
                    quote = await self.broker_manager.alpaca.get_quote(underlying)
                    price = quote.get("mid", 0)
                    if price > 0:
                        quantity = int(position_size / price)
                        if quantity > 0:
                            order = await self.broker_manager.submit_stock_order(
                                symbol=underlying,
                                quantity=quantity,
                                side=side,
                            )
                            self._add_commentary(
                                f"📈 LIVE ORDER: {order.side.upper()} {order.quantity} {order.symbol} "
                                f"@ {order.order_type} | Status: {order.status}",
                                "execution"
                            )
                            return True

            elif opp.asset_class == AssetClass.CRYPTO_PERPETUAL:
                crypto_symbol = symbol.replace("-PERP", "")
                if self.broker_manager.binance and self.broker_manager.binance._connected:
                    price = await self.broker_manager.get_live_price(crypto_symbol, "crypto_futures")
                    if price > 0:
                        quantity = position_size / price
                        order = await self.broker_manager.submit_crypto_order(
                            symbol=crypto_symbol,
                            quantity=quantity,
                            side=side,
                            is_futures=True,
                        )
                        self._add_commentary(
                            f"🔥 LIVE FUTURES ORDER: {order.side.upper()} {order.quantity:.6f} {order.symbol} "
                            f"@ {order.order_type} | Status: {order.status}",
                            "execution"
                        )
                        return True

            elif opp.asset_class == AssetClass.CRYPTO_OPTIONS:
                # Crypto options executed as spot for now
                base = symbol.split("-")[0]
                if self.broker_manager.binance and self.broker_manager.binance._connected:
                    price = await self.broker_manager.get_live_price(base, "crypto")
                    if price > 0:
                        quantity = position_size / price
                        order = await self.broker_manager.submit_crypto_order(
                            symbol=base,
                            quantity=quantity,
                            side=side,
                            is_futures=False,
                        )
                        self._add_commentary(
                            f"💰 LIVE SPOT ORDER: {order.side.upper()} {order.quantity:.6f} {order.symbol} "
                            f"@ {order.order_type} | Status: {order.status}",
                            "execution"
                        )
                        return True

        except Exception as e:
            logger.error(f"Live trade execution failed: {e}")
            self._add_commentary(
                f"⚠️ LIVE TRADE FAILED: {opp.symbol} - {str(e)}",
                "error"
            )

        return False

    def _has_position(self, symbol: str) -> bool:
        """Check if already have a position in this symbol."""
        for pos in self.engine.positions.values():
            if pos.symbol == symbol:
                return True

        for pos in self.engine.crypto_positions.values():
            if symbol in pos.symbol:
                return True

        return False

    # ===================
    # BOT LIFECYCLE
    # ===================

    async def start(self):
        """Start the Master Quant Bot."""
        if self.is_running:
            return

        self.is_running = True
        await self.engine.start()

        self._add_commentary(
            "🚀 MASTER QUANT BOT STARTED | "
            "ML Models Active: DQN, PPO, LSTM, Transformer, HMM, VAE, GARCH | "
            "Scanning all markets...",
            "system"
        )

        # Log startup to activity logger
        await self.activity_logger.log_lifecycle(
            subtype=EventSubtype.START,
            message=f"Master Quant Bot started with ${self.initial_capital:,.0f} capital, mode={self.mode.value}",
            details={
                "capital": self.initial_capital,
                "mode": self.mode.value,
                "ml_models": ["DQN", "PPO", "LSTM", "Transformer", "HMM", "VAE", "GARCH"],
                "asset_classes": [ac.value for ac in AssetClass],
            }
        )

        self._task = asyncio.create_task(self._run_loop())

    async def stop(self):
        """Stop the Master Quant Bot."""
        self.is_running = False

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        await self.engine.stop()

        self._add_commentary(
            f"🛑 MASTER BOT STOPPED | "
            f"Total RL Training Steps: {self.analytics.training_step} | "
            f"Episodes: {len(self.analytics.episode_rewards)}",
            "system"
        )

        # Log shutdown to activity logger
        await self.activity_logger.log_lifecycle(
            subtype=EventSubtype.STOP,
            message=f"Master Quant Bot stopped after {self.analytics.training_step} RL training steps",
            details={
                "rl_training_steps": self.analytics.training_step,
                "episodes_completed": len(self.analytics.episode_rewards),
                "final_pnl": self.engine.total_pnl,
                "trades_executed": len(self.trade_history),
            }
        )

    async def _run_loop(self):
        """Main trading loop with RL training."""
        scan_interval = 60
        position_check_interval = 30
        rl_train_interval = 10
        live_price_update_interval = 300  # Update live prices every 5 minutes

        last_scan = datetime.min
        last_position_check = datetime.min
        last_rl_train = datetime.min
        last_price_update = datetime.min

        # Load real market data on first run
        await self._load_real_market_data()

        while self.is_running:
            try:
                now = datetime.now()

                # Full market scan
                if (now - last_scan).seconds >= scan_interval:
                    await self._assess_market_regime()
                    await self._scan_all_markets()
                    await self._execute_best_opportunities()
                    last_scan = now

                # Position management
                if (now - last_position_check).seconds >= position_check_interval:
                    await self._manage_positions()
                    last_position_check = now

                # RL training (compute rewards and train)
                if (now - last_rl_train).seconds >= rl_train_interval:
                    await self._train_rl_models()
                    last_rl_train = now

                # Update live prices from Binance
                if (now - last_price_update).seconds >= live_price_update_interval:
                    await self._update_live_prices()
                    last_price_update = now

                await asyncio.sleep(5)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in master bot loop: {e}")
                # Log error to activity logger
                await self.activity_logger.log_error(
                    subtype=EventSubtype.EXCEPTION,
                    message=f"Error in bot main loop: {str(e)[:200]}",
                    details={
                        "error_type": type(e).__name__,
                        "error_message": str(e),
                    }
                )
                await asyncio.sleep(10)

    async def _manage_positions(self):
        """Manage positions with RL-informed decisions."""
        await self.engine._check_exits()
        await self.engine._update_positions()

        for pos_id, pos in list(self.engine.crypto_positions.items()):
            pos.current_price = await self.engine._get_crypto_price(pos.symbol)

            # Skip if no valid price
            if pos.current_price <= 0:
                continue

            # Minimum hold time before allowing stop/take-profit (prevent instant closes)
            MIN_HOLD_MINUTES = 2
            opened_at = getattr(pos, 'opened_at', None)
            if opened_at:
                hold_time = (datetime.now() - opened_at).total_seconds() / 60
                if hold_time < MIN_HOLD_MINUTES:
                    continue  # Don't check stops yet, position too new

            # Check stop loss / take profit
            close_reason = None
            if pos.side == "long":
                if pos.current_price <= pos.stop_loss:
                    close_reason = "Stop loss hit"
                elif pos.current_price >= pos.take_profit:
                    close_reason = "Take profit hit"
            else:
                if pos.current_price >= pos.stop_loss:
                    close_reason = "Stop loss hit"
                elif pos.current_price <= pos.take_profit:
                    close_reason = "Take profit hit"

            if close_reason:
                # Calculate P&L before closing
                realized_pnl = pos.calculate_pnl()
                exit_price = pos.current_price
                trade_id = getattr(pos, 'trade_id', None)

                # Close the position
                await self.engine.close_crypto_perpetual(pos_id, close_reason)

                # Update trade record with exit details
                if trade_id:
                    self._update_trade_closed(
                        trade_id=trade_id,
                        exit_price=exit_price,
                        realized_pnl=realized_pnl,
                        close_reason=close_reason,
                    )

    async def _train_rl_models(self):
        """Train RL models with current market feedback."""
        # Compute reward based on P&L change
        current_pnl = self.engine.total_pnl
        if hasattr(self, '_last_pnl'):
            reward = (current_pnl - self._last_pnl) / self.initial_capital * 100
        else:
            reward = 0
        self._last_pnl = current_pnl

        # Sharpe-based reward shaping
        if len(self.daily_pnl) >= 20:
            recent_returns = [p[1] for p in self.daily_pnl[-20:]]
            if np.std(recent_returns) > 0:
                sharpe_component = np.mean(recent_returns) / np.std(recent_returns) * 0.1
                reward += sharpe_component

        # Update RL if we have a previous state
        if self.last_state is not None and self.last_action is not None:
            # Construct current state
            current_state = self.analytics._construct_state("SPY", {"vix": self.vix_level})

            # Train step
            self.analytics.train_rl_step(
                state=self.last_state,
                action=self.last_action,
                reward=reward,
                next_state=current_state,
                done=False,
            )

            self.episode_reward += reward

        # Record daily P&L
        self.daily_pnl.append((datetime.now(), current_pnl))

    # ===================
    # STATUS & GETTERS
    # ===================

    def _add_commentary(self, message: str, category: str):
        """Add commentary for UI."""
        self.commentary.append({
            "timestamp": datetime.now().isoformat(),
            "message": message,
            "category": category,
        })
        if len(self.commentary) > 100:
            self.commentary = self.commentary[-100:]

        self.engine._add_commentary(message, category)

    @property
    def capital(self) -> float:
        """Get current capital (for API compatibility)."""
        return self.initial_capital

    def get_status(self) -> Dict:
        """Get comprehensive bot status with ML metrics."""
        engine_status = self.engine.get_status()

        # Get training status
        meets_req, training_reason = self.model_pretrainer.meets_training_requirements()
        training_metrics = self.model_pretrainer.training_metrics

        return {
            "is_running": self.is_running,
            "mode": self.mode.value,
            "market_regime": self.market_regime.value,
            "regime_confidence": round(self.regime_confidence, 2),
            "vix_level": round(self.vix_level, 1),
            "initial_capital": self.initial_capital,
            "cash": engine_status["cash"],
            "total_value": engine_status["total_value"],
            "total_pnl": engine_status["total_pnl"],
            "total_pnl_pct": engine_status["total_pnl_pct"],
            "positions": {
                "options": engine_status["options_positions"],
                "crypto": engine_status["crypto_positions"],
                "total": engine_status["positions_count"],
            },
            "allocations": {
                ac.value: round(alloc * 100, 1)
                for ac, alloc in self.current_allocations.items()
            },
            "ml_metrics": {
                "rl_training_steps": self.analytics.training_step,
                "dqn_epsilon": round(self.analytics.dqn.epsilon, 4),
                "episode_reward": round(self.episode_reward, 2),
                "total_episodes": len(self.analytics.episode_rewards),
                "hmm_fitted": self.analytics.hmm_fitted,
                "garch_fitted": self.analytics.garch_fitted,
                "real_data_loaded": getattr(self, '_real_data_loaded', False),
                "data_source": "Binance.US" if getattr(self, '_real_data_loaded', False) else "Synthetic",
            },
            # NEW: Training status
            "training_status": {
                "models_trained": self.models_trained,
                "meets_requirements": meets_req,
                "status_message": training_reason,
                "epochs_completed": training_metrics.epochs_completed,
                "total_samples": training_metrics.total_samples,
                "checkpoint_exists": (CHECKPOINT_DIR / "model_checkpoint.pkl").exists(),
            },
            "last_scan": self.last_full_scan.isoformat() if self.last_full_scan else None,
            "opportunities_count": len(self.opportunities),
            "risk_summary": engine_status["risk_summary"],
            "live_trading_enabled": self.live_trading_enabled,
            "broker_connected": self.broker_manager is not None,
        }

    def get_opportunities(self, limit: int = 20) -> List[Dict]:
        """Get ML-scored opportunities."""
        return [opp.to_dict() for opp in self.opportunities[:limit]]

    def get_all_positions(self) -> Dict:
        """Get all positions across all asset classes."""
        return {
            "options_positions": self.engine.get_positions(),
            "crypto_positions": self.engine.get_crypto_positions(),
        }

    def get_commentary(self, limit: int = 50) -> List[Dict]:
        """Get bot commentary."""
        return self.commentary[-limit:]

    def get_performance(self) -> Dict:
        """Get performance metrics with ML analytics."""
        engine_perf = self.engine.get_performance()

        # Compute Bayesian Sharpe if we have enough data
        sharpe_mean, sharpe_std = 0, 0.5
        if len(self.daily_pnl) >= 30:
            returns = np.diff([p[1] for p in self.daily_pnl])
            sharpe_mean, sharpe_std, _ = self.analytics.bayesian.estimate_sharpe_ratio(returns)

        return {
            **engine_perf,
            "market_regime": self.market_regime.value,
            "vix_level": round(self.vix_level, 1),
            "opportunities_scanned": len(self.opportunities),
            "allocation_efficiency": sum(self.current_allocations.values()) * 100,
            "ml_performance": {
                "bayesian_sharpe": round(sharpe_mean, 3),
                "sharpe_uncertainty": round(sharpe_std, 3),
                "rl_training_steps": self.analytics.training_step,
                "avg_episode_reward": round(np.mean(self.analytics.episode_rewards[-10:]), 2) if self.analytics.episode_rewards else 0,
                "dqn_losses": round(np.mean(self.analytics.dqn.losses[-100:]), 4) if self.analytics.dqn.losses else 0,
            },
        }

    def get_ml_analysis(self, symbol: str) -> Dict:
        """Get detailed ML analysis for a symbol."""
        prediction = self.analytics.get_ml_prediction(symbol)
        risk = self.analytics.compute_risk_metrics(symbol)

        return {
            "symbol": symbol,
            "prediction": {
                "action": prediction.action_name,
                "confidence": round(prediction.confidence, 3),
                "dqn_q_value": round(prediction.dqn_q_value, 3),
                "ppo_prob": round(prediction.ppo_prob, 3),
                "lstm_pred": round(prediction.lstm_pred, 5),
                "transformer_pred": round(prediction.transformer_pred, 5),
                "ensemble_agreement": round(prediction.ensemble_agreement, 3),
            },
            "regime": {
                "current": prediction.regime,
                "confidence": round(prediction.regime_confidence, 3),
            },
            "factors": {k: round(v, 4) for k, v in prediction.factors.items()},
            "risk": {
                "var_95": round(risk.var_95, 4),
                "var_99": round(risk.var_99, 4),
                "cvar_95": round(risk.cvar_95, 4),
                "volatility_forecast": round(risk.volatility_forecast, 4),
                "sharpe_ratio": round(risk.sharpe_ratio, 3),
                "sharpe_std_error": round(risk.sharpe_std_error, 3),
                "max_drawdown": round(risk.max_drawdown, 4),
                "tail_index": round(risk.tail_index, 2),
            },
        }


# Singleton instance
_master_bot: Optional[MasterQuantBot] = None


def get_master_bot() -> MasterQuantBot:
    """Get or create the Master Quant Bot singleton."""
    global _master_bot
    if _master_bot is None:
        _master_bot = MasterQuantBot()
    return _master_bot


def create_master_bot(
    capital: float = 100000,
    mode: str = "balanced"
) -> MasterQuantBot:
    """Create a new Master Quant Bot instance."""
    global _master_bot
    _master_bot = MasterQuantBot(initial_capital=capital, mode=mode)
    return _master_bot


async def run_training_pipeline(
    days_of_data: int = 180,
    training_epochs: int = 40  # Optimized for ~1 hour training
) -> Dict:
    """
    Run the full ML training pipeline.

    This should be run BEFORE starting live/paper trading to ensure
    models are properly trained on historical data.

    Args:
        days_of_data: Number of days of historical data to download
        training_epochs: Number of training epochs

    Returns:
        Training results including backtest performance
    """
    from .backtester import run_full_training_pipeline

    logger.info("="*60)
    logger.info("STARTING ML TRAINING PIPELINE")
    logger.info("="*60)

    result = await run_full_training_pipeline(
        days_of_data=days_of_data,
        training_epochs=training_epochs
    )

    # Update the master bot's training status
    global _master_bot
    if _master_bot is not None:
        _master_bot.model_pretrainer.load_checkpoints()
        meets_req, reason = _master_bot.model_pretrainer.meets_training_requirements()
        _master_bot.models_trained = meets_req

        if meets_req:
            _master_bot._add_commentary(
                "✅ Training complete! Models are ready for intelligent trading.",
                "system"
            )
        else:
            _master_bot._add_commentary(
                f"⚠️ Training incomplete: {reason}",
                "system"
            )

    return result


async def run_quick_backtest(
    days: int = 90
) -> Dict:
    """
    Run a quick backtest with current model state.

    Returns backtest results without full retraining.
    """
    from .backtester import (
        get_data_downloader,
        get_model_pretrainer,
        get_backtester,
    )

    downloader = get_data_downloader()
    pretrainer = get_model_pretrainer()
    backtester = get_backtester()

    # Load data
    historical_data = downloader.load_all_from_disk()
    if not historical_data:
        return {"error": "No historical data available. Run training pipeline first."}

    # Run backtest
    result = backtester.run_backtest(historical_data, pretrainer)

    return result.to_dict()
