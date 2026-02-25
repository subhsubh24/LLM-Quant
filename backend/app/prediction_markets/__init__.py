"""
Prediction Markets Module.

Integrates with Polymarket (and extensible to Kalshi, Manifold, etc.)
for automated trading of prediction market outcomes.

Strategies:
- Weather arbitrage (NOAA vs market prices)
- Near-certainty harvesting (buy 95c+ outcomes at scale)
- Cross-market arbitrage (logical inconsistencies)
- Same-market arbitrage (YES + NO < $1.00)
"""
