"""
API routes for QuantLab.
"""

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Header
from pydantic import BaseModel, Field
from typing import Dict, List, Optional, Any
from datetime import date, datetime, timedelta
import json
import logging

logger = logging.getLogger(__name__)
import numpy as np
import pandas as pd

from ..db.database import get_session_dependency
from ..db.models import Universe, BacktestRun, PaperPortfolio, PaperPosition
from ..data import DataCache, UniverseManager, get_data_provider
from ..features import FeaturePipeline, FeatureConfig
from ..models import ModelConfig, ModelTrainer, EnsembleRanker
from ..portfolio import PortfolioConfig, MeanVarianceOptimizer, RiskManager
from ..portfolio.optimizer import estimate_covariance, estimate_expected_returns
from ..backtest import BacktestConfig, BacktestEngine
from ..llm import QuantExplainer, QuantTutor, ResearchMemoGenerator
from ..config import get_settings
from .. import DISCLAIMER

router = APIRouter()


# ============ Debug/Health Endpoints ============

@router.get("/debug/routes-loaded")
async def debug_routes_loaded():
    """Debug endpoint to verify all routes are loaded."""
    return {
        "status": "ok",
        "message": "All routes loaded successfully",
        "sections": ["universes", "data", "features", "models", "backtest", "portfolio", "trading", "options", "crypto", "bot", "prediction-markets"]
    }


# ============ Request/Response Models ============

class UniverseCreate(BaseModel):
    name: str
    description: str = ""
    tickers: List[str]


class UniverseResponse(BaseModel):
    id: int
    name: str
    description: str
    tickers: List[str]
    sectors: Dict[str, List[str]]


class DataRequest(BaseModel):
    universe_name: str = "liquid_50"
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    refresh: bool = False


class FeatureRequest(BaseModel):
    universe_name: str = "liquid_50"
    enabled_features: List[str] = ["returns", "momentum", "volatility", "drawdown"]
    standardize_method: str = "cross_sectional"


class ModelRequest(BaseModel):
    model_config = {"protected_namespaces": ()}
    model_type: str = "ensemble"
    model_params: Dict[str, Any] = {}
    train_window_days: int = 756
    validation_window_days: int = 63
    prediction_horizon: int = 5


class BacktestRequest(BaseModel):
    universe_name: str = "liquid_50"
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    rebalance_frequency: str = "weekly"
    # FIX #8: Add validators to prevent invalid input values
    initial_cash: float = Field(default=100000.0, gt=0, description="Initial cash must be positive")
    transaction_cost_bps: float = Field(default=10.0, ge=0, le=1000, description="Transaction cost in basis points")
    max_position_weight: float = Field(default=0.10, gt=0, le=1.0, description="Max position weight 0-100%")
    target_volatility: float = Field(default=0.15, gt=0, le=1.0, description="Target volatility 0-100%")


class PaperTradeRequest(BaseModel):
    ticker: str
    side: str  # buy, sell
    shares: float
    portfolio_name: str = "default"


class ExplainRequest(BaseModel):
    topic: str  # data, features, model, portfolio, backtest
    context: Dict[str, Any] = {}


# ============ Universe Endpoints ============

@router.get("/universes")
async def list_universes(session=Depends(get_session_dependency)):
    """List all available universes."""
    manager = UniverseManager(session)
    universes = manager.list_universes()

    # Ensure default exists
    if not universes:
        manager.get_or_create_default()
        universes = manager.list_universes()

    return [
        UniverseResponse(
            id=u.id,
            name=u.name,
            description=u.description,
            tickers=u.tickers,
            sectors=u.sectors
        )
        for u in universes
    ]


@router.post("/universes")
async def create_universe(
    request: UniverseCreate,
    session=Depends(get_session_dependency)
):
    """Create a custom universe."""
    manager = UniverseManager(session)

    # Check if exists
    existing = manager.get_by_name(request.name)
    if existing:
        raise HTTPException(status_code=400, detail="Universe already exists")

    universe = manager.create_custom(
        name=request.name,
        description=request.description,
        tickers=request.tickers
    )

    return UniverseResponse(
        id=universe.id,
        name=universe.name,
        description=universe.description,
        tickers=universe.tickers,
        sectors=universe.sectors
    )


# ============ Data Endpoints ============

@router.post("/data/fetch")
async def fetch_data(
    request: DataRequest,
    session=Depends(get_session_dependency)
):
    """Fetch price data for a universe."""
    manager = UniverseManager(session)
    universe = manager.get_by_name(request.universe_name)

    if universe is None:
        universe = manager.get_or_create_default()

    # Default date range
    end_date = request.end_date or date.today()
    start_date = request.start_date or (end_date - timedelta(days=365 * 5))

    cache = DataCache(session)
    data = cache.get_multiple(
        universe.tickers,
        start_date,
        end_date,
        refresh=request.refresh
    )

    return {
        "universe": universe.name,
        "tickers_requested": len(universe.tickers),
        "tickers_fetched": len(data),
        "start_date": str(start_date),
        "end_date": str(end_date),
        "data_quality": {
            ticker: cache.get_data_quality_report(ticker)
            for ticker in list(data.keys())[:5]  # Sample
        }
    }


@router.get("/data/prices/{universe_name}")
async def get_prices(
    universe_name: str,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    session=Depends(get_session_dependency)
):
    """Get price matrix for a universe."""
    manager = UniverseManager(session)
    universe = manager.get_by_name(universe_name)

    if universe is None:
        raise HTTPException(status_code=404, detail="Universe not found")

    end_date = end_date or date.today()
    start_date = start_date or (end_date - timedelta(days=365))

    cache = DataCache(session)
    prices = cache.get_price_matrix(universe.tickers, start_date, end_date)

    if prices.empty:
        raise HTTPException(status_code=404, detail="No price data available")

    # Convert to dict for JSON serialization
    # FIX #7: Don't mask missing data with fillna(0) - return NaN/null instead
    return {
        "dates": [str(d.date()) for d in prices.index],
        "tickers": prices.columns.tolist(),
        "prices": prices.where(pd.notna(prices), None).values.tolist(),  # Convert NaN to None for JSON
    }


# ============ Feature Endpoints ============

@router.post("/features/compute")
async def compute_features(
    request: FeatureRequest,
    session=Depends(get_session_dependency)
):
    """Compute features for a universe."""
    manager = UniverseManager(session)
    universe = manager.get_by_name(request.universe_name)

    if universe is None:
        raise HTTPException(status_code=404, detail="Universe not found")

    # Get price data
    end_date = date.today()
    start_date = end_date - timedelta(days=365 * 5)

    cache = DataCache(session)
    prices = cache.get_price_matrix(universe.tickers, start_date, end_date)

    if prices.empty:
        raise HTTPException(status_code=404, detail="No price data available")

    # Get volume data if available
    volumes = cache.get_price_matrix(universe.tickers, start_date, end_date, "volume")

    # Configure and run pipeline
    config = FeatureConfig(
        enabled_features=request.enabled_features,
        standardize_method=request.standardize_method
    )

    pipeline = FeaturePipeline(config)

    # Get market proxy for risk features
    market_proxy = None
    if "SPY" in prices.columns:
        market_proxy = prices["SPY"]
    elif len(prices.columns) > 0:
        market_proxy = prices.mean(axis=1)

    features = pipeline.compute_features(
        prices=prices,
        volumes=volumes if not volumes.empty else None,
        market_proxy=market_proxy
    )

    return {
        "n_features": len(features.columns),
        "n_samples": len(features),
        "feature_groups": pipeline.get_feature_importance_groups(),
        "missing_pct": float(features.isna().mean().mean()),
        "config_hash": config.compute_hash(),
    }


# ============ Model Endpoints ============

@router.post("/model/train")
async def train_model(
    request: ModelRequest,
    background_tasks: BackgroundTasks,
    session=Depends(get_session_dependency)
):
    """Train and validate a model."""
    # This is a simplified version - full implementation would be more complex
    config = ModelConfig(
        model_type=request.model_type,
        model_params=request.model_params,
        train_window_days=request.train_window_days,
        validation_window_days=request.validation_window_days,
        prediction_horizon=request.prediction_horizon
    )

    return {
        "status": "training_started",
        "config_hash": config.compute_hash(),
        "message": "Model training initiated. Check /model/status for progress."
    }


# ============ Backtest Endpoints ============

@router.post("/backtest/run")
async def run_backtest(
    request: BacktestRequest,
    session=Depends(get_session_dependency)
):
    """Run a full backtest."""
    settings = get_settings()

    # Get universe
    manager = UniverseManager(session)
    universe = manager.get_by_name(request.universe_name)
    if universe is None:
        universe = manager.get_or_create_default()

    # Get price data
    end_date = request.end_date or date.today()
    start_date = request.start_date or (end_date - timedelta(days=365 * 5))

    cache = DataCache(session)
    prices = cache.get_price_matrix(universe.tickers, start_date, end_date)

    if prices.empty or len(prices) < 500:
        raise HTTPException(
            status_code=400,
            detail="Insufficient data for backtest (need at least 500 days)"
        )

    # Get volume data
    volumes = cache.get_price_matrix(universe.tickers, start_date, end_date, "volume")

    # Compute features
    feature_config = FeatureConfig()
    pipeline = FeaturePipeline(feature_config)

    market_proxy = prices["SPY"] if "SPY" in prices.columns else prices.mean(axis=1)

    features = pipeline.compute_features(
        prices=prices,
        volumes=volumes if not volumes.empty else None,
        market_proxy=market_proxy
    )

    # Compute target
    target = pipeline.compute_target(prices, horizon=5)

    # Train model
    model_config = ModelConfig(model_type="ensemble")
    trainer = ModelTrainer(model_config)

    # Flatten features for training (simplified)
    X, y = pipeline.prepare_training_data(features, target.iloc[:, 0])

    if len(X) < 100:
        raise HTTPException(
            status_code=400,
            detail="Insufficient training data after feature computation"
        )

    model, validation_result = trainer.train_and_validate(X, y)

    # Configure backtest
    portfolio_config = PortfolioConfig(
        max_position_weight=request.max_position_weight,
        target_volatility=request.target_volatility
    )

    backtest_config = BacktestConfig(
        start_date=start_date + timedelta(days=365),  # Skip warmup
        end_date=end_date,
        rebalance_frequency=request.rebalance_frequency,
        initial_cash=request.initial_cash,
        transaction_cost_bps=request.transaction_cost_bps,
        portfolio_config=portfolio_config,
        random_seed=settings.demo_seed if settings.demo_mode else 42
    )

    # Run backtest
    engine = BacktestEngine(backtest_config)
    result = engine.run(
        prices=prices,
        model=model,
        features=features,
        volumes=volumes if not volumes.empty else None
    )

    return {
        "config_hash": backtest_config.compute_hash(),
        "metrics": result.metrics.to_dict(),
        "equity_curve": {
            "dates": [str(d.date()) for d in result.equity_curve.index],
            "values": result.equity_curve.values.tolist()
        },
        "benchmark_curve": {
            "dates": [str(d.date()) for d in result.benchmark_curve.index],
            "values": result.benchmark_curve.values.tolist()
        },
        "n_trades": len(result.trades),
        "validation": {
            "mean_score": validation_result.mean_validation_score,
            "std_score": validation_result.std_validation_score,
            "n_folds": len(validation_result.fold_results)
        },
        "disclaimer": DISCLAIMER
    }


# ============ Paper Trading Endpoints ============

@router.get("/paper/portfolios")
async def list_portfolios(session=Depends(get_session_dependency)):
    """List paper trading portfolios."""
    from sqlmodel import select

    statement = select(PaperPortfolio).where(PaperPortfolio.is_active == True)
    portfolios = session.exec(statement).all()

    if not portfolios:
        # Create default portfolio
        settings = get_settings()
        default = PaperPortfolio(
            name="default",
            initial_cash=settings.initial_cash,
            current_cash=settings.initial_cash,
            total_value=settings.initial_cash,
            total_pnl=0,
            total_pnl_pct=0,
            realized_pnl=0,
            unrealized_pnl=0
        )
        session.add(default)
        session.commit()
        portfolios = [default]

    return [
        {
            "id": p.id,
            "name": p.name,
            "initial_cash": p.initial_cash,
            "current_cash": p.current_cash,
            "total_value": p.total_value,
            "total_pnl": p.total_pnl,
            "total_pnl_pct": p.total_pnl_pct,
            "positions_count": len([pos for pos in session.exec(
                select(PaperPosition).where(PaperPosition.portfolio_id == p.id)
            ).all()])
        }
        for p in portfolios
    ]


@router.get("/paper/portfolio/{name}")
async def get_portfolio(name: str, session=Depends(get_session_dependency)):
    """Get paper portfolio details."""
    from sqlmodel import select

    statement = select(PaperPortfolio).where(PaperPortfolio.name == name)
    portfolio = session.exec(statement).first()

    if not portfolio:
        raise HTTPException(status_code=404, detail="Portfolio not found")

    # Get positions
    pos_statement = select(PaperPosition).where(PaperPosition.portfolio_id == portfolio.id)
    positions = session.exec(pos_statement).all()

    return {
        "id": portfolio.id,
        "name": portfolio.name,
        "initial_cash": portfolio.initial_cash,
        "current_cash": portfolio.current_cash,
        "total_value": portfolio.total_value,
        "total_pnl": portfolio.total_pnl,
        "total_pnl_pct": portfolio.total_pnl_pct,
        "realized_pnl": portfolio.realized_pnl,
        "unrealized_pnl": portfolio.unrealized_pnl,
        "positions": [
            {
                "ticker": pos.ticker,
                "shares": pos.shares,
                "avg_cost": pos.avg_cost,
                "current_price": pos.current_price,
                "market_value": pos.market_value,
                "unrealized_pnl": pos.unrealized_pnl,
                "weight": pos.weight
            }
            for pos in positions
        ]
    }


@router.post("/paper/recommendations")
async def get_recommendations(
    universe_name: str = "liquid_50",
    session=Depends(get_session_dependency)
):
    """Get today's trade recommendations from the quant engine."""
    manager = UniverseManager(session)
    universe = manager.get_by_name(universe_name)
    if universe is None:
        universe = manager.get_or_create_default()

    # Get recent price data
    end_date = date.today()
    start_date = end_date - timedelta(days=365 * 2)

    cache = DataCache(session)
    prices = cache.get_price_matrix(universe.tickers, start_date, end_date)

    if prices.empty:
        raise HTTPException(status_code=404, detail="No price data available")

    # Simple momentum-based recommendations for demo
    # In production, this would use the trained model
    returns_21d = prices.pct_change(21).iloc[-1].dropna()
    returns_63d = prices.pct_change(63).iloc[-1].dropna()

    # CRITICAL FIX: Check if both have data before combining
    if len(returns_21d) == 0 or len(returns_63d) == 0:
        raise HTTPException(status_code=400, detail="Insufficient data for momentum calculations")

    # Combine momentum signals
    signal = (returns_21d.rank(pct=True) + returns_63d.rank(pct=True)) / 2

    # Top 10 buys, bottom 5 sells
    buys = signal.nlargest(10)
    sells = signal.nsmallest(5)

    return {
        "date": str(end_date),
        "recommendations": {
            "buy": [
                {"ticker": t, "signal": float(s), "action": "BUY"}
                for t, s in buys.items()
            ],
            "sell": [
                {"ticker": t, "signal": float(s), "action": "SELL"}
                for t, s in sells.items()
            ]
        },
        "disclaimer": "These are simulated recommendations for educational purposes only."
    }


# ============ Learning Endpoints ============

@router.get("/learn/lessons")
async def list_lessons(category: Optional[str] = None):
    """List available lessons."""
    tutor = QuantTutor()
    lessons = tutor.list_lessons(category)

    return [
        {
            "id": l.id,
            "title": l.title,
            "difficulty": l.difficulty,
            "category": l.category,
            "key_concepts": l.key_concepts
        }
        for l in lessons
    ]


@router.get("/learn/lesson/{lesson_id}")
async def get_lesson(lesson_id: str):
    """Get a specific lesson."""
    tutor = QuantTutor()
    lesson = tutor.get_lesson(lesson_id)

    if not lesson:
        raise HTTPException(status_code=404, detail="Lesson not found")

    return {
        "id": lesson.id,
        "title": lesson.title,
        "difficulty": lesson.difficulty,
        "category": lesson.category,
        "content": lesson.content,
        "key_concepts": lesson.key_concepts,
        "pitfalls": lesson.pitfalls,
        "next_lessons": lesson.next_lessons
    }


@router.get("/learn/glossary/{term}")
async def get_glossary_term(term: str):
    """Look up a glossary term."""
    tutor = QuantTutor()
    entry = tutor.get_glossary_term(term)

    if not entry:
        raise HTTPException(status_code=404, detail="Term not found")

    return entry


@router.post("/learn/explain")
async def explain_topic(request: ExplainRequest):
    """Get explanation for a topic."""
    explainer = QuantExplainer()

    method_map = {
        "data": explainer.explain_data_ingestion,
        "features": explainer.explain_features,
        "model": explainer.explain_model,
        "portfolio": explainer.explain_portfolio,
        "backtest": explainer.explain_backtest,
    }

    method = method_map.get(request.topic)
    if not method:
        raise HTTPException(status_code=400, detail="Unknown topic")

    # Build context based on topic
    if request.topic == "data":
        explanation = method(
            tickers=request.context.get("tickers", []),
            date_range=(
                request.context.get("start_date", "2020-01-01"),
                request.context.get("end_date", "2024-01-01")
            ),
            data_quality=request.context.get("data_quality", {})
        )
    else:
        # Generic context handling
        explanation = method(**request.context) if request.context else {}

    return explanation


@router.get("/learn/help/{context}")
async def get_contextual_help(context: str):
    """Get help based on current context."""
    tutor = QuantTutor()
    return tutor.get_contextual_help(context)


# ============ Research Memo Endpoints ============

@router.post("/memo/generate")
async def generate_memo(
    backtest_hash: str,
    session=Depends(get_session_dependency)
):
    """Generate a research memo from backtest results."""
    # In a full implementation, we'd load the backtest from DB
    # For now, generate a sample memo

    generator = ResearchMemoGenerator()

    # Sample data for demo
    memo = generator.generate(
        backtest_result={
            "metrics": {
                "sharpe_ratio": 0.85,
                "cagr": 0.12,
                "max_drawdown": -0.18,
                "total_return": 0.45
            },
            "n_trades": 150
        },
        model_config={"model_type": "ensemble"},
        feature_config={"enabled_features": ["returns", "momentum", "volatility"]},
        portfolio_config={"rebalance_frequency": "weekly", "max_position_weight": 0.10}
    )

    return {
        "title": memo.title,
        "date": memo.date,
        "sections": {
            "hypothesis": memo.hypothesis,
            "data_description": memo.data_description,
            "methodology": memo.methodology,
            "results": memo.results,
            "limitations": memo.limitations,
            "next_steps": memo.next_steps
        },
        "full_memo": memo.full_memo
    }


# ============ Status Endpoints ============

@router.get("/status")
async def get_status():
    """Get system status."""
    settings = get_settings()

    return {
        "demo_mode": settings.demo_mode,
        "llm_available": settings.has_llm_key,
        "data_provider": settings.data_provider,
        "initial_cash": settings.initial_cash,
        "disclaimer": DISCLAIMER
    }


# ============ Live Market Data Endpoints ============

@router.get("/market/quote/{symbol}")
async def get_quote(symbol: str):
    """Get real-time quote for a symbol."""
    from ..data.live import get_live_market_service

    service = get_live_market_service()
    quote = await service.get_quote(symbol.upper())

    if not quote:
        raise HTTPException(status_code=404, detail=f"Quote not found for {symbol}")

    return quote.to_dict()


@router.post("/market/quotes")
async def get_quotes(symbols: List[str]):
    """Get real-time quotes for multiple symbols."""
    from ..data.live import get_live_market_service

    service = get_live_market_service()
    quotes = await service.get_quotes_batch([s.upper() for s in symbols])

    return {
        symbol: quote.to_dict()
        for symbol, quote in quotes.items()
    }


@router.get("/market/overview")
async def get_market_overview():
    """Get market overview with indices and sector performance."""
    from ..data.live import get_live_market_service

    service = get_live_market_service()
    overview = await service.get_market_overview()

    return overview


@router.get("/market/news")
async def get_market_news(category: str = "general", limit: int = 20):
    """Get market news."""
    from ..data.live import get_live_market_service

    service = get_live_market_service()
    news = await service.get_news(category, limit)

    return {
        "news": [n.to_dict() for n in news],
        "count": len(news),
    }


@router.get("/market/news/{symbol}")
async def get_symbol_news(symbol: str, limit: int = 10):
    """Get news for a specific symbol."""
    from ..data.live import get_live_market_service

    service = get_live_market_service()
    news = await service.get_symbol_news(symbol.upper(), limit)

    return {
        "symbol": symbol.upper(),
        "news": [n.to_dict() for n in news],
        "count": len(news),
    }


@router.get("/market/watchlist")
async def get_watchlist_data(session=Depends(get_session_dependency)):
    """Get data for default watchlist (top liquid stocks)."""
    from ..data.live import get_live_market_service

    # Default watchlist
    watchlist = [
        "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA",
        "JPM", "V", "UNH", "XOM", "JNJ", "WMT", "MA"
    ]

    service = get_live_market_service()
    quotes = await service.get_quotes_batch(watchlist)

    return {
        "watchlist": [
            quotes[s].to_dict() if s in quotes else {"symbol": s, "error": "unavailable"}
            for s in watchlist
        ],
        "timestamp": datetime.now().isoformat()
    }


# ============ AI Analysis Endpoints ============

@router.get("/ai/analyze/{symbol}")
async def analyze_stock(symbol: str):
    """Get AI-powered deep analysis for a stock."""
    from ..llm.analyst import get_quant_analyst
    from ..data.live import get_live_market_service

    # Get current quote
    market_service = get_live_market_service()
    quote = await market_service.get_quote(symbol.upper())
    news = await market_service.get_symbol_news(symbol.upper(), limit=5)

    if not quote:
        raise HTTPException(status_code=404, detail=f"Quote not found for {symbol}")

    analyst = get_quant_analyst()
    analysis = await analyst.analyze_stock(
        symbol=symbol.upper(),
        quote=quote.to_dict(),
        news=[n.to_dict() for n in news]
    )

    return analysis


@router.get("/ai/market-commentary")
async def get_market_commentary():
    """Get AI-generated market commentary."""
    from ..llm.analyst import get_quant_analyst
    from ..data.live import get_live_market_service

    market_service = get_live_market_service()
    overview = await market_service.get_market_overview()

    analyst = get_quant_analyst()
    commentary = await analyst.generate_market_commentary(overview)

    return commentary


@router.post("/ai/critique-strategy")
async def critique_strategy(strategy: str, backtest_results: Optional[Dict] = None):
    """Get rigorous AI critique of a trading strategy."""
    from ..llm.analyst import get_quant_analyst

    analyst = get_quant_analyst()
    critique = await analyst.critique_strategy(strategy, backtest_results)

    return critique


@router.get("/ai/learning-path")
async def get_learning_path(
    level: str = "beginner",
    interests: str = "general quant",
    goal: str = "become a quant trader"
):
    """Get personalized quant learning path."""
    from ..llm.analyst import get_quant_analyst

    analyst = get_quant_analyst()
    path = await analyst.get_learning_path(
        current_level=level,
        interests=interests.split(","),
        goals=goal
    )

    return path


@router.get("/ai/explain/{concept}")
async def explain_concept(concept: str, context: str = ""):
    """Get deep dive explanation of a quant concept."""
    from ..llm.analyst import get_quant_analyst

    analyst = get_quant_analyst()
    explanation = await analyst.explain_concept(concept, context)

    return explanation


@router.post("/ai/analyze-portfolio")
async def analyze_portfolio(session=Depends(get_session_dependency)):
    """Get AI analysis of the current paper portfolio."""
    from sqlmodel import select
    from ..llm.analyst import get_quant_analyst

    # Get active portfolio
    statement = select(PaperPortfolio).where(PaperPortfolio.is_active == True)
    portfolio = session.exec(statement).first()

    if not portfolio:
        raise HTTPException(status_code=404, detail="No active portfolio")

    # Get positions
    pos_statement = select(PaperPosition).where(PaperPosition.portfolio_id == portfolio.id)
    positions = session.exec(pos_statement).all()

    positions_data = [
        {
            "ticker": pos.ticker,
            "shares": pos.shares,
            "market_value": pos.market_value,
            "weight": pos.weight,
            "unrealized_pnl": pos.unrealized_pnl
        }
        for pos in positions
    ]

    analyst = get_quant_analyst()
    analysis = await analyst.analyze_portfolio(
        positions=positions_data,
        total_value=portfolio.total_value
    )

    return analysis


# ============ Order Validation Models ============
# FIX #7: Add input validation using Pydantic

class MarketOrderRequest(BaseModel):
    """Validated market order request."""
    symbol: str = Field(..., min_length=1, max_length=20, pattern="^[A-Z0-9]{1,20}$")
    side: str = Field(..., pattern="^(buy|sell)$")
    quantity: float = Field(..., gt=0, lt=1e8)


class LimitOrderRequest(BaseModel):
    """Validated limit order request."""
    symbol: str = Field(..., min_length=1, max_length=20, pattern="^[A-Z0-9]{1,20}$")
    side: str = Field(..., pattern="^(buy|sell)$")
    quantity: float = Field(..., gt=0, lt=1e8)
    limit_price: float = Field(..., gt=0, lt=1e8)


class StopOrderRequest(BaseModel):
    """Validated stop order request."""
    symbol: str = Field(..., min_length=1, max_length=20, pattern="^[A-Z0-9]{1,20}$")
    side: str = Field(..., pattern="^(buy|sell)$")
    quantity: float = Field(..., gt=0, lt=1e8)
    stop_price: float = Field(..., gt=0, lt=1e8)


# ============ Automated Trading Endpoints ============

@router.get("/signals/generate")
async def generate_signals(
    universe_name: str = "liquid_50",
    session=Depends(get_session_dependency)
):
    """Generate trading signals for a universe."""
    from ..signals import get_signal_engine
    from ..data import DataCache, UniverseManager

    # Get universe
    manager = UniverseManager(session)
    universe = manager.get_by_name(universe_name)
    if universe is None:
        universe = manager.get_or_create_default()

    # Get price data
    end_date = date.today()
    start_date = end_date - timedelta(days=365 * 2)

    cache = DataCache(session)
    prices = cache.get_price_matrix(universe.tickers, start_date, end_date)

    if prices.empty:
        raise HTTPException(status_code=404, detail="No price data available")

    # Generate signals
    engine = get_signal_engine()
    signals = engine.generate_signals(prices)

    return signals.to_dict()


@router.get("/trading/status")
async def get_trading_status():
    """Get auto-trader status."""
    from ..trading import get_auto_trader

    trader = get_auto_trader()
    return trader.get_status()


@router.post("/trading/enable")
async def enable_auto_trading():
    """Enable automated trading."""
    from ..trading import get_auto_trader

    trader = get_auto_trader()
    trader.enable_auto_trading()
    return {"status": "enabled", "message": "Auto-trading enabled (paper mode)"}


@router.post("/trading/disable")
async def disable_auto_trading():
    """Disable automated trading."""
    from ..trading import get_auto_trader

    trader = get_auto_trader()
    trader.disable_auto_trading()
    return {"status": "disabled", "message": "Auto-trading disabled"}


@router.post("/trading/rebalance")
async def trigger_rebalance(
    universe_name: str = "liquid_50",
    session=Depends(get_session_dependency)
):
    """Trigger portfolio rebalance based on current signals."""
    from ..signals import get_signal_engine
    from ..trading import get_auto_trader
    from ..data import DataCache, UniverseManager
    from ..data.live import get_live_market_service

    # Get universe and prices
    manager = UniverseManager(session)
    universe = manager.get_by_name(universe_name)
    if universe is None:
        universe = manager.get_or_create_default()

    end_date = date.today()
    start_date = end_date - timedelta(days=365 * 2)

    cache = DataCache(session)
    prices = cache.get_price_matrix(universe.tickers, start_date, end_date)

    if prices.empty:
        raise HTTPException(status_code=404, detail="No price data available")

    # Get current prices
    # BUG FIX #13: Add error handling for async market service calls
    try:
        market_service = get_live_market_service()
        quotes = await market_service.get_quotes_batch(universe.tickers)
        # Validate quotes before accessing attributes
        if not quotes:
            raise HTTPException(status_code=503, detail="Failed to fetch market quotes")
        current_prices = {q.symbol: q.price for q in quotes.values() if q and hasattr(q, 'symbol') and hasattr(q, 'price')}
        if not current_prices:
            raise HTTPException(status_code=503, detail="No valid quotes received")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Market service error in rebalance: {e}")
        raise HTTPException(status_code=503, detail=f"Market service unavailable: {str(e)}")

    # Generate signals and rebalance (uses hybrid ML+Rules engine when available)
    trader = get_auto_trader()
    signals = trader.generate_hybrid_signals(prices)
    trader.update_prices(current_prices)
    orders = trader.rebalance(signals, current_prices)

    return {
        "status": "rebalanced",
        "orders_created": len(orders),
        "orders": [o.to_dict() for o in orders],
        "new_weights": signals.recommended_weights,
        "market_regime": signals.market_regime,
    }


@router.post("/trading/order/market")
async def create_market_order(request: MarketOrderRequest):
    """Create a market order with validation."""
    from ..trading import get_order_manager, OrderSide

    manager = get_order_manager()
    order_side = OrderSide.BUY if request.side.lower() == "buy" else OrderSide.SELL

    order = manager.create_market_order(
        symbol=request.symbol,
        side=order_side,
        quantity=request.quantity,
    )

    return order.to_dict()


@router.post("/trading/order/limit")
async def create_limit_order(request: LimitOrderRequest):
    """Create a limit order with validation."""
    from ..trading import get_order_manager, OrderSide

    manager = get_order_manager()
    order_side = OrderSide.BUY if request.side.lower() == "buy" else OrderSide.SELL

    order = manager.create_limit_order(
        symbol=request.symbol,
        side=order_side,
        quantity=request.quantity,
        limit_price=request.limit_price,
    )

    return order.to_dict()


@router.post("/trading/order/bracket")
async def create_bracket_order(
    symbol: str,
    side: str,
    quantity: float,
    entry_price: Optional[float] = None,
    stop_loss_pct: float = 0.05,
    take_profit_pct: float = 0.10,
):
    """Create a bracket order with automatic stop-loss and take-profit."""
    from ..trading import get_order_manager, OrderSide

    manager = get_order_manager()
    order_side = OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL

    bracket = manager.create_bracket_order(
        symbol=symbol,
        side=order_side,
        quantity=quantity,
        entry_price=entry_price,
        stop_loss_pct=stop_loss_pct,
        take_profit_pct=take_profit_pct,
    )

    return bracket.to_dict()


@router.post("/trading/order/stop")
async def create_stop_order(request: StopOrderRequest):
    """Create a stop or stop-limit order with validation.

    CRITICAL FIX: Removed unused limit_price parameter - was never used.
    If stop-limit orders needed, add limit_price to StopOrderRequest model.
    """
    from ..trading import get_order_manager, OrderSide

    manager = get_order_manager()
    order_side = OrderSide.BUY if request.side.lower() == "buy" else OrderSide.SELL

    order = manager.create_stop_order(
        symbol=request.symbol,
        side=order_side,
        quantity=request.quantity,
        stop_price=request.stop_price,
        limit_price=None,  # Stop-market order (not stop-limit)
    )

    return order.to_dict()


@router.post("/trading/order/trailing-stop")
async def create_trailing_stop(
    symbol: str,
    side: str,
    quantity: float,
    trail_amount: float,
    trail_percent: bool = False,
):
    """Create a trailing stop order."""
    from ..trading import get_order_manager, OrderSide

    manager = get_order_manager()
    order_side = OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL

    order = manager.create_trailing_stop(
        symbol=symbol,
        side=order_side,
        quantity=quantity,
        trail_amount=trail_amount,
        trail_percent=trail_percent,
    )

    return order.to_dict()


@router.get("/trading/orders")
async def get_orders(status: str = "open"):
    """Get orders by status."""
    from ..trading import get_order_manager

    manager = get_order_manager()

    if status == "open":
        orders = manager.get_open_orders()
    elif status == "filled":
        orders = manager.get_filled_orders()
    else:
        orders = list(manager.orders.values())

    return {
        "orders": [o.to_dict() for o in orders],
        "count": len(orders),
    }


@router.delete("/trading/order/{order_id}")
async def cancel_order(order_id: str):
    """Cancel an order."""
    from ..trading import get_order_manager

    manager = get_order_manager()
    success = manager.cancel_order(order_id)

    if not success:
        raise HTTPException(status_code=404, detail="Order not found or cannot be cancelled")

    return {"status": "cancelled", "order_id": order_id}


@router.get("/trading/portfolio")
async def get_trading_portfolio():
    """Get current auto-trader portfolio."""
    from ..trading import get_auto_trader

    trader = get_auto_trader()
    return trader.portfolio.to_dict()


@router.get("/trading/performance")
async def get_trading_performance():
    """Get trading performance metrics."""
    from ..trading import get_auto_trader

    trader = get_auto_trader()
    return trader.get_performance_metrics()


@router.get("/trading/history")
async def get_trade_history(limit: int = 50):
    """Get trade history."""
    from ..trading import get_auto_trader

    trader = get_auto_trader()
    trades = trader.trade_history[-limit:]

    return {
        "trades": [t.to_dict() for t in trades],
        "count": len(trades),
        "total_trades": len(trader.trade_history),
    }


@router.post("/trading/execute-signal")
async def execute_signal(symbol: str):
    """Execute the current signal for a symbol."""
    from ..trading import get_auto_trader
    from ..data.live import get_live_market_service

    trader = get_auto_trader()

    if not trader.last_signals:
        raise HTTPException(status_code=400, detail="No signals generated yet")

    # Find signal for symbol
    signal = next(
        (s for s in trader.last_signals.signals if s.symbol == symbol.upper()),
        None
    )

    if not signal:
        raise HTTPException(status_code=404, detail=f"No signal found for {symbol}")

    # Get current price
    market_service = get_live_market_service()
    quote = await market_service.get_quote(symbol.upper())

    if not quote:
        raise HTTPException(status_code=404, detail=f"Quote not found for {symbol}")

    # Execute
    order = trader.execute_signal(signal, quote.price)

    if not order:
        return {"status": "no_action", "signal": signal.to_dict()}

    return {
        "status": "executed",
        "signal": signal.to_dict(),
        "order": order.to_dict(),
    }


# ============ Options Trading Endpoints ============

@router.get("/options/chain/{symbol}")
async def get_options_chain(
    symbol: str,
    expiration_date: Optional[str] = None,
):
    """
    Get options chain for a symbol using real market data from yfinance.

    Args:
        symbol: Ticker symbol (e.g., "AAPL")
        expiration_date: Specific expiration date "YYYY-MM-DD". If None, uses nearest available.

    Returns real market options data only. Returns 404 if real data is unavailable
    rather than silently returning synthetic/fabricated prices.
    """
    from ..trading import get_options_manager

    manager = get_options_manager()

    try:
        chain = manager.generate_real_options_chain(
            symbol=symbol.upper(),
            expiration=expiration_date,
        )
    except Exception as e:
        logger.error(f"Failed to fetch real options data for {symbol}: {e}")
        chain = None

    if chain is None or chain.get("data_source") != "yfinance_real":
        raise HTTPException(
            status_code=404,
            detail=f"Real options data unavailable for {symbol}. Ensure yfinance is installed and the symbol has listed options.",
        )

    return {
        "symbol": symbol.upper(),
        "underlying_price": chain["underlying_price"],
        "data_source": chain["data_source"],
        "fetch_time": chain["fetch_time"],
        "calls": [c.to_dict() for c in chain["calls"]],
        "puts": [p.to_dict() for p in chain["puts"]],
    }


@router.post("/options/price")
async def price_option(
    symbol: str,
    strike: float,
    expiration_days: int,
    option_type: str = "call",
    volatility: float = 0.30,
):
    """Price a single option contract."""
    from ..trading import get_options_manager, OptionType
    from ..data.live import get_live_market_service

    market_service = get_live_market_service()
    quote = await market_service.get_quote(symbol.upper())

    if not quote:
        raise HTTPException(status_code=404, detail=f"Quote not found for {symbol}")

    manager = get_options_manager()
    opt_type = OptionType.CALL if option_type.lower() == "call" else OptionType.PUT
    expiration = date.today() + timedelta(days=expiration_days)

    contract = manager.price_option(
        symbol=symbol.upper(),
        underlying_price=quote.price,
        strike=strike,
        expiration=expiration,
        volatility=volatility,
        option_type=opt_type,
    )

    return contract.to_dict()


@router.post("/options/implied-volatility")
async def calculate_iv(
    symbol: str,
    strike: float,
    expiration_days: int,
    option_price: float,
    option_type: str = "call",
):
    """Calculate implied volatility from option price."""
    from ..trading import BlackScholes, OptionType
    from ..data.live import get_live_market_service

    market_service = get_live_market_service()
    quote = await market_service.get_quote(symbol.upper())

    if not quote:
        raise HTTPException(status_code=404, detail=f"Quote not found for {symbol}")

    opt_type = OptionType.CALL if option_type.lower() == "call" else OptionType.PUT
    T = expiration_days / 365.0
    r = 0.05  # Risk-free rate

    iv = BlackScholes.implied_volatility(
        option_price=option_price,
        S=quote.price,
        K=strike,
        T=T,
        r=r,
        option_type=opt_type,
    )

    return {
        "symbol": symbol.upper(),
        "strike": strike,
        "option_type": option_type,
        "option_price": option_price,
        "implied_volatility": round(iv, 4),
        "implied_volatility_pct": f"{iv * 100:.1f}%",
    }


@router.post("/options/strategy/covered-call")
async def create_covered_call(
    symbol: str,
    strike: float,
    expiration_days: int,
    volatility: float = 0.30,
):
    """Create a covered call strategy."""
    from ..trading import get_options_manager
    from ..data.live import get_live_market_service

    market_service = get_live_market_service()
    quote = await market_service.get_quote(symbol.upper())

    if not quote:
        raise HTTPException(status_code=404, detail=f"Quote not found for {symbol}")

    manager = get_options_manager()
    expiration = date.today() + timedelta(days=expiration_days)

    strategy = manager.create_covered_call(
        symbol=symbol.upper(),
        underlying_price=quote.price,
        strike=strike,
        expiration=expiration,
        volatility=volatility,
    )

    return strategy.to_dict()


@router.post("/options/strategy/protective-put")
async def create_protective_put(
    symbol: str,
    strike: float,
    expiration_days: int,
    volatility: float = 0.30,
):
    """Create a protective put strategy."""
    from ..trading import get_options_manager
    from ..data.live import get_live_market_service

    market_service = get_live_market_service()
    quote = await market_service.get_quote(symbol.upper())

    if not quote:
        raise HTTPException(status_code=404, detail=f"Quote not found for {symbol}")

    manager = get_options_manager()
    expiration = date.today() + timedelta(days=expiration_days)

    strategy = manager.create_protective_put(
        symbol=symbol.upper(),
        underlying_price=quote.price,
        strike=strike,
        expiration=expiration,
        volatility=volatility,
    )

    return strategy.to_dict()


@router.post("/options/strategy/bull-call-spread")
async def create_bull_call_spread(
    symbol: str,
    lower_strike: float,
    upper_strike: float,
    expiration_days: int,
    volatility: float = 0.30,
):
    """Create a bull call spread strategy."""
    from ..trading import get_options_manager
    from ..data.live import get_live_market_service

    market_service = get_live_market_service()
    quote = await market_service.get_quote(symbol.upper())

    if not quote:
        raise HTTPException(status_code=404, detail=f"Quote not found for {symbol}")

    manager = get_options_manager()
    expiration = date.today() + timedelta(days=expiration_days)

    strategy = manager.create_bull_call_spread(
        symbol=symbol.upper(),
        underlying_price=quote.price,
        lower_strike=lower_strike,
        upper_strike=upper_strike,
        expiration=expiration,
        volatility=volatility,
    )

    return strategy.to_dict()


@router.post("/options/strategy/bear-put-spread")
async def create_bear_put_spread(
    symbol: str,
    lower_strike: float,
    upper_strike: float,
    expiration_days: int,
    volatility: float = 0.30,
):
    """Create a bear put spread strategy."""
    from ..trading import get_options_manager
    from ..data.live import get_live_market_service

    market_service = get_live_market_service()
    quote = await market_service.get_quote(symbol.upper())

    if not quote:
        raise HTTPException(status_code=404, detail=f"Quote not found for {symbol}")

    manager = get_options_manager()
    expiration = date.today() + timedelta(days=expiration_days)

    strategy = manager.create_bear_put_spread(
        symbol=symbol.upper(),
        underlying_price=quote.price,
        lower_strike=lower_strike,
        upper_strike=upper_strike,
        expiration=expiration,
        volatility=volatility,
    )

    return strategy.to_dict()


@router.post("/options/strategy/straddle")
async def create_straddle(
    symbol: str,
    strike: float,
    expiration_days: int,
    is_long: bool = True,
    volatility: float = 0.30,
):
    """Create a straddle strategy (long or short)."""
    from ..trading import get_options_manager
    from ..data.live import get_live_market_service

    market_service = get_live_market_service()
    quote = await market_service.get_quote(symbol.upper())

    if not quote:
        raise HTTPException(status_code=404, detail=f"Quote not found for {symbol}")

    manager = get_options_manager()
    expiration = date.today() + timedelta(days=expiration_days)

    strategy = manager.create_straddle(
        symbol=symbol.upper(),
        underlying_price=quote.price,
        strike=strike,
        expiration=expiration,
        volatility=volatility,
        is_long=is_long,
    )

    return strategy.to_dict()


@router.post("/options/strategy/strangle")
async def create_strangle(
    symbol: str,
    put_strike: float,
    call_strike: float,
    expiration_days: int,
    is_long: bool = True,
    volatility: float = 0.30,
):
    """Create a strangle strategy (long or short)."""
    from ..trading import get_options_manager
    from ..data.live import get_live_market_service

    market_service = get_live_market_service()
    quote = await market_service.get_quote(symbol.upper())

    if not quote:
        raise HTTPException(status_code=404, detail=f"Quote not found for {symbol}")

    manager = get_options_manager()
    expiration = date.today() + timedelta(days=expiration_days)

    strategy = manager.create_strangle(
        symbol=symbol.upper(),
        underlying_price=quote.price,
        put_strike=put_strike,
        call_strike=call_strike,
        expiration=expiration,
        volatility=volatility,
        is_long=is_long,
    )

    return strategy.to_dict()


@router.post("/options/strategy/iron-condor")
async def create_iron_condor(
    symbol: str,
    put_lower: float,
    put_upper: float,
    call_lower: float,
    call_upper: float,
    expiration_days: int,
    volatility: float = 0.30,
):
    """Create an iron condor strategy."""
    from ..trading import get_options_manager
    from ..data.live import get_live_market_service

    market_service = get_live_market_service()
    quote = await market_service.get_quote(symbol.upper())

    if not quote:
        raise HTTPException(status_code=404, detail=f"Quote not found for {symbol}")

    manager = get_options_manager()
    expiration = date.today() + timedelta(days=expiration_days)

    strategy = manager.create_iron_condor(
        symbol=symbol.upper(),
        underlying_price=quote.price,
        put_lower=put_lower,
        put_upper=put_upper,
        call_lower=call_lower,
        call_upper=call_upper,
        expiration=expiration,
        volatility=volatility,
    )

    return strategy.to_dict()


@router.post("/options/strategy/butterfly")
async def create_butterfly(
    symbol: str,
    lower_strike: float,
    middle_strike: float,
    upper_strike: float,
    expiration_days: int,
    use_calls: bool = True,
    volatility: float = 0.30,
):
    """Create a butterfly spread strategy."""
    from ..trading import get_options_manager
    from ..data.live import get_live_market_service

    market_service = get_live_market_service()
    quote = await market_service.get_quote(symbol.upper())

    if not quote:
        raise HTTPException(status_code=404, detail=f"Quote not found for {symbol}")

    manager = get_options_manager()
    expiration = date.today() + timedelta(days=expiration_days)

    strategy = manager.create_butterfly(
        symbol=symbol.upper(),
        underlying_price=quote.price,
        lower_strike=lower_strike,
        middle_strike=middle_strike,
        upper_strike=upper_strike,
        expiration=expiration,
        volatility=volatility,
        use_calls=use_calls,
    )

    return strategy.to_dict()


@router.get("/options/strategies")
async def list_strategies():
    """List all options strategies."""
    from ..trading import get_options_manager

    manager = get_options_manager()
    return {
        "strategies": manager.list_strategies(),
        "count": len(manager.strategies),
    }


@router.get("/options/strategy/{strategy_id}")
async def get_strategy(strategy_id: str):
    """Get strategy details and risk analysis."""
    from ..trading import get_options_manager

    manager = get_options_manager()
    strategy = manager.get_strategy(strategy_id)

    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")

    return strategy.to_dict()


@router.get("/options/strategy/{strategy_id}/risk")
async def get_strategy_risk(strategy_id: str):
    """Get comprehensive risk analysis for a strategy."""
    from ..trading import get_options_manager

    manager = get_options_manager()
    analysis = manager.analyze_strategy_risk(strategy_id)

    if "error" in analysis:
        raise HTTPException(status_code=404, detail=analysis["error"])

    return analysis


@router.get("/options/greeks-explain")
async def explain_greeks():
    """Get explanation of option Greeks for education."""
    return {
        "delta": {
            "definition": "Rate of change of option price with respect to underlying price",
            "range": "Calls: 0 to 1, Puts: -1 to 0",
            "interpretation": "Delta of 0.5 means option price moves $0.50 for every $1 move in stock",
            "hedge_ratio": "Number of shares needed to delta hedge 100 options",
        },
        "gamma": {
            "definition": "Rate of change of delta with respect to underlying price",
            "interpretation": "Measures how fast delta changes - high gamma = delta changes quickly",
            "peak": "Highest for ATM options near expiration",
        },
        "theta": {
            "definition": "Rate of time decay (per day)",
            "interpretation": "How much value the option loses each day from time decay",
            "sign": "Negative for long options (lose value), positive for short options",
        },
        "vega": {
            "definition": "Sensitivity to volatility (per 1% change)",
            "interpretation": "How much option price changes for 1% change in implied volatility",
            "highest": "ATM options have highest vega",
        },
        "rho": {
            "definition": "Sensitivity to interest rate changes (per 1% change)",
            "interpretation": "Usually small impact except for long-dated options",
        },
    }


# ============ Cryptocurrency Endpoints ============

@router.get("/crypto/quote/{symbol}")
async def get_crypto_quote(symbol: str):
    """Get real-time cryptocurrency quote."""
    from ..data.crypto import get_crypto_service

    service = get_crypto_service()
    quote = await service.get_quote(symbol.upper())

    if not quote:
        raise HTTPException(status_code=404, detail=f"Crypto quote not found for {symbol}")

    return quote.to_dict()


@router.post("/crypto/quotes")
async def get_crypto_quotes(symbols: List[str]):
    """Get quotes for multiple cryptocurrencies."""
    from ..data.crypto import get_crypto_service

    service = get_crypto_service()
    quotes = await service.get_quotes_batch([s.upper() for s in symbols])

    return {
        symbol: quote.to_dict()
        for symbol, quote in quotes.items()
    }


@router.get("/crypto/overview")
async def get_crypto_overview():
    """Get cryptocurrency market overview."""
    from ..data.crypto import get_crypto_service

    service = get_crypto_service()
    overview = await service.get_market_overview()

    return overview


@router.get("/crypto/watchlist")
async def get_crypto_watchlist():
    """Get data for default crypto watchlist."""
    from ..data.crypto import get_crypto_service

    watchlist = ["BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "DOGE", "DOT", "AVAX", "LINK"]

    service = get_crypto_service()
    quotes = await service.get_quotes_batch(watchlist)

    return {
        "watchlist": [
            quotes[s].to_dict() if s in quotes else {"symbol": s, "error": "unavailable"}
            for s in watchlist
        ],
        "timestamp": datetime.now().isoformat()
    }


@router.get("/crypto/history/{symbol}")
async def get_crypto_history(symbol: str, days: int = 30):
    """Get price history for a cryptocurrency."""
    from ..data.crypto import get_crypto_service

    service = get_crypto_service()
    history = await service.get_price_history(symbol.upper(), days)

    return history


@router.get("/crypto/signals")
async def generate_crypto_signals():
    """Generate trading signals for top cryptocurrencies."""
    from ..data.crypto import get_crypto_service
    import random

    service = get_crypto_service()
    overview = await service.get_market_overview()

    # Simple momentum-based signals
    signals = []
    for crypto in overview.get("top_cryptos", []):
        change = crypto.get("change_percent_24h", 0)

        # Generate signal based on momentum
        if change > 5:
            action = "STRONG_BUY"
            score = min(1.0, 0.6 + change / 20)
        elif change > 2:
            action = "BUY"
            score = 0.5 + change / 20
        elif change < -5:
            action = "STRONG_SELL"
            score = max(-1.0, -0.6 + change / 20)
        elif change < -2:
            action = "SELL"
            score = -0.5 + change / 20
        else:
            action = "HOLD"
            score = change / 10

        signals.append({
            "symbol": crypto["symbol"],
            "name": crypto["name"],
            "price": crypto["price"],
            "change_24h": change,
            "action": action,
            "signal_score": round(score, 3),
            "volume_24h": crypto.get("volume_24h", 0),
            "market_cap": crypto.get("market_cap", 0),
        })

    # Sort by absolute signal strength
    signals.sort(key=lambda x: abs(x["signal_score"]), reverse=True)

    return {
        "signals": signals,
        "timestamp": datetime.now().isoformat(),
        "market_sentiment": "bullish" if sum(s["signal_score"] for s in signals) > 0 else "bearish",
    }


@router.post("/crypto/order")
async def create_crypto_order(
    symbol: str,
    side: str,
    quantity: float,
    order_type: str = "market",
    limit_price: Optional[float] = None,
):
    """Create a crypto order (paper trading)."""
    from ..trading import get_order_manager, OrderSide
    from ..data.crypto import get_crypto_service

    # Get current price
    service = get_crypto_service()
    quote = await service.get_quote(symbol.upper())

    if not quote:
        raise HTTPException(status_code=404, detail=f"Crypto not found: {symbol}")

    manager = get_order_manager()
    order_side = OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL

    if order_type == "market":
        order = manager.create_market_order(
            symbol=f"CRYPTO:{symbol.upper()}",
            side=order_side,
            quantity=quantity,
        )
    else:
        if not limit_price:
            raise HTTPException(status_code=400, detail="Limit price required for limit orders")
        order = manager.create_limit_order(
            symbol=f"CRYPTO:{symbol.upper()}",
            side=order_side,
            quantity=quantity,
            limit_price=limit_price,
        )

    return {
        "order": order.to_dict(),
        "current_price": quote.price,
        "estimated_value": quantity * quote.price,
    }


@router.get("/crypto/portfolio")
async def get_crypto_portfolio():
    """Get crypto portfolio (paper trading)."""
    from ..trading import get_auto_trader

    trader = get_auto_trader()

    # Filter for crypto positions
    crypto_positions = {
        k.replace("CRYPTO:", ""): v.to_dict()
        for k, v in trader.portfolio.positions.items()
        if k.startswith("CRYPTO:")
    }

    return {
        "positions": crypto_positions,
        "count": len(crypto_positions),
    }


@router.get("/ai/analyze-crypto/{symbol}")
async def analyze_crypto(symbol: str):
    """Get AI-powered analysis for a cryptocurrency."""
    from ..llm.analyst import get_quant_analyst
    from ..data.crypto import get_crypto_service

    service = get_crypto_service()
    quote = await service.get_quote(symbol.upper())

    if not quote:
        raise HTTPException(status_code=404, detail=f"Crypto not found: {symbol}")

    analyst = get_quant_analyst()

    # Build crypto-specific context
    crypto_context = f"""
    Cryptocurrency: {quote.name} ({quote.symbol})
    Current Price: ${quote.price:,.2f}
    24h Change: {quote.change_percent_24h:+.2f}%
    24h High/Low: ${quote.high_24h:,.2f} / ${quote.low_24h:,.2f}
    24h Volume: ${quote.volume_24h:,.0f}
    Market Cap: ${quote.market_cap:,.0f} (Rank #{quote.market_cap_rank})
    All-Time High: ${quote.ath:,.2f} ({quote.ath_change_percent:+.2f}% from ATH)
    """

    analysis = await analyst.analyze_stock(
        symbol=quote.symbol,
        quote=quote.to_dict(),
        news=[],  # Would add crypto news here
        context=f"This is a cryptocurrency analysis. {crypto_context}"
    )

    return analysis


@router.get("/ai/crypto-market-commentary")
async def get_crypto_market_commentary():
    """Get AI-generated crypto market commentary."""
    from ..llm.analyst import get_quant_analyst
    from ..data.crypto import get_crypto_service

    service = get_crypto_service()
    overview = await service.get_market_overview()

    analyst = get_quant_analyst()

    # Build crypto market context
    context = {
        "asset_class": "cryptocurrency",
        "total_market_cap": overview.get("total_market_cap", 0),
        "btc_dominance": overview.get("btc_dominance", 0),
        "top_cryptos": overview.get("top_cryptos", [])[:5],
        "top_gainers": overview.get("top_gainers", [])[:3],
        "top_losers": overview.get("top_losers", [])[:3],
    }

    commentary = await analyst.generate_market_commentary(context)

    return commentary


# ============ Autonomous Trading Bot Endpoints ============

@router.get("/bot/status")
async def get_bot_status():
    """Get the autonomous trading bot status."""
    from ..trading import get_quant_bot

    bot = get_quant_bot()
    return bot.get_status()


@router.post("/bot/start")
async def start_bot(
    capital: float = 10000.0,
    mode: str = "balanced",
    asset_class: str = "both",
    background_tasks: BackgroundTasks = None,
):
    """Start the autonomous trading bot."""
    from ..trading import get_quant_bot, TradingMode, AssetClass, QuantBot

    global _bot

    # Parse mode
    trading_mode = TradingMode.BALANCED
    if mode == "aggressive":
        trading_mode = TradingMode.AGGRESSIVE
    elif mode == "conservative":
        trading_mode = TradingMode.CONSERVATIVE

    # Parse asset class
    asset = AssetClass.BOTH
    if asset_class == "stocks":
        asset = AssetClass.STOCKS
    elif asset_class == "crypto":
        asset = AssetClass.CRYPTO

    # Create new bot with specified settings
    from ..trading import quant_bot
    quant_bot._bot = QuantBot(
        initial_capital=capital,
        mode=trading_mode,
        asset_class=asset,
    )

    bot = get_quant_bot()

    # Start in background
    if background_tasks:
        background_tasks.add_task(bot.start)
        return {
            "status": "started",
            "message": f"Bot started with ${capital:,.2f} in {mode} mode trading {asset_class}",
            "config": bot.get_status(),
        }

    return {
        "status": "ready",
        "message": "Bot initialized but not started (use background_tasks to auto-start)",
        "config": bot.get_status(),
    }


@router.post("/bot/stop")
async def stop_bot():
    """Stop the autonomous trading bot."""
    from ..trading import get_quant_bot

    bot = get_quant_bot()
    bot.stop()

    return {
        "status": "stopped",
        "message": "Autonomous trading bot stopped",
        "final_value": bot.total_value,
        "total_pnl": bot.total_pnl,
    }


@router.get("/bot/positions")
async def get_bot_positions():
    """Get all bot positions with entry rationale."""
    from ..trading import get_quant_bot

    bot = get_quant_bot()
    positions = bot.get_positions()

    return {
        "positions": positions,
        "count": len(positions),
        "total_value": sum(p.get("market_value", 0) for p in positions),
    }


@router.get("/bot/trades")
async def get_bot_trades(limit: int = 50):
    """Get bot trade history with full rationale."""
    from ..trading import get_quant_bot

    bot = get_quant_bot()
    trades = bot.get_trades(limit)

    return {
        "trades": trades,
        "count": len(trades),
        "total_trades": len(bot.trade_history),
    }


@router.get("/bot/performance")
async def get_bot_performance():
    """Get comprehensive bot performance metrics."""
    from ..trading import get_quant_bot

    bot = get_quant_bot()
    return bot.get_performance()


@router.post("/bot/scan")
async def trigger_bot_scan():
    """Manually trigger a market scan cycle."""
    from ..trading import get_quant_bot

    bot = get_quant_bot()

    # Run one trading cycle
    await bot._run_trading_cycle(0)

    return {
        "status": "scan_complete",
        "last_scan": bot.last_scan_time.isoformat() if bot.last_scan_time else None,
        "positions": len(bot.positions),
        "pending_signals": len(bot.pending_signals),
    }


@router.get("/bot/equity-curve")
async def get_bot_equity_curve():
    """Get bot equity curve for charting."""
    from ..trading import get_quant_bot

    bot = get_quant_bot()

    return {
        "equity_curve": [
            {"timestamp": ts.isoformat(), "value": value}
            for ts, value in bot.equity_curve
        ],
        "initial_capital": bot.initial_capital,
        "current_value": bot.total_value,
    }


@router.post("/bot/close-position/{symbol}")
async def close_bot_position(symbol: str, reason: str = "Manual close"):
    """Manually close a bot position."""
    from ..trading import get_quant_bot

    bot = get_quant_bot()

    if symbol.upper() not in bot.positions:
        raise HTTPException(status_code=404, detail=f"Position not found: {symbol}")

    success = await bot._close_position(symbol.upper(), reason)

    if not success:
        raise HTTPException(status_code=400, detail="Failed to close position")

    return {
        "status": "closed",
        "symbol": symbol.upper(),
        "reason": reason,
    }


@router.get("/bot/commentary")
async def get_bot_commentary(limit: int = 50):
    """Get real-time bot thinking and commentary."""
    from ..trading import get_quant_bot

    bot = get_quant_bot()
    commentary = bot.get_commentary(limit)

    return {
        "commentary": commentary,
        "count": len(commentary),
        "bot_running": bot.is_running,
    }


@router.get("/bot/data-health")
async def get_bot_data_health():
    """
    Check health and freshness of market data sources.

    Returns:
    - crypto: CoinGecko API status (live/mock)
    - stocks: yfinance/Finnhub status (live/mock)
    - overall: Combined status with message

    Use this to verify if prices are real-time or simulated fallback data.
    """
    from ..trading import get_quant_bot

    bot = get_quant_bot()
    health = await bot.get_data_health()

    return health


@router.get("/bot/learning")
async def get_bot_learning_insights():
    """
    Get reinforcement learning insights and adaptation status.

    Returns comprehensive RL metrics:
    - learning_status: Whether bot has enough data to adapt
    - factor_performance: Which factors predict profitable trades
    - adapted_weights: How weights have changed from learning
    - asset_win_rates: Real win rates from actual trades
    - regime_insights: Performance in different market regimes
    - top_factors: Best performing factors (high win rate)
    - weak_factors: Worst performing factors (low win rate)

    The bot learns from every completed trade and adapts its:
    1. Factor weights (increases weight for predictive factors)
    2. Kelly sizing (adjusts position size based on actual win rate)
    3. Strategy selection (Thompson Sampling for regime-based selection)
    """
    from ..trading import get_quant_bot

    bot = get_quant_bot()
    insights = bot.get_learning_insights()

    return insights


@router.post("/bot/config")
async def update_bot_config(
    max_positions: Optional[int] = None,
    max_position_pct: Optional[float] = None,
    stop_loss_pct: Optional[float] = None,
    take_profit_pct: Optional[float] = None,
):
    """Update bot configuration."""
    from ..trading import get_quant_bot

    bot = get_quant_bot()

    if max_positions is not None:
        bot.max_positions = max_positions
    if max_position_pct is not None:
        bot.max_position_pct = max_position_pct
    if stop_loss_pct is not None:
        bot.stop_loss_pct = stop_loss_pct
    if take_profit_pct is not None:
        bot.take_profit_pct = take_profit_pct

    return {
        "status": "updated",
        "config": {
            "max_positions": bot.max_positions,
            "max_position_pct": bot.max_position_pct,
            "stop_loss_pct": bot.stop_loss_pct,
            "take_profit_pct": bot.take_profit_pct,
        }
    }


# ============ Options Quant Bot Endpoints ============

# ============ Master Quant Bot (Unified Trading) ============

@router.post("/master-bot/start")
async def start_master_bot(
    capital: float = 100000,
    mode: str = "balanced"
):
    """
    Start the Master Quant Bot - unified trading across ALL asset classes.

    The bot will automatically:
    - Scan all markets (stocks, ETFs, commodities, crypto)
    - Score opportunities using expected return, IV, and risk/reward
    - Execute the best trades across options, perpetuals, and crypto options
    - Manage positions with automatic stop-loss and take-profit

    Modes:
    - aggressive: Higher risk tolerance, more trades, tighter profit targets
    - balanced: Mix of strategies, moderate risk
    - conservative: Capital preservation focus, wider stops
    """
    from ..trading.master_bot import create_master_bot

    bot = create_master_bot(capital=capital, mode=mode)
    await bot.start()

    return {
        "status": "started",
        "capital": capital,
        "mode": mode,
        "message": f"Master Bot started - scanning ALL markets with ${capital:,.0f}",
        "asset_classes": ["stock_options", "etf_options", "commodity_options", "crypto_perpetual", "crypto_options"],
    }


@router.post("/master-bot/stop")
async def stop_master_bot():
    """Stop the Master Quant Bot."""
    from ..trading.master_bot import get_master_bot

    bot = get_master_bot()
    await bot.stop()
    return {"status": "stopped", "message": "Master Bot stopped - all trading halted"}


@router.get("/master-bot/status")
async def get_master_bot_status():
    """Get comprehensive Master Bot status including all asset classes."""
    from ..trading.master_bot import get_master_bot

    bot = get_master_bot()
    return bot.get_status()


@router.get("/master-bot/opportunities")
async def get_master_bot_opportunities(limit: int = 20):
    """Get top ranked trading opportunities across all markets."""
    from ..trading.master_bot import get_master_bot

    bot = get_master_bot()
    return {"opportunities": bot.get_opportunities(limit)}


@router.get("/master-bot/positions")
async def get_master_bot_positions():
    """Get all positions across all asset classes."""
    from ..trading.master_bot import get_master_bot

    bot = get_master_bot()
    return bot.get_all_positions()


@router.get("/master-bot/commentary")
async def get_master_bot_commentary(limit: int = 50):
    """Get the bot's real-time thinking and decisions."""
    from ..trading.master_bot import get_master_bot

    bot = get_master_bot()
    return {"commentary": bot.get_commentary(limit)}


@router.get("/master-bot/performance")
async def get_master_bot_performance():
    """Get performance metrics for the Master Bot."""
    from ..trading.master_bot import get_master_bot

    bot = get_master_bot()
    return bot.get_performance()


@router.get("/master-bot/trade-log")
async def get_master_bot_trade_log(limit: int = 50):
    """Get the trade log with LLM-generated summaries."""
    from ..trading.master_bot import get_master_bot

    bot = get_master_bot()
    return {
        "trades": bot.get_trade_log(limit),
        "total_trades": len(bot.trade_history),
    }


@router.get("/master-bot/activity-logs")
async def get_activity_logs(
    limit: int = 100,
    event_type: Optional[str] = None,
    symbol: Optional[str] = None,
):
    """
    Get bot activity logs for monitoring and debugging.

    Query params:
    - limit: Number of logs to return (default 100)
    - event_type: Filter by type (lifecycle, broker, trade, scan, ml, error, position, config, data)
    - symbol: Filter by trading symbol
    """
    from ..trading.activity_logger import get_activity_logger

    activity_logger = get_activity_logger()

    if event_type:
        logs = activity_logger.get_logs_by_type(event_type, limit)
    elif symbol:
        logs = activity_logger.get_logs_by_symbol(symbol.upper(), limit)
    else:
        logs = activity_logger.get_recent_logs(limit)

    return {
        "status": "success",
        "logs": logs,
        "count": len(logs),
        "session_id": activity_logger.session_id,
    }


@router.get("/master-bot/activity-logs/errors")
async def get_error_logs(limit: int = 50):
    """Get error, warning, and critical activity logs."""
    from ..trading.activity_logger import get_activity_logger

    activity_logger = get_activity_logger()
    logs = activity_logger.get_error_logs(limit)

    return {
        "status": "success",
        "logs": logs,
        "count": len(logs),
    }


@router.get("/master-bot/activity-logs/stats")
async def get_activity_stats():
    """Get activity logging statistics."""
    from ..trading.activity_logger import get_activity_logger

    activity_logger = get_activity_logger()
    stats = activity_logger.get_stats()

    return {
        "status": "success",
        "stats": stats,
    }


@router.post("/master-bot/scan")
async def trigger_master_bot_scan():
    """Manually trigger a full market scan."""
    from ..trading.master_bot import get_master_bot

    bot = get_master_bot()
    opportunities = await bot._scan_all_markets()
    return {
        "status": "scan_completed",
        "opportunities_found": len(opportunities),
        "top_5": [opp.to_dict() for opp in opportunities[:5]],
    }


@router.get("/master-bot/ml-analysis/{symbol}")
async def get_ml_analysis(symbol: str):
    """
    Get detailed ML analysis for a specific symbol.

    Returns:
    - ML prediction (DQN, PPO, LSTM, Transformer ensemble)
    - Market regime detection (HMM, VAE)
    - Risk metrics (VaR, CVaR, GARCH volatility forecast)
    - Factor exposures (market, size, value, momentum, etc.)
    - Bayesian Sharpe ratio with uncertainty
    """
    from ..trading.master_bot import get_master_bot

    bot = get_master_bot()
    analysis = bot.get_ml_analysis(symbol.upper())

    return {
        "status": "success",
        "analysis": analysis,
    }


@router.get("/master-bot/portfolio-optimization")
async def get_portfolio_optimization(
    method: str = "risk_parity",
    symbols: str = "SPY,QQQ,IWM,GLD,TLT",
):
    """
    Get optimal portfolio allocation using advanced optimization.

    Methods:
    - mean_variance: Classic Markowitz optimization
    - risk_parity: Equal risk contribution
    - cvar: Minimize Conditional Value at Risk (tail risk)
    - max_diversification: Maximum diversification ratio
    """
    from ..trading.master_bot import get_master_bot

    bot = get_master_bot()
    symbol_list = [s.strip().upper() for s in symbols.split(",")]

    weights = bot.analytics.optimize_portfolio(symbol_list, method=method)

    return {
        "status": "success",
        "method": method,
        "allocation": {k: round(v * 100, 2) for k, v in weights.items()},
        "total": round(sum(weights.values()) * 100, 2),
    }


@router.get("/master-bot/ml-metrics")
async def get_ml_metrics():
    """
    Get ML model training metrics and performance.

    Returns:
    - DQN training metrics (epsilon, losses)
    - PPO training metrics (policy loss, value loss)
    - Episode rewards
    - Model fit status (HMM, GARCH)
    """
    from ..trading.master_bot import get_master_bot
    import numpy as np

    bot = get_master_bot()
    analytics = bot.analytics

    return {
        "status": "success",
        "dqn": {
            "epsilon": round(analytics.dqn.epsilon, 4),
            "training_steps": analytics.training_step,
            "recent_losses": [round(l, 6) for l in analytics.dqn.losses[-20:]] if analytics.dqn.losses else [],
            "buffer_size": len(analytics.dqn.replay_buffer),
        },
        "ppo": {
            "policy_losses": [round(l, 4) for l in analytics.ppo.policy_losses[-10:]] if analytics.ppo.policy_losses else [],
            "value_losses": [round(l, 4) for l in analytics.ppo.value_losses[-10:]] if analytics.ppo.value_losses else [],
        },
        "episodes": {
            "total": len(analytics.episode_rewards),
            "recent_rewards": [round(r, 2) for r in analytics.episode_rewards[-10:]] if analytics.episode_rewards else [],
            # CRITICAL FIX: Check if list is not empty before np.mean, otherwise returns NaN
            "avg_reward": round(float(np.nanmean(analytics.episode_rewards[-50:]) if len(analytics.episode_rewards[-50:]) > 0 else 0.0), 2) if analytics.episode_rewards else 0,
        },
        "models_fitted": {
            "hmm": analytics.hmm_fitted,
            "garch": analytics.garch_fitted,
        },
    }


# ============ Options Bot (Legacy - use Master Bot instead) ============

@router.post("/options-bot/start")
async def start_options_bot(
    capital: float = 100000,
    mode: str = "balanced"
):
    """
    Start the Options Quant Bot.

    Modes:
    - aggressive: Higher delta targets, more trades, tighter strikes
    - balanced: Mix of strategies, moderate risk
    - conservative: Wide spreads, theta-focused, lower frequency
    """
    from ..trading.options_bot import create_options_bot

    bot = create_options_bot(capital=capital, mode=mode)
    await bot.start()

    return {
        "status": "started",
        "capital": capital,
        "mode": mode,
        "message": f"Options Bot started with ${capital:,.0f} in {mode} mode",
    }


@router.post("/options-bot/stop")
async def stop_options_bot():
    """Stop the Options Quant Bot."""
    from ..trading.options_bot import get_options_bot

    bot = get_options_bot()
    await bot.stop()
    return {"status": "stopped"}


@router.get("/options-bot/status")
async def get_options_bot_status():
    """Get current Options Bot status including Greeks exposure."""
    from ..trading.options_bot import get_options_bot

    bot = get_options_bot()
    return bot.get_status()


@router.get("/options-bot/positions")
async def get_options_bot_positions():
    """Get all current options positions with Greeks and P&L."""
    from ..trading.options_bot import get_options_bot

    bot = get_options_bot()
    return {"positions": bot.get_positions()}


@router.get("/options-bot/trades")
async def get_options_bot_trades(limit: int = 50):
    """Get recent options trades with full rationale."""
    from ..trading.options_bot import get_options_bot

    bot = get_options_bot()
    return {"trades": bot.get_trades(limit)}


@router.get("/options-bot/performance")
async def get_options_bot_performance():
    """Get performance metrics for the Options Bot."""
    from ..trading.options_bot import get_options_bot

    bot = get_options_bot()
    return bot.get_performance()


@router.get("/options-bot/commentary")
async def get_options_bot_commentary(limit: int = 50):
    """Get bot's real-time thinking/commentary."""
    from ..trading.options_bot import get_options_bot

    bot = get_options_bot()
    return {"commentary": bot.get_commentary(limit)}


@router.get("/options-bot/iv-analysis")
async def get_iv_analysis():
    """
    Get IV (Implied Volatility) analysis for watched symbols.

    Returns IV Rank, IV Percentile, and premium selling conditions.
    """
    from ..trading.options_bot import get_options_bot

    bot = get_options_bot()
    return {"iv_analysis": bot.get_iv_analysis()}


@router.post("/options-bot/scan")
async def trigger_options_scan():
    """Manually trigger a market scan for options opportunities."""
    from ..trading.options_bot import get_options_bot

    bot = get_options_bot()
    if not bot.is_running:
        raise HTTPException(status_code=400, detail="Options bot is not running")

    await bot._scan_opportunities()
    return {"status": "scan_completed", "positions": len(bot.positions)}


# ============ Crypto Derivatives Endpoints ============

@router.get("/options-bot/crypto/positions")
async def get_crypto_positions():
    """Get all crypto derivative positions (perpetuals, options)."""
    from ..trading.options_bot import get_options_bot

    bot = get_options_bot()
    return {"crypto_positions": bot.get_crypto_positions()}


class CryptoPerpRequest(BaseModel):
    """Request model for opening crypto perpetual."""
    symbol: str = "BTC-PERP"
    side: str = "long"  # "long" or "short"
    size_usd: float = 10000
    leverage: float = 1.0
    take_profit_pct: float = 0.10
    stop_loss_pct: float = 0.05


@router.post("/options-bot/crypto/perpetual/open")
async def open_crypto_perpetual(request: CryptoPerpRequest):
    """
    Open a crypto perpetual futures position.

    Supports: BTC-PERP, ETH-PERP, SOL-PERP, and other major perpetuals.
    """
    from ..trading.options_bot import get_options_bot

    bot = get_options_bot()

    if request.leverage > 10:
        raise HTTPException(status_code=400, detail="Max leverage is 10x for risk management")

    if request.side not in ["long", "short"]:
        raise HTTPException(status_code=400, detail="Side must be 'long' or 'short'")

    position = await bot.open_crypto_perpetual(
        symbol=request.symbol,
        side=request.side,
        size_usd=request.size_usd,
        leverage=request.leverage,
        take_profit_pct=request.take_profit_pct,
        stop_loss_pct=request.stop_loss_pct,
    )

    if position is None:
        raise HTTPException(status_code=400, detail="Failed to open position - check margin")

    return {"status": "opened", "position": position.to_dict()}


@router.post("/options-bot/crypto/perpetual/close/{position_id}")
async def close_crypto_perpetual(position_id: str, reason: str = "Manual close"):
    """Close a crypto perpetual position."""
    from ..trading.options_bot import get_options_bot

    bot = get_options_bot()

    if position_id not in bot.crypto_positions:
        raise HTTPException(status_code=404, detail="Position not found")

    await bot.close_crypto_perpetual(position_id, reason)
    return {"status": "closed", "position_id": position_id}


@router.get("/options-bot/crypto/supported")
async def get_supported_crypto_derivatives():
    """Get list of supported crypto derivatives."""
    from ..trading.options_bot import OptionsQuantBot

    return {
        "perpetuals": [d for d in OptionsQuantBot.CRYPTO_DERIVATIVES if d.endswith("-PERP")],
        "options": [d for d in OptionsQuantBot.CRYPTO_DERIVATIVES if d.endswith("-OPT")],
        "all": OptionsQuantBot.CRYPTO_DERIVATIVES,
    }


class CryptoOptionRequest(BaseModel):
    """Request model for opening crypto option."""
    base_asset: str = "BTC"  # "BTC" or "ETH"
    option_type: str = "call"  # "call" or "put"
    strike: float = 100000
    expiry_days: int = 30
    size_usd: float = 5000
    is_buy: bool = True


@router.post("/options-bot/crypto/option/open")
async def open_crypto_option(request: CryptoOptionRequest):
    """
    Open a crypto option position (Deribit-style).

    Supports BTC and ETH options with Black-Scholes pricing.
    """
    from ..trading.options_bot import get_options_bot

    bot = get_options_bot()

    if request.base_asset not in ["BTC", "ETH"]:
        raise HTTPException(status_code=400, detail="Only BTC and ETH options supported")

    if request.option_type not in ["call", "put"]:
        raise HTTPException(status_code=400, detail="Option type must be 'call' or 'put'")

    position = await bot.open_crypto_option(
        base_asset=request.base_asset,
        option_type=request.option_type,
        strike=request.strike,
        expiry_days=request.expiry_days,
        size_usd=request.size_usd,
        is_buy=request.is_buy,
    )

    if position is None:
        raise HTTPException(status_code=400, detail="Failed to open option - check funds")

    return {"status": "opened", "position": position.to_dict()}


@router.post("/options-bot/crypto/option/close/{position_id}")
async def close_crypto_option(position_id: str, reason: str = "Manual close"):
    """Close a crypto option position."""
    from ..trading.options_bot import get_options_bot

    bot = get_options_bot()

    if position_id not in bot.crypto_positions:
        raise HTTPException(status_code=404, detail="Position not found")

    await bot.close_crypto_option(position_id, reason)
    return {"status": "closed", "position_id": position_id}


# ============ Strategy Backtesting Endpoints ============

class StrategyBacktestRequest(BaseModel):
    """Request model for strategy backtesting."""
    symbol: str = "BTC"
    strategy_type: str = "combined_multi_factor"
    # RSI parameters
    rsi_period: int = 14
    rsi_oversold: float = 30
    rsi_overbought: float = 70
    # MACD parameters
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    # Bollinger parameters
    bb_period: int = 20
    bb_std: float = 2.0
    # Momentum parameters
    momentum_lookback: int = 20
    momentum_threshold: float = 0.05
    # Z-score parameters
    zscore_lookback: int = 20
    zscore_entry: float = -2.0
    zscore_exit: float = 0.0
    # Risk parameters
    stop_loss_pct: float = 0.05
    take_profit_pct: float = 0.10
    max_holding_days: int = 10
    position_size_pct: float = 0.10
    # Time period
    lookback_days: int = 365


@router.post("/strategy/backtest")
async def backtest_strategy(request: StrategyBacktestRequest):
    """
    Run a backtest for a specific trading strategy configuration.

    This tests the strategy on historical data to validate its effectiveness
    before deploying it in the Quant Bot.
    """
    from ..backtest.strategy_tester import (
        get_strategy_backtester,
        StrategyConfig,
        StrategyType,
    )

    # Map strategy type string to enum
    strategy_type_map = {
        "rsi_oversold": StrategyType.RSI_OVERSOLD,
        "rsi_overbought": StrategyType.RSI_OVERBOUGHT,
        "macd_crossover": StrategyType.MACD_CROSSOVER,
        "bollinger_bands": StrategyType.BOLLINGER_BANDS,
        "momentum": StrategyType.MOMENTUM,
        "mean_reversion": StrategyType.MEAN_REVERSION,
        "zscore": StrategyType.ZSCORE,
        "combined_multi_factor": StrategyType.COMBINED_MULTI_FACTOR,
    }

    strategy_type = strategy_type_map.get(
        request.strategy_type,
        StrategyType.COMBINED_MULTI_FACTOR
    )

    config = StrategyConfig(
        strategy_type=strategy_type,
        rsi_period=request.rsi_period,
        rsi_oversold=request.rsi_oversold,
        rsi_overbought=request.rsi_overbought,
        macd_fast=request.macd_fast,
        macd_slow=request.macd_slow,
        macd_signal=request.macd_signal,
        bb_period=request.bb_period,
        bb_std=request.bb_std,
        momentum_lookback=request.momentum_lookback,
        momentum_threshold=request.momentum_threshold,
        zscore_lookback=request.zscore_lookback,
        zscore_entry=request.zscore_entry,
        zscore_exit=request.zscore_exit,
        stop_loss_pct=request.stop_loss_pct,
        take_profit_pct=request.take_profit_pct,
        max_holding_days=request.max_holding_days,
        position_size_pct=request.position_size_pct,
    )

    backtester = get_strategy_backtester()

    end_date = datetime.now()
    start_date = end_date - timedelta(days=request.lookback_days)

    result = backtester.run_backtest(
        symbol=request.symbol,
        config=config,
        start_date=start_date,
        end_date=end_date,
    )

    if result is None:
        raise HTTPException(
            status_code=400,
            detail=f"Could not run backtest for {request.symbol}. Check that the symbol is valid."
        )

    return result.to_dict()


@router.post("/strategy/compare")
async def compare_strategies(
    symbol: str = "BTC",
    lookback_days: int = 365,
):
    """
    Compare all strategy types on a single symbol.

    Returns performance metrics for each strategy type to help users
    identify the best approach for their trading style.
    """
    from ..backtest.strategy_tester import (
        get_strategy_backtester,
        StrategyConfig,
        StrategyType,
    )

    backtester = get_strategy_backtester()
    end_date = datetime.now()
    start_date = end_date - timedelta(days=lookback_days)

    results = []
    for strategy_type in StrategyType:
        config = StrategyConfig(strategy_type=strategy_type)
        result = backtester.run_backtest(
            symbol=symbol,
            config=config,
            start_date=start_date,
            end_date=end_date,
        )
        if result:
            results.append({
                "strategy": strategy_type.value,
                "total_return": round(result.total_return * 100, 2),
                "sharpe_ratio": round(result.sharpe_ratio, 2),
                "max_drawdown": round(result.max_drawdown * 100, 2),
                "win_rate": round(result.win_rate * 100, 1),
                "total_trades": result.total_trades,
                "profit_factor": round(result.profit_factor, 2),
            })

    # Sort by Sharpe ratio
    results.sort(key=lambda x: x["sharpe_ratio"], reverse=True)

    return {
        "symbol": symbol,
        "period_days": lookback_days,
        "comparison": results,
        "best_strategy": results[0]["strategy"] if results else None,
    }


@router.get("/strategy/presets")
async def get_strategy_presets():
    """
    Get predefined strategy presets optimized for different trading styles.

    These presets are based on backtested configurations that have shown
    good risk-adjusted returns across different market conditions.
    """
    return {
        "conservative": {
            "name": "Conservative",
            "description": "Low risk, steady returns. Focus on mean reversion and quality signals.",
            "config": {
                "strategy_type": "combined_multi_factor",
                "rsi_period": 14,
                "rsi_oversold": 25,
                "rsi_overbought": 75,
                "macd_fast": 12,
                "macd_slow": 26,
                "macd_signal": 9,
                "bb_period": 20,
                "bb_std": 2.5,
                "momentum_lookback": 30,
                "momentum_threshold": 0.08,
                "zscore_lookback": 30,
                "zscore_entry": -2.5,
                "zscore_exit": 0.0,
                "stop_loss_pct": 0.08,
                "take_profit_pct": 0.15,
                "max_holding_days": 14,
                "position_size_pct": 0.05,
            },
            "expected_metrics": {
                "annual_return": "8-15%",
                "max_drawdown": "5-10%",
                "sharpe_ratio": "1.0-1.5",
            }
        },
        "moderate": {
            "name": "Moderate",
            "description": "Balanced risk/reward. Multi-factor approach with momentum and mean reversion.",
            "config": {
                "strategy_type": "combined_multi_factor",
                "rsi_period": 14,
                "rsi_oversold": 30,
                "rsi_overbought": 70,
                "macd_fast": 12,
                "macd_slow": 26,
                "macd_signal": 9,
                "bb_period": 20,
                "bb_std": 2.0,
                "momentum_lookback": 20,
                "momentum_threshold": 0.05,
                "zscore_lookback": 20,
                "zscore_entry": -2.0,
                "zscore_exit": 0.0,
                "stop_loss_pct": 0.05,
                "take_profit_pct": 0.10,
                "max_holding_days": 10,
                "position_size_pct": 0.10,
            },
            "expected_metrics": {
                "annual_return": "15-25%",
                "max_drawdown": "10-15%",
                "sharpe_ratio": "1.2-1.8",
            }
        },
        "aggressive": {
            "name": "Aggressive",
            "description": "High risk, high reward. Momentum-focused with tight stops.",
            "config": {
                "strategy_type": "momentum",
                "rsi_period": 10,
                "rsi_oversold": 35,
                "rsi_overbought": 65,
                "macd_fast": 8,
                "macd_slow": 17,
                "macd_signal": 9,
                "bb_period": 15,
                "bb_std": 1.5,
                "momentum_lookback": 10,
                "momentum_threshold": 0.03,
                "zscore_lookback": 15,
                "zscore_entry": -1.5,
                "zscore_exit": 0.5,
                "stop_loss_pct": 0.025,
                "take_profit_pct": 0.05,
                "max_holding_days": 5,
                "position_size_pct": 0.15,
            },
            "expected_metrics": {
                "annual_return": "25-50%",
                "max_drawdown": "15-25%",
                "sharpe_ratio": "0.8-1.5",
            }
        },
        "mean_reversion": {
            "name": "Mean Reversion",
            "description": "Buy oversold, sell overbought. Statistical approach.",
            "config": {
                "strategy_type": "zscore",
                "rsi_period": 14,
                "rsi_oversold": 25,
                "rsi_overbought": 75,
                "macd_fast": 12,
                "macd_slow": 26,
                "macd_signal": 9,
                "bb_period": 20,
                "bb_std": 2.0,
                "momentum_lookback": 20,
                "momentum_threshold": 0.05,
                "zscore_lookback": 20,
                "zscore_entry": -2.0,
                "zscore_exit": 0.0,
                "stop_loss_pct": 0.06,
                "take_profit_pct": 0.08,
                "max_holding_days": 7,
                "position_size_pct": 0.10,
            },
            "expected_metrics": {
                "annual_return": "12-20%",
                "max_drawdown": "8-12%",
                "sharpe_ratio": "1.3-2.0",
            }
        },
        "momentum_breakout": {
            "name": "Momentum Breakout",
            "description": "Catch strong trends early. MACD and momentum focused.",
            "config": {
                "strategy_type": "macd_crossover",
                "rsi_period": 14,
                "rsi_oversold": 40,
                "rsi_overbought": 60,
                "macd_fast": 12,
                "macd_slow": 26,
                "macd_signal": 9,
                "bb_period": 20,
                "bb_std": 2.0,
                "momentum_lookback": 15,
                "momentum_threshold": 0.04,
                "zscore_lookback": 20,
                "zscore_entry": -1.5,
                "zscore_exit": 0.5,
                "stop_loss_pct": 0.04,
                "take_profit_pct": 0.08,
                "max_holding_days": 8,
                "position_size_pct": 0.12,
            },
            "expected_metrics": {
                "annual_return": "18-30%",
                "max_drawdown": "12-18%",
                "sharpe_ratio": "1.0-1.6",
            }
        },
    }


# ============ Live Broker Management Endpoints ============


class BrokerCredentialsRequest(BaseModel):
    """Request model for setting broker credentials."""
    broker: str  # "alpaca" or "binance"
    is_paper: bool = True  # Paper/testnet mode by default for safety
    # FIX #15: Credentials now passed via Authorization header (not in request body)


class LiveOrderRequest(BaseModel):
    """Request model for live order submission."""
    symbol: str
    side: str  # "buy" or "sell"
    quantity: float
    order_type: str = "market"
    limit_price: Optional[float] = None


@router.post("/broker/credentials")
async def set_broker_credentials(
    request: BrokerCredentialsRequest,
    authorization: str = Header(None)
):
    """
    Set API credentials for a broker (Alpaca or Binance).

    IMPORTANT: Start with paper/testnet mode to verify everything works!

    For Alpaca (stocks/options):
    - Get API keys at: https://alpaca.markets
    - Paper trading is free and uses real market data
    - Set is_paper=false only when ready for live trading

    For Binance (crypto):
    - Get API keys at: https://www.binance.com/en/my/settings/api-management
    - Testnet available at: https://testnet.binancefuture.com
    - Set is_paper=false only when ready for live trading

    **Authorization Header Format:**
    Authorization: Bearer api_key:api_secret
    """
    from ..trading.live_brokers import get_broker_manager, BrokerType

    # FIX #15: Extract credentials from Authorization header (not request body)
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Missing or invalid Authorization header. Format: Bearer api_key:api_secret"
        )

    try:
        # Extract credentials from "Bearer api_key:api_secret" format
        credentials_str = authorization[7:]  # Remove "Bearer " prefix
        if ":" not in credentials_str:
            raise ValueError("Credentials must be in format: api_key:api_secret")
        api_key, api_secret = credentials_str.split(":", 1)
    except (ValueError, IndexError):
        raise HTTPException(
            status_code=400,
            detail="Invalid credentials format. Use: api_key:api_secret"
        )

    manager = get_broker_manager()

    if request.broker.lower() == "alpaca":
        broker_type = BrokerType.ALPACA
    elif request.broker.lower() == "binance":
        broker_type = BrokerType.BINANCE
    else:
        raise HTTPException(status_code=400, detail="Invalid broker. Use 'alpaca' or 'binance'")

    manager.set_credentials(
        broker=broker_type,
        api_key=api_key,
        api_secret=api_secret,
        is_paper=request.is_paper,
    )

    return {
        "status": "credentials_set",
        "broker": request.broker,
        "mode": "paper" if request.is_paper else "LIVE",
        "message": f"Credentials saved for {request.broker}. Use /broker/connect to connect.",
    }


@router.post("/broker/connect")
async def connect_brokers():
    """
    Connect to all configured brokers.

    Must set credentials first via /broker/credentials.
    Returns connection status for each broker.
    """
    from ..trading.live_brokers import get_broker_manager

    manager = get_broker_manager()

    if not manager.credentials:
        raise HTTPException(
            status_code=400,
            detail="No credentials configured. Use /broker/credentials first."
        )

    results = await manager.connect_all()

    return {
        "status": "connected",
        "results": results,
        "is_live_trading": manager.is_live,
        "warning": "LIVE TRADING ENABLED - Real money at risk!" if manager.is_live else None,
    }


@router.post("/broker/disconnect")
async def disconnect_brokers():
    """Disconnect from all brokers."""
    from ..trading.live_brokers import get_broker_manager

    manager = get_broker_manager()
    await manager.disconnect_all()

    return {"status": "disconnected", "message": "All broker connections closed"}


@router.get("/broker/status")
async def get_broker_status():
    """
    Get connection status for all brokers.

    Shows:
    - Which brokers are configured
    - Connection status
    - Trading mode (paper/live)
    """
    from ..trading.live_brokers import get_broker_manager

    manager = get_broker_manager()
    return manager.get_status()


@router.get("/broker/account")
async def get_broker_accounts():
    """
    Get account information from all connected brokers.

    Returns balances, buying power, and account status.
    """
    from ..trading.live_brokers import get_broker_manager

    manager = get_broker_manager()
    accounts = {}

    if manager.alpaca and manager.alpaca._connected:
        try:
            alpaca_account = await manager.alpaca.get_account()
            accounts["alpaca"] = {
                "equity": float(alpaca_account.get("equity", 0)),
                "cash": float(alpaca_account.get("cash", 0)),
                "buying_power": float(alpaca_account.get("buying_power", 0)),
                "portfolio_value": float(alpaca_account.get("portfolio_value", 0)),
                "status": alpaca_account.get("status"),
            }
        except Exception as e:
            # BUG FIX #28: Add logging for debugging account fetch failures
            logger.warning(f"Alpaca account fetch error: {e}")
            accounts["alpaca"] = {"error": str(e)}

    if manager.binance and manager.binance._connected:
        try:
            # Spot account
            spot_account = await manager.binance.get_account()
            balances = {
                b["asset"]: float(b["free"])
                for b in spot_account.get("balances", [])
                if float(b["free"]) > 0
            }

            # Futures account
            try:
                futures_account = await manager.binance.get_futures_account()
                futures_balance = float(futures_account.get("totalWalletBalance", 0))
                futures_unrealized = float(futures_account.get("totalUnrealizedProfit", 0))
            except Exception as e:  # FIX #10: Use Exception instead of bare except
                logger.warning(f"Failed to fetch futures account: {e}")
                futures_balance = 0
                futures_unrealized = 0

            accounts["binance"] = {
                "spot_balances": balances,
                "futures_balance": futures_balance,
                "futures_unrealized_pnl": futures_unrealized,
            }
        except Exception as e:
            accounts["binance"] = {"error": str(e)}

    if not accounts:
        raise HTTPException(status_code=400, detail="No brokers connected")

    return {"accounts": accounts}


@router.get("/broker/positions")
async def get_live_positions():
    """
    Get all live positions from connected brokers.

    Returns positions from both Alpaca (stocks) and Binance (crypto).
    """
    from ..trading.live_brokers import get_broker_manager

    manager = get_broker_manager()
    positions = await manager.get_all_positions()

    return {
        "positions": [
            {
                "symbol": p.symbol,
                "quantity": p.quantity,
                "side": p.side,
                "entry_price": p.entry_price,
                "current_price": p.current_price,
                "unrealized_pnl": p.unrealized_pnl,
                "market_value": p.market_value,
                "broker": p.broker.value,
            }
            for p in positions
        ],
        "total_positions": len(positions),
    }


@router.get("/broker/price/{symbol}")
async def get_live_price(symbol: str, asset_type: str = "stock"):
    """
    Get live price for a symbol.

    asset_type: 'stock' (Alpaca), 'crypto' (Binance spot), 'crypto_futures' (Binance perps)
    """
    from ..trading.live_brokers import get_broker_manager

    manager = get_broker_manager()
    price = await manager.get_live_price(symbol.upper(), asset_type)

    if price == 0:
        raise HTTPException(status_code=404, detail=f"Price not found for {symbol}")

    return {
        "symbol": symbol.upper(),
        "price": price,
        "asset_type": asset_type,
    }


@router.post("/broker/order/stock")
async def submit_live_stock_order(request: LiveOrderRequest):
    """
    Submit a live stock order via Alpaca.

    WARNING: This executes a REAL trade if connected in live mode!
    """
    from ..trading.live_brokers import get_broker_manager

    manager = get_broker_manager()

    if not manager.alpaca or not manager.alpaca._connected:
        raise HTTPException(status_code=400, detail="Alpaca not connected")

    try:
        order = await manager.submit_stock_order(
            symbol=request.symbol.upper(),
            quantity=request.quantity,
            side=request.side.lower(),
            order_type=request.order_type.lower(),
        )

        # BUG FIX #8: Fix boolean operator precedence error
        # Check if alpaca is connected and in credentials before accessing is_paper
        is_live = False
        if (manager.alpaca and manager.alpaca._connected and
            BrokerType.ALPACA in manager.credentials):
            is_live = not manager.credentials[BrokerType.ALPACA].is_paper

        return {
            "status": "order_submitted",
            "order_id": order.id,
            "symbol": order.symbol,
            "side": order.side,
            "quantity": order.quantity,
            "order_type": order.order_type,
            "order_status": order.status,
            "is_live": is_live,
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Order failed: {str(e)}")


@router.post("/broker/order/crypto")
async def submit_live_crypto_order(request: LiveOrderRequest, is_futures: bool = False):
    """
    Submit a live crypto order via Binance.

    WARNING: This executes a REAL trade if connected in live mode!

    Set is_futures=true for perpetual futures, false for spot.
    """
    from ..trading.live_brokers import get_broker_manager, BrokerType

    manager = get_broker_manager()

    if not manager.binance or not manager.binance._connected:
        raise HTTPException(status_code=400, detail="Binance not connected")

    try:
        order = await manager.submit_crypto_order(
            symbol=request.symbol.upper(),
            quantity=request.quantity,
            side=request.side.lower(),
            is_futures=is_futures,
        )

        return {
            "status": "order_submitted",
            "order_id": order.id,
            "symbol": order.symbol,
            "side": order.side,
            "quantity": order.quantity,
            "order_type": order.order_type,
            "order_status": order.status,
            "is_futures": is_futures,
            # BUG FIX #15: Use .get() for safe dict access (prevents KeyError)
            "is_live": not manager.credentials.get(BrokerType.BINANCE, type('obj', (), {'is_paper': True})).is_paper,
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Order failed: {str(e)}")


# ============ Live Trading Master Bot Endpoints ============


@router.post("/master-bot/enable-live-trading")
async def enable_live_trading():
    """
    Enable live trading mode for the Master Bot.

    IMPORTANT: Must configure and connect brokers first!

    This switches the bot from paper trading to live trading.
    All subsequent trades will be executed on real exchanges.
    """
    from ..trading.master_bot import get_master_bot
    from ..trading.live_brokers import get_broker_manager

    manager = get_broker_manager()
    bot = get_master_bot()

    # Verify brokers are connected
    status = manager.get_status()
    if not status["alpaca"]["connected"] and not status["binance"]["connected"]:
        raise HTTPException(
            status_code=400,
            detail="No brokers connected. Configure and connect brokers first."
        )

    # Set live trading mode on bot
    bot.live_trading_enabled = True
    bot.broker_manager = manager

    return {
        "status": "live_trading_enabled",
        "broker_status": status,
        "warning": "LIVE TRADING MODE - Real money will be used for trades!",
        "connected_brokers": [
            k for k, v in status.items()
            if isinstance(v, dict) and v.get("connected")
        ],
    }


@router.post("/master-bot/disable-live-trading")
async def disable_live_trading():
    """Switch Master Bot back to paper trading mode."""
    from ..trading.master_bot import get_master_bot

    bot = get_master_bot()
    bot.live_trading_enabled = False
    bot.broker_manager = None

    return {
        "status": "paper_trading_mode",
        "message": "Switched back to paper trading. No real trades will be executed.",
    }


@router.get("/master-bot/live-status")
async def get_live_trading_status():
    """
    Get the live trading status of the Master Bot.

    Shows whether live trading is enabled and broker connections.
    """
    from ..trading.master_bot import get_master_bot
    from ..trading.live_brokers import get_broker_manager

    bot = get_master_bot()
    manager = get_broker_manager()

    return {
        "live_trading_enabled": getattr(bot, 'live_trading_enabled', False),
        "broker_status": manager.get_status(),
        "bot_running": bot.is_running,
        "capital": bot.capital,
        "mode": bot.mode,
    }


# ===================
# ML TRAINING ENDPOINTS
# ===================

@router.post("/master-bot/train")
async def run_ml_training(
    days_of_data: int = 180,
    training_epochs: int = 40,  # Optimized for ~1 hour training
    background_tasks: BackgroundTasks = None
):
    """
    Run the ML training pipeline.

    This downloads historical data, trains all ML models (DQN, PPO, LSTM,
    Transformer, VAE), and saves checkpoints. Should be run BEFORE live trading.

    Args:
        days_of_data: Number of days of historical data to use (default: 180)
        training_epochs: Number of training epochs (default: 100)

    Returns:
        Training status and backtest results
    """
    from ..trading.master_bot import run_training_pipeline, get_master_bot

    bot = get_master_bot()

    # Check if bot is running - training shouldn't happen during live trading
    if bot.is_running:
        return {
            "error": "Cannot train while bot is running. Stop the bot first.",
            "is_running": True
        }

    bot._add_commentary(
        f"🧠 Starting ML training pipeline: {days_of_data} days, {training_epochs} epochs",
        "system"
    )

    try:
        result = await run_training_pipeline(
            days_of_data=days_of_data,
            training_epochs=training_epochs
        )

        return {
            "status": "success" if result.get("success") else "incomplete",
            "message": result.get("reason", "Training complete"),
            "training_metrics": result.get("training_metrics"),
            "backtest_result": result.get("backtest_result"),
            "checkpoint_path": result.get("checkpoint_path"),
        }

    except Exception as e:
        logger.error(f"Training pipeline error: {e}")
        return {
            "status": "error",
            "error": str(e)
        }


@router.get("/master-bot/training-status")
async def get_training_status():
    """
    Get the current ML training status.

    Returns whether models are trained and ready for live trading.
    """
    from ..trading.master_bot import get_master_bot
    from ..trading.backtester import CHECKPOINT_DIR

    bot = get_master_bot()
    pretrainer = bot.model_pretrainer

    meets_req, reason = pretrainer.meets_training_requirements()
    metrics = pretrainer.training_metrics

    checkpoint_exists = (CHECKPOINT_DIR / "model_checkpoint.pkl").exists()

    # CRITICAL FIX: If models are untrained, reset epsilon to 1.0
    # This ensures the dashboard always shows correct state
    if not bot.models_trained:
        pretrainer.dqn.epsilon = pretrainer.dqn.epsilon_start
        dqn_epsilon = round(pretrainer.dqn.epsilon, 4)
    else:
        dqn_epsilon = round(pretrainer.dqn.epsilon, 4)

    return {
        "models_trained": bot.models_trained,
        "meets_requirements": meets_req,
        "status_message": reason,
        "training_metrics": {
            "epochs_completed": metrics.epochs_completed,
            "total_samples": metrics.total_samples,
            "training_loss": metrics.training_loss[-10:] if metrics.training_loss else [],
            "prediction_accuracy": metrics.prediction_accuracy[-10:] if metrics.prediction_accuracy else [],
        },
        "checkpoint_exists": checkpoint_exists,
        "checkpoint_path": str(CHECKPOINT_DIR / "model_checkpoint.pkl"),
        "dqn_epsilon": dqn_epsilon,
        "is_pretrained_loaded": pretrainer.is_trained,
    }


@router.post("/master-bot/backtest")
async def run_backtest(days: int = 90):
    """
    Run a quick backtest with current models.

    Uses existing historical data and trained models to simulate trading.

    Args:
        days: Number of days to backtest (default: 90)

    Returns:
        Backtest results including Sharpe ratio, returns, win rate
    """
    from ..trading.master_bot import run_quick_backtest

    try:
        result = await run_quick_backtest(days=days)
        return result

    except Exception as e:
        logger.error(f"Backtest error: {e}")
        return {
            "error": str(e)
        }


@router.post("/master-bot/download-data")
async def download_historical_data(days: int = 365):
    """
    Download historical data for training.

    Downloads price data from Binance (crypto) and Yahoo Finance (stocks).

    Args:
        days: Number of days of data to download (default: 365)
    """
    from ..trading.backtester import get_data_downloader

    downloader = get_data_downloader()

    try:
        data = await downloader.download_all(days=days)

        symbols = list(data.keys())
        total_candles = sum(len(candles) for candles in data.values())

        return {
            "status": "success",
            "symbols_downloaded": symbols,
            "total_symbols": len(symbols),
            "total_candles": total_candles,
            "days": days,
        }

    except Exception as e:
        logger.error(f"Data download error: {e}")
        return {
            "status": "error",
            "error": str(e)
        }


@router.get("/master-bot/alpha-signals/{symbol}")
async def get_alpha_signals(symbol: str):
    """
    Get alternative alpha signals for a symbol.

    Returns sentiment, on-chain metrics, Fear & Greed index, and combined signal.
    """
    from ..trading.master_bot import get_master_bot

    bot = get_master_bot()

    try:
        alpha = await bot.alpha_manager.get_combined_alpha(symbol)
        return alpha

    except Exception as e:
        logger.error(f"Alpha signal error: {e}")
        return {
            "error": str(e),
            "symbol": symbol
        }


# ============ Prediction Markets ============

# Lazy-initialized singletons (avoids import-time HTTP calls)
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
            WeatherArbitrageStrategy,
            WhaleCopyTradingStrategy,
        )
        from ..prediction_markets.noaa_weather import NOAAWeatherClient

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
        _prediction_scanner.add_strategy(WhaleCopyTradingStrategy(client, config))

        # Advanced strategies
        try:
            from ..prediction_markets.advanced_strategies import (
                NOPositionScanner,
                LogicalImplicationDetector,
                WalletBehaviorDivergence,
                AdaptiveBuySignalThreshold,
            )
            _prediction_scanner.add_strategy(NOPositionScanner(client, config))
            _prediction_scanner.add_strategy(LogicalImplicationDetector(client, config))
            _prediction_scanner.add_strategy(WalletBehaviorDivergence(client, config))
        except Exception as e:
            logger.warning(f"Advanced strategies not loaded: {e}")

        # Weather arb needs NOAA forecasts
        weather_strategy = WeatherArbitrageStrategy(client, config)
        try:
            noaa = NOAAWeatherClient()
            forecasts = noaa.get_all_forecasts()
            weather_strategy.update_forecasts(forecasts)
        except Exception as e:
            logger.warning(f"NOAA forecast fetch failed (weather arb degraded): {e}")
        _prediction_scanner.add_strategy(weather_strategy)

    return _prediction_scanner


class MarketSearchRequest(BaseModel):
    query: str
    limit: int = 20


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
        status["gamma_api"]["error"] = str(e)

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
        status["clob_api"]["error"] = str(e)

    all_connected = status["gamma_api"]["connected"] and status["clob_api"]["connected"]
    return {
        "connected": all_connected,
        "exchange": "polymarket",
        **status,
    }


@router.get("/prediction-markets/markets")
async def list_prediction_markets(
    limit: int = 100,
    offset: int = 0,
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


@router.post("/prediction-markets/scan")
async def scan_prediction_markets(market_limit: int = 200):
    """Run all strategies and return identified opportunities."""
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
        raise HTTPException(status_code=502, detail=str(e))


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
        raise HTTPException(status_code=502, detail=str(e))


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
    exchange: str = "polymarket"
    market_id: str
    token_id: str
    side: str = "BUY"            # "BUY" or "SELL"
    order_type: str = "LIMIT"    # "MARKET", "LIMIT", "GTC", "FOK"
    size: float = 10.0           # Number of contracts
    price: Optional[float] = None  # Limit price (0.01-0.99)
    strategy: str = ""


@router.post("/prediction-markets/execute")
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


@router.post("/prediction-markets/portfolio/reset")
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
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/prediction-markets/orders")
async def get_prediction_orders(limit: int = 50):
    """Get prediction market order history."""
    executor = _get_prediction_executor()
    return {"orders": executor.get_order_history(limit=limit)}


@router.post("/prediction-markets/cancel/{order_id}")
async def cancel_prediction_order(order_id: str, exchange: str = "polymarket"):
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
    exchange: str = "polymarket"
    identifiers: List[str] = []  # token_ids for Polymarket


@router.post("/prediction-markets/feeds/subscribe")
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
    token_id: str,
    limit: int = 100,
    exchange: str = "polymarket",
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
async def get_prediction_pnl_history(portfolio_id: int = 1, limit: int = 200):
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
        from ..prediction_markets.orchestrator import PredictionMarketOrchestrator
        _orchestrator_instance = PredictionMarketOrchestrator(
            scanner=_get_prediction_scanner(),
            executor=_get_prediction_executor(),
        )
    return _orchestrator_instance


@router.post("/prediction-markets/bot/start")
async def start_prediction_bot(
    scan_interval_sec: int = 120,
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


@router.post("/prediction-markets/bot/stop")
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
async def get_prediction_activity_log(limit: int = 50):
    """Get recent activity log entries from the orchestrator."""
    orchestrator = _get_orchestrator()
    return {
        "entries": orchestrator.activity_log[:limit],
        "total_scans": orchestrator.total_scans,
        "total_executions": orchestrator.total_executions,
        "last_scan_result": orchestrator.last_scan_result,
    }


@router.post("/prediction-markets/bot/scan-now")
async def trigger_scan_and_execute():
    """Manually trigger one scan-and-execute cycle."""
    orchestrator = _get_orchestrator()
    if not orchestrator.scanner:
        orchestrator.scanner = _get_prediction_scanner()
    if not orchestrator.executor:
        orchestrator.executor = _get_prediction_executor()

    result = await orchestrator.scan_and_execute()
    return result


# ============ Prediction Markets — Risk Manager ============

@router.get("/prediction-markets/risk/status")
async def get_risk_status():
    """Get risk manager status (daily P&L, circuit breaker, limits)."""
    orchestrator = _get_orchestrator()
    return orchestrator.risk_manager.get_status()


@router.post("/prediction-markets/risk/enable-strategy/{strategy_name}")
async def enable_strategy(strategy_name: str):
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


@router.post("/prediction-markets/risk/config")
async def update_risk_config(req: RiskConfigUpdate):
    """Update risk manager configuration."""
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

@router.post("/prediction-markets/kill-switch/activate")
async def activate_kill_switch(reason: str = "manual"):
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


@router.post("/prediction-markets/kill-switch/deactivate")
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
async def get_vpin_metrics(token_id: Optional[str] = None):
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
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/prediction-markets/quant/avellaneda-stoikov")
async def get_as_diagnostics(token_id: str, mid_price: float, inventory: float = 0.0, hours_to_resolution: float = 24.0):
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
        raise HTTPException(status_code=500, detail=str(e))


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
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/prediction-markets/quant/bayesian/update")
async def update_bayesian_prior(key: str, signal_mean: float, signal_weight: float = 5.0):
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
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/prediction-markets/quant/monte-carlo-kelly")
async def get_mc_kelly_estimate(
    naive_kelly_fraction: float = 0.05,
    bankroll: float = 500.0,
    strategy: str = "market_making",
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
        raise HTTPException(status_code=500, detail=str(e))
