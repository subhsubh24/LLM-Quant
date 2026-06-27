# Project State Assessment

**Date**: 2026-03-14 (updated from 2026-03-07)
**Branch**: `claude/assess-project-state-rlGsj`
**Codebase**: QuantLab (LLM-Quant)

## Executive Summary

QuantLab is a large, ambitious quantitative finance platform with ~88,400 lines of Python backend code, a Next.js frontend, and Docker containerization. The system now runs live: the prediction market orchestrator scans Polymarket, tracks 50 whale wallets, enriches order books via the CLOB API, and executes through Alpaca (paper) and Binance (live) brokers with real-time WebSocket price feeds (Kraken, Polymarket). Recent commits fixed critical scanner bugs (stale markets, false 99%+ edges, aggressive adaptive thresholds) and reduced log noise. The core loop — scan → filter → size → execute — is operational in dry-run mode.

---

## 1. Codebase Metrics

| Metric | Value |
|--------|-------|
| Backend Python files | ~163 |
| Backend lines of code | ~88,400 |
| Test files | 42+ |
| Tests collected | 1,133 |
| Largest file | `backtester.py` (6,824 lines) |
| Markdown docs at root | 22 files |
| Frontend pages | 12 (dashboard, research, crypto, options, performance, bot, insights, learn, trading, predictions) |

## 2. Architecture

### Backend (`backend/app/`)

The backend is a FastAPI application with these major subsystems:

| Module | Purpose | Files |
|--------|---------|-------|
| `trading/` | Core engine: backtester (6.8k LOC), master_bot, ML models, paper trader, stat arb, quant analytics | ~15 files |
| `strategies/` | 14 independent trading strategies (trend, mean reversion, volatility, sector rotation, etc.) | ~14 files |
| `prediction_markets/` | Polymarket/Kalshi integration, orchestrator, risk manager, quant models, whale indexer | ~10 files |
| `data/` | Market data providers (Yahoo, Binance, Kraken, Coinbase) + 17 alternative data providers | ~20 files |
| `data/alternative/` | FRED, Google Trends, EDGAR, news sentiment, options signals, weather, congressional trades | 17 files |
| `portfolio/` | Mean-variance, Black-Litterman, CVaR, risk parity optimization | ~5 files |
| `features/` | 64+ technical feature engineering with lag handling | 2 files |
| `signals/` | Hybrid signal generation (rules + ML + factors + regime) | ~3 files |
| `models/` | Ensemble ML combiners | ~3 files |
| `backtest/` | Advanced backtesting, attribution, metrics, validation | 6 files |
| `execution/` | Smart order routing, adaptive execution | 3 files |
| `monitoring/` | Anomaly detection, performance monitoring | ~3 files |
| `simulation/` | Monte Carlo, importance sampling, particle filters, vine copulas, agent-based models | 6 files (UNTRACKED) |
| `llm/` | Anthropic Claude teaching layer integration | ~2 files |
| `db/` | SQLModel database layer | 2 files |
| `api/` | FastAPI routes and main app | 2 files |

### Frontend (`frontend/`)

Next.js + TypeScript + React + Tailwind CSS with 12 pages covering portfolio dashboard, research lab, crypto/options trading, performance analytics, bot control, and educational modules.

### Infrastructure

- **Docker Compose**: Backend (FastAPI) + Frontend (Next.js) containers
- **Database**: SQLite via SQLModel (lightweight, local-first)
- **Optional**: Redis for caching

## 3. Key Strengths

1. **Comprehensive test suite**: 1,077 tests all passing. Good coverage of strategies, edge cases, bug fixes, and integration scenarios.
2. **Rich strategy library**: 14 well-structured strategies inheriting from `BaseStrategy` with `StrategyRegistry` pattern.
3. **Production-grade risk controls**: Circuit breakers, kill switch, daily loss limits, position limits, drawdown stops.
4. **Institutional quant models**: Avellaneda-Stoikov market making, VPIN toxicity, Bayesian updating, Monte Carlo Kelly, copulas, EVT/tail risk, GARCH, HMM regime detection.
5. **Broad data integration**: 5+ market data providers, 17 alternative data providers with graceful fallbacks.
6. **Prediction markets**: Full Polymarket/Kalshi cross-exchange arbitrage with on-chain whale tracking.
7. **Educational design**: Paper trading only, with LLM teaching layer for explanations.

## 4. Key Concerns

### 4.1 Architectural Debt

- **`backtester.py` is 6,824 lines** — a God Object that handles position management, exit logic, regime detection, pyramiding, trailing stops, and more. The PLAN.md identifies specific bugs in this file. It needs decomposition.
- **Tight coupling** between trading logic and backtesting infrastructure makes unit testing of individual concerns difficult.

### 4.2 Documentation Sprawl

22 markdown files at the root level, many overlapping:
- 6 audit-related docs (`AUDIT_FINDINGS.md`, `AUDIT_FIXES_SUMMARY.md`, `AUDIT_PLAN.md`, `AUDIT_STATUS.txt`, `COMPREHENSIVE_AUDIT_*`, `CLUSTER_4_AUDIT_RESULTS.md`)
- 4 bug fix docs (`BUG_FIX_SUMMARY.md`, `CRITICAL_BUG_FIXES_SUMMARY.md`, `COMPREHENSIVE_BUG_AUDIT*.md`, `FINAL_BUG_AUDIT_SUMMARY.md`)
- 3 test docs (`TEST_SUITE_*.md`)

These appear to be artifacts of iterative AI-assisted development. A single `CHANGELOG.md` or consolidated status doc would be cleaner.

### 4.3 Untracked Simulation Layer

6 new simulation files in `backend/app/simulation/` plus 2 integration files are **untracked** (not committed):
- `monte_carlo.py` - GBM path simulation, binary contract pricing
- `importance_sampling.py` - Rare event estimation
- `variance_reduction.py` - Antithetic/stratified/control variates
- `particle_filter.py` - Sequential Monte Carlo
- `vine_copula.py` - High-dimensional dependency modeling
- `agent_based.py` - Heterogeneous agent simulation
- `prediction_markets/simulation_integration.py` - Bridge to prediction markets
- `trading/simulation_integration.py` - Bridge to trading engine

These address the gaps identified in `QUANT_SIMULATION_ASSESSMENT.md` (improving coverage from ~60-65% to potentially ~90%+ of the quant desk framework). **They need tests and should be committed.**

### 4.4 Known Bugs (from PLAN.md)

The backtester has a documented risk/reward asymmetry:
- 54% win rate but -10.56% return (profit factor 0.71)
- Trailing stop prematurely kills winning trades
- Counter-trend stops are widened instead of tightened
- No R:R safety net at entry

Three specific fixes are planned but not yet implemented.

### 4.5 Test Warnings

14 warnings about test functions returning values instead of using `assert` (in `test_training_pipeline.py`). These tests pass but may not actually validate their results.

### 4.6 Security

- `.env` file is tracked in git (contains API key placeholders). Should be in `.gitignore`.
- No secrets appear to be committed (keys are placeholder values).

## 5. Technology Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.11+, FastAPI, SQLModel, SQLite |
| ML/DS | PyTorch, TensorFlow, scikit-learn, LightGBM, XGBoost, SciPy, cvxpy |
| Data | yfinance, python-binance, ccxt, aiohttp |
| Frontend | Next.js, TypeScript, React, Tailwind CSS |
| Infra | Docker Compose, Redis (optional), uvicorn |
| LLM | Anthropic Claude API (optional) |

## 6. Live System Observations (2026-03-14)

From the server startup logs, the following subsystems are **confirmed operational**:

### Working Well
- **Startup pipeline**: DB init → Crypto WS → Prediction feeds → Orchestrator → Broker auto-connect all succeed
- **Polymarket scanner**: Fetches 100 markets, filters 58 stale ones, leaving 42 active markets
- **CLOB enrichment**: Enriches 74 outcomes across 40 markets with live order book data
- **Whale feed**: Seeds 3 hardcoded whales, discovers 47 more from `/holders` (50 total), fetches 334 whale trades, feeds them to WhaleCopy and WalletDivergence strategies
- **Strategy execution**: 6 strategies run per scan cycle:
  - `same_market_arb`: 0 hits (correct — no easy arb)
  - `market_making`: 8 opportunities
  - `logical_implication`: 9 hits (graph: 15 nodes, 14 edges)
  - `wallet_divergence`: 0 signals (2 divergences, no actionable markets)
  - `near_certainty`: 3 hits
  - `cross_market_arb`: 0 hits (20 rules, 108 pairs)
  - `no_position_scanner`: 2 hits
  - `adaptive_threshold`: 3 passed / 2 filtered
- **Broker connections**: Alpaca (paper) and Binance (US, live) both connect successfully
- **Crypto WebSocket**: Kraken connected, streaming 51 pairs
- **Polymarket WebSocket**: Connected for live price updates
- **Scan result**: 20 total opportunities → 10 executed, 10 skipped (risk controls working)

### Issues Observed
1. **Coinbase WebSocket timeout**: `timed out during opening handshake` — falls back to Kraken (working as designed, but Coinbase is effectively dead)
2. **Polymarket WS initial disconnect**: Timeout on first attempt, reconnects successfully after 1s
3. **Most tracked whales show $0 PnL/0% WR**: 47 of 50 whales discovered from `/holders` have no profile data — the feed discovers them but can't fetch their historical PnL. Only the 3 hardcoded whales (Theo4, Fredi9999, SeriouslySirius) have meaningful profiles
4. **All adaptive_threshold passes have very high edges**: 72.3% edge on "Wizards vs. Celtics" suggests the model may be mispricing or the market is illiquid — warrants investigation
5. **Scan cycle takes ~108 seconds**: First scan started at 15:15:39, completed at 15:17:27. This is close to the 120s scan interval, meaning scans run nearly back-to-back with minimal idle time

## 7. Recent Fixes (last 10 commits)

| Commit | Fix |
|--------|-----|
| `26115fe` | Fix false 99%+ edges and reduce log noise |
| `6272253` | Downgrade CLOB 404 errors to debug level |
| `b1449fe` | Fix scanner fetching stale resolved markets from Gamma API |
| `49e626f` | Fix Pydantic `protected_namespaces` warnings for `model_` fields |
| `31ee2db` | Fix scanner finding zero opportunities due to 20% adaptive threshold |
| `ef5f068` | Lower Kelly sizing min_edge 3%→1% and min_confidence 60%→50% |
| `4d90f33` | Fix snapshot `kalshi_value` error and loosen scanner thresholds |
| `bd47f1b` | Add top tab navigation with Dashboard, Predictions, Quant Bot |
| `b7c2c5f` | Remove sidebar navigation and tabs |
| `ceea83b` | Run scanner in thread, log CLOB enrichment failures |

## 8. Recommended Priorities

### Immediate (operational issues)
1. **Enrich discovered whale profiles** — 47/50 whales have $0 PnL. Either fetch historical data from the Data API or rank by position size instead of PnL/win-rate.
2. **Validate high-edge opportunities** — 72.3% edge on a sports market likely indicates a stale price or illiquid book. Add a liquidity/freshness gate.
3. **Investigate Coinbase WS failures** — If Coinbase is consistently dead, remove it from the fallback chain or add a longer timeout.

### Short-term (code quality)
4. **Commit the simulation layer** — The 8 untracked files in `simulation/` represent significant work. Add tests and commit.
5. **Fix backtester bugs** — Implement the 3 changes in PLAN.md (trailing stop, counter-trend stops, R:R gate).
6. **Refactor `backtester.py`** — Extract position management, exit logic, and regime detection into separate modules (6,824 lines is unmaintainable).

### Medium-term (project hygiene)
7. **Consolidate documentation** — Replace 22 root-level markdown files with a single CHANGELOG and focused ARCHITECTURE doc.
8. **Fix test warnings** — Convert `return True/False` patterns to proper `assert` in `test_training_pipeline.py`.
9. **Add `.env` to `.gitignore`** — Prevent accidental secret commits.
