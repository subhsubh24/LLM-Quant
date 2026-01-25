# QuantLab

**Rigorous Quant Research & Paper Trading Education Platform**

QuantLab is a local-first application for learning quantitative finance through hands-on research and paper trading. It combines a rigorous quant engine with an AI teaching layer to help data scientists transition into quantitative finance.

> **IMPORTANT DISCLAIMER**: This is an educational sandbox for paper trading only. It does NOT provide financial advice and should NOT be used for real investment decisions. Past performance in backtests does not indicate future results. Backtested results are subject to survivorship bias, look-ahead bias, and overfitting.

## Philosophy

This application takes a clear stance:

- **LLMs are NOT alpha engines**. The quant engine (math + stats + ML) produces forecasts and portfolios.
- **LLMs are teachers and analysts**. They explain what's happening, write research memos, and surface pitfalls.
- **Paper trading only**. No real money, no brokerage integration.
- **Research hygiene is paramount**. Leakage prevention, walk-forward validation, realistic costs.

## Features

### Quant Engine
- **Data Pipeline**: Fetch daily OHLCV from Stooq/Yahoo Finance, cached locally in SQLite
- **Feature Engineering**: Momentum, volatility, risk metrics with proper lag handling
- **ML Models**: Ridge, ElasticNet, Random Forest, Gradient Boosting, Ensemble
- **Walk-Forward Validation**: Proper time-series CV with embargo periods
- **Portfolio Optimization**: Mean-variance with Ledoit-Wolf shrinkage, position limits, volatility targeting
- **Backtesting**: Vectorized backtest with transaction costs, slippage, risk controls
- **Paper Trading**: Simulated portfolio execution with realistic costs

### Teaching Layer
- **Explain Mode**: Explanations for every stage (data → features → model → portfolio)
- **Pitfall Alerts**: Warnings about leakage, overfitting, survivorship bias
- **Research Memos**: Structured documentation of experiments
- **Quant Tutor**: Interactive lessons aligned with your work
- **Glossary**: Quick reference for quant terminology

### UI
- **Dashboard**: Portfolio overview, metrics, signals
- **Research Lab**: Configure and run backtests
- **Paper Trading**: Execute simulated trades
- **Performance**: Equity curves, risk metrics, attribution
- **Learn**: Structured lessons and contextual help

## Quick Start

### Prerequisites
- Python 3.11+
- Node.js 18+
- Git

### Option 1: Docker (Recommended)
```bash
# Clone the repository
git clone https://github.com/your-repo/quantlab.git
cd quantlab

# Start with Docker Compose
docker-compose up --build

# Open http://localhost:3000
```

### Option 2: Manual Setup

#### Backend
```bash
cd backend

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Copy environment file
cp .env.example .env

# Run the server
uvicorn app.api.main:app --reload --port 8000
```

#### Frontend
```bash
cd frontend

# Install dependencies
npm install

# Copy environment file
cp .env.example .env

# Run development server
npm run dev
```

Open http://localhost:3000

### Demo Mode

The app runs in demo mode by default with:
- Pre-configured universe of 50 liquid US stocks
- Cached sample data (no API calls needed)
- Deterministic random seed for reproducibility

### Adding LLM Support (Optional)

To enable AI-powered explanations:

1. Get an OpenAI API key from https://platform.openai.com/api-keys
2. Add to `backend/.env`:
   ```
   OPENAI_API_KEY=your-key-here
   ```
3. Restart the backend

The app works fully without an API key using template-based explanations.

## Project Structure

```
quantlab/
├── backend/
│   ├── app/
│   │   ├── api/          # FastAPI routes
│   │   ├── backtest/     # Backtesting engine
│   │   ├── data/         # Data providers and caching
│   │   ├── db/           # SQLModel database models
│   │   ├── features/     # Feature engineering
│   │   ├── llm/          # LLM teaching layer
│   │   ├── models/       # ML models and validation
│   │   └── portfolio/    # Portfolio optimization
│   ├── tests/
│   └── requirements.txt
├── frontend/
│   ├── app/              # Next.js pages
│   ├── components/       # React components
│   └── lib/              # Utilities
├── docker-compose.yml
└── README.md
```

## Learning Path to Quant Interviews

This app maps directly to concepts tested in quant interviews:

| App Feature | Interview Topic |
|-------------|-----------------|
| Data Quality Checks | "How do you handle survivorship bias?" |
| Feature Lag Logic | "How do you prevent look-ahead bias?" |
| Walk-Forward Validation | "Why not use k-fold cross-validation?" |
| Covariance Shrinkage | "Why use Ledoit-Wolf?" |
| Transaction Costs | "What's realistic slippage?" |
| Risk Metrics | "Explain Sharpe vs Sortino" |
| Attribution | "How do you decompose returns?" |

## What Quant Firms Look For

Based on the project philosophy:

1. **Research Hygiene**: Can you avoid leakage and overfitting?
2. **Statistical Rigor**: Do you understand validation, significance, regime shifts?
3. **Risk Awareness**: Do you think about drawdowns, constraints, tail risk?
4. **Clean Engineering**: Is your code modular, tested, and documented?
5. **Realistic Expectations**: Do you understand backtest != live trading?

## Contributing

This is an educational project. Contributions that improve rigor, add lessons, or fix bugs are welcome.

## License

MIT License - See LICENSE file.

## Acknowledgments

Built with:
- FastAPI (backend)
- Next.js + Tailwind (frontend)
- scikit-learn, pandas, cvxpy (quant engine)
- OpenAI API (optional LLM layer)

---

**Remember**: This is a learning tool. The goal is not to find the next alpha, but to build the skills and habits that quant firms value. Good luck with your interviews!
