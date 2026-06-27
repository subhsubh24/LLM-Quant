# QuantLab

**Rigorous Quant Research & Paper Trading Education Platform**

QuantLab is a local-first application for learning quantitative finance through hands-on research and paper trading. It combines a production-grade quant engine with an AI teaching layer (Anthropic Claude) to help data scientists transition into quantitative finance.

> **DISCLAIMER**: This is an educational sandbox for paper trading only. It does NOT provide financial advice and should NOT be used for real investment decisions. Past performance in backtests does not indicate future results.

## Philosophy

- **LLMs are NOT alpha engines**. The quant engine (math + stats + ML) produces forecasts and portfolios.
- **LLMs are teachers and analysts**. They explain what's happening, write research memos, and surface pitfalls.
- **Paper trading only**. No real money, no live brokerage execution.
- **Research hygiene is paramount**. Leakage prevention, walk-forward validation, realistic costs.

## Architecture Overview

```
LLM-Quant/
├── run_backtest.py            # Full pipeline: train + backtest
├── run_training.py            # Training only with checkpointing
├── run_backtest_only.py       # Synthetic data validation
├── requirements.txt           # Root dependencies
├── docker-compose.yml         # Full containerization
│
├── backend/
│   ├── app/
│   │   ├── api/               # FastAPI routes & main app
│   │   ├── config.py          # Settings management
│   │   ├── trading/           # Core trading engine (20+ modules)
│   │   │   ├── backtester.py  # Walk-forward backtest engine
│   │   │   ├── master_bot.py  # Training pipeline orchestrator
│   │   │   ├── ml_models.py   # DQN, PPO, LSTM, Transformer, VAE
│   │   │   ├── paper_trader.py
│   │   │   └── checkpoints/   # Saved model weights
│   │   ├── strategies/        # 14 independent trading strategies
│   │   ├── signals/           # Hybrid signal generation engines
│   │   ├── models/            # Ensemble ML combiners
│   │   ├── portfolio/         # Portfolio optimization & risk
│   │   ├── features/          # Feature engineering pipeline
│   │   ├── data/              # Market data providers
│   │   ├── llm/               # Anthropic Claude integration
│   │   ├── execution/         # Order execution layer
│   │   ├── monitoring/        # Performance monitoring
│   │   └── db/                # SQLModel database layer
│   ├── tests/
│   └── requirements.txt
│
└── frontend/                  # Next.js + TypeScript UI
    ├── app/
    │   ├── dashboard/         # Portfolio overview
    │   ├── research/          # Backtest research lab
    │   ├── crypto/            # Crypto trading interface
    │   ├── options/           # Options trading interface
    │   ├── performance/       # Equity curves & metrics
    │   ├── bot/               # Trading bot control panel
    │   ├── insights/          # Performance attribution
    │   └── learn/             # Educational modules
    └── components/            # Reusable React components
```

## Quick Start

### Prerequisites
- Python 3.11+
- Node.js 18+ (for frontend)
- Git

### Option 1: Docker (Recommended)
```bash
git clone https://github.com/subhsubh24/LLM-Quant.git
cd LLM-Quant
docker-compose up --build

# Backend: http://localhost:8000
# Frontend: http://localhost:3000
# API docs: http://localhost:8000/docs
```

### Option 2: Manual Setup

#### Backend
```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
pip install -r backend/requirements.txt

# Run the API server
uvicorn backend.app.api.main:app --reload --port 8000
```

#### Frontend
```bash
cd frontend
npm install
npm run dev
# Open http://localhost:3000
```

### Running Backtests

```bash
# Full pipeline: download data, train models, run backtest
python run_backtest.py

# Training only (with checkpoint saving)
python run_training.py

# Validate pipeline with synthetic data (no API keys needed)
python run_backtest_only.py
```

### Demo Mode

The app runs in demo mode by default:
- Pre-configured universe of liquid US stocks and crypto
- Deterministic random seed for reproducibility
- No API keys required for basic operation

## Core Components

### Trading Strategies (14 strategies)

All strategies inherit from `BaseStrategy` and register via `StrategyRegistry`:

| Strategy | Approach |
|----------|----------|
| **Trend Following** | Dual MA crossover with volume confirmation |
| **Mean Reversion** | Bollinger Bands + volume divergence |
| **Volatility Trading** | VIX-based with dynamic position sizing |
| **Sector Rotation** | Relative strength rotation across sectors |
| **Carry Trading** | Risk-on/risk-off positioning |
| **Technical Patterns** | RSI + MACD confluence signals |
| **Sentiment Analysis** | Alternative data integration |
| **Factor Rotation** | Value/Growth/Momentum switching |
| **Regime-Aware** | 3-state HMM regime detection |
| **Long Volatility** | Tail risk harvesting |
| **Intraday Mean Reversion** | Short-horizon mean reversion |
| **Kalman Filter Stat Arb** | Statistical arbitrage via Kalman filter |
| **Aristotle Rules-Based** | Rules-primary trend-following (bypasses ML for strong signals) |
| **Hybrid Ensemble** | Weighted combination of all strategies |

### Machine Learning Models

Five deep learning architectures trained via walk-forward validation:

- **DQN** (Deep Q-Network) - Reinforcement learning with prioritized experience replay
- **PPO** (Proximal Policy Optimization) - Policy gradient agent
- **LSTM** - Sequence prediction for multi-horizon forecasting
- **Transformer** - Attention-based cross-asset correlation modeling
- **VAE** (Variational Autoencoder) - Market regime detection

Models are combined via confidence-weighted ensemble voting with adaptive weighting based on recent performance.

### Signal Generation

The hybrid signal engine combines:
1. **Rules-based signals** (Aristotle strategy) - primary signal source
2. **ML consensus** - ensemble model predictions
3. **Factor signals** - 64+ technical features (MACD, Stochastic, ADX, OBV, Bollinger, Fibonacci, etc.)
4. **Regime detection** - sideways/trending/volatile classification

Strong rules-based signals bypass ML consensus checks for faster execution.

### Portfolio Optimization

- **Mean-Variance** with Ledoit-Wolf covariance shrinkage
- **Black-Litterman** portfolio optimization
- **CVaR** tail risk optimization
- **Risk Parity** allocation
- **Kelly Criterion** position sizing

### Risk Controls

| Control | Default |
|---------|---------|
| Max position weight | 10% |
| Max sector weight | 25% |
| Max leverage | 1.5x |
| Daily loss limit | 5% |
| Weekly loss limit | 10% |
| Max drawdown | 15-20% |
| Transaction costs | 10 bps |
| Slippage | 5 bps |
| Min stop-loss | 3% |

### Data Sources

| Market | Provider |
|--------|----------|
| US Stocks/ETFs | Yahoo Finance, Stooq |
| Crypto Spot | Binance, Kraken, Coinbase |
| Crypto Perpetuals | Binance, OKX |
| Options | Binance options chains |
| Commodities | ETF proxies (GLD, SLV, USO) |

### Broker Integration (Paper Trading)

- **Alpaca** - US stocks/ETFs (paper trading / testnet mode)
- **Binance** - Crypto spot & perpetuals (testnet mode by default)

All broker connections run in paper/testnet mode. Real API keys are optional.

## Feature Engineering

64+ features computed with proper lag handling (no look-ahead bias):

- **Momentum**: ROC, RSI, MACD, Stochastic, Williams %R
- **Volatility**: ATR, Bollinger Bands, Keltner Channels, historical vol
- **Volume**: OBV, VWAP, accumulation/distribution, money flow
- **Trend**: ADX, Aroon, Ichimoku, Parabolic SAR
- **Pattern**: Fibonacci levels, support/resistance, candlestick patterns
- **Cross-asset**: Correlation matrices, relative strength

## Teaching Layer (Optional)

Powered by Anthropic Claude:

- **Explain Mode** - Natural language explanations for every pipeline stage
- **Pitfall Alerts** - Warnings about leakage, overfitting, survivorship bias
- **Research Memos** - Structured documentation of experiments
- **Quant Tutor** - Interactive lessons aligned with your work

To enable:
```bash
# Add to backend/.env
ANTHROPIC_API_KEY=your-key-here
```

The app works fully without an API key using template-based explanations.

## API Endpoints

FastAPI server with auto-generated docs at `/docs`:

```
GET  /health                  # Health check
GET  /api/universes           # List symbol universes
POST /api/universes           # Create custom universe
GET  /api/data                # Fetch OHLCV data
POST /api/features            # Generate features
POST /api/models              # Train models
POST /api/backtest            # Run backtest
POST /api/paper-trade         # Execute paper trade
GET  /api/performance         # Portfolio metrics
POST /api/explain             # LLM explanations
```

## Learning Path to Quant Interviews

| App Feature | Interview Topic |
|-------------|-----------------|
| Data Quality Checks | "How do you handle survivorship bias?" |
| Feature Lag Logic | "How do you prevent look-ahead bias?" |
| Walk-Forward Validation | "Why not use k-fold cross-validation?" |
| Covariance Shrinkage | "Why use Ledoit-Wolf?" |
| Transaction Costs | "What's realistic slippage?" |
| Risk Metrics | "Explain Sharpe vs Sortino" |
| Regime Detection | "How do you handle regime changes?" |
| Ensemble Methods | "How do you combine model predictions?" |
| Position Sizing | "Explain Kelly Criterion vs risk parity" |
| Attribution | "How do you decompose returns?" |

## Tech Stack

**Backend**: Python 3.11+, FastAPI, SQLModel, SQLite

**ML/Data Science**: PyTorch, TensorFlow, scikit-learn, LightGBM, XGBoost, pandas, NumPy, SciPy, cvxpy, statsmodels

**Data**: yfinance, python-binance, ccxt, aiohttp

**Frontend**: Next.js, TypeScript, React, Tailwind CSS

**Infrastructure**: Docker Compose, Redis (optional), uvicorn

**LLM**: Anthropic Claude API (optional)

## Contributing

This is an educational project. Contributions that improve rigor, add lessons, or fix bugs are welcome.

## License

MIT License - See LICENSE file.

---

**Remember**: This is a learning tool. The goal is not to find the next alpha, but to build the skills and habits that quant firms value. Good luck with your interviews!
