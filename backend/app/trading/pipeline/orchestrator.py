"""
PipelineOrchestrator — thin coordinator replacing MasterQuantBot's god-object.

Lifecycle (one cycle):
  1. Update FeatureStore with latest market data
  2. Assess regime
  3. Fan out to registered strategies → collect Opportunities
  4. ML-score each opportunity
  5. Apply RiskGate
  6. Execute surviving opportunities
  7. RL feedback

Exposes the **same public API** that MasterQuantBot had so existing
API routes keep working:
  - start(), stop()
  - get_status(), get_opportunities(), get_all_positions()
  - get_commentary(), get_performance(), get_trade_log()
  - get_ml_analysis(symbol)
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple

import numpy as np

from ..master_bot import (
    AssetClass,
    MarketRegime,
    MLPrediction,
    Opportunity,
    RiskMetrics,
)
from ..activity_logger import get_activity_logger, EventSubtype

from .feature_store import FeatureStore
from .persistence import TradePersistence, ModelCheckpointer
from .risk_gate import RiskGate
from .strategies.base import BaseStrategy
from .strategies.pairs_trading import PairsTradingStrategy
from .strategies.momentum import MomentumStrategy
from .strategies.options_premium import OptionsPremiumStrategy
from .strategies.perpetual import PerpetualStrategy
from .strategies.funding_rate_arb import FundingRateArbStrategy

logger = logging.getLogger(__name__)


class PipelineOrchestrator:
    """
    Drop-in replacement for MasterQuantBot.

    Delegates to FeatureStore (shared state), registered Strategies
    (opportunity generation), and RiskGate (risk filtering).
    """

    # ──────────────────────────────────────────────────────────
    # Construction
    # ──────────────────────────────────────────────────────────

    def __init__(
        self,
        initial_capital: float = 100_000.0,
        mode: str = "balanced",
    ):
        self.initial_capital = initial_capital
        self.mode = mode
        self.is_running = False
        self._task: Optional[asyncio.Task] = None

        # Core execution engine (keeps options/crypto position mgmt)
        from ..options_bot import create_options_bot
        self.engine = create_options_bot(capital=initial_capital, mode=mode)

        # Shared feature store (single source of truth)
        self.store = FeatureStore(lookback_days=252)

        # Backward-compatible alias so old code referencing
        # bot.analytics still works (e.g. backtester)
        self.analytics = self.store

        # Risk gate
        self.risk_gate = RiskGate(initial_capital=initial_capital)

        # ── Register strategies ───────────────────────────────
        self.strategies: List[BaseStrategy] = [
            PerpetualStrategy(),
            MomentumStrategy(),
            OptionsPremiumStrategy(),
            PairsTradingStrategy(),
            FundingRateArbStrategy(
                get_price_fn=self.engine._get_crypto_price,
            ),
        ]

        # ── Market state (kept on orchestrator for API compat) ─
        self.market_regime = MarketRegime.RANGE_BOUND
        self.regime_confidence: float = 0.5
        self.vix_level: float = 18.0

        # ── Persistence ────────────────────────────────────────
        self.persistence = TradePersistence()
        self.checkpointer = ModelCheckpointer()

        # ── Opportunity / trade tracking ──────────────────────
        self.opportunities: List[Opportunity] = []
        self.last_full_scan: Optional[datetime] = None
        self.trade_history: List[Dict] = self.persistence.load_trades()
        self.daily_pnl: List[Tuple[datetime, float]] = []
        self.commentary: List[Dict] = []

        self.current_allocations: Dict[AssetClass, float] = {
            ac: 0.0 for ac in AssetClass
        }

        # ── Order lifecycle tracking ──────────────────────────
        # Maps order_id → {status, symbol, side, broker_order_id, ...}
        self.pending_orders: Dict[str, Dict] = {}

        # ── RL state ──────────────────────────────────────────
        self.last_state: Optional[np.ndarray] = None
        self.last_action: Optional[int] = None
        self.episode_reward: float = 0.0

        # ── Live trading ──────────────────────────────────────
        self.live_trading_enabled = False
        self.broker_manager = None

        # ── Activity logger ───────────────────────────────────
        self.activity_logger = get_activity_logger()

        # ── Pre-training integration ──────────────────────────
        from ..backtester import get_model_pretrainer, get_alpha_manager
        self.model_pretrainer = get_model_pretrainer()
        self.alpha_manager = get_alpha_manager()
        self.models_trained = False
        self.training_required = True

        # ── Data loading flag ─────────────────────────────────
        self._real_data_loaded = False

        logger.info(
            f"PipelineOrchestrator initialised: {len(self.strategies)} strategies, "
            f"capital={initial_capital}, mode={mode}"
        )

    # ──────────────────────────────────────────────────────────
    # Lifecycle
    # ──────────────────────────────────────────────────────────

    async def start(self):
        """Start the orchestrator background loop."""
        if self.is_running:
            return
        self.is_running = True
        await self.engine.start()
        self._task = asyncio.create_task(self._run_loop())
        self._add_commentary("Pipeline orchestrator started", "system")
        await self.activity_logger.log_system(
            subtype=EventSubtype.BOT_START,
            message="Pipeline orchestrator started",
            details={"strategies": [s.name for s in self.strategies]},
        )

    async def stop(self):
        """Stop the orchestrator."""
        self.is_running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await self.engine.stop()
        self._add_commentary("Pipeline orchestrator stopped", "system")
        await self.activity_logger.log_system(
            subtype=EventSubtype.BOT_STOP,
            message="Pipeline orchestrator stopped",
            details={},
        )

    # ──────────────────────────────────────────────────────────
    # Main loop
    # ──────────────────────────────────────────────────────────

    async def _run_loop(self):
        scan_interval = 60
        position_check_interval = 30
        rl_train_interval = 10
        price_update_interval = 300

        last_scan = datetime.min
        last_pos_check = datetime.min
        last_rl = datetime.min
        last_price = datetime.min

        await self._load_real_market_data()

        while self.is_running:
            try:
                now = datetime.now()

                if (now - last_scan).seconds >= scan_interval:
                    await self._cycle()
                    last_scan = now

                if (now - last_pos_check).seconds >= position_check_interval:
                    await self._manage_positions()
                    last_pos_check = now

                if (now - last_rl).seconds >= rl_train_interval:
                    self._train_rl()
                    last_rl = now

                if (now - last_price).seconds >= price_update_interval:
                    await self._update_live_prices()
                    last_price = now

                await asyncio.sleep(5)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Pipeline loop error: {e}")
                await self.activity_logger.log_error(
                    subtype=EventSubtype.EXCEPTION,
                    message=f"Pipeline loop error: {str(e)[:200]}",
                    details={"error_type": type(e).__name__},
                )
                await asyncio.sleep(10)

    # ──────────────────────────────────────────────────────────
    # Single scan→filter→execute cycle
    # ──────────────────────────────────────────────────────────

    async def _cycle(self):
        """One full scan → risk-filter → execute cycle."""
        # 1. Regime
        self.store.assess_market_regime()
        self.market_regime = self.store.market_regime
        self.regime_confidence = self.store.regime_confidence
        self.vix_level = self.store.vix_level

        # 2. Fan out to strategies
        all_opps: List[Opportunity] = []
        for strat in self.strategies:
            try:
                opps = await strat.scan(self.store)
                all_opps.extend(opps)
            except Exception as e:
                logger.error(f"Strategy {strat.name} failed: {e}")

        # 3. ML-score and sort
        for opp in all_opps:
            opp.ml_prediction = self.store.get_ml_prediction(opp.symbol.split("/")[0])
            opp.risk_metrics = self.store.get_risk_metrics(opp.symbol.split("/")[0])
            opp.regime_alignment = self.risk_gate.regime_alignment(opp, self.market_regime)
            opp.score = self._compute_ml_score(opp)

        all_opps.sort(key=lambda o: o.score, reverse=True)

        # 4. Risk gate
        held = self._held_symbols()
        existing_pos = self._existing_positions_map()

        passed = self.risk_gate.filter(
            all_opps,
            total_pnl=self.engine.total_pnl,
            regime=self.market_regime,
            current_allocations=self.current_allocations,
            held_symbols=held,
            existing_positions=existing_pos,
        )

        self.opportunities = all_opps  # keep full list for UI
        self.last_full_scan = datetime.now()

        # 5. Execute passed opportunities
        await self._execute_passed(passed)

        # 6. Log
        self._add_commentary(
            f"Cycle: {len(all_opps)} scanned, {len(passed)} passed risk gate | "
            f"Regime: {self.market_regime.value}",
            "scan",
        )
        await self.activity_logger.log_scan(
            subtype=EventSubtype.SCAN_COMPLETE,
            message=f"Pipeline scan: {len(all_opps)} opportunities, {len(passed)} actionable",
            details={
                "total_opportunities": len(all_opps),
                "passed_risk_gate": len(passed),
                "strategies": {s.name: 0 for s in self.strategies},
                "market_regime": self.market_regime.value,
                "vix_level": self.vix_level,
            },
        )

    # ──────────────────────────────────────────────────────────
    # ML scoring
    # ──────────────────────────────────────────────────────────

    def _compute_ml_score(self, opp: Opportunity) -> float:
        base = opp.score
        ml = opp.ml_prediction
        if ml is None:
            return base

        ml_factor = 1.0
        if ml.action == 2 and "Long" in opp.strategy:
            ml_factor = 1.0 + ml.confidence * 0.3
        elif ml.action == 0 and "Short" in opp.strategy:
            ml_factor = 1.0 + ml.confidence * 0.3
        elif ml.action == 1:
            ml_factor = 0.7

        agreement_bonus = ml.ensemble_agreement * 15

        risk = opp.risk_metrics
        risk_adj = 1.0
        if risk and risk.sharpe_ratio > 1.0:
            risk_adj = 1.1
        elif risk and risk.max_drawdown > 0.20:
            risk_adj = 0.85

        regime_bonus = opp.regime_alignment * 10

        score = base * ml_factor * risk_adj + agreement_bonus + regime_bonus

        if opp.bayesian_confidence > 0.7:
            score *= 1.05
        if ml.ensemble_agreement > 0.8:
            score *= 1.15

        return score

    # ──────────────────────────────────────────────────────────
    # Execution
    # ──────────────────────────────────────────────────────────

    async def _execute_passed(self, passed: List[Opportunity]):
        """Execute opportunities that cleared the risk gate."""
        if not passed:
            return

        # Model-training gate
        if self.training_required and not self.models_trained:
            meets, reason = self.model_pretrainer.meets_training_requirements()
            if not meets:
                self._add_commentary(
                    f"Trading paused — models not trained: {reason}", "system"
                )
                return
            self.models_trained = True

        executed = 0
        for opp in passed:
            # Get pre-trained prediction for final gate
            state = self.store.get_state_vector(opp.symbol.split("/")[0], {"vix": self.vix_level})
            ml_pred = self.model_pretrainer.predict(state)
            action = ml_pred["action"]
            confidence = ml_pred["confidence"]

            ml_agrees = action != 1
            conf_ok = confidence >= self.risk_gate.confidence_threshold(self.market_regime)

            if not (ml_agrees and conf_ok):
                continue

            success = await self._execute_opportunity(opp)
            if success:
                executed += 1
                alloc_delta = opp.max_loss / self.initial_capital if self.initial_capital > 0 else 0
                self.current_allocations[opp.asset_class] = (
                    self.current_allocations.get(opp.asset_class, 0) + alloc_delta
                )
                self.last_state = state
                self.last_action = action
                self._add_commentary(
                    f"TRADE: {opp.symbol} | {opp.strategy} | "
                    f"conf={confidence:.0%} score={opp.score:.1f}",
                    "execution",
                )

        if executed:
            self._add_commentary(
                f"Executed {executed} trades | "
                f"DQN eps={self.store.dqn.epsilon:.3f}",
                "execution",
            )

    async def _execute_opportunity(self, opp: Opportunity) -> bool:
        """Execute a single opportunity (delegates to engine + broker)."""
        try:
            # Market-hours check for equity options
            if opp.asset_class in (
                AssetClass.STOCK_OPTIONS, AssetClass.ETF_OPTIONS, AssetClass.COMMODITY_OPTIONS,
            ):
                try:
                    from ..quant_bot import is_market_open
                    if not is_market_open():
                        return False
                except Exception:
                    pass

            # Live order submission (in parallel with engine paper trade)
            if self.live_trading_enabled and self.broker_manager is not None:
                base_sym = opp.symbol.split("-")[0].split("/")[0]
                side = "buy" if "Long" in opp.strategy or "Buy" in opp.strategy else "sell"
                is_futures = opp.asset_class == AssetClass.CRYPTO_PERPETUAL
                await self._submit_live_order(
                    base_sym, side,
                    self._vol_size(opp.symbol, 0.02, 2000),
                    asset_type="crypto" if "CRYPTO" in opp.asset_class.value else "stock",
                    is_futures=is_futures,
                )

            if opp.asset_class == AssetClass.CRYPTO_PERPETUAL:
                side = "long" if "Long" in opp.strategy else "short"
                pos = await self.engine.open_crypto_perpetual(
                    symbol=opp.symbol, side=side,
                    size_usd=self._vol_size(opp.symbol, 0.05, 5000, 2.0),
                    leverage=2.0,
                )
                if pos:
                    tid = self._record_trade(opp, "crypto_perpetual", pos.entry_price, pos.size)
                    pos.trade_id = tid
                    pos.opened_at = datetime.now()
                return pos is not None

            elif opp.asset_class == AssetClass.CRYPTO_SPOT:
                side = "buy" if "Long" in opp.strategy else "sell"
                pos = await self.engine.open_crypto_spot(
                    symbol=opp.symbol, side=side,
                    size_usd=self._vol_size(opp.symbol, 0.02, 2000),
                )
                if pos:
                    tid = self._record_trade(opp, "crypto_spot", pos.entry_price, pos.size)
                    pos.trade_id = tid
                    pos.opened_at = datetime.now()
                return pos is not None

            elif opp.asset_class == AssetClass.CRYPTO_OPTIONS:
                base = opp.symbol.split("-")[0]
                opt_type = "call" if "CALL" in opp.symbol or "Call" in opp.strategy else "put"
                is_buy = "Buy" in opp.strategy
                price = await self.engine._get_crypto_price(f"{base}-OPT")
                strike = round(price * (1.05 if opt_type == "call" else 0.95), -2)
                pos = await self.engine.open_crypto_option(
                    base_asset=base, option_type=opt_type,
                    strike=strike, expiry_days=30,
                    size_usd=self._vol_size(opp.symbol, 0.03, 3000),
                    is_buy=is_buy,
                )
                if pos:
                    tid = self._record_trade(opp, "crypto_option", pos.entry_price, pos.size)
                    pos.trade_id = tid
                    pos.opened_at = datetime.now()
                return pos is not None

            elif opp.asset_class in (
                AssetClass.STOCK_OPTIONS, AssetClass.ETF_OPTIONS, AssetClass.COMMODITY_OPTIONS,
            ):
                iv_analysis = self.engine.iv_cache.get(opp.symbol)
                if not iv_analysis:
                    return False
                signal = self.engine._generate_signal(opp.symbol, iv_analysis)
                if signal:
                    await self.engine._execute_signal(opp.symbol, signal, iv_analysis)
                    self._record_trade(opp, "options")
                    return True

        except Exception as e:
            logger.error(f"Execution failed {opp.symbol}: {e}")
        return False

    # ──────────────────────────────────────────────────────────
    # Position management
    # ──────────────────────────────────────────────────────────

    async def _manage_positions(self):
        """Check stop-loss / take-profit for open positions."""
        await self.engine._check_exits()
        await self.engine._update_positions()

        for pos_id, pos in list(self.engine.crypto_positions.items()):
            pos.current_price = await self.engine._get_crypto_price(pos.symbol)
            if pos.current_price <= 0:
                continue

            opened_at = getattr(pos, "opened_at", None)
            if opened_at and (datetime.now() - opened_at).total_seconds() < 120:
                continue

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
                pnl = pos.calculate_pnl()
                exit_price = pos.current_price
                tid = getattr(pos, "trade_id", None)
                await self.engine.close_crypto_perpetual(pos_id, close_reason)
                if tid:
                    self._update_trade_closed(tid, exit_price, pnl, close_reason)

    # ──────────────────────────────────────────────────────────
    # RL training
    # ──────────────────────────────────────────────────────────

    def _train_rl(self):
        pnl = self.engine.total_pnl
        # Reward as fraction of capital (not * 100) so it stays in [-1, 1]
        # range that DQN's reward clipping expects.
        raw_reward = (pnl - getattr(self, "_last_pnl", 0)) / self.initial_capital
        self._last_pnl = pnl

        # Small Sharpe-ratio bonus for consistent recent returns
        sharpe_bonus = 0.0
        if len(self.daily_pnl) >= 20:
            recent = [p[1] for p in self.daily_pnl[-20:]]
            std = np.std(recent)
            if std > 0:
                sharpe_bonus = np.clip(np.mean(recent) / std * 0.01, -0.1, 0.1)

        reward = np.clip(raw_reward + sharpe_bonus, -1.0, 1.0)

        if self.last_state is not None and self.last_action is not None:
            cur = self.store.get_state_vector("SPY", {"vix": self.vix_level})
            self.store.train_rl_step(self.last_state, self.last_action, reward, cur, False)
            self.episode_reward += reward

        self.daily_pnl.append((datetime.now(), pnl))

    # ──────────────────────────────────────────────────────────
    # Data loading
    # ──────────────────────────────────────────────────────────

    async def _load_real_market_data(self):
        if self._real_data_loaded:
            return
        total = 0
        try:
            from ..master_bot import _load_crypto_data
        except ImportError:
            _load_crypto_data = None

        # Crypto data from Binance
        try:
            from ...data.binance_data import get_binance_fetcher
            fetcher = get_binance_fetcher()
            crypto_syms = [
                "BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX",
                "LINK", "DOT", "MATIC", "LTC", "ATOM", "UNI", "FET",
                "AAVE", "MKR", "CRV", "NEAR", "APT", "ARB", "OP", "SUI",
            ]
            data = await fetcher.get_multi_symbol_data(crypto_syms, days=252, interval="1d")
            for sym, (prices, _) in data.items():
                if len(prices) >= 60:
                    self.store.update_price_history(sym, prices)
                    self.store.update_price_history(f"{sym}-PERP", prices)
                    total += 1
            if total:
                self._add_commentary(f"Loaded {total} crypto symbols from Binance", "system")
        except Exception as e:
            logger.warning(f"Binance load failed: {e}")

        # Stock data from Alpaca
        try:
            from ...data.alpaca_data import get_alpaca_fetcher
            alpaca = get_alpaca_fetcher()
            if alpaca.has_keys:
                stocks = [
                    "SPY", "QQQ", "IWM", "DIA",
                    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA",
                    "GLD", "SLV", "USO", "JPM", "BAC", "GS", "AMD", "COIN",
                ]
                sdata = await alpaca.get_multi_symbol_data(stocks, days=252)
                for sym, (prices, _) in sdata.items():
                    if len(prices) >= 60:
                        self.store.update_price_history(sym, prices)
                        total += 1
        except Exception as e:
            logger.warning(f"Alpaca load failed: {e}")

        self._real_data_loaded = total > 0
        self._add_commentary(f"Market data loaded: {total} symbols", "system")

        # Load model checkpoint if available
        self.checkpointer.load(self.store)

        # Train supervised models (LSTM, Transformer, VAE) on historical data
        if total > 0:
            try:
                self.store.train_supervised_models(n_epochs=5)
                self.save_checkpoint()
                self._add_commentary(
                    "Supervised models trained + checkpoint saved", "system",
                )
            except Exception as e:
                logger.warning(f"Supervised training failed: {e}")

    async def _update_live_prices(self):
        try:
            from ...data.binance_data import get_binance_fetcher
            fetcher = get_binance_fetcher()
            active = list(set(
                p.symbol.replace("-PERP", "").split("-")[0]
                for p in self.engine.crypto_positions.values()
            ))
            for sym in (active + ["BTC", "ETH", "SOL", "BNB", "XRP"])[:10]:
                try:
                    price = await fetcher.get_price(sym)
                    if price:
                        key = sym if sym in self.store.price_history else f"{sym}-PERP"
                        if key in self.store.price_history:
                            arr = np.append(self.store.price_history[key], price)[-500:]
                            self.store.update_price_history(key, arr)
                except Exception:
                    pass
        except Exception:
            pass

    # ──────────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────────

    def _vol_size(
        self, symbol: str, base_pct: float = 0.02,
        max_usd: float = 2000, leverage: float = 1.0,
    ) -> float:
        """Vol-adjusted position size."""
        risk = self.store.get_risk_metrics(symbol.split("-")[0])
        vol = max(risk.volatility_forecast, 0.05)
        target_vol = 0.15
        scale = target_vol / vol
        raw = self.initial_capital * base_pct * scale * leverage
        return min(raw, max_usd)

    def _held_symbols(self) -> Set[str]:
        held: Set[str] = set()
        for p in self.engine.crypto_positions.values():
            held.add(p.symbol)
        for p in self.engine.positions.values():
            held.add(p.symbol)
        return held

    def _existing_positions_map(self) -> Dict[str, str]:
        m: Dict[str, str] = {}
        for p in self.engine.crypto_positions.values():
            m[p.symbol] = getattr(p, "side", "long")
        return m

    def _has_position(self, symbol: str) -> bool:
        return symbol in self._held_symbols()

    def _add_commentary(self, message: str, category: str):
        self.commentary.append({
            "timestamp": datetime.now().isoformat(),
            "message": message,
            "category": category,
        })
        if len(self.commentary) > 500:
            self.commentary = self.commentary[-300:]

    def _record_trade(
        self, opp: Opportunity, trade_type: str,
        price: float = 0, size: float = 0,
    ) -> str:
        tid = str(uuid.uuid4())[:8]
        side = "long" if "Long" in opp.strategy or "Buy" in opp.strategy else "short"
        trade = {
            "id": tid,
            "timestamp": datetime.now().isoformat(),
            "symbol": opp.symbol,
            "asset_class": opp.asset_class.value,
            "type": trade_type,
            "strategy": opp.strategy,
            "side": side,
            "price": price,
            "entry_price": price,
            "size": size if size > 0 else min(5000, self.initial_capital * 0.05),
            "status": "open",
            "exit_price": None,
            "exit_timestamp": None,
            "close_reason": None,
            "realized_pnl": None,
            "realized_pnl_pct": None,
            "duration_minutes": None,
            "score": round(opp.score, 1),
            "ml_confidence": opp.ml_prediction.confidence if opp.ml_prediction else 0,
            "iv_rank": opp.iv_rank,
            "regime": self.market_regime.value,
            "rationale": opp.rationale,
            "live_executed": self.live_trading_enabled,
        }
        self.trade_history.append(trade)
        self.persistence.save_trades(self.trade_history)
        return tid

    def _update_trade_closed(
        self, trade_id: str, exit_price: float,
        realized_pnl: float, close_reason: str,
    ):
        for t in self.trade_history:
            if t["id"] == trade_id:
                t["status"] = "closed"
                t["exit_price"] = exit_price
                t["exit_timestamp"] = datetime.now().isoformat()
                t["close_reason"] = close_reason
                t["realized_pnl"] = round(realized_pnl, 2)
                entry = t.get("entry_price", 0)
                t["realized_pnl_pct"] = (
                    round(realized_pnl / entry * 100, 2)
                    if entry and entry > 0 else 0
                )
                entry_ts = t.get("timestamp")
                if entry_ts:
                    try:
                        dur = (datetime.now() - datetime.fromisoformat(entry_ts)).total_seconds() / 60
                        t["duration_minutes"] = round(dur, 1)
                    except Exception:
                        pass
                break
        self.persistence.save_trades(self.trade_history)

    # ──────────────────────────────────────────────────────────
    # Public API  (same surface as MasterQuantBot)
    # ──────────────────────────────────────────────────────────

    def get_status(self) -> Dict:
        return {
            "is_running": self.is_running,
            "mode": self.mode,
            "architecture": "pipeline",
            "strategies": [s.name for s in self.strategies],
            "market_regime": self.market_regime.value,
            "regime_confidence": round(self.regime_confidence, 2),
            "vix_level": round(self.vix_level, 1),
            "initial_capital": self.initial_capital,
            "cash": round(self.engine.cash, 2),
            "total_value": round(self.engine.total_value, 2),
            "total_pnl": round(self.engine.total_pnl, 2),
            "total_pnl_pct": round(self.engine.total_pnl / self.initial_capital * 100, 2),
            "positions": {
                "options": len(self.engine.positions),
                "crypto": len(self.engine.crypto_positions),
                "total": len(self.engine.positions) + len(self.engine.crypto_positions),
            },
            "allocations": {ac.value: round(v, 3) for ac, v in self.current_allocations.items()},
            "ml_metrics": {
                "rl_training_steps": self.store.training_step,
                "dqn_epsilon": round(self.store.dqn.epsilon, 4),
                "hmm_fitted": self.store.hmm_fitted,
                "garch_fitted": self.store.garch_fitted,
            },
            "training_status": {
                "models_trained": self.models_trained,
            },
            "last_scan": self.last_full_scan.isoformat() if self.last_full_scan else None,
            "opportunities_count": len(self.opportunities),
            "live_trading_enabled": self.live_trading_enabled,
        }

    def get_opportunities(self, limit: int = 20) -> List[Dict]:
        return [o.to_dict() for o in self.opportunities[:limit]]

    def get_all_positions(self) -> Dict:
        return {
            "options_positions": self.engine.get_positions(),
            "crypto_positions": self.engine.get_crypto_positions(),
        }

    def get_commentary(self, limit: int = 50) -> List[Dict]:
        return self.commentary[-limit:]

    def get_performance(self) -> Dict:
        perf = self.engine.get_performance()
        perf.update({
            "architecture": "pipeline",
            "strategies": [s.name for s in self.strategies],
            "market_regime": self.market_regime.value,
            "vix_level": self.vix_level,
            "opportunities_scanned": len(self.opportunities),
            "ml_performance": {
                "rl_training_steps": self.store.training_step,
                "dqn_epsilon": round(self.store.dqn.epsilon, 4),
                "episode_reward": round(self.episode_reward, 4),
            },
        })
        return perf

    def get_trade_log(self, limit: int = 50) -> List[Dict]:
        return sorted(
            self.trade_history, key=lambda t: t["timestamp"], reverse=True,
        )[:limit]

    def get_ml_analysis(self, symbol: str) -> Dict:
        pred = self.store.get_ml_prediction(symbol)
        risk = self.store.get_risk_metrics(symbol)
        return {
            "symbol": symbol,
            "prediction": {
                "action": pred.action_name,
                "confidence": pred.confidence,
                "dqn_q": pred.dqn_q_value,
                "ppo_prob": pred.ppo_prob,
                "lstm_pred": pred.lstm_pred,
                "transformer_pred": pred.transformer_pred,
                "regime": pred.regime,
                "ensemble_agreement": pred.ensemble_agreement,
            },
            "risk": {
                "var_95": risk.var_95,
                "var_99": risk.var_99,
                "volatility_forecast": risk.volatility_forecast,
                "max_drawdown": risk.max_drawdown,
                "sharpe_ratio": risk.sharpe_ratio,
            },
        }

    # ──────────────────────────────────────────────────────────
    # Broker integration
    # ──────────────────────────────────────────────────────────

    async def initialize_broker(self) -> bool:
        """Connect to configured brokers (Alpaca, Binance)."""
        try:
            from ..live_brokers import get_broker_manager, auto_initialize_brokers
            self.broker_manager = get_broker_manager()
            result = await auto_initialize_brokers()
            connected = sum(1 for v in result.values() if v is True)
            if connected > 0:
                self._add_commentary(
                    f"Broker connected: {connected} broker(s)", "system",
                )
                return True
            logger.warning("No brokers connected — paper trading only")
        except Exception as e:
            logger.warning(f"Broker init failed: {e}")
        return False

    async def enable_live_trading(self) -> Tuple[bool, str]:
        """Enable live trading after validating all prerequisites.

        Checks:
          1. At least one broker is connected
          2. Models meet training requirements
          3. No active circuit breaker
        """
        if self.broker_manager is None:
            return False, "No broker manager — call initialize_broker() first"
        status = self.broker_manager.get_status()
        if not any(v.get("connected") for v in status.get("brokers", {}).values()):
            return False, "No brokers connected"

        meets, reason = self.model_pretrainer.meets_training_requirements()
        if not meets:
            return False, f"Models not ready: {reason}"

        drawdown = -self.engine.total_pnl / self.initial_capital
        if drawdown >= self.risk_gate.drawdown_hard:
            return False, f"Circuit breaker active: drawdown {drawdown:.1%}"

        self.live_trading_enabled = True
        self.models_trained = True
        self._add_commentary("Live trading ENABLED", "system")
        return True, "Live trading enabled"

    # ──────────────────────────────────────────────────────────
    # Order lifecycle
    # ──────────────────────────────────────────────────────────

    async def _submit_live_order(
        self, symbol: str, side: str, size_usd: float,
        asset_type: str = "crypto", is_futures: bool = False,
    ) -> Optional[str]:
        """Submit a live order through the broker manager.

        Returns broker order ID on success, None on failure.
        """
        if not self.live_trading_enabled or self.broker_manager is None:
            return None

        try:
            # Calculate quantity from USD size
            price = await self.broker_manager.get_live_price(
                symbol, asset_type,
            )
            if price <= 0:
                return None
            qty = size_usd / price

            if asset_type == "crypto":
                order = await self.broker_manager.submit_crypto_order(
                    symbol=symbol, quantity=qty, side=side,
                    is_futures=is_futures,
                )
            else:
                order = await self.broker_manager.submit_stock_order(
                    symbol=symbol, quantity=qty, side=side,
                )

            if order:
                self.pending_orders[order.order_id] = {
                    "status": order.status,
                    "symbol": symbol,
                    "side": side,
                    "quantity": qty,
                    "submitted_at": datetime.now().isoformat(),
                    "broker_order_id": order.order_id,
                }
                return order.order_id
        except Exception as e:
            logger.error(f"Live order failed {symbol}: {e}")
        return None

    # ──────────────────────────────────────────────────────────
    # Position reconciliation
    # ──────────────────────────────────────────────────────────

    async def reconcile_positions(self) -> Dict:
        """Compare engine positions with broker positions.

        Returns discrepancies for manual review.
        """
        if self.broker_manager is None:
            return {"status": "no_broker", "discrepancies": []}

        try:
            broker_positions = await self.broker_manager.get_all_positions()
        except Exception as e:
            return {"status": "error", "error": str(e), "discrepancies": []}

        broker_syms = {p.symbol: p for p in broker_positions}
        engine_syms = set()
        for p in self.engine.crypto_positions.values():
            engine_syms.add(p.symbol.replace("-PERP", ""))

        discrepancies = []

        # Positions in engine but not on broker
        for sym in engine_syms:
            if sym not in broker_syms:
                discrepancies.append({
                    "type": "engine_only",
                    "symbol": sym,
                    "action": "Position exists in engine but not on broker",
                })

        # Positions on broker but not in engine
        for sym, bp in broker_syms.items():
            if sym not in engine_syms and abs(bp.quantity) > 0:
                discrepancies.append({
                    "type": "broker_only",
                    "symbol": sym,
                    "quantity": bp.quantity,
                    "action": "Position exists on broker but not in engine",
                })

        return {
            "status": "ok",
            "engine_count": len(engine_syms),
            "broker_count": len(broker_positions),
            "discrepancies": discrepancies,
        }

    # ──────────────────────────────────────────────────────────
    # Walk-forward backtesting
    # ──────────────────────────────────────────────────────────

    async def backtest(
        self,
        symbols: Optional[List[str]] = None,
        days: int = 252,
    ) -> Dict:
        """Run walk-forward backtest using the pipeline's trained models.

        This validates strategy performance on historical data before
        enabling live trading.
        """
        from ..backtester import get_backtester

        bt = get_backtester()
        data = {}

        # Use already-loaded price history
        target_syms = symbols or list(self.store.price_history.keys())[:10]
        for sym in target_syms:
            prices = self.store.price_history.get(sym)
            if prices is not None and len(prices) >= 60:
                from ..backtester import OHLCV
                candles = []
                for i, p in enumerate(prices):
                    candles.append(OHLCV(
                        timestamp=datetime(2024, 1, 1),  # placeholder
                        open=p, high=p * 1.01, low=p * 0.99,
                        close=p, volume=1000,
                    ))
                data[sym] = candles

        if not data:
            return {"error": "No price data available for backtesting"}

        try:
            result = bt.run_backtest(data, self.model_pretrainer)
            self._add_commentary(
                f"Backtest complete: Sharpe={result.sharpe_ratio:.2f}, "
                f"return={result.total_return:.1%}, "
                f"max DD={result.max_drawdown:.1%}",
                "system",
            )
            return {
                "sharpe_ratio": result.sharpe_ratio,
                "sortino_ratio": result.sortino_ratio,
                "total_return": result.total_return,
                "max_drawdown": result.max_drawdown,
                "win_rate": result.win_rate,
                "total_trades": result.total_trades,
                "equity_curve_length": len(result.equity_curve),
            }
        except Exception as e:
            logger.error(f"Backtest failed: {e}")
            return {"error": str(e)}

    # ──────────────────────────────────────────────────────────
    # Model checkpointing
    # ──────────────────────────────────────────────────────────

    def save_checkpoint(self, tag: str = "latest"):
        """Save model weights + portfolio state to disk."""
        self.checkpointer.save(self.store, tag)
        self.persistence.save_portfolio_state({
            "total_pnl": self.engine.total_pnl,
            "cash": self.engine.cash,
            "total_value": self.engine.total_value,
            "regime": self.market_regime.value,
            "training_step": self.store.training_step,
            "dqn_epsilon": self.store.dqn.epsilon,
            "episode_reward": self.episode_reward,
            "allocations": {ac.value: v for ac, v in self.current_allocations.items()},
        })

    def load_checkpoint(self, tag: str = "latest") -> bool:
        """Load model weights from disk."""
        return self.checkpointer.load(self.store, tag)
