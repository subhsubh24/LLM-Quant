"""
API routes for QuantLab.
"""

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
from typing import Dict, List, Optional, Any
from datetime import date, datetime, timedelta
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
        "sections": ["universes", "data", "features", "models", "backtest", "portfolio", "trading", "options", "crypto", "bot"]
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
    market_service = get_live_market_service()
    quotes = await market_service.get_quotes_batch(universe.tickers)
    current_prices = {q.symbol: q.price for q in quotes.values()}

    # Generate signals and rebalance
    trader = get_auto_trader()
    signals = trader.generate_signals(prices)
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
async def create_market_order(
    symbol: str,
    side: str,  # buy, sell
    quantity: float,
):
    """Create a market order."""
    from ..trading import get_order_manager, OrderSide

    manager = get_order_manager()
    order_side = OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL

    order = manager.create_market_order(
        symbol=symbol,
        side=order_side,
        quantity=quantity,
    )

    return order.to_dict()


@router.post("/trading/order/limit")
async def create_limit_order(
    symbol: str,
    side: str,
    quantity: float,
    limit_price: float,
):
    """Create a limit order."""
    from ..trading import get_order_manager, OrderSide

    manager = get_order_manager()
    order_side = OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL

    order = manager.create_limit_order(
        symbol=symbol,
        side=order_side,
        quantity=quantity,
        limit_price=limit_price,
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
async def create_stop_order(
    symbol: str,
    side: str,
    quantity: float,
    stop_price: float,
    limit_price: Optional[float] = None,
):
    """Create a stop or stop-limit order."""
    from ..trading import get_order_manager, OrderSide

    manager = get_order_manager()
    order_side = OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL

    order = manager.create_stop_order(
        symbol=symbol,
        side=order_side,
        quantity=quantity,
        stop_price=stop_price,
        limit_price=limit_price,
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
    expiration_days: int = 30,
    volatility: float = 0.30,
    num_strikes: int = 11,
):
    """Get options chain for a symbol."""
    from ..trading import get_options_manager
    from ..data.live import get_live_market_service

    # Get current price
    market_service = get_live_market_service()
    quote = await market_service.get_quote(symbol.upper())

    if not quote:
        raise HTTPException(status_code=404, detail=f"Quote not found for {symbol}")

    # Generate chain
    manager = get_options_manager()
    expiration = date.today() + timedelta(days=expiration_days)

    chain = manager.generate_options_chain(
        symbol=symbol.upper(),
        underlying_price=quote.price,
        expiration=expiration,
        volatility=volatility,
        num_strikes=num_strikes,
    )

    return {
        "symbol": symbol.upper(),
        "underlying_price": quote.price,
        "expiration": expiration.isoformat(),
        "volatility": volatility,
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
