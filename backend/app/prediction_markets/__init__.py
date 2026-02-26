"""
Prediction Markets Module.

Integrates with Polymarket and Kalshi (extensible to Manifold, etc.)
for automated scanning and trading of prediction market outcomes.

Exchanges:
- Polymarket: Crypto-based (Polygon), largest volume, no auth for scanning
- Kalshi: CFTC-regulated US exchange, no auth for market data

Strategies:
- Weather arbitrage (NOAA vs market prices)
- Near-certainty harvesting (buy 95c+ outcomes at scale)
- Cross-market arbitrage (logical inconsistencies)
- Same-market arbitrage (YES + NO < $1.00)
- Market making (two-sided liquidity, capture spread)
- Flash crash detection (crypto short-duration markets)
- Whale copy trading (follow profitable wallets)
"""
