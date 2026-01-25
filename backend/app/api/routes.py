"""
API routes for QuantLab.
"""

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
from typing import Dict, List, Optional, Any
from datetime import date, datetime, timedelta
from loguru import logger
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
    initial_cash: float = 100000.0
    transaction_cost_bps: float = 10.0
    max_position_weight: float = 0.10
    target_volatility: float = 0.15


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
    return {
        "dates": [str(d.date()) for d in prices.index],
        "tickers": prices.columns.tolist(),
        "prices": prices.fillna(0).values.tolist(),
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
