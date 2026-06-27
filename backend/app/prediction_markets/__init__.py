"""
Prediction Markets Module.

Integrates with Polymarket for automated scanning and trading
of prediction market outcomes.

Exchange:
- Polymarket: Crypto-based (Polygon), largest volume, no auth for scanning

Strategies:
- Weather arbitrage (NOAA vs market prices)
- Near-certainty harvesting (buy 95c+ outcomes at scale)
- Cross-market arbitrage (logical inconsistencies)
- Same-market arbitrage (YES + NO < $1.00)
- Market making (two-sided liquidity, capture spread)
- Flash crash detection (crypto short-duration markets)
- Whale copy trading (follow profitable wallets)

Execution:
- Order execution layer (Polymarket CLOB)
- Unified executor with risk checks and dry-run mode

Persistence:
- PredictionPortfolio, PredictionPosition, PredictionOrder (SQLModel)
- PnL snapshots for equity curve tracking
- PredictionPriceHistory for WebSocket price sampling

Real-time:
- WebSocket feeds for Polymarket
- Periodic price sampling to DB
"""
