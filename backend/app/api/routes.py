"""
API routes for QuantLab.
"""

from fastapi import APIRouter, HTTPException, Depends, Query, Path
from pydantic import BaseModel, Field, field_validator
from typing import List, Optional
from datetime import datetime
import json
import logging

from .auth import require_backend_token

logger = logging.getLogger(__name__)

from ..config import get_settings
from .. import DISCLAIMER

router = APIRouter()

# Shared-secret guard for STATE-MUTATING routes (kill-switch, risk config, execute,
# portfolio reset, bot control, …). No-op when BACKEND_API_TOKEN is unset (degrades
# safely); enforces `Authorization: Bearer <token>` when the owner sets it. See auth.py.
_MUTATING_AUTH = [Depends(require_backend_token)]


def _safe_conn_error(e: Exception) -> str:
    """Return a SANITIZED connection-error label for a public response.

    The ``/prediction-markets/status`` endpoint is unauthenticated. Returning a raw
    ``str(e)`` from a failed venue request leaks internals to any caller — the full URL,
    library internals, proxy/timeout details, sometimes a chunk of stack. We surface only
    the exception TYPE name (e.g. ``ConnectTimeout``), which is enough to diagnose
    reachability without disclosing anything sensitive. The full error is still logged
    server-side for the operator.
    """
    logger.warning("venue connectivity check failed: %s", e)
    return type(e).__name__


# ============ Debug/Health Endpoints ============

@router.get("/debug/routes-loaded")
async def debug_routes_loaded():
    """Debug endpoint to verify all routes are loaded."""
    return {
        "status": "ok",
        "message": "All routes loaded successfully",
        "sections": ["status", "prediction-markets"],
    }


# ============ Status Endpoints ============

@router.get("/status")
async def get_status():
    """Get system status."""
    settings = get_settings()

    return {
        "demo_mode": settings.demo_mode,
        "llm_available": settings.has_llm_key,
        "initial_cash": settings.initial_cash,
        "disclaimer": DISCLAIMER
    }


# ============ Prediction Markets — module singletons ============
# Declared at module level so the lazy _get_* helpers' `global` reads never hit
# a NameError on first call (the prediction-markets path is the only venue now).
_polymarket_client = None
_prediction_scanner = None


def _get_polymarket_client():
    global _polymarket_client
    if _polymarket_client is None:
        from ..prediction_markets.polymarket_client import PolymarketClient
        _polymarket_client = PolymarketClient()
    return _polymarket_client


def _get_prediction_scanner():
    global _prediction_scanner
    if _prediction_scanner is None:
        from ..prediction_markets.strategies import (
            PredictionMarketScanner,
            StrategyConfig,
            NearCertaintyStrategy,
            SameMarketArbitrageStrategy,
            CrossMarketArbitrageStrategy,
            MarketMakingStrategy,
            FlashCrashStrategy,
        )

        client = _get_polymarket_client()
        _prediction_scanner = PredictionMarketScanner(
            client,
            use_clob=True,           # Enrich Gamma data with live CLOB prices
            clob_market_limit=15,    # Price up to 15 markets per scan (~30 API calls, ~25s)
            clob_fetch_books=False,  # Order books fetched on-demand by strategies
        )

        config = StrategyConfig(
            enabled=True,
            max_position_usd=5.0,
            max_positions=20,
            min_edge=0.02,       # 2% edge minimum (was 5% — too restrictive for scanning)
            min_liquidity=500.0, # Lower bar — Gamma API often doesn't report liquidity
            scan_interval_sec=120,
            dry_run=True,
        )

        _prediction_scanner.add_strategy(NearCertaintyStrategy(
            client, config,
            min_price=0.85,     # Wider price range (was 0.90)
            min_volume=1000,    # Lower volume threshold (was 5000)
        ))
        _prediction_scanner.add_strategy(SameMarketArbitrageStrategy(client, config))
        _prediction_scanner.add_strategy(CrossMarketArbitrageStrategy(client, config))
        _prediction_scanner.add_strategy(MarketMakingStrategy(client, config))
        _prediction_scanner.add_strategy(FlashCrashStrategy(client, config))

        # Advanced strategies
        try:
            from ..prediction_markets.advanced_strategies import (
                NOPositionScanner,
                LogicalImplicationDetector,
            )
            _prediction_scanner.add_strategy(NOPositionScanner(client, config))
            _prediction_scanner.add_strategy(LogicalImplicationDetector(client, config))
        except Exception as e:
            logger.warning(f"Advanced strategies not loaded: {e}")

        # UNVALIDATED strategies (whale copy-trading, weather arb, wallet-behavior
        # divergence) — off by default. They are untracked in ROADMAP/RESEARCH_MEMORY, have
        # no B3 registry evidence, and the whale feed historically shipped a fabricated
        # hardcoded seed. WalletBehaviorDivergence additionally sizes on a FABRICATED edge
        # (whale_feed: abs(price-0.5)*0.2) and was safe-by-ACCIDENT only while its
        # data-api.polymarket.com feed was egress-blocked; that block no longer holds (the
        # feed is now reachable), so it is gated with its siblings (2026-07-04, PENDING_OPS
        # OA-13 pre-registered remediation). Per FACTORY_STANDARD "no alpha ships while
        # integrity is weak" they only load when the owner explicitly opts in via
        # ENABLE_UNVALIDATED_STRATEGIES. See the 2026-07-01 Research Run 11 integrity finding
        # in docs/growth/RESEARCH_MEMORY.md.
        if get_settings().enable_unvalidated_strategies:
            from ..prediction_markets.advanced_strategies import WalletBehaviorDivergence
            from ..prediction_markets.strategies import (
                WeatherArbitrageStrategy,
                WhaleCopyTradingStrategy,
            )
            _prediction_scanner.add_strategy(WalletBehaviorDivergence(client, config))
            _prediction_scanner.add_strategy(WhaleCopyTradingStrategy(client, config))
            weather_strategy = WeatherArbitrageStrategy(client, config)
            try:
                from ..prediction_markets.noaa_weather import NOAAWeatherClient
                noaa = NOAAWeatherClient()
                forecasts = noaa.get_all_forecasts()
                weather_strategy.update_forecasts(forecasts)
            except Exception as e:
                logger.warning(f"NOAA forecast fetch failed (weather arb degraded): {e}")
            _prediction_scanner.add_strategy(weather_strategy)
        else:
            logger.info(
                "Unvalidated strategies (whale copy-trading, weather arb, wallet-behavior "
                "divergence) gated OFF (ENABLE_UNVALIDATED_STRATEGIES not set)."
            )

    return _prediction_scanner


class MarketSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=200)
    limit: int = Field(20, ge=1, le=500)


def _serialize_market(m, exchange: str = "polymarket") -> dict:
    """Convert a Market dataclass to a JSON-safe dict with exchange tag."""
    from dataclasses import asdict
    d = asdict(m)
    if m.end_date:
        d["end_date"] = m.end_date.isoformat()
    d["exchange"] = exchange
    return d


@router.get("/prediction-markets/status")
async def get_polymarket_connection_status():
    """Check if Polymarket APIs are reachable and return connection status."""
    import requests
    import time

    status = {
        "gamma_api": {"connected": False, "latency_ms": None, "error": None},
        "clob_api": {"connected": False, "latency_ms": None, "error": None},
    }

    # Check Gamma API (market discovery)
    try:
        t0 = time.time()
        resp = requests.get(
            "https://gamma-api.polymarket.com/markets",
            params={"limit": 1, "active": "true"},
            timeout=10,
        )
        latency = round((time.time() - t0) * 1000)
        status["gamma_api"]["connected"] = resp.status_code == 200
        status["gamma_api"]["latency_ms"] = latency
        if resp.status_code != 200:
            status["gamma_api"]["error"] = f"HTTP {resp.status_code}"
    except Exception as e:
        status["gamma_api"]["error"] = _safe_conn_error(e)

    # Check CLOB API (pricing)
    try:
        t0 = time.time()
        resp = requests.get(
            "https://clob.polymarket.com/time",
            timeout=10,
        )
        latency = round((time.time() - t0) * 1000)
        status["clob_api"]["connected"] = resp.status_code == 200
        status["clob_api"]["latency_ms"] = latency
        if resp.status_code != 200:
            status["clob_api"]["error"] = f"HTTP {resp.status_code}"
    except Exception as e:
        status["clob_api"]["error"] = _safe_conn_error(e)

    all_connected = status["gamma_api"]["connected"] and status["clob_api"]["connected"]
    return {
        "connected": all_connected,
        "exchange": "polymarket",
        **status,
    }


@router.get("/prediction-markets/markets")
async def list_prediction_markets(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0, le=1_000_000),
):
    """List active prediction markets from Polymarket."""
    result = []

    try:
        poly = _get_polymarket_client()
        poly_markets = poly.get_markets(limit=limit, offset=offset)
        result.extend(_serialize_market(m, "polymarket") for m in poly_markets)
    except Exception as e:
        logger.error(f"Polymarket fetch error: {e}")

    return {"markets": result, "count": len(result)}


@router.post("/prediction-markets/search")
async def search_prediction_markets(req: MarketSearchRequest):
    """Search prediction markets by keyword on Polymarket."""
    result = []

    try:
        poly = _get_polymarket_client()
        poly_results = poly.search_markets(req.query, limit=req.limit)
        result.extend(_serialize_market(m, "polymarket") for m in poly_results)
    except Exception as e:
        logger.error(f"Polymarket search error: {e}")

    return {"markets": result, "count": len(result)}


@router.post("/prediction-markets/scan", dependencies=_MUTATING_AUTH)
async def scan_prediction_markets(
    market_limit: int = Query(200, ge=1, le=5000),
):
    """Run all strategies and return identified opportunities.

    Guarded by the shared-secret bearer (like its sibling ``/bot/scan-now``): a scan
    mutates scanner counters and fans out many rate-limited Gamma/CLOB HTTP calls, so it
    is a state-mutating / expensive endpoint, not a free read. ``market_limit`` is bounded
    so the endpoint can't be driven into a million-page fetch.
    """
    import asyncio
    scanner = _get_prediction_scanner()
    try:
        # Run synchronous scanner in a thread to avoid blocking the async event loop.
        # The scanner makes many rate-limited HTTP calls (Gamma + CLOB + Data API).
        results = await asyncio.to_thread(scanner.scan, market_limit)
        return {
            "timestamp": datetime.now().isoformat(),
            "scan_number": scanner.total_scans,
            "markets_scanned": getattr(scanner, 'last_market_count', market_limit),
            "total_opportunities": len(results),
            "opportunities": [
                {
                    "strategy": r.strategy,
                    "market": r.market.question,
                    "market_id": r.market.id,
                    "outcome": (
                        r.market.outcomes[r.outcome_idx].label
                        if 0 <= r.outcome_idx < len(r.market.outcomes)
                        else "Both"
                    ),
                    "side": r.side,
                    "entry_price": r.entry_price,
                    "expected_value": r.expected_value,
                    "edge": r.edge,
                    "confidence": r.confidence,
                    "reason": r.reason,
                    "timestamp": r.timestamp.isoformat(),
                }
                for r in results
            ],
        }
    except Exception as e:
        logger.error(f"Prediction scan error: {e}")
        raise HTTPException(status_code=502, detail="Prediction scan failed")


@router.get("/prediction-markets/weather")
async def get_weather_forecasts():
    """Get NOAA weather forecasts for tracked cities."""
    from ..prediction_markets.noaa_weather import NOAAWeatherClient

    try:
        noaa = NOAAWeatherClient()
        forecasts = noaa.get_all_forecasts()
        return {
            "count": len(forecasts),
            "forecasts": {
                city: {
                    "location": f.location,
                    "temp_high_f": f.temp_high_f,
                    "temp_low_f": f.temp_low_f,
                    "temp_mean_f": f.temp_mean_f,
                    "precipitation_pct": f.precipitation_pct,
                    "wind_mph": f.wind_mph,
                    "confidence": f.confidence,
                }
                for city, f in forecasts.items()
            },
        }
    except Exception as e:
        logger.error(f"Weather forecast error: {e}")
        raise HTTPException(status_code=502, detail="Weather forecast failed")


@router.get("/prediction-markets/strategies")
async def get_prediction_strategies():
    """Get status of all registered prediction market strategies."""
    scanner = _get_prediction_scanner()
    return {
        "total_scans": scanner.total_scans,
        "strategies": [
            {
                "name": s.name,
                "enabled": s.config.enabled,
                "dry_run": s.config.dry_run,
                "positions": len(s.positions),
                "total_pnl": s.total_pnl,
                "trades_executed": s.trades_executed,
                "config": {
                    "max_position_usd": s.config.max_position_usd,
                    "max_positions": s.config.max_positions,
                    "min_edge": s.config.min_edge,
                    "scan_interval_sec": s.config.scan_interval_sec,
                },
            }
            for s in scanner.strategies
        ],
        "recent_opportunities": len(scanner.scan_history),
    }


# ============ Prediction Markets — Execution ============

_prediction_executor = None


def _get_prediction_executor():
    global _prediction_executor
    if _prediction_executor is None:
        from ..prediction_markets.execution import get_executor
        _prediction_executor = get_executor(dry_run=True)
    return _prediction_executor


class PlaceOrderRequest(BaseModel):
    # §12 input bounds: /execute is a state-mutating (auth-guarded) route whose payload
    # flows straight into the executor + quant sizing. Without bounds a caller could send
    # size=inf / price=NaN (poisoning risk math + the loss-cap counters) or a multi-MB
    # market_id (resource exhaustion). allow_inf_nan=False rejects non-finite floats.
    exchange: str = Field("polymarket", max_length=50)
    market_id: str = Field(..., min_length=1, max_length=200)
    token_id: str = Field(..., min_length=1, max_length=200)
    side: str = Field("BUY", max_length=8)            # "BUY" or "SELL"
    order_type: str = Field("LIMIT", max_length=8)    # "MARKET", "LIMIT", "GTC", "FOK"
    size: float = Field(10.0, gt=0.0, le=1_000_000.0, allow_inf_nan=False)   # contracts
    price: Optional[float] = Field(None, ge=0.0, le=1.0, allow_inf_nan=False)  # limit price 0..1
    strategy: str = Field("", max_length=100)


@router.post("/prediction-markets/execute", dependencies=_MUTATING_AUTH)
async def execute_prediction_order(req: PlaceOrderRequest):
    """
    Execute an order on a prediction market.

    Runs through risk checks. In dry_run mode (default), simulates the fill.
    """
    from ..prediction_markets.execution import (
        Exchange, OrderRequest, OrderSide, OrderType,
    )

    executor = _get_prediction_executor()

    try:
        exchange = Exchange(req.exchange)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown exchange: {req.exchange}")

    try:
        side = OrderSide(req.side.upper())
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid side: {req.side}")

    try:
        order_type = OrderType(req.order_type.upper())
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid order type: {req.order_type}")

    order_req = OrderRequest(
        exchange=exchange,
        market_id=req.market_id,
        token_id=req.token_id,
        side=side,
        order_type=order_type,
        size=req.size,
        price=req.price,
        strategy=req.strategy,
    )

    result = executor.execute(order_req)

    # Persist to DB
    try:
        from ..db.database import get_session
        from ..prediction_markets.models import PredictionOrder

        with get_session() as session:
            db_order = PredictionOrder(
                portfolio_id=1,  # Default portfolio
                order_id=result.order_id,
                exchange=result.exchange.value,
                market_id=result.market_id,
                token_id=result.token_id,
                side=result.side.value,
                order_type=result.order_type.value,
                size=result.size,
                limit_price=result.price,
                status=result.status.value,
                filled_size=result.filled_size,
                filled_price=result.filled_price,
                fees=result.fees,
                strategy=req.strategy,
                error=result.error,
                is_dry_run=executor.dry_run,
                raw_response_json=json.dumps(result.raw_response) if result.raw_response else None,
            )
            session.add(db_order)
    except Exception as e:
        logger.warning(f"Failed to persist order to DB: {e}")

    return {
        "order_id": result.order_id,
        "exchange": result.exchange.value,
        "market_id": result.market_id,
        "side": result.side.value,
        "order_type": result.order_type.value,
        "size": result.size,
        "price": result.price,
        "status": result.status.value,
        "filled_size": result.filled_size,
        "filled_price": result.filled_price,
        "fees": result.fees,
        "error": result.error,
        "is_success": result.is_success,
        "dry_run": executor.dry_run,
    }


@router.get("/prediction-markets/portfolio")
async def get_prediction_portfolio():
    """Get prediction market portfolio summary with all positions and P&L."""
    executor = _get_prediction_executor()
    return executor.get_portfolio_summary()


@router.post("/prediction-markets/portfolio/reset", dependencies=_MUTATING_AUTH)
async def reset_prediction_portfolio():
    """Reset all paper trading positions and P&L."""
    executor = _get_prediction_executor()
    try:
        executor.positions.clear()
        executor.order_history.clear()
        executor.total_fees = 0.0

        # Also reset strategy-level state
        scanner = _get_prediction_scanner()
        for s in scanner.strategies:
            s.positions.clear()
            s.total_pnl = 0.0
            s.trades_executed = 0
        scanner.scan_history.clear()
        scanner.total_scans = 0

        return {"status": "ok", "message": "Portfolio and strategy state reset"}
    except Exception as e:
        logger.error(f"Portfolio reset error: {e}")
        raise HTTPException(status_code=500, detail="Portfolio reset failed")


@router.get("/prediction-markets/orders")
async def get_prediction_orders(limit: int = Query(50, ge=1, le=1000)):
    """Get prediction market order history."""
    executor = _get_prediction_executor()
    return {"orders": executor.get_order_history(limit=limit)}


@router.post("/prediction-markets/cancel/{order_id}", dependencies=_MUTATING_AUTH)
async def cancel_prediction_order(
    order_id: str = Path(..., min_length=1, max_length=200),
    exchange: str = Query("polymarket", min_length=1, max_length=50),
):
    """Cancel an open prediction market order."""
    from ..prediction_markets.execution import Exchange
    executor = _get_prediction_executor()
    try:
        ex = Exchange(exchange)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown exchange: {exchange}")

    success = executor.cancel_order(order_id, ex)
    return {"order_id": order_id, "cancelled": success}


# ============ Prediction Markets — WebSocket Feeds ============

@router.get("/prediction-markets/feeds/status")
async def get_prediction_feed_status():
    """Get WebSocket feed connection status for prediction markets."""
    from ..prediction_markets.websocket_feeds import get_feed_manager
    manager = get_feed_manager()
    return manager.get_status()


@router.get("/prediction-markets/feeds/prices")
async def get_prediction_live_prices():
    """Get all live prices from WebSocket feeds."""
    from ..prediction_markets.websocket_feeds import get_feed_manager
    manager = get_feed_manager()
    prices = manager.get_all_prices()
    return {
        "count": len(prices),
        "prices": {
            key: {
                "exchange": p.exchange,
                "market_id": p.market_id,
                "token_id": p.token_id,
                "outcome_label": p.outcome_label,
                "price": p.price,
                "bid": p.bid,
                "ask": p.ask,
                "spread": p.spread,
                "midpoint": p.midpoint,
                "volume_24h": p.volume_24h,
                "last_trade_price": p.last_trade_price,
                "data_age_seconds": p.data_age_seconds,
            }
            for key, p in prices.items()
        },
    }


class SubscribeRequest(BaseModel):
    # §12 input bounds: an unbounded identifiers list let a caller POST millions of
    # token_ids, fanning out unbounded WebSocket subscriptions (resource exhaustion).
    # Cap the list length and each identifier's length.
    exchange: str = Field("polymarket", max_length=50)
    identifiers: List[str] = Field(default_factory=list, max_length=1000)

    @field_validator("identifiers")
    @classmethod
    def _bound_identifier_lengths(cls, v: List[str]) -> List[str]:
        for ident in v:
            if len(ident) > 200:
                raise ValueError("identifier too long (max 200 chars)")
        return v


@router.post("/prediction-markets/feeds/subscribe", dependencies=_MUTATING_AUTH)
async def subscribe_prediction_feeds(req: SubscribeRequest):
    """Subscribe to real-time price updates for specific markets."""
    from ..prediction_markets.websocket_feeds import get_feed_manager
    manager = get_feed_manager()

    if req.exchange == "polymarket":
        await manager.subscribe_polymarket(req.identifiers)
    else:
        raise HTTPException(status_code=400, detail=f"Unknown exchange: {req.exchange}")

    return {
        "subscribed": len(req.identifiers),
        "exchange": req.exchange,
    }


# ============ Prediction Markets — Price History ============

@router.get("/prediction-markets/price-history/{token_id}")
async def get_prediction_price_history(
    token_id: str = Path(..., min_length=1, max_length=200),
    limit: int = Query(100, ge=1, le=1000),
    exchange: str = Query("polymarket", min_length=1, max_length=50),
):
    """Get price history for a prediction market outcome token."""
    from ..db.database import get_session
    from ..prediction_markets.models import PredictionPriceHistory
    from sqlmodel import select

    with get_session() as session:
        statement = (
            select(PredictionPriceHistory)
            .where(PredictionPriceHistory.token_id == token_id)
            .where(PredictionPriceHistory.exchange == exchange)
            .order_by(PredictionPriceHistory.sampled_at.desc())
            .limit(limit)
        )
        results = session.exec(statement).all()

    return {
        "token_id": token_id,
        "exchange": exchange,
        "count": len(results),
        "history": [
            {
                "price": r.price,
                "bid": r.bid,
                "ask": r.ask,
                "spread": r.spread,
                "volume_24h": r.volume_24h,
                "sampled_at": r.sampled_at.isoformat(),
            }
            for r in reversed(results)  # Chronological order
        ],
    }


# ============ Prediction Markets — P&L Snapshots ============

@router.get("/prediction-markets/pnl-history")
async def get_prediction_pnl_history(
    portfolio_id: int = Query(1, ge=1, le=1_000_000),
    limit: int = Query(200, ge=1, le=5000),
):
    """Get P&L snapshot history for equity curve charting."""
    from ..db.database import get_session
    from ..prediction_markets.models import PredictionPnLSnapshot
    from sqlmodel import select

    with get_session() as session:
        statement = (
            select(PredictionPnLSnapshot)
            .where(PredictionPnLSnapshot.portfolio_id == portfolio_id)
            .order_by(PredictionPnLSnapshot.snapshot_at.desc())
            .limit(limit)
        )
        results = session.exec(statement).all()
        # Build response inside session to avoid DetachedInstanceError
        snapshots = [
            {
                "total_value_usd": s.total_value_usd,
                "cash_usd": s.cash_usd,
                "positions_value_usd": s.positions_value_usd,
                "realized_pnl": s.realized_pnl,
                "unrealized_pnl": s.unrealized_pnl,
                "total_fees": s.total_fees,
                "num_positions": s.num_positions,
                "polymarket_value": s.polymarket_value,
                "snapshot_at": s.snapshot_at.isoformat(),
            }
            for s in reversed(results)
        ]

    return {
        "portfolio_id": portfolio_id,
        "count": len(snapshots),
        "snapshots": snapshots,
    }


# ============ Prediction Markets — Orchestrator ============

_orchestrator_instance = None


def _get_orchestrator():
    global _orchestrator_instance
    if _orchestrator_instance is None:
        from ..prediction_markets.orchestrator import get_orchestrator
        _orchestrator_instance = get_orchestrator()
        # Ensure scanner and executor are wired up
        if _orchestrator_instance.scanner is None:
            _orchestrator_instance.scanner = _get_prediction_scanner()
        if _orchestrator_instance.executor is None:
            from ..prediction_markets.execution import get_executor
            _orchestrator_instance.executor = get_executor(dry_run=True)
        # The orchestrator is constructed with scanner=None, so its B3 registry seeds
        # empty at __init__; now that the scanner is attached, seed the deployed
        # strategies as PROPOSED (idempotent — reviewer S1, else the registry is empty
        # forever in the normal API path).
        try:
            _orchestrator_instance.sync_registry_with_scanner()
        except Exception as e:
            logger.debug(f"[ORCHESTRATOR] registry sync skipped: {e}")
    return _orchestrator_instance


@router.post("/prediction-markets/bot/start", dependencies=_MUTATING_AUTH)
async def start_prediction_bot(
    # Bound the scan interval: a non-positive value would spin the scan loop with no delay
    # (CPU exhaustion / venue hammering); cap at 1 day. Guards the authed control surface
    # against a compromised/fat-fingered token holder (extends the #99/#109 §12 bounds).
    scan_interval_sec: int = Query(120, gt=0, le=86400),
    dry_run: bool = True,
):
    """
    Start the prediction market trading bot.

    The bot runs scan → Kelly size → execute → persist in a loop.
    Default: dry_run=True (paper trading).
    """
    orchestrator = _get_orchestrator()
    if orchestrator._running:
        return {"status": "already_running", **orchestrator.get_status()}

    # Update executor dry_run setting
    executor = _get_prediction_executor()
    executor.dry_run = dry_run

    orchestrator.scan_interval_sec = scan_interval_sec
    orchestrator.scanner = _get_prediction_scanner()
    orchestrator.executor = executor

    await orchestrator.start()

    return {
        "status": "started",
        "dry_run": dry_run,
        "scan_interval_sec": scan_interval_sec,
    }


@router.post("/prediction-markets/bot/stop", dependencies=_MUTATING_AUTH)
async def stop_prediction_bot():
    """Stop the prediction market trading bot."""
    orchestrator = _get_orchestrator()
    if not orchestrator._running:
        return {"status": "not_running"}

    await orchestrator.stop()
    return {"status": "stopped", **orchestrator.get_status()}


@router.get("/prediction-markets/bot/status")
async def get_prediction_bot_status():
    """Get full bot status: orchestrator, risk manager, portfolio, MTM."""
    orchestrator = _get_orchestrator()
    return orchestrator.get_status()


@router.get("/prediction-markets/bot/activity")
async def get_prediction_activity_log(limit: int = Query(50, ge=1, le=1000)):
    """Get recent activity log entries and last scan opportunities from the orchestrator."""
    orchestrator = _get_orchestrator()
    return {
        "entries": orchestrator.activity_log[:limit],
        "total_scans": orchestrator.total_scans,
        "total_executions": orchestrator.total_executions,
        "last_scan_result": orchestrator.last_scan_result,
        "opportunities": orchestrator.last_scan_opportunities_raw,
    }


@router.post("/prediction-markets/bot/scan-now", dependencies=_MUTATING_AUTH)
async def trigger_scan_and_execute():
    """Manually trigger one scan-and-execute cycle.

    Runs scan as a background asyncio task to avoid blocking the request
    and causing ECONNRESET on the frontend proxy.  Also auto-starts the
    bot loop so subsequent scans happen automatically without manual clicks.
    """
    import asyncio

    orchestrator = _get_orchestrator()
    if not orchestrator.scanner:
        orchestrator.scanner = _get_prediction_scanner()
    if not orchestrator.executor:
        orchestrator.executor = _get_prediction_executor()

    # Fire-and-forget: run the heavy scan in the background
    async def _bg_scan():
        try:
            await orchestrator.scan_and_execute()
        except Exception as e:
            logger.error(f"Background scan failed: {e}")

    asyncio.create_task(_bg_scan())

    # Auto-start the bot loop so future scans are fully automated
    if not orchestrator._running:
        await orchestrator.start()

    return {
        "status": "scan_queued",
        "bot_running": orchestrator._running,
        "total_scans": orchestrator.total_scans,
        "message": "Scan triggered in background. Bot loop auto-started.",
    }


# ============ Prediction Markets — Metrics (C5 + B2) ============

@router.get("/prediction-markets/metrics/weekly")
async def get_weekly_metrics():
    """
    Weekly PnL series and portfolio-level performance summary.

    Computed from genuinely resolved positions only (orchestrator.get_resolved_trades).
    All numbers flow from real trades; if no trades have resolved, returns honest
    zero-valued state — not an error, not stubbed fake numbers.

    Returns
    -------
    JSON with keys:
        source, num_input_trades, total_pnl_usd, avg_weekly_pnl_usd, weekly_sharpe,
        max_drawdown_usd, max_drawdown_pct, hit_rate, total_trades, best_week_usd,
        worst_week_usd, num_weeks, weekly_series (list of per-week dicts).
    """
    from ..prediction_markets.metrics_aggregator import compute_weekly_metrics

    try:
        orchestrator = _get_orchestrator()
        trades = orchestrator.get_resolved_trades()
    except Exception as e:
        logger.warning(f"[METRICS/weekly] get_resolved_trades failed: {e}")
        trades = []

    return compute_weekly_metrics(trades)


@router.get("/prediction-markets/metrics/floor-status")
async def get_floor_status():
    """
    ROADMAP C5 go-live floor status ($2 k/week average PnL threshold).

    Returns
    -------
    JSON with keys:
        meets_floor (bool), floor_usd, avg_weekly_pnl_usd, weeks_counted, total_trades.
    """
    from ..prediction_markets.metrics_aggregator import compute_floor_status

    try:
        orchestrator = _get_orchestrator()
        trades = orchestrator.get_resolved_trades()
    except Exception as e:
        logger.warning(f"[METRICS/floor] get_resolved_trades failed: {e}")
        trades = []

    return compute_floor_status(trades)


@router.get("/prediction-markets/metrics/calibration")
async def get_calibration():
    """
    ROADMAP B2 calibration evaluation.

    Reads resolved positions that have a model_prob distinct from market_price
    (i.e. non-degenerate predictions).  Current paper-trading reality: strategies
    seed model to the crowd price → model_prob == market_price for all records →
    the evaluation is reported as ``"insufficient_degenerate"`` and a plain-language
    note is included.  This endpoint NEVER fabricates a passing calibration.

    Because the calibration module requires ResolvedPrediction records (not just
    TradePnL), and the current DB schema does not store model_prob / market_price /
    outcome per-position, the endpoint returns an honest empty-prediction state until
    the prediction pipeline writes those fields.

    Returns
    -------
    JSON with keys:
        status, n, passes, strategy_brier, baseline_brier, improvement,
        improvement_ci_low, improvement_ci_high, expected_calibration_error, note.
    """
    from ..prediction_markets.metrics_aggregator import compute_calibration

    # The current DB schema does not persist ResolvedPrediction fields
    # (predicted_prob, market_price, outcome) — those would need to be recorded at
    # resolution time by a future pipeline step.  Until then we return an honest
    # empty-prediction state rather than invent numbers.
    predictions = []

    try:
        # Attempt to load from DB if the field ever becomes available.
        # This block is intentionally future-proof; it produces the same
        # honest empty result for now.
        from ..db.database import get_session
        from ..prediction_markets.models import PredictionPosition
        from ..prediction_markets.calibration import ResolvedPrediction
        from sqlmodel import select

        with get_session() as session:
            stmt = select(PredictionPosition).where(
                PredictionPosition.is_resolved == True  # noqa: E712
            )
            db_positions = session.exec(stmt).all()

            for pos in db_positions:
                # edge_at_entry is the GROSS edge the strategy recorded.
                # predicted_prob = market_price + edge_at_entry (our entry model prob).
                # market_price = avg_entry_price (the contemporaneous crowd quote).
                # outcome = 1 if resolution_value >= 0.5, 0 otherwise.
                if pos.resolution_value is None:
                    continue
                if pos.avg_entry_price <= 0.0 or pos.avg_entry_price >= 1.0:
                    continue
                # HONESTY (reviewer MUST-FIX M2): a position with no recorded model
                # edge carries predicted_prob == market_price, which cannot inform a
                # calibration-vs-crowd test. Skip it explicitly rather than silently
                # adding 0.0 and letting it masquerade as a (degenerate) prediction.
                # This makes "no non-degenerate predictions" the honest default for the
                # current paper reality (strategies seed model prob to the crowd).
                if pos.edge_at_entry == 0.0:
                    continue

                market_price = pos.avg_entry_price
                # The strategy's predicted_prob at entry, from the recorded gross edge.
                predicted_prob = market_price + pos.edge_at_entry
                # Clamp to [0, 1].
                predicted_prob = max(0.0, min(1.0, predicted_prob))
                outcome = 1 if pos.resolution_value >= 0.5 else 0

                predictions.append(
                    ResolvedPrediction(
                        market_id=pos.market_id,
                        predicted_prob=predicted_prob,
                        market_price=market_price,
                        outcome=outcome,
                    )
                )
    except Exception as e:
        logger.debug(f"[METRICS/calibration] DB prediction load failed: {e}")
        predictions = []

    return compute_calibration(predictions)


@router.get("/prediction-markets/metrics/per-strategy")
async def get_per_strategy_metrics():
    """
    ROADMAP E6 — per-strategy realized-PnL attribution.

    Groups genuinely-resolved positions by the strategy that opened them
    (orchestrator.get_resolved_trades_by_strategy) and reports each alpha's realized
    PnL, hit-rate, best/worst trade, and weekly series, plus a ranking by total PnL.

    Honest: strategies with zero resolved trades never appear (no fabricated rows);
    untagged positions bucket under ``"unattributed"`` so totals still reconcile.
    Empty input → ``{"strategies": [], "ranking": [], "num_input_trades": 0}``.
    """
    from ..prediction_markets.metrics_aggregator import compute_per_strategy_metrics

    try:
        orchestrator = _get_orchestrator()
        trades = orchestrator.get_resolved_trades_by_strategy()
    except Exception as e:
        logger.warning(f"[METRICS/per-strategy] get_resolved_trades_by_strategy failed: {e}")
        trades = []

    return compute_per_strategy_metrics(trades)


@router.get("/prediction-markets/metrics/evaluation-windows")
async def get_evaluation_windows():
    """
    ROADMAP E5 — per-window realized metrics (evaluation-window engine).

    Buckets genuinely-resolved, strategy-tagged trades into ISO-week windows
    (orchestrator.get_resolved_evaluation_trades) and reports each window's realized
    PnL / hit-rate / drawdown. Only windows with >= 1 trade are emitted (never
    fabricated); Brier stays null until per-trade calibration signals are persisted.

    Returns
    -------
    JSON with keys: source, num_input_trades, num_windows, windows (list).
    """
    from ..prediction_markets.metrics_aggregator import compute_evaluation_windows

    try:
        orchestrator = _get_orchestrator()
        trades = orchestrator.get_resolved_evaluation_trades()
    except Exception as e:
        logger.warning(f"[METRICS/eval-windows] get_resolved_evaluation_trades failed: {e}")
        trades = []

    return compute_evaluation_windows(trades)


@router.get("/prediction-markets/metrics/calibration-drift")
async def get_calibration_drift():
    """
    ROADMAP E2 — calibration-drift signal (significance-gated).

    Splits time-ordered resolved NON-degenerate predictions
    (orchestrator.get_resolved_predictions) into an older baseline + a recent window and
    runs the drift detector. Honest: with too few non-degenerate predictions — the
    current paper reality — it returns ``status="insufficient_data"`` and never raises a
    false drift alarm (E7 discipline).

    Returns
    -------
    JSON: either an ``insufficient_data`` status dict, or ``status="evaluated"`` plus the
    full drift result (drift_detected, severity, brier deltas, CI, de_rating, …).
    """
    from ..prediction_markets.metrics_aggregator import compute_calibration_drift

    try:
        orchestrator = _get_orchestrator()
        preds = orchestrator.get_resolved_predictions()
    except Exception as e:
        logger.warning(f"[METRICS/drift] get_resolved_predictions failed: {e}")
        preds = []

    return compute_calibration_drift(preds)


@router.get("/prediction-markets/strategies/registry")
async def get_strategy_registry():
    """
    ROADMAP B3 — the alpha-lifecycle registry snapshot (READ-ONLY).

    Returns each alpha's current lifecycle state (proposed → backtesting → paper →
    promoted → retired) and its append-only transition history with recorded
    evidence. Deterministic, JSON-serializable. In the current paper reality every
    deployed strategy is seeded ``proposed`` (no backtest/OOS/calibration evidence
    recorded yet) — the registry truthfully shows that NO alpha has passed the
    integrity gate.

    NOTE (honesty, ROADMAP B3 follow-up): there is deliberately NO public WRITE
    endpoint for lifecycle transitions yet. The registry engine gates on the PRESENCE
    of caller-supplied evidence (backtest/OOS/calibration booleans) — it is an audit
    trail, not an authenticity verifier — so exposing a transition over an HTTP body
    would let a caller PROMOTE an alpha with self-asserted (fabricated) evidence. Real
    transitions are recorded only by trusted in-process code
    (``orchestrator.record_strategy_transition``) once it DERIVES the evidence from the
    actual E5/E2 gate results. Wiring that derivation + a secured write path is the
    named follow-up; until then we do not expose a fabricable promotion surface.
    """
    try:
        orchestrator = _get_orchestrator()
        return orchestrator.get_strategy_registry()
    except Exception as e:
        logger.warning(f"[STRATEGIES/registry] snapshot failed: {e}")
        return {"alphas": []}


# ============ Prediction Markets — Risk Manager ============

@router.get("/prediction-markets/risk/status")
async def get_risk_status():
    """Get risk manager status (daily P&L, circuit breaker, limits)."""
    orchestrator = _get_orchestrator()
    return orchestrator.risk_manager.get_status()


@router.post("/prediction-markets/risk/enable-strategy/{strategy_name}", dependencies=_MUTATING_AUTH)
async def enable_strategy(strategy_name: str = Path(..., min_length=1, max_length=100)):
    """Re-enable a strategy that was auto-disabled by drawdown."""
    orchestrator = _get_orchestrator()
    orchestrator.risk_manager.enable_strategy(strategy_name)
    return {"strategy": strategy_name, "enabled": True}


class RiskConfigUpdate(BaseModel):
    daily_loss_limit_usd: Optional[float] = None
    max_portfolio_exposure_usd: Optional[float] = None
    max_single_position_usd: Optional[float] = None
    max_total_positions: Optional[int] = None
    max_orders_per_minute: Optional[int] = None


@router.post("/prediction-markets/risk/config", dependencies=_MUTATING_AUTH)
async def update_risk_config(req: RiskConfigUpdate):
    """Update risk manager configuration."""
    # Bounds-validate BEFORE mutating live limits. A non-positive daily-loss cap would
    # DISABLE loss protection (the check is realized_loss > limit, which a negative limit
    # can never trip); NaN/inf/absurd values are likewise rejected. Pure decision in
    # risk_config_validation so the CI-light gate can test it without fastapi.
    from ..prediction_markets.risk_config_validation import validate_risk_config_update
    errors = validate_risk_config_update(
        daily_loss_limit_usd=req.daily_loss_limit_usd,
        max_portfolio_exposure_usd=req.max_portfolio_exposure_usd,
        max_single_position_usd=req.max_single_position_usd,
        max_total_positions=req.max_total_positions,
        max_orders_per_minute=req.max_orders_per_minute,
    )
    if errors:
        raise HTTPException(status_code=422, detail={"errors": errors})

    orchestrator = _get_orchestrator()
    config = orchestrator.risk_manager.config

    if req.daily_loss_limit_usd is not None:
        config.daily_loss_limit_usd = req.daily_loss_limit_usd
    if req.max_portfolio_exposure_usd is not None:
        config.max_portfolio_exposure_usd = req.max_portfolio_exposure_usd
    if req.max_single_position_usd is not None:
        config.max_single_position_usd = req.max_single_position_usd
    if req.max_total_positions is not None:
        config.max_total_positions = req.max_total_positions
    if req.max_orders_per_minute is not None:
        config.max_orders_per_minute = req.max_orders_per_minute

    return {"status": "updated", "config": orchestrator.risk_manager.get_status()}


# ============ Prediction Markets — Kill Switch ============

@router.post("/prediction-markets/kill-switch/activate", dependencies=_MUTATING_AUTH)
async def activate_kill_switch(reason: str = Query("manual", max_length=200)):
    """Emergency kill switch — immediately blocks ALL new orders."""
    executor = _get_prediction_executor()
    executor.activate_kill_switch(reason=reason)
    return {
        "status": "activated",
        "reason": reason,
        "timestamp": datetime.now().isoformat(),
        "positions_held": len(executor.positions),
        "exposure_usd": executor.total_exposure,
    }


@router.post("/prediction-markets/kill-switch/deactivate", dependencies=_MUTATING_AUTH)
async def deactivate_kill_switch():
    """Deactivate the kill switch and resume trading."""
    executor = _get_prediction_executor()
    was_active = executor.kill_switch_active
    executor.deactivate_kill_switch()
    return {
        "status": "deactivated",
        "was_active": was_active,
    }


@router.get("/prediction-markets/kill-switch/status")
async def kill_switch_status():
    """Get kill switch status."""
    executor = _get_prediction_executor()
    return {
        "active": executor._kill_switch_active,
        "reason": executor._kill_switch_reason,
        "activated_at": executor._kill_switch_time.isoformat() if executor._kill_switch_time else None,
        "positions_held": len(executor.positions),
        "exposure_usd": executor.total_exposure,
    }


# ============ Prediction Markets — Quant Model Diagnostics ============

@router.get("/prediction-markets/quant/vpin")
async def get_vpin_metrics(token_id: Optional[str] = Query(None, max_length=200)):
    """Get VPIN (Volume-synchronized Probability of Informed Trading) metrics."""
    try:
        scanner = _get_prediction_scanner()
        for strategy in scanner.strategies:
            if strategy.name == "market_making" and hasattr(strategy, "_vpin"):
                vpin_tracker = strategy._vpin
                if token_id:
                    vpin_val = vpin_tracker.get_vpin(token_id)
                    is_toxic = vpin_tracker.is_toxic(token_id) if hasattr(vpin_tracker, "is_toxic") else (vpin_val or 0) > 0.7
                    return {
                        "token_id": token_id,
                        "vpin": vpin_val,
                        "is_toxic": is_toxic,
                        "threshold": 0.7,
                    }
                else:
                    # Return all tracked tokens
                    all_vpin = {}
                    for tid in vpin_tracker._buckets:
                        val = vpin_tracker.get_vpin(tid)
                        if val is not None:
                            all_vpin[tid] = {"vpin": val, "is_toxic": val > 0.7}
                    return {"tracked_tokens": len(all_vpin), "metrics": all_vpin}
        return {"error": "Market making strategy not active or VPIN tracker not initialized"}
    except Exception as e:
        logger.error(f"VPIN metrics error: {e}")
        raise HTTPException(status_code=500, detail="VPIN metrics unavailable")


@router.get("/prediction-markets/quant/avellaneda-stoikov")
async def get_as_diagnostics(
    token_id: str = Query(..., min_length=1, max_length=200),
    mid_price: float = Query(..., ge=0.0, le=1.0),
    inventory: float = Query(0.0, ge=-1_000_000.0, le=1_000_000.0),
    hours_to_resolution: float = Query(24.0, gt=0.0, le=100_000.0),
):
    """Get Avellaneda-Stoikov optimal quotes for a given market state."""
    try:
        from ..prediction_markets.quant_models import AvellanedaStoikovModel
        model = AvellanedaStoikovModel()
        bid, ask, diagnostics = model.compute_quotes(
            token_id=token_id,
            mid_price=mid_price,
            inventory=inventory,
            time_to_resolution_hours=hours_to_resolution,
        )
        return {
            "bid": bid,
            "ask": ask,
            "spread": ask - bid if bid and ask else None,
            "diagnostics": diagnostics,
        }
    except Exception as e:
        logger.error(f"Avellaneda-Stoikov diagnostics error: {e}")
        raise HTTPException(status_code=500, detail="Quote diagnostics failed")


@router.get("/prediction-markets/quant/bayesian")
async def get_bayesian_priors():
    """Get all active Bayesian priors and posteriors."""
    try:
        from ..prediction_markets.quant_models import BayesianUpdater
        updater = BayesianUpdater()
        # Return the singleton state if market making strategy has one
        scanner = _get_prediction_scanner()
        for strategy in scanner.strategies:
            if hasattr(strategy, "_bayesian"):
                updater = strategy._bayesian
                break
        priors = {}
        for key, (alpha, beta) in updater._priors.items():
            mean = alpha / (alpha + beta)
            priors[key] = {
                "alpha": alpha,
                "beta": beta,
                "mean": mean,
                "confidence": alpha + beta,
            }
        return {"active_priors": len(priors), "priors": priors}
    except Exception as e:
        logger.error(f"Bayesian priors error: {e}")
        raise HTTPException(status_code=500, detail="Bayesian priors unavailable")


@router.post("/prediction-markets/quant/bayesian/update", dependencies=_MUTATING_AUTH)
async def update_bayesian_prior(
    key: str = Query(..., min_length=1, max_length=200),
    signal_mean: float = Query(..., ge=0.0, le=1.0),
    signal_weight: float = Query(5.0, gt=0.0, le=1_000_000.0),
):
    """Update a Bayesian prior with a new signal (e.g., from news, polls)."""
    try:
        from ..prediction_markets.quant_models import BayesianUpdater
        scanner = _get_prediction_scanner()
        for strategy in scanner.strategies:
            if hasattr(strategy, "_bayesian"):
                strategy._bayesian.update_with_signal(key, signal_mean, signal_weight)
                alpha, beta = strategy._bayesian._priors[key]
                return {
                    "key": key,
                    "updated_mean": alpha / (alpha + beta),
                    "alpha": alpha,
                    "beta": beta,
                }
        return {"error": "No strategy with Bayesian updater found"}
    except Exception as e:
        logger.error(f"Bayesian update error: {e}")
        raise HTTPException(status_code=500, detail="Bayesian update failed")


@router.get("/prediction-markets/quant/monte-carlo-kelly")
async def get_mc_kelly_estimate(
    naive_kelly_fraction: float = Query(0.05, gt=0.0, le=1.0),
    bankroll: float = Query(500.0, gt=0.0, le=1_000_000_000.0),
    strategy: str = Query("market_making", min_length=1, max_length=100),
):
    """Run Monte Carlo Kelly simulation and return sizing recommendation."""
    try:
        from ..prediction_markets.quant_models import MonteCarloKelly
        mc = MonteCarloKelly()
        result = mc.compute_size(
            strategy=strategy,
            naive_kelly_fraction=naive_kelly_fraction,
            bankroll=bankroll,
        )
        return result
    except Exception as e:
        logger.error(f"Monte Carlo Kelly error: {e}")
        raise HTTPException(status_code=500, detail="Kelly sizing failed")
