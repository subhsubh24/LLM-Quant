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


# ============ Signal Generation ============

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
        from ..prediction_markets.orchestrator import get_orchestrator
        _orchestrator_instance = get_orchestrator()
        # Ensure scanner and executor are wired up
        if _orchestrator_instance.scanner is None:
            _orchestrator_instance.scanner = _get_prediction_scanner()
        if _orchestrator_instance.executor is None:
            from ..prediction_markets.execution import get_executor
            _orchestrator_instance.executor = get_executor(dry_run=True)
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
    """Get recent activity log entries and last scan opportunities from the orchestrator."""
    orchestrator = _get_orchestrator()
    return {
        "entries": orchestrator.activity_log[:limit],
        "total_scans": orchestrator.total_scans,
        "total_executions": orchestrator.total_executions,
        "last_scan_result": orchestrator.last_scan_result,
        "opportunities": orchestrator.last_scan_opportunities_raw,
    }


@router.post("/prediction-markets/bot/scan-now")
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
