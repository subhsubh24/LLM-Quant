"""
FastAPI application entry point.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import logging

logger = logging.getLogger(__name__)

from .. import __version__, DISCLAIMER
from ..config import get_settings
from ..db.database import init_db
from ..data.crypto_ws import start_crypto_ws, stop_crypto_ws
from .routes import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup
    logger.info("Starting QuantLab API...")
    init_db()
    logger.info("Database initialized")

    # Start multi-provider WebSocket for real-time crypto prices
    # Tries: Coinbase -> Kraken -> Binance.US -> Binance Global
    await start_crypto_ws()
    logger.info("Crypto WebSocket started - LIVE prices enabled")

    # Auto-initialize live brokers from config
    settings = get_settings()
    if settings.auto_connect_brokers:
        try:
            from ..trading.live_brokers import auto_initialize_brokers
            broker_results = await auto_initialize_brokers()
            if broker_results.get("errors"):
                logger.warning(f"Broker init warnings: {broker_results['errors']}")
            else:
                logger.info(f"Live brokers initialized: {broker_results}")
        except Exception as e:
            logger.warning(f"Broker auto-init skipped: {e}")

    # Initialize Supabase for portfolio persistence
    if settings.supabase_enabled and settings.supabase_url and settings.supabase_key:
        try:
            from ..data.supabase_client import init_supabase
            await init_supabase(settings.supabase_url, settings.supabase_key)
            logger.info("Supabase initialized - portfolio persistence enabled")
        except Exception as e:
            logger.warning(f"Supabase init failed: {e}")

    yield

    # Shutdown
    logger.info("Shutting down QuantLab API...")
    await stop_crypto_ws()

    # Disconnect brokers
    try:
        from ..trading.live_brokers import get_broker_manager
        manager = get_broker_manager()
        await manager.disconnect_all()
        logger.info("Brokers disconnected")
    except Exception as e:
        logger.warning(f"Broker disconnect error: {e}")

    logger.info("Crypto WebSocket stopped")


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
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:3001",
        "http://localhost:3002",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:3001",
        "http://127.0.0.1:3002",
    ],
    allow_credentials=True,
    allow_methods=["*"],
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

    # Get broker status
    broker_status = {"alpaca": "not_configured", "binance": "not_configured"}
    try:
        from ..trading.live_brokers import get_broker_manager
        manager = get_broker_manager()
        status = manager.get_status()
        broker_status = {
            "alpaca": "connected" if status["alpaca"]["connected"] else ("configured" if status["alpaca"]["configured"] else "not_configured"),
            "binance": "connected" if status["binance"]["connected"] else ("configured" if status["binance"]["configured"] else "not_configured"),
        }
    except:
        pass

    return {
        "status": "healthy",
        "demo_mode": settings.demo_mode,
        "llm_available": settings.has_llm_key,
        "brokers": broker_status,
        "live_data_enabled": broker_status["alpaca"] == "connected" or broker_status["binance"] == "connected",
    }
