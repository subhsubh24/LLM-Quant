# Prediction Market Bot Ecosystem Research (Feb 2026)

## Viable Strategies (Ranked by Current Profitability)

### 1. Market Making + Liquidity Rewards (DOMINANT)
- Post two-sided quotes, earn spread + Polymarket USDC rebates
- Q-score formula: `((max_spread - order_spread) / max_spread)^2 * order_size`
- Two-sided liquidity scores ~3x single-sided
- Conservative returns: 0.5-2% monthly, <1% drawdown
- **Requirement**: Cancel/replace loop must stay within 100ms
- Key repos: `warproxxx/poly-maker` (610 stars), `terrytrl100/polymarket-automated-mm`

### 2. Weather Market Information Edge
- Compare NOAA 1-3 day forecasts to market prices
- NOAA short-range accuracy >90%; casual bettors are often 30-50% off
- Documented profits: "meropi" ~$30K, "1pixel" $18.5K from $2.3K deposits
- Start with $1-$2 micro bets, focus NYC/London markets
- **Our implementation**: `WeatherArbitrageStrategy` + `NOAAWeatherClient`

### 3. Near-Certainty Harvesting ("Bond Strategy")
- Buy 95-99c outcomes on near-certain events, collect $1.00 at resolution
- 90% of large orders (>$10K) occur at prices >$0.95
- Risk: ~1-2% reversal rate destroys many wins (asymmetric downside)
- **Our implementation**: `NearCertaintyStrategy`

### 4. AI/LLM Ensemble Trading
- Multi-model approach (Grok, Claude, GPT-4o, Gemini, DeepSeek)
- Each model assigned distinct analytical role + weighted vote
- Divergence threshold: reduce position or skip when models disagree
- Key repos: `ryanfrigo/kalshi-ai-trading-bot`, `Polymarket/agents`
- **Our edge**: Claude integration already built in LLM module

### 5. Gabagool's Pair Trading (Sum-to-One Temporal)
- Buy YES and NO at different timestamps when combined cost < $0.99
- Never directional — guaranteed profit when both legs fill
- Needs sub-second execution, Rust+Python stack
- Earning $5K-$10K/day on 15-min BTC markets

### 6. Cross-Exchange Arbitrage (Polymarket vs Kalshi)
- Buy cheap YES on one exchange, sell expensive on the other
- Polymarket leads price discovery; Kalshi often lags minutes
- Risk: Resolution divergence (UMA vs CFTC oracle)
- Min spread needed: ~6% (4% Poly fees + 2% Kalshi fees)
- Key repos: `speedyhughes/kalshi-poly-arb` (Rust), `taetaehoho/poly-kalshi-arb`
- **Our implementation**: `CrossExchangeArbitrageStrategy`

## Dead Strategies (as of Feb 2026)

### Temporal/Latency Arbitrage — DEAD
- 0x8dxd turned $313→$438K in one month (98% win rate)
- Monitored BTC spot on Binance, bet on Polymarket before repricing
- **Killed Feb 18, 2026**: Polymarket removed 500ms taker delay + added dynamic fees

### Simple Sum-to-One Arbitrage — DEAD for Retail
- Average opportunity window: 2.7 seconds (down from 12.3s in 2024)
- 73% of profits captured by sub-100ms bots with dedicated Polygon RPC nodes
- $40M in arb profits documented Apr 2024 – Apr 2025

## Technical Stack Reference

### Polymarket
- Python: `py-clob-client` (pin `web3==6.14.0`)
- Chain: Polygon (chain ID 137), gas ~$0.007/tx
- Rate limits: 60 orders/min, batch up to 15 orders/call
- Fees: 2% taker (dynamic on crypto), makers earn rebates
- Auth: EIP712 signatures (3 types: EOA, Magic, browser proxy)

### Kalshi
- Python: `kalshi-python` (v2.1.4+, Python >=3.9)
- Auth: RSA key pairs from Settings > API
- Fees: Currently 0%
- Demo environment available for safe testing
- API: 50-200ms latency REST + WebSocket

## Key Numbers
- Only 7.6% of Polymarket wallets are profitable
- Only 0.51% earn >$1K
- $44B+ prediction market volume in 2025
- Top trader (Theo4/Fredi9999): ~$85M profit across 11 accounts
- Polymarket valued at $8B (ICE $2B investment)

## Architecture Patterns
- WebSocket mandatory (REST polling too slow in 2026)
- Cancel/replace loop target: <100ms for market making
- Risk controls: max 5-10% portfolio per market, daily loss caps, kill switch
- Telegram/Discord alerts for disconnections
- Separate IP for data collection vs trading (avoid rate limiting)

## Open-Source Repos to Watch
- `warproxxx/poly-maker` — Market making via Google Sheets config (610 stars)
- `Polymarket/agents` — Official LangChain + Chroma AI trading agent
- `ryanfrigo/kalshi-ai-trading-bot` — 5-model ensemble
- `speedyhughes/kalshi-poly-arb` — Rust cross-platform arbitrage
- `aarora4/Awesome-Prediction-Market-Tools` — Curated resource list
