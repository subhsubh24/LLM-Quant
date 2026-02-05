"""
FeatureStore — single source of truth for market data, indicators, and ML state.

Replaces the duplicated price_history / return_history / indicator computation
that previously lived independently in MasterQuantBot, QuantAnalyticsEngine,
and QuantBot.

Owns:
  - Raw price & return arrays (per symbol)
  - Technical indicators (RSI, MACD, Bollinger, momentum, z-score)
  - ML model ensemble (DQN, PPO, LSTM, Transformer, VAE)
  - Statistical models (HMM, GARCH, EVT, Bayesian, Copula, Factor)
  - Market regime detection
  - Cointegration state for pairs trading
  - Funding rate cache

All strategies consume the FeatureStore read-only.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np

from ..ml_models import (
    DQN,
    PPOAgent,
    LSTM,
    TransformerPredictor,
    MarketRegimeVAE,
    EnsemblePredictor,
    create_dqn_agent,
    create_ppo_agent,
)
from ..quant_analytics import (
    BayesianEstimator,
    GaussianHMM,
    GARCH,
    StudentTCopula,
    ExtremeValueAnalyzer,
    FactorModel,
    SignalGenerator,
    WalkForwardOptimizer,
)
from ..master_bot import MLPrediction, RiskMetrics, MarketRegime

logger = logging.getLogger(__name__)

# ────────────────────────────────────────────────────────────────
# Technical-indicator helpers (computed once, shared by all strategies)
# ────────────────────────────────────────────────────────────────

def _rsi(returns: np.ndarray, period: int = 14) -> float:
    """Relative Strength Index from return series."""
    r = returns[-period:]
    gains = np.where(r > 0, r, 0)
    losses = np.where(r < 0, -r, 0)
    avg_gain = np.mean(gains)
    avg_loss = np.mean(losses)
    rs = avg_gain / (avg_loss + 1e-8)
    return float(100 - 100 / (1 + rs))


def _bollinger_position(prices: np.ndarray, period: int = 20) -> float:
    """Position within Bollinger Bands (0 = lower, 1 = upper)."""
    ma = np.mean(prices[-period:])
    std = np.std(prices[-period:])
    return float((prices[-1] - ma) / (2 * std + 1e-8))


def _momentum(prices: np.ndarray, lookback: int = 20) -> float:
    """Simple momentum: current / past - 1."""
    ref = max(prices[-lookback], 1e-8)
    return float(prices[-1] / ref - 1)


# ────────────────────────────────────────────────────────────────
# FeatureStore
# ────────────────────────────────────────────────────────────────

STATE_DIM = 64
N_ACTIONS = 5


class FeatureStore:
    """
    Centralised market state consumed by all strategies.

    Usage::

        store = FeatureStore()
        store.update_price_history("BTC", prices_array)
        pred  = store.get_ml_prediction("BTC")
        risk  = store.get_risk_metrics("BTC")
        state = store.get_state_vector("BTC")
    """

    def __init__(self, lookback_days: int = 252):
        self.lookback_days = lookback_days

        # ── Raw data ──────────────────────────────────────────
        self.price_history: Dict[str, np.ndarray] = {}
        self.return_history: Dict[str, np.ndarray] = {}

        # ── ML models ─────────────────────────────────────────
        # (match QuantAnalyticsEngine constructor signatures exactly)
        self.dqn: DQN = create_dqn_agent(
            state_dim=STATE_DIM, action_dim=N_ACTIONS,
            hidden_dims=[512, 256, 128],
            lr=0.0001,
        )
        self.ppo: PPOAgent = create_ppo_agent(
            state_dim=STATE_DIM, action_dim=N_ACTIONS,
            hidden_dims=[256, 256],
        )
        self.lstm = LSTM(input_dim=16, hidden_dim=128)
        self.transformer = TransformerPredictor(
            input_dim=16, d_model=64, n_heads=4, n_layers=3,
        )
        self.regime_vae = MarketRegimeVAE(input_dim=32, latent_dim=8)
        self.ensemble = EnsemblePredictor(
            state_dim=STATE_DIM, action_dim=N_ACTIONS, seq_len=60,
        )

        # ── Statistical models ────────────────────────────────
        self.bayesian = BayesianEstimator(n_samples=5000)
        self.hmm = GaussianHMM(n_states=3, n_iter=100)
        self.garch = GARCH(p=1, q=1, model_type="garch")
        self.egarch = GARCH(p=1, q=1, model_type="egarch")
        self.copula = StudentTCopula(df=5)
        self.evt = ExtremeValueAnalyzer(threshold_quantile=0.95)
        self.factor_model = FactorModel(
            factors=["market", "size", "value", "momentum", "volatility", "quality"],
        )
        self.signal_generator = SignalGenerator()
        self.walk_forward = WalkForwardOptimizer(
            in_sample_periods=252, out_of_sample_periods=63, n_windows=4,
        )

        # ── Fitting flags ─────────────────────────────────────
        self.hmm_fitted = False
        self.garch_fitted = False

        # ── RL bookkeeping ────────────────────────────────────
        self.training_step = 0
        self.episode_rewards: List[float] = []

        # ── Regime state ──────────────────────────────────────
        self.market_regime = MarketRegime.RANGE_BOUND
        self.regime_confidence: float = 0.5
        self.vix_level: float = 18.0

        # ── Cointegration cache (for pairs trading) ──────────
        self.cointegrated_pairs: Dict[Tuple[str, str], Dict] = {}
        self.spread_history: Dict[Tuple[str, str], List[float]] = {}
        self._last_coint_scan: datetime = datetime.min

        # ── Funding-rate cache ────────────────────────────────
        self._funding_rate_cache: Dict[str, Tuple[float, datetime]] = {}
        self._funding_rate_cache_ttl = timedelta(minutes=30)

        logger.info("FeatureStore initialised (ML + stats suite)")

    # ──────────────────────────────────────────────────────────
    # Data ingestion
    # ──────────────────────────────────────────────────────────

    def update_price_history(self, symbol: str, prices: np.ndarray):
        """Update price & return history for *symbol*."""
        self.price_history[symbol] = prices
        if len(prices) > 1:
            denom = prices[:-1]
            safe_denom = np.where(denom > 0, denom, 1.0)
            returns = np.diff(prices) / safe_denom
            self.return_history[symbol] = np.nan_to_num(
                returns, nan=0.0, posinf=0.0, neginf=0.0,
            )

    # ──────────────────────────────────────────────────────────
    # Technical indicators (computed, not stored)
    # ──────────────────────────────────────────────────────────

    def get_indicators(self, symbol: str) -> Dict[str, float]:
        """Return a dict of common indicators for *symbol*."""
        out: Dict[str, float] = {}
        returns = self.return_history.get(symbol)
        prices = self.price_history.get(symbol)
        if returns is None or prices is None or len(returns) < 20:
            return out

        out["rsi"] = _rsi(returns)
        out["bb_position"] = _bollinger_position(prices)
        out["momentum_5d"] = _momentum(prices, 5)
        out["momentum_20d"] = _momentum(prices, 20)
        if len(prices) >= 60:
            out["momentum_60d"] = _momentum(prices, 60)
        out["vol_20d"] = float(np.std(returns[-20:]) * np.sqrt(252))
        out["vol_5d"] = float(np.std(returns[-5:]) * np.sqrt(252))
        out["vol_ratio"] = out["vol_5d"] / (out["vol_20d"] + 1e-8)
        out["return_zscore"] = float(
            (returns[-1] - np.mean(returns[-20:])) / (np.std(returns[-20:]) + 1e-8)
        )
        return out

    # ──────────────────────────────────────────────────────────
    # 64-dim RL state vector
    # ──────────────────────────────────────────────────────────

    def get_state_vector(
        self,
        symbol: str,
        additional_features: Optional[Dict] = None,
    ) -> np.ndarray:
        """Construct 64-dim state vector for RL agents."""
        state = np.zeros(STATE_DIM)
        returns = self.return_history.get(symbol)
        prices = self.price_history.get(symbol)

        if returns is not None and len(returns) >= 20:
            state[0] = returns[-1]
            state[1] = np.mean(returns[-5:])
            state[2] = np.mean(returns[-20:])
            state[3] = np.std(returns[-20:]) * np.sqrt(252)
            state[4] = np.sum(returns[-5:])
            state[5] = np.sum(returns[-20:])
            state[6] = (returns[-1] - np.mean(returns[-20:])) / (np.std(returns[-20:]) + 1e-8)
            state[7] = np.percentile(returns, 95) if len(returns) >= 100 else 0
            state[8] = np.percentile(returns, 5) if len(returns) >= 100 else 0
            state[9] = (
                np.corrcoef(returns[-20:], np.arange(20))[0, 1]
                if len(returns) >= 20 else 0
            )

        if returns is not None and len(returns) >= 60:
            state[10] = np.std(returns[-5:]) * np.sqrt(252)
            state[11] = np.std(returns[-20:]) * np.sqrt(252)
            state[12] = np.std(returns[-60:]) * np.sqrt(252)
            state[13] = state[10] / (state[12] + 1e-8)
            if self.garch_fitted:
                try:
                    forecast = self.garch.forecast(returns[-60:], horizon=5)
                    state[14] = forecast.current_vol
                    state[15] = np.mean(forecast.forecast_vol)
                except Exception:
                    pass

        if prices is not None and len(prices) >= 20:
            state[20] = _rsi(self.return_history.get(symbol, np.zeros(14)))
            state[21] = _bollinger_position(prices)
            state[22] = prices[-1] / max(prices[-5], 1e-8) - 1
            state[23] = prices[-1] / max(prices[-20], 1e-8) - 1
            if len(prices) >= 60:
                state[24] = prices[-1] / max(prices[-60], 1e-8) - 1

        if additional_features:
            state[35] = additional_features.get("position_size", 0)
            state[36] = additional_features.get("unrealized_pnl", 0)
            state[37] = additional_features.get("delta", 0)
            state[38] = additional_features.get("gamma", 0)
            state[39] = additional_features.get("theta", 0)
            state[40] = additional_features.get("vega", 0)
            state[45] = additional_features.get("vix", 18) / 100
            state[46] = additional_features.get("market_return", 0)
            state[47] = additional_features.get("sector_return", 0)

        if returns is not None and len(returns) >= 30:
            r30 = returns[-30:]
            try:
                r_input = (
                    r30.reshape(1, -1)[:, :32]
                    if len(r30) >= 32
                    else np.pad(r30, (0, 32 - len(r30))).reshape(1, -1)
                )
                regime_id, regime_probs, latent = self.regime_vae.detect_regime(r_input)
                state[55:59] = regime_probs
                state[59:63] = latent[:4] if len(latent) >= 4 else latent
            except Exception:
                pass

        # Final sanitisation
        state = np.nan_to_num(state, nan=0.0, posinf=0.0, neginf=0.0)
        state = np.clip(state, -10, 10)
        return state

    # ──────────────────────────────────────────────────────────
    # ML ensemble prediction
    # ──────────────────────────────────────────────────────────

    def get_ml_prediction(
        self,
        symbol: str,
        additional_features: Optional[Dict] = None,
    ) -> MLPrediction:
        """Unified ML prediction combining DQN, PPO, LSTM, Transformer, VAE."""
        state = self.get_state_vector(symbol, additional_features)

        # DQN
        dqn_action = self.dqn.select_action(state, training=False)
        dqn_q_values = self.dqn._forward(state.reshape(1, -1), self.dqn._q_network)
        dqn_q = float(np.max(dqn_q_values))

        # PPO
        ppo_action, ppo_log_prob, ppo_value = self.ppo.select_action(state)
        ppo_probs = self.ppo._forward_actor(state.reshape(1, -1)).flatten()

        # LSTM
        lstm_pred = 0.0
        if symbol in self.return_history and len(self.return_history[symbol]) >= 60:
            try:
                self.lstm.reset_state()
                r60 = np.array(self.return_history[symbol][-60:]).flatten()
                lstm_input = np.pad(r60.reshape(-1, 1), ((0, 0), (0, 15)), mode="constant")
                lstm_out = self.lstm.forward(lstm_input)
                lstm_pred = float(lstm_out[0, -1, 0])
            except Exception:
                pass

        # Transformer
        transformer_pred = 0.0
        if symbol in self.return_history and len(self.return_history[symbol]) >= 60:
            try:
                r60 = np.array(self.return_history[symbol][-60:]).flatten()
                t_input = np.pad(r60.reshape(-1, 1), ((0, 0), (0, 15)), mode="constant")
                transformer_pred = self.transformer.predict(t_input)
            except Exception:
                pass

        # Regime
        regime, regime_confidence = "Unknown", 0.5
        if symbol in self.return_history and len(self.return_history[symbol]) >= 32:
            try:
                r32 = self.return_history[symbol][-32:]
                rid, rp, _ = self.regime_vae.detect_regime(r32.reshape(1, -1))
                regime = self.regime_vae.get_regime_name(rid)
                regime_confidence = float(np.max(rp))
            except Exception:
                pass

        # Factors
        factors: Dict[str, float] = {}
        if symbol in self.return_history and len(self.return_history[symbol]) >= 60:
            try:
                fe = self.factor_model.fit(self.return_history[symbol][-60:])
                factors = fe.betas
                factors["alpha"] = fe.alpha
            except Exception:
                pass

        # Ensemble vote (5-action → 3-action)
        action_votes = np.zeros(3)
        dqn_vote = 0 if dqn_action in [0, 1] else (2 if dqn_action in [3, 4] else 1)
        ppo_vote = 0 if ppo_action in [0, 1] else (2 if ppo_action in [3, 4] else 1)
        lstm_vote = 2 if lstm_pred > 0.005 else (0 if lstm_pred < -0.005 else 1)
        trans_vote = 2 if transformer_pred > 0.005 else (0 if transformer_pred < -0.005 else 1)

        weights = [0.30, 0.25, 0.20, 0.25]
        for v, w in zip([dqn_vote, ppo_vote, lstm_vote, trans_vote], weights):
            action_votes[v] += w

        final_action = int(np.argmax(action_votes))
        action_names = ["sell", "hold", "buy"]
        confidence = float(action_votes[final_action])
        agreement = (action_votes[final_action] - 0.25) / 0.75

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

    # ──────────────────────────────────────────────────────────
    # Risk metrics
    # ──────────────────────────────────────────────────────────

    def get_risk_metrics(self, symbol: str) -> RiskMetrics:
        """Compute comprehensive risk metrics using EVT, GARCH, Bayesian."""
        if symbol not in self.return_history or len(self.return_history[symbol]) < 60:
            return RiskMetrics(
                var_95=0.02, var_99=0.03, cvar_95=0.03, cvar_99=0.05,
                volatility_forecast=0.20, tail_index=3.0, max_drawdown=0.10,
                sharpe_ratio=0.0, sharpe_std_error=0.5, correlation_to_market=0.5,
            )

        returns = self.return_history[symbol]
        losses = -returns

        evt_analysis = self.evt.analyze(
            losses[losses > 0] if np.any(losses > 0) else np.abs(losses)
        )

        vol_forecast = 0.20
        try:
            gf = self.garch.forecast(returns[-60:], horizon=5)
            vol_forecast = float(np.mean(gf.forecast_vol))
            self.garch_fitted = True
        except Exception:
            vol_forecast = float(np.std(returns) * np.sqrt(252))

        sharpe_mean, sharpe_std, _ = self.bayesian.estimate_sharpe_ratio(
            returns[-252:] if len(returns) >= 252 else returns
        )

        cumulative = np.cumprod(1 + returns)
        running_max = np.maximum.accumulate(cumulative)
        drawdowns = (cumulative - running_max) / running_max
        max_dd = float(-np.min(drawdowns))

        corr_to_market = 0.5
        if "SPY" in self.return_history:
            spy = self.return_history["SPY"]
            n = min(len(returns), len(spy))
            if n >= 20:
                c = np.corrcoef(returns[-n:], spy[-n:])[0, 1]
                corr_to_market = 0.0 if np.isnan(c) else float(c)

        # EVT may return 0; fall back to empirical percentiles
        var95 = float(evt_analysis.var_95) if hasattr(evt_analysis, "var_95") else 0.0
        var99 = float(evt_analysis.var_99) if hasattr(evt_analysis, "var_99") else 0.0
        cvar95 = float(evt_analysis.cvar_95) if hasattr(evt_analysis, "cvar_95") else 0.0
        cvar99 = float(evt_analysis.cvar_99) if hasattr(evt_analysis, "cvar_99") else 0.0
        if var95 <= 0:
            var95 = float(np.percentile(losses, 95))
        if var99 <= 0:
            var99 = float(np.percentile(losses, 99))
        if cvar95 <= 0:
            cvar95 = float(np.mean(losses[losses >= np.percentile(losses, 95)])) if np.any(losses >= np.percentile(losses, 95)) else var95
        if cvar99 <= 0:
            cvar99 = float(np.mean(losses[losses >= np.percentile(losses, 99)])) if np.any(losses >= np.percentile(losses, 99)) else var99

        return RiskMetrics(
            var_95=var95 if var95 > 0 else 0.02,
            var_99=var99 if var99 > 0 else 0.03,
            cvar_95=cvar95 if cvar95 > 0 else 0.03,
            cvar_99=cvar99 if cvar99 > 0 else 0.05,
            volatility_forecast=vol_forecast,
            tail_index=float(evt_analysis.tail_index) if hasattr(evt_analysis, "tail_index") else 3.0,
            max_drawdown=max_dd,
            sharpe_ratio=float(sharpe_mean),
            sharpe_std_error=float(sharpe_std),
            correlation_to_market=corr_to_market,
        )

    # ──────────────────────────────────────────────────────────
    # Regime detection
    # ──────────────────────────────────────────────────────────

    def detect_regime_hmm(self, returns: np.ndarray) -> Tuple[int, np.ndarray]:
        """Fit / predict HMM regime on *returns*."""
        if len(returns) < 30:
            return 1, np.array([0.33, 0.34, 0.33])
        try:
            self.hmm.fit(returns.reshape(-1, 1))
            self.hmm_fitted = True
            state = self.hmm.predict(returns[-1:].reshape(-1, 1))
            probs = self.hmm.predict_proba(returns[-1:].reshape(-1, 1)).flatten()
            return int(state[0]), probs
        except Exception:
            return 1, np.array([0.33, 0.34, 0.33])

    def assess_market_regime(self):
        """Update self.market_regime and self.vix_level from SPY data."""
        if "SPY" not in self.return_history:
            return

        spy_returns = self.return_history["SPY"]
        hmm_state, hmm_probs = self.detect_regime_hmm(spy_returns)

        vae_regime, vae_probs = 1, np.array([0.25, 0.25, 0.25, 0.25])
        if len(spy_returns) >= 32:
            try:
                vae_regime, vae_probs, _ = self.regime_vae.detect_regime(
                    spy_returns[-32:].reshape(1, -1)
                )
            except Exception:
                pass

        self.regime_confidence = float((np.max(hmm_probs) + np.max(vae_probs)) / 2)
        actual_vol = (
            float(np.std(spy_returns[-20:]) * np.sqrt(252) * 100)
            if len(spy_returns) >= 20 else 18
        )
        self.vix_level = max(10, min(50, actual_vol + hmm_state * 2))

        if self.vix_level > 25:
            self.market_regime = MarketRegime.HIGH_VOLATILITY
        elif self.vix_level < 14:
            self.market_regime = MarketRegime.LOW_VOLATILITY
        elif vae_regime == 0:
            self.market_regime = MarketRegime.BULL_MARKET
        elif vae_regime == 1:
            self.market_regime = MarketRegime.BEAR_MARKET
        else:
            self.market_regime = MarketRegime.RANGE_BOUND

    # ──────────────────────────────────────────────────────────
    # RL training step
    # ──────────────────────────────────────────────────────────

    def train_rl_step(
        self,
        state: np.ndarray,
        action: int,
        reward: float,
        next_state: np.ndarray,
        done: bool = False,
    ):
        """Single RL training step for DQN + PPO."""
        self.dqn.store_experience(state, action, reward, next_state, done)
        if self.dqn.replay_buffer is not None and len(self.dqn.replay_buffer) >= self.dqn.batch_size:
            self.dqn.train_step()
        self.training_step += 1

    # ──────────────────────────────────────────────────────────
    # Cointegration / stat-arb helpers (shared by PairsTradingStrategy)
    # ──────────────────────────────────────────────────────────

    def adf_test(self, series: np.ndarray) -> Tuple[float, bool]:
        """ADF test for stationarity (numpy-only)."""
        series = np.asarray(series, dtype=float)
        if len(series) < 20:
            return (0.0, False)

        dy = np.diff(series)
        n = len(dy)
        y_lag = series[:-1]
        y_dep = dy[1:]
        X = np.column_stack([np.ones(n - 1), y_lag[1:], dy[:-1]])

        try:
            XtX = X.T @ X
            Xty = X.T @ y_dep
            beta = np.linalg.solve(XtX, Xty)
        except np.linalg.LinAlgError:
            return (0.0, False)

        residuals = y_dep - X @ beta
        s2 = np.sum(residuals ** 2) / (len(y_dep) - X.shape[1])
        try:
            var_beta = s2 * np.linalg.inv(XtX)
        except np.linalg.LinAlgError:
            return (0.0, False)

        se = np.sqrt(max(var_beta[1, 1], 1e-16))
        t_stat = beta[1] / se
        return (float(t_stat), t_stat < -2.86)

    def test_cointegration(
        self, sym_a: str, sym_b: str, min_obs: int = 60,
    ) -> Optional[Dict]:
        """Engle-Granger two-step cointegration test."""
        pa = self.price_history.get(sym_a)
        pb = self.price_history.get(sym_b)
        if pa is None or pb is None:
            return None

        n = min(len(pa), len(pb))
        if n < min_obs:
            return None

        a, b = pa[-n:], pb[-n:]
        X = np.column_stack([np.ones(n), b])
        try:
            beta = np.linalg.lstsq(X, a, rcond=None)[0]
        except np.linalg.LinAlgError:
            return None

        hedge_ratio = beta[1]
        spread = a - beta[0] - hedge_ratio * b
        t_stat, is_coint = self.adf_test(spread)
        if not is_coint:
            return None

        half_life = self.estimate_half_life(spread)
        if half_life < 1 or half_life > 60:
            return None

        result = {
            "sym_a": sym_a,
            "sym_b": sym_b,
            "hedge_ratio": float(hedge_ratio),
            "intercept": float(beta[0]),
            "t_stat": float(t_stat),
            "half_life": float(half_life),
            "is_cointegrated": True,
        }
        self.cointegrated_pairs[(sym_a, sym_b)] = result
        return result

    def estimate_half_life(self, spread: np.ndarray) -> float:
        """OU half-life: ΔS = a + b·S_{t-1}, half_life = -ln(2)/b."""
        spread = np.asarray(spread, dtype=float)
        if len(spread) < 10:
            return 999.0
        ds = np.diff(spread)
        s_lag = spread[:-1]
        X = np.column_stack([np.ones(len(s_lag)), s_lag])
        try:
            beta = np.linalg.lstsq(X, ds, rcond=None)[0]
        except np.linalg.LinAlgError:
            return 999.0
        b = beta[1]
        if b >= 0:
            return 999.0
        return max(float(-np.log(2) / b), 1.0)

    def find_cointegrated_pairs(self, min_obs: int = 60) -> List[Dict]:
        """Scan all tracked symbols for cointegrated pairs (throttled to 4 h)."""
        now = datetime.now()
        if (now - self._last_coint_scan).total_seconds() < 4 * 3600:
            return list(self.cointegrated_pairs.values())

        self._last_coint_scan = now
        symbols = [s for s, p in self.price_history.items() if len(p) >= min_obs]
        found: Dict[Tuple[str, str], Dict] = {}
        for i, sa in enumerate(symbols):
            for sb in symbols[i + 1:]:
                result = self.test_cointegration(sa, sb, min_obs)
                if result:
                    found[(sa, sb)] = result
        self.cointegrated_pairs = found
        return list(found.values())

    def get_spread_zscore(self, sym_a: str, sym_b: str) -> Optional[Dict]:
        """Adaptive z-score for a cointegrated pair's spread."""
        key = (sym_a, sym_b)
        pair_info = self.cointegrated_pairs.get(key)
        if pair_info is None:
            return None

        pa = self.price_history.get(sym_a)
        pb = self.price_history.get(sym_b)
        if pa is None or pb is None:
            return None

        n = min(len(pa), len(pb))
        if n < 20:
            return None

        hedge = pair_info["hedge_ratio"]
        intercept = pair_info["intercept"]
        half_life = pair_info["half_life"]

        spread = pa[-n:] - intercept - hedge * pb[-n:]
        self.spread_history[key] = list(spread[-200:])

        lookback = max(int(2 * half_life), 10)
        lookback = min(lookback, len(spread))
        recent = spread[-lookback:]
        mu = np.mean(recent)
        sigma = np.std(recent)
        if sigma < 1e-10:
            return None

        zscore = float((spread[-1] - mu) / sigma)

        if zscore < -1.0:
            signal = "buy_spread"
        elif zscore > 1.0:
            signal = "sell_spread"
        elif abs(zscore) < 0.5:
            signal = "exit"
        elif abs(zscore) > 4.0:
            signal = "stop"
        else:
            signal = "hold"

        confidence = min(abs(zscore) / 3.0, 1.0)

        return {
            "zscore": zscore,
            "signal": signal,
            "confidence": confidence,
            "half_life": half_life,
            "hedge_ratio": hedge,
            "spread_std": float(sigma),
            "lookback": lookback,
        }

    # ──────────────────────────────────────────────────────────
    # Funding-rate helpers (shared by FundingRateArbStrategy)
    # ──────────────────────────────────────────────────────────

    async def fetch_funding_rate(self, symbol: str) -> float:
        """Fetch real funding rate from Binance with 30-min cache."""
        base = symbol.split("-")[0].replace("USDT", "").replace("/USD", "")
        if base in self._funding_rate_cache:
            rate, ts = self._funding_rate_cache[base]
            if datetime.now() - ts < self._funding_rate_cache_ttl:
                return rate
        try:
            import httpx
            binance_sym = f"{base}USDT"
            url = f"https://fapi.binance.com/fapi/v1/fundingRate?symbol={binance_sym}&limit=1"
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    data = resp.json()
                    if data:
                        rate = float(data[0]["fundingRate"])
                        self._funding_rate_cache[base] = (rate, datetime.now())
                        return rate
        except Exception as e:
            logger.debug(f"Funding rate API failed for {symbol}: {e}")

        fallback = 0.0001
        self._funding_rate_cache[base] = (fallback, datetime.now())
        return fallback

    def get_funding_rate_arb_signal(
        self,
        symbol: str,
        funding_rate: float,
        spot_price: float,
        perp_price: float,
    ) -> Dict:
        """Funding-rate arbitrage signal."""
        basis = (perp_price - spot_price) / spot_price if spot_price > 0 else 0.0
        annual_funding = funding_rate * 3 * 365

        signal, confidence, carry = "neutral", 0.0, 0.0

        if funding_rate > 0.0005:
            signal = "short_perp_long_spot"
            carry = abs(annual_funding)
            confidence = min(abs(funding_rate) / 0.002, 1.0)
        elif funding_rate < -0.0001:
            signal = "long_perp_short_spot"
            carry = abs(annual_funding)
            confidence = min(abs(funding_rate) / 0.001, 1.0)

        return {
            "signal": signal,
            "funding_rate": float(funding_rate),
            "basis": float(basis),
            "annualized_carry": float(carry),
            "confidence": float(confidence),
        }
