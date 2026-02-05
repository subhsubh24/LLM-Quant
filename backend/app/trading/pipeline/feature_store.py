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
    LSTMClassifier,
    TransformerPredictor,
    MarketRegimeVAE,
    EnsemblePredictor,
    Experience,
    Adam,
    create_dqn_agent,
    create_ppo_agent,
)
from ..quant_analytics import (
    BayesianEstimator,
    GaussianHMM,
    GARCH,
    ExtremeValueAnalyzer,
    FactorModel,
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


def _build_seq_features(returns: np.ndarray, n_features: int = 16) -> np.ndarray:
    """Build a rich (seq_len, n_features) matrix from a 1-D return series.

    Instead of zero-padding a single column, compute 16 meaningful per-
    timestep features so the LSTM / Transformer can learn from rich input.

    Features per timestep t:
      0  raw return
      1  |return|  (realised vol proxy)
      2  return²   (quadratic variation)
      3  sign(r) * log(1+|r|)  (log-scaled signed return)
      4  rolling mean  (past 5)
      5  rolling std   (past 5, annualised)
      6  z-score relative to rolling 20
      7  cumulative return from window start
      8  rolling min   (past 5)
      9  rolling max   (past 5)
     10  return acceleration  (Δreturn)
     11  sign of return  (+1 / -1)
     12  rolling positive-return ratio (past 14)
     13  time fraction  (t / seq_len)
     14  distance from running mean
     15  percentile rank within past 20
    """
    T = len(returns)
    out = np.zeros((T, n_features), dtype=np.float64)

    cum = np.cumsum(returns)

    for t in range(T):
        r = returns[t]
        out[t, 0] = r
        out[t, 1] = abs(r)
        out[t, 2] = r * r
        out[t, 3] = np.sign(r) * np.log1p(abs(r))

        # Rolling windows (handle early timesteps gracefully)
        s5 = max(t - 4, 0)
        s14 = max(t - 13, 0)
        s20 = max(t - 19, 0)
        win5 = returns[s5:t + 1]
        win20 = returns[s20:t + 1]
        win14 = returns[s14:t + 1]

        out[t, 4] = np.mean(win5)
        out[t, 5] = np.std(win5) * np.sqrt(252) if len(win5) > 1 else 0.0
        mu20 = np.mean(win20)
        std20 = np.std(win20) + 1e-8
        out[t, 6] = (r - mu20) / std20
        out[t, 7] = cum[t]
        out[t, 8] = np.min(win5)
        out[t, 9] = np.max(win5)
        out[t, 10] = r - returns[t - 1] if t > 0 else 0.0
        out[t, 11] = 1.0 if r >= 0 else -1.0
        out[t, 12] = float(np.mean(win14 > 0))
        out[t, 13] = t / max(T - 1, 1)
        out[t, 14] = r - mu20
        # Percentile rank within past 20
        out[t, 15] = float(np.mean(win20 <= r))

    # Clip extreme values for numerical stability
    np.clip(out, -10, 10, out=out)
    return out


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
        # LSTMClassifier has BPTT + Adam — used for supervised training
        self.lstm_classifier = LSTMClassifier(
            input_dim=16, hidden_dim=128, output_dim=2, lr=0.001,
        )
        self.transformer = TransformerPredictor(
            input_dim=16, d_model=64, n_heads=4, n_layers=3,
        )
        # Transformer output projection optimizer (for supervised gradient descent)
        self._transformer_opt = Adam(
            self.transformer.output_projection.parameters(), lr=0.001,
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
        self.evt = ExtremeValueAnalyzer(threshold_quantile=0.95)
        self.factor_model = FactorModel(
            factors=["market", "size", "value", "momentum", "volatility", "quality"],
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

        # ── [16-19] Higher-order return statistics ──────────────
        if returns is not None and len(returns) >= 20:
            r20 = returns[-20:]
            mu, sigma = np.mean(r20), np.std(r20) + 1e-8
            # Skewness
            state[16] = float(np.mean(((r20 - mu) / sigma) ** 3))
            # Excess kurtosis
            state[17] = float(np.mean(((r20 - mu) / sigma) ** 4) - 3)
            # Lag-1 autocorrelation (mean-reversion indicator)
            if len(r20) > 1:
                r_lag = r20[:-1] - np.mean(r20[:-1])
                r_cur = r20[1:] - np.mean(r20[1:])
                denom = np.sqrt(np.sum(r_lag ** 2) * np.sum(r_cur ** 2) + 1e-16)
                state[18] = float(np.sum(r_lag * r_cur) / denom)
            # Hurst exponent estimate (R/S method, simplified)
            if len(returns) >= 40:
                hl = 20
                rs_vals = []
                for start_rs in range(0, len(returns) - hl, hl):
                    blk = returns[start_rs:start_rs + hl]
                    bmu = np.mean(blk)
                    cum_dev = np.cumsum(blk - bmu)
                    R = np.max(cum_dev) - np.min(cum_dev)
                    S = np.std(blk) + 1e-10
                    rs_vals.append(R / S)
                if rs_vals:
                    state[19] = float(np.log(np.mean(rs_vals) + 1e-8) / np.log(hl))

        if prices is not None and len(prices) >= 20:
            state[20] = _rsi(self.return_history.get(symbol, np.zeros(14)))
            state[21] = _bollinger_position(prices)
            state[22] = prices[-1] / max(prices[-5], 1e-8) - 1
            state[23] = prices[-1] / max(prices[-20], 1e-8) - 1
            if len(prices) >= 60:
                state[24] = prices[-1] / max(prices[-60], 1e-8) - 1

        # ── [25-34] Extended technical features ─────────────────
        if returns is not None and len(returns) >= 20:
            r20 = returns[-20:]
            r5 = returns[-5:]
            # MACD-like: short momentum minus long
            state[25] = float(np.mean(r5) - np.mean(r20))
            # Rate of change of volatility
            if len(returns) >= 40:
                vol_recent = np.std(returns[-10:])
                vol_prior = np.std(returns[-20:-10])
                state[26] = float((vol_recent - vol_prior) / (vol_prior + 1e-8))
            # Average absolute return (ATR proxy)
            state[27] = float(np.mean(np.abs(r20)))
            # SMA crossover: sign(mean_5 - mean_20)
            state[28] = float(np.sign(np.mean(r5) - np.mean(r20)))
            # Return dispersion (IQR of last 20)
            state[29] = float(np.percentile(r20, 75) - np.percentile(r20, 25))
            # Median return (robust location)
            state[30] = float(np.median(r20))
            # Win rate (fraction of positive returns)
            state[31] = float(np.mean(r20 > 0))
            # Max consecutive losses in last 20
            neg = (r20 < 0).astype(int)
            max_consec = 0
            cur_consec = 0
            for n_val in neg:
                cur_consec = cur_consec + 1 if n_val else 0
                max_consec = max(max_consec, cur_consec)
            state[32] = float(max_consec / 20.0)

        if prices is not None and len(prices) >= 20:
            p20 = prices[-20:]
            # Distance from 20d high (0 = at high)
            state[33] = float((prices[-1] - np.max(p20)) / (np.max(p20) + 1e-8))
            # Distance from 20d low (0 = at low)
            state[34] = float((prices[-1] - np.min(p20)) / (np.min(p20) + 1e-8))

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

        # ── [41-44] Time-of-day / day-of-week cyclical encoding ─
        now = datetime.now()
        hour_frac = (now.hour + now.minute / 60.0) / 24.0
        dow_frac = now.weekday() / 7.0
        state[41] = float(np.sin(2 * np.pi * hour_frac))
        state[42] = float(np.cos(2 * np.pi * hour_frac))
        state[43] = float(np.sin(2 * np.pi * dow_frac))
        state[44] = float(np.cos(2 * np.pi * dow_frac))

        # ── [48-54] Statistical model outputs ───────────────────
        if returns is not None and len(returns) >= 60:
            try:
                bayes_mean, bayes_std, _ = self.bayesian.estimate_sharpe_ratio(returns[-60:])
                state[48] = float(bayes_mean)
                state[49] = float(bayes_std)
            except Exception:
                pass
            if self.hmm_fitted:
                try:
                    hmm_state, hmm_probs = self.detect_regime_hmm(returns)
                    state[50] = float(hmm_state / 2.0)  # normalise to [0, 1]
                    state[51] = float(np.max(hmm_probs))
                except Exception:
                    pass
            if self.garch_fitted:
                try:
                    gf = self.garch.forecast(returns[-60:], horizon=5)
                    state[52] = float(gf.current_vol)
                    # Vol term structure slope
                    if len(gf.forecast_vol) >= 2:
                        state[53] = float(gf.forecast_vol[-1] - gf.forecast_vol[0])
                except Exception:
                    pass
            try:
                losses = -returns
                evt_a = self.evt.analyze(
                    losses[losses > 0] if np.any(losses > 0) else np.abs(losses)
                )
                if hasattr(evt_a, "tail_index"):
                    state[54] = float(evt_a.tail_index) / 10.0  # normalise
            except Exception:
                pass

        # ── [63] Data quality indicator ─────────────────────────
        state[63] = float(np.count_nonzero(state[:63])) / 63.0

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

        # LSTM (use trained LSTMClassifier — output is [P(down), P(up)])
        lstm_pred = 0.0
        if symbol in self.return_history and len(self.return_history[symbol]) >= 60:
            try:
                r60 = np.array(self.return_history[symbol][-60:]).flatten()
                lstm_input = _build_seq_features(r60)  # (60, 16) rich features
                probs, _ = self.lstm_classifier.forward(lstm_input)
                # Convert P(up) to a signed prediction: >0.5 = bullish, <0.5 = bearish
                lstm_pred = float(probs[0, 1] - 0.5)
            except Exception:
                pass

        # Transformer
        transformer_pred = 0.0
        if symbol in self.return_history and len(self.return_history[symbol]) >= 60:
            try:
                r60 = np.array(self.return_history[symbol][-60:]).flatten()
                t_input = _build_seq_features(r60)  # (60, 16) rich features
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

        # Factors (use real market returns when available)
        factors: Dict[str, float] = {}
        if symbol in self.return_history and len(self.return_history[symbol]) >= 60:
            try:
                sym_rets = self.return_history[symbol][-60:]
                mkt_rets = self.return_history.get("SPY")
                factor_rets = self.factor_model.generate_factor_returns(
                    len(sym_rets), market_returns=mkt_rets,
                )
                fe = self.factor_model.fit(sym_rets, factor_returns=factor_rets)
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
        agreement = float(np.clip(
            (action_votes[final_action] - 0.25) / 0.75, 0.0, 1.0
        ))

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
        # DQN: push experience and train if buffer large enough
        self.dqn.replay_buffer.push(
            Experience(state=state, action=action, reward=reward,
                       next_state=next_state, done=done)
        )
        if len(self.dqn.replay_buffer) >= 64:
            self.dqn.train_step(batch_size=64)

        # PPO: store transition and train when trajectory is long enough
        ppo_value = self.ppo.get_value(state)
        ppo_log_prob = float(np.log(
            self.ppo.get_action_probs(state)[action] + 1e-10
        ))
        self.ppo.store_transition(state, action, reward, ppo_value, ppo_log_prob, done)
        if len(self.ppo.states) >= 128 or done:
            next_value = self.ppo.get_value(next_state) if not done else 0.0
            self.ppo.train(next_value=next_value, n_epochs=4, batch_size=64)

        self.training_step += 1

    def train_supervised_models(self, n_epochs: int = 5):
        """Train LSTMClassifier and Transformer on return-direction prediction.

        Uses walk-forward: last 20% of data held out for validation to
        avoid in-sample overfit.  Target: class 0 = negative return,
        class 1 = positive return.
        """
        # ── Collect training sequences ──────────────────────
        X_seqs, y_labels = [], []
        for sym, rets in self.return_history.items():
            if len(rets) < 80:
                continue
            # Sliding windows: 60 timesteps → predict sign of next return
            for start in range(0, len(rets) - 61, 5):  # stride 5
                window = rets[start:start + 60]
                target = 1 if rets[start + 60] > 0 else 0
                seq = _build_seq_features(window)  # (60, 16) rich features
                X_seqs.append(seq)
                y_labels.append(target)

        if len(X_seqs) < 64:
            logger.info("Not enough data for supervised training")
            return

        X_all = np.array(X_seqs)       # (N, 60, 16)
        y_all = np.array(y_labels)     # (N,) ints

        # Walk-forward split: 80% train, 20% validation
        split = int(len(X_all) * 0.8)
        X_train, y_train = X_all[:split], y_all[:split]
        X_val, y_val = X_all[split:], y_all[split:]

        # ── Train LSTMClassifier (BPTT + Adam) ──────────────
        lstm_train_losses, lstm_val_losses = [], []
        for epoch in range(n_epochs):
            # Shuffle training data each epoch
            perm = np.random.permutation(len(X_train))
            epoch_loss, n = 0.0, 0
            for idx in perm:
                try:
                    loss = self.lstm_classifier.train_step(
                        X_train[idx], np.array([y_train[idx]]),
                    )
                    epoch_loss += loss
                    n += 1
                except Exception:
                    continue
            if n > 0:
                lstm_train_losses.append(epoch_loss / n)
            # Validation accuracy
            correct = 0
            for idx in range(len(X_val)):
                try:
                    pred_cls = self.lstm_classifier.predict(X_val[idx])
                    if pred_cls == y_val[idx]:
                        correct += 1
                except Exception:
                    continue
            val_acc = correct / max(len(X_val), 1)
            lstm_val_losses.append(val_acc)

        if lstm_train_losses:
            logger.info(
                f"LSTM trained: {n_epochs} epochs, "
                f"loss {lstm_train_losses[0]:.4f} → {lstm_train_losses[-1]:.4f}, "
                f"val acc {lstm_val_losses[-1]:.1%}"
            )

        # ── Train Transformer (gradient descent on output projection) ──
        trans_train_losses = []
        for epoch in range(n_epochs):
            perm = np.random.permutation(len(X_train))
            epoch_loss, n = 0.0, 0
            for idx in perm:
                try:
                    x = X_train[idx]
                    y_target = float(y_train[idx])  # 0 or 1
                    pred = self.transformer.predict(x)
                    error = pred - y_target
                    epoch_loss += error ** 2
                    n += 1

                    # Backprop through output projection (Dense layer)
                    # Gradient of MSE: d_loss/d_pred = 2 * error / 1
                    grad_out = np.array([[2 * error]])
                    self.transformer.output_projection.backward(grad_out)
                    grads = self.transformer.output_projection.gradients()
                    # Clip gradients
                    grad_norm = np.sqrt(sum(np.sum(g ** 2) for g in grads) + 1e-8)
                    if grad_norm > 1.0:
                        grads = [g * 1.0 / grad_norm for g in grads]
                    self._transformer_opt.step(grads)
                except Exception:
                    continue
            if n > 0:
                trans_train_losses.append(epoch_loss / n)

        if trans_train_losses:
            logger.info(
                f"Transformer trained: {n_epochs} epochs, "
                f"loss {trans_train_losses[0]:.4f} → {trans_train_losses[-1]:.4f}"
            )

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
