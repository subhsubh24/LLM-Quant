# Live Trading Setup Guide

## Overview
This guide provides step-by-step instructions for setting up live trading with the LLM-Quant system using Binance API.

## Prerequisites
- Python 3.9+
- Binance account (https://www.binance.com or https://www.binance.us for US residents)
- API keys from Binance
- Initial trading capital ($100-$10,000 recommended for starting)

---

## Step 1: Generate Binance API Keys

### For Binance Global (https://www.binance.com)
1. Log in to your Binance account
2. Go to Account → API Management
3. Create a New Key
4. Set a label (e.g., "LLM-Quant Trading")
5. **Enable these permissions:**
   - ✅ Enable Reading
   - ✅ Enable Spot & Margin Trading
   - ❌ Enable Futures (optional, for advanced users)
6. Set IP whitelist (recommended: your server IP)
7. Click "Create" and save your API Key and Secret Key

### For Binance.US (https://www.binance.us)
1. Log in to your Binance.US account
2. Go to Settings → API Keys
3. Create a New Key
4. Set a label (e.g., "LLM-Quant Trading")
5. **Enable these permissions:**
   - ✅ Enable Reading
   - ✅ Enable Spot Trading
6. Set IP whitelist (recommended: your server IP)
7. Click "Create" and save your API Key and Secret Key

---

## Step 2: Store API Keys Securely

### Option A: Environment Variables (Recommended for servers)
```bash
export BINANCE_API_KEY="your_api_key_here"
export BINANCE_API_SECRET="your_secret_key_here"
export BINANCE_US_MODE="true"  # Set to true for Binance.US, false for Binance Global
```

### Option B: Configuration File
Create `~/.llm_quant_config.json`:
```json
{
  "binance": {
    "api_key": "your_api_key_here",
    "api_secret": "your_secret_key_here",
    "us_mode": true,
    "testnet": false
  }
}
```

### Option C: Using Python (for development)
```python
from backend.app.trading.live_brokers import BinanceBroker

# Initialize broker
broker = BinanceBroker(
    api_key="your_api_key",
    api_secret="your_secret_key",
    testnet=False,  # Set to True for paper trading first!
    us_mode=True    # True for Binance.US, False for Binance Global
)
```

---

## Step 3: Start with Testnet (Paper Trading)

### CRITICAL: Always test in testnet first!
Before trading with real money, validate your setup in the Binance testnet:

```python
from backend.app.trading.live_brokers import BinanceBroker

# Use testnet for paper trading
broker = BinanceBroker(
    api_key="your_testnet_api_key",
    api_secret="your_testnet_api_secret",
    testnet=True,  # Paper trading mode
    us_mode=False  # Testnet doesn't have .US endpoint
)

# Test connection
connected = asyncio.run(broker.connect())
if connected:
    print("✅ Successfully connected to Binance Testnet!")
else:
    print("❌ Failed to connect")
```

### Testnet API Keys
Get testnet credentials from: https://testnet.binance.vision

---

## Step 4: Run Backtester with Microstructure Features

The system now includes live order book integration. To verify it works:

```bash
cd /home/user/LLM-Quant
python -m backend.app.trading.run_backtest
```

You should see in the logs:
```
📊 PHASE A: Microstructure Order Book Integration initialized
  Order Book Fetcher: Binance US API (depth=20)
  Microstructure Extractors: 30 symbols
  Fetch Interval: 300s to avoid rate limiting
```

---

## Step 5: Start Live Trading

### Option A: Using the Master Bot
```python
from backend.app.trading.master_bot import MasterBot
from backend.app.trading.live_brokers import BrokerType, TradingMode

bot = MasterBot(
    broker_type=BrokerType.BINANCE,
    trading_mode=TradingMode.LIVE,  # or TradingMode.PAPER
    initial_capital=1000.0,  # Start with $1,000
)

bot.start()
```

### Option B: Using Auto Trader
```python
from backend.app.trading.auto_trader import AutoTrader
from backend.app.config import TradingMode

trader = AutoTrader(
    mode=TradingMode.LIVE,
    broker="binance_us",
    initial_capital=1000.0,
)

trader.run()
```

---

## Step 6: Monitor Trading Activity

### Real-time Dashboard
```bash
# View live trading logs
tail -f logs/trading.log
```

### Performance Metrics
The system logs:
- All trades (entry time, price, size, exit time, P&L)
- Win rate and profit factor
- Daily/weekly/monthly returns
- Maximum drawdown
- Model accuracy
- Signal statistics

---

## Best Practices

### Risk Management
1. **Start small**: Begin with $100-$500 to validate strategy
2. **Position sizing**: System uses 1-3% per trade (Kelly Criterion)
3. **Daily loss limit**: Stop trading if daily loss > $50
4. **Diversification**: Trade 5-10+ different crypto assets

### Capital Requirements
- **Minimum**: $100 (but very risky)
- **Recommended**: $1,000-$5,000 (safe starting point)
- **Optimal**: $10,000+ (better risk/reward)

### API Security
1. **Never hardcode keys** in source code
2. **Use environment variables** or secure config files
3. **Whitelist IP addresses** on Binance API
4. **Enable 2FA** on Binance account
5. **Monitor API key usage** regularly
6. **Rotate keys** monthly

### Trading Hours
- Binance operates 24/7
- Best trading times: 14:00-22:00 UTC (highest volume)
- Avoid low-liquidity periods (01:00-07:00 UTC)

---

## Troubleshooting

### Connection Failed
```
❌ Failed to connect to Binance
```
**Solutions:**
- Verify API keys are correct
- Check IP is whitelisted on Binance
- Verify internet connection
- Check Binance API status (status.binance.com)

### Order Rejected
```
❌ Order rejected: Insufficient balance
```
**Solutions:**
- Verify you have sufficient USDT
- Check position sizing is not too large
- Verify trading pair is available on Binance

### Order Book Data Not Fetching
```
⚠️ Order book fetch failed for BTC, using cached data
```
**Solutions:**
- This is normal and expected (data cached)
- If persistent, check API rate limits
- Verify internet connectivity
- Check Binance API status

### High Latency
```
⚠️ Order execution took 1.5s (expected <500ms)
```
**Solutions:**
- Use faster internet connection
- Trade fewer symbols to reduce CPU load
- Use server closer to Binance servers (AWS/GCP in Singapore)

---

## Live Monitoring Checklist

- [ ] API connection successful
- [ ] Testnet trades executing correctly
- [ ] Order book data fetching (check logs)
- [ ] Microstructure features active
- [ ] Position sizing correct (1-3% per trade)
- [ ] P&L tracking accurate
- [ ] Win rate > 45%
- [ ] Daily loss < $50
- [ ] Capital growing (not depleting)

---

## Advanced Configuration

### Custom Symbol List
Edit trading configuration:
```python
SYMBOLS = [
    "BTC",    # Bitcoin
    "ETH",    # Ethereum
    "SOL",    # Solana
    "AVAX",   # Avalanche
    # Add more symbols...
]
```

### Adjust Position Sizing
```python
config = {
    "kelly_fraction": 0.02,  # 2% per trade (default)
    "max_kelly_position": 0.10,  # Cap at 10% portfolio
    "recovery_scale": 1.0,  # Reduce size during drawdown
}
```

### Enable More Features
```python
config = {
    "continuous_learning": True,  # Retrain models during trading
    "microstructure_filter": True,  # Use order book analysis
    "portfolio_vol_targeting": True,  # Dynamic leverage
    "correlation_hedging": True,  # Avoid correlated bets
}
```

---

## Support & Documentation

- **Binance API Docs**: https://binance-docs.github.io/apidocs/
- **Binance.US Docs**: https://docs.binance.us/
- **System Architecture**: See SYSTEM_ARCHITECTURE.md
- **Model Details**: See ML_MODELS.md

---

## Safety Disclaimers

⚠️ **WARNING**: Live trading involves real financial risk.
- Past performance does not guarantee future results
- Start with paper trading (testnet) first
- Risk only capital you can afford to lose
- Monitor positions actively
- Have stop-loss orders in place
- Understand the risks before trading

---

## Changelog

### v2.0 (Second Pass - 2025)
- ✅ Live order book integration from Binance API
- ✅ Microstructure feature extraction (bid-ask, imbalance, flow)
- ✅ Microstructure-based signal filtering
- ✅ Support for Binance.US API
- ✅ Testnet/paper trading mode

### v1.0 (Initial Release)
- Multi-model ensemble (LightGBM, XGBoost, LSTM, Transformer)
- Multi-horizon training (24h-1600h predictions)
- Portfolio risk management
- Continuous learning

---

Last updated: 2025-02-14
