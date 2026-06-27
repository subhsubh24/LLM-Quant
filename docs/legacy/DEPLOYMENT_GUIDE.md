# LLM-Quant Trading System - Deployment Guide

**Version**: 1.0
**Environment**: Production-grade
**Target Uptime**: 99.5%+
**Deployment Time**: 30-60 minutes

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Installation](#installation)
3. [Configuration](#configuration)
4. [Deployment](#deployment)
5. [Post-Deployment Validation](#post-deployment-validation)
6. [Operational Runbook](#operational-runbook)
7. [Troubleshooting](#troubleshooting)
8. [Rollback Procedures](#rollback-procedures)

---

## 1. Prerequisites

### System Requirements

**Hardware**:
- CPU: 8+ cores (Intel/AMD)
- RAM: 32GB minimum (64GB recommended)
- Storage: 500GB SSD (1TB for historical data)
- Network: 1Gbps connection, <50ms latency to exchanges

**Software**:
- OS: Linux (Ubuntu 20.04 LTS recommended)
- Python: 3.9+ (3.11 recommended)
- Database: Redis 6.0+ (caching)
- Message Queue: RabbitMQ 3.8+ (order routing)
- Container: Docker 20.10+ (optional but recommended)

### Dependencies

```bash
# Core
numpy>=1.21.0
pandas>=1.3.0
scipy>=1.7.0
scikit-learn>=1.0.0

# ML/Data
lightgbm>=3.3.0
tensorflow>=2.8.0
keras>=2.8.0

# Trading
ccxt>=2.0.0  # Exchange connectivity
broker-api>=1.0.0  # Broker integration

# Utilities
python-dateutil>=2.8.0
pytz>=2021.3
pyyaml>=5.4.0
pytest>=7.0.0
```

### Credentials & APIs

Required before deployment:
- Broker API credentials (paper/live trading)
- Market data API keys
- NewsAPI key (for sentiment)
- Monitoring tool credentials (if external)

---

## 2. Installation

### 2.1 Clone Repository

```bash
git clone https://github.com/yourusername/LLM-Quant.git
cd LLM-Quant
git checkout main  # or specific release tag
```

### 2.2 Environment Setup

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Upgrade pip
pip install --upgrade pip setuptools wheel

# Install dependencies
pip install -r requirements.txt

# Install development dependencies (testing)
pip install -r requirements-dev.txt
```

### 2.3 Verify Installation

```bash
# Test imports
python -c "import numpy, pandas, lightgbm; print('✓ Core dependencies OK')"

# Run basic tests
pytest backend/tests/test_execution_optimization.py::TestOptimizedExecutionEngine -v

# Check system configuration
python scripts/validate_system.py
```

### 2.4 Docker Setup (Optional)

```bash
# Build Docker image
docker build -t llm-quant:1.0 .

# Run container
docker run -d \
  --name llm-quant-prod \
  -e CONFIG_FILE=/config/production.yaml \
  -v /data/config:/config \
  -v /data/logs:/logs \
  -p 8080:8080 \
  llm-quant:1.0
```

---

## 3. Configuration

### 3.1 Main Configuration File

Create `config/production.yaml`:

```yaml
# System Configuration
system:
  name: "LLM-Quant Trading System"
  version: "1.0"
  environment: "production"
  log_level: "INFO"

# Trading Parameters
trading:
  initial_capital: 1000000  # $1M
  max_leverage: 2.0
  rebalance_frequency: 5  # days
  update_interval: 60  # seconds

# Risk Management
risk:
  daily_loss_limit: 0.05  # 5%
  weekly_loss_limit: 0.15  # 15%
  monthly_loss_limit: 0.30  # 30%
  max_position_size: 0.01  # 1%
  correlation_alert_threshold: 0.85

# Strategy Configuration
strategies:
  enabled:
    - "trend_following"
    - "mean_reversion"
    - "volatility_trading"
    - "sector_rotation"
    - "sentiment_analysis"
  weights:
    core: 0.40
    enhanced: 0.35
    ml: 0.20
    sentiment: 0.05

# Execution
execution:
  order_type: "vwap"  # vwap, twap, market
  max_slippage_bps: 10.0
  execution_timeout_seconds: 300
  retry_max_attempts: 5
  retry_backoff_initial: 2.0  # seconds

# Data Sources
data:
  market_data:
    source: "broker_api"
    update_frequency: "1min"
  alternative_data:
    news_api: true
    options_data: true
    social_sentiment: true

# Monitoring
monitoring:
  health_check_interval: 60  # seconds
  alert_webhook: "https://hooks.slack.com/..."
  metrics_collection: true
  dashboard_port: 8080

# Broker Configuration
broker:
  name: "interactive_brokers"  # or your broker
  account_type: "paper"  # "paper" for testing, "live" for production
  connect_timeout: 30  # seconds
```

### 3.2 Strategy Parameters

Create `config/strategy_params.yaml`:

```yaml
strategies:
  trend_following:
    sma_short: 20
    sma_long: 50
    momentum_period: 14
    confidence_threshold: 0.5

  mean_reversion:
    period: 20
    std_dev_multiplier: 2.0
    min_volume_ratio: 1.0
    use_atr: true

  sentiment_analysis:
    confidence_threshold: 0.3
    source_count_required: 1
    trend_boost: 0.1

  ml_ensemble:
    lightgbm_weight: 0.4
    lstm_weight: 0.4
    meta_weight: 0.2
    degradation_threshold: 0.1
```

### 3.3 Risk Parameters

Create `config/risk_params.yaml`:

```yaml
risk_management:
  position_limits:
    per_security: 0.01  # 1%
    per_sector: 0.10    # 10%
    total_leverage: 2.0

  circuit_breakers:
    daily:
      warning: 0.05     # 5%
      critical: 0.08    # 8%
    weekly:
      warning: 0.15     # 15%
      critical: 0.20    # 20%

  correlation_limits:
    portfolio_correlation_max: 0.85
    sector_correlation_max: 0.90
```

---

## 4. Deployment

### 4.1 Pre-Deployment Checklist

```bash
# 1. Run all tests
pytest backend/tests/ -v --tb=short

# 2. Validate configuration
python scripts/validate_config.py --config config/production.yaml

# 3. Backtest on last 60 days
python scripts/backtest.py --config config/production.yaml --days 60

# 4. Check data feed connectivity
python scripts/test_data_feed.py

# 5. Verify broker connectivity
python scripts/test_broker_connection.py --paper
```

### 4.2 Database Initialization

```bash
# Initialize Redis cache
redis-cli FLUSHALL  # Clean slate
redis-cli CONFIG SET maxmemory 4gb
redis-cli CONFIG SET maxmemory-policy allkeys-lru

# Initialize PostgreSQL (if using for historical data)
psql -U postgres -f scripts/init_database.sql
python scripts/load_historical_data.py --source "IB" --days 1825  # 5 years
```

### 4.3 System Start-Up

```bash
# Method 1: Direct Python
python -m backend.app.main --config config/production.yaml &

# Method 2: Systemd Service
sudo systemctl start llm-quant

# Method 3: Docker
docker run -d --name llm-quant-prod \
  --network host \
  -v $(pwd)/config:/config \
  -v $(pwd)/logs:/logs \
  llm-quant:1.0

# Verify startup
sleep 5
curl http://localhost:8080/health
# Expected: {"status": "RUNNING", "score": 85}
```

### 4.4 Gradual Rollout (Canary Deployment)

```bash
# Phase 1: Paper Trading (24 hours)
- Run system on paper trading account
- Monitor P&L, execution quality, latency
- Validate all signals

# Phase 2: Small Live Position (1-5% allocation)
- Deploy to live account with 1% of capital
- Monitor for 1 week
- Check execution costs, market impact

# Phase 3: Ramp (5-25% allocation)
- Increase to 5% over 3 days
- Watch for slippage, correlation changes
- Scale to 25% over next week

# Phase 4: Full Deployment (100% allocation)
- After 2 weeks of stable operation
- Full capital deployment
- Continuous monitoring
```

---

## 5. Post-Deployment Validation

### 5.1 Immediate Checks (Hour 1)

```bash
# System health
curl http://localhost:8080/health

# Strategy performance
curl http://localhost:8080/strategies/status

# Execution metrics
curl http://localhost:8080/execution/quality

# Data feed
curl http://localhost:8080/data/feed-health
```

### 5.2 Daily Validation (End of Day)

```bash
# Run health report
python scripts/daily_report.py --date today

# Backtest today's trades
python scripts/validate_daily_trades.py

# Model performance
python scripts/ml_model_check.py

# Risk check
python scripts/check_risk_limits.py
```

### 5.3 Weekly Validation

```bash
# Performance metrics
- Sharpe ratio: target 4.0+
- Max drawdown: should be <15%
- Win rate: should be 55%+
- Execution cost: should be <5 bps

# System metrics
- Uptime: >99.5%
- P99 latency: <100ms
- Data gaps: 0

# Model drift
- Model accuracy stable
- No degradation detected
- Calibration error <5%
```

---

## 6. Operational Runbook

### 6.1 Normal Operations

**Morning Pre-Market (8:00 AM)**
```bash
# 1. System startup
systemctl start llm-quant

# 2. Verify all components
python scripts/pre_market_check.py

# 3. Check overnight news/sentiment
python scripts/check_sentiment.py

# 4. Verify market data feed
curl http://localhost:8080/data/feed-health

# 5. Review risk limits
python scripts/check_risk_limits.py

# 6. Approve trading start
echo "APPROVED" > /tmp/trading_approved
```

**During Market Hours**
```bash
# Every 15 minutes: Quick check
python scripts/health_check.py

# Every hour: Performance review
python scripts/hourly_report.py

# On alert: Investigate and respond
python scripts/investigate_alert.py --alert_id <id>
```

**End of Day (4:30 PM)**
```bash
# 1. Position reconciliation
python scripts/reconcile_positions.py

# 2. Final P&L
python scripts/calculate_daily_pnl.py

# 3. Cost analysis
python scripts/daily_cost_analysis.py

# 4. Risk summary
python scripts/end_of_day_risk.py

# 5. System shutdown
systemctl stop llm-quant
```

### 6.2 Emergency Procedures

**Execution System Down**
```bash
# 1. Immediate action: STOP all trading
kill -TERM $(pidof python)

# 2. Manually cancel all pending orders
python scripts/cancel_all_orders.py --force

# 3. Diagnose issue
python scripts/diagnose_execution.py

# 4. Restart
systemctl restart llm-quant

# 5. Verify before trading resumes
python scripts/post_restart_validation.py
```

**Market Data Corruption**
```bash
# 1. Alert: Pause trading
python scripts/pause_trading.py --reason "DATA_CORRUPTION"

# 2. Diagnostics
python scripts/check_data_integrity.py

# 3. Recover from backup
python scripts/restore_data.py --backup latest

# 4. Resume after verification
python scripts/resume_trading.py
```

**Circuit Breaker Triggered**
```bash
# 1. Immediate: Check P&L
python scripts/check_pnl.py

# 2. Assess situation
- Is this a real market crisis?
- Are signals still valid?
- What is the correlation?

# 3. Decision:
# Option A: Wait for recovery
# Option B: Manually override (rare)
# Option C: Liquidate positions

python scripts/crisis_decision.py
```

---

## 7. Troubleshooting

### Issue: Low Sharpe Ratio (<2.0)

**Diagnosis**:
```bash
python scripts/diagnose_performance.py

# Check:
# 1. Is model performing well?
# 2. Are correlations elevated?
# 3. Is execution cost too high?
# 4. Are strategies complementary?
```

**Solutions**:
```bash
# 1. Recalibrate weights
python scripts/optimize_weights.py

# 2. Check for market regime change
python scripts/detect_regime.py

# 3. Validate data quality
python scripts/validate_data.py

# 4. Retrain ML models
python scripts/retrain_models.py --force
```

### Issue: High Latency (P99 > 200ms)

**Diagnosis**:
```bash
python scripts/profile_latency.py --duration 3600

# Check:
# 1. Which operation is slow?
# 2. Is it network or CPU-bound?
# 3. Are we hitting resource limits?
```

**Solutions**:
```bash
# 1. Increase compute
- Add CPU cores
- Increase RAM

# 2. Optimize code
python scripts/optimize_bottleneck.py

# 3. Cache more aggressively
redis-cli CONFIG SET maxmemory 8gb

# 4. Separate components
- Run on dedicated machines
```

### Issue: Circuit Breaker Frequently Triggered

**Diagnosis**:
```bash
python scripts/analyze_circuit_breakers.py

# Check trigger frequency by type
# Check if legitimate or false positives
```

**Solutions**:
```bash
# 1. Adjust circuit breaker levels
# Edit config/risk_params.yaml

# 2. Reduce leverage
risk.trading.max_leverage: 1.5  # from 2.0

# 3. Increase diversification
# Add new strategies

# 4. Retune correlation alerts
# Raise from 0.85 to 0.90
```

---

## 8. Rollback Procedures

### 8.1 Version Rollback

```bash
# 1. Stop current version
systemctl stop llm-quant

# 2. Check git status
git status
git log --oneline -10

# 3. Rollback to previous version
git revert <commit_id>
# OR
git checkout main~1  # Go back one commit

# 4. Restart with previous version
systemctl start llm-quant

# 5. Verify
python scripts/verify_rollback.py
```

### 8.2 Data Rollback

```bash
# 1. Identify corrupted data
python scripts/check_data_integrity.py

# 2. Restore from backup
python scripts/restore_data.py --backup <date>

# 3. Validate restored data
python scripts/validate_data.py

# 4. Recalculate metrics
python scripts/recalculate_metrics.py --from-date <date>
```

### 8.3 Configuration Rollback

```bash
# 1. View configuration history
git log --oneline config/

# 2. Restore previous config
git checkout <commit> -- config/production.yaml

# 3. Reload configuration
systemctl reload llm-quant

# 4. Verify behavior
python scripts/validate_config.py
```

---

## Checklist: Production Deployment

- [ ] All tests passing
- [ ] Configuration validated
- [ ] Data feed verified
- [ ] Broker connectivity confirmed
- [ ] Credentials configured
- [ ] Risk limits set
- [ ] Monitoring alerts configured
- [ ] Backup procedures in place
- [ ] Runbook reviewed by operations team
- [ ] Disaster recovery plan documented
- [ ] Insurance/risk mitigation in place
- [ ] Initial deployment on paper trading
- [ ] Canary deployment (small capital)
- [ ] Gradual ramp to full allocation
- [ ] Continuous monitoring active
- [ ] Post-deployment review scheduled

---

**END OF DEPLOYMENT GUIDE**
