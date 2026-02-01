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
from ..data.binance_ws import start_binance_ws, stop_binance_ws
from .routes import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup
    logger.info("Starting QuantLab API...")
    init_db()
    logger.info("Database initialized")

    # Start Binance WebSocket for real-time crypto prices
    await start_binance_ws()
    logger.info("✅ Binance WebSocket started - LIVE crypto prices enabled")

    yield

    # Shutdown
    logger.info("Shutting down QuantLab API...")
    await stop_binance_ws()
    logger.info("Binance WebSocket stopped")


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
    return {
        "status": "healthy",
        "demo_mode": settings.demo_mode,
        "llm_available": settings.has_llm_key,
    }
