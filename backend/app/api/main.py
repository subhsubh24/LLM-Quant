"""
FastAPI application entry point.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .. import __version__, DISCLAIMER
from ..config import get_settings
from ..db.database import init_db
from ..prediction_markets.websocket_feeds import start_prediction_feeds, stop_prediction_feeds
from ..prediction_markets.orchestrator import init_orchestrator, stop_orchestrator
from .routes import router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup
    logger.info("Starting QuantLab API...")
    init_db()
    logger.info("Database initialized")

    # Start prediction market WebSocket feeds (Polymarket)
    try:
        await start_prediction_feeds()
        logger.info("Prediction market WebSocket feeds started")
    except Exception as e:
        logger.warning(f"Prediction market feeds start failed (degraded): {e}")

    # Bootstrap default prediction market portfolio (ensures FK target exists)
    try:
        from ..prediction_markets.models import PredictionPortfolio
        from ..db.database import get_session
        from sqlmodel import select
        with get_session() as session:
            existing = session.exec(
                select(PredictionPortfolio).where(PredictionPortfolio.id == 1)
            ).first()
            if not existing:
                session.add(PredictionPortfolio(
                    name="default",
                    exchange="all",
                    initial_capital_usd=100.0,
                    current_cash_usd=100.0,
                    total_deposited_usd=100.0,
                    total_value_usd=100.0,
                    dry_run=True,
                ))
                logger.info("Created default prediction market portfolio")
    except Exception as e:
        logger.warning(f"Portfolio bootstrap skipped: {e}")

    # Initialize prediction market orchestrator (but don't start scanning)
    # User can start the bot from the Predictions UI or trigger manual scans
    try:
        init_orchestrator(scan_interval_sec=120)
        logger.info("Prediction market orchestrator initialized (idle — start from UI)")
    except Exception as e:
        logger.warning(f"Prediction market orchestrator init failed (degraded): {e}")

    # NOTE: Equity/crypto live-broker auto-connect removed (ROADMAP A1 — retire
    # stock/crypto trading). Prediction-markets is the only venue path now; its live
    # path is gated behind LIVE_TRADING_ENABLED in the prediction_markets executor.

    yield

    # Shutdown
    logger.info("Shutting down QuantLab API...")
    await stop_orchestrator()
    await stop_prediction_feeds()
    logger.info("Prediction market feeds stopped")


app = FastAPI(
    title="QuantLab API",
    description=f"""
    Rigorous Quant Research & Paper Trading Education Platform

    {DISCLAIMER}
    """,
    version=__version__,
    lifespan=lifespan,
)

# CORS configuration
# Local dev origins are always allowed. Deployed frontends (e.g. the Vercel domain)
# are added via the CORS_ALLOW_ORIGINS env var (comma-separated, exact origins —
# scheme + host, no trailing slash), since allow_credentials=True forbids a wildcard.
_default_cors_origins = [
    "http://localhost:3000",
    "http://localhost:3001",
    "http://localhost:3002",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:3001",
    "http://127.0.0.1:3002",
]
_extra_cors = [
    o.strip()
    for o in (get_settings().cors_allow_origins or "").split(",")
    if o.strip()
]
_allow_origins = _default_cors_origins + _extra_cors
logger.info(f"CORS allowed origins: {_allow_origins}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allow_origins,
    allow_credentials=True,
    # BUG FIX #43: Restrict to safe HTTP methods (not TRACE, CONNECT)
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["*"],
)

# Include routes
app.include_router(router, prefix="/api")


@app.get("/")
async def root():
    """Root endpoint with disclaimer."""
    return {
        "name": "QuantLab",
        "version": __version__,
        "disclaimer": DISCLAIMER,
        "docs": "/docs",
    }


@app.get("/health")
async def health():
    """Health check endpoint."""
    settings = get_settings()
    return {
        "status": "healthy",
        "demo_mode": settings.demo_mode,
        "llm_available": settings.has_llm_key,
        "live_trading_enabled": settings.live_trading_enabled,
    }
