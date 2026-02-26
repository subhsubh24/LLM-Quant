"""
Prediction Market Trading Strategies.

Each strategy scans markets and returns ScanResult objects when it finds
opportunities. The scanner runs these periodically (configurable interval).

Strategies:
1. WeatherArbitrage: Compare NOAA forecasts to weather market prices
2. NearCertaintyHarvester: Buy 95c+ outcomes for penny profits at scale
3. SameMarketArbitrage: Exploit YES + NO < $1.00 within a single market
4. CrossMarketArbitrage: Find logical inconsistencies across related markets
5. MarketMaking: Provide liquidity on both sides, capture spread + rebates
6. FlashCrashDetector: Buy crashed tokens on BTC/crypto short-duration markets
7. WhaleCopyTrading: Follow the top 7.6% of profitable wallets
8. CrossExchangeArbitrage: Polymarket vs Kalshi price discrepancies
"""

import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from .polymarket_client import Market, OrderBook, PolymarketClient, ScanResult

logger = logging.getLogger(__name__)


@dataclass
class StrategyConfig:
    """Configuration for a prediction market strategy."""
    enabled: bool = True
    max_position_usd: float = 5.0       # Max per-position size in USD
    max_positions: int = 20              # Max concurrent positions
    min_edge: float = 0.05              # Minimum expected edge (5%)
    min_liquidity: float = 1000.0       # Minimum market liquidity
    scan_interval_sec: int = 120         # Scan every 2 minutes
    dry_run: bool = True                 # Paper trade by default


class BaseStrategy(ABC):
    """Base class for prediction market strategies."""

    def __init__(self, client: PolymarketClient, config: StrategyConfig):
        self.client = client
        self.config = config
        self.positions: Dict[str, dict] = {}  # token_id -> position info
        self.total_pnl: float = 0.0
        self.trades_executed: int = 0

    @property
    @abstractmethod
    def name(self) -> str:
        """Strategy identifier."""
        ...

    @abstractmethod
    def scan(self, markets: List[Market]) -> List[ScanResult]:
        """Scan markets for opportunities. Returns list of actionable signals."""
        ...

    def can_open_position(self) -> bool:
        """Check if we can open another position."""
        return len(self.positions) < self.config.max_positions


# ================================================================
# Strategy 1: Weather Arbitrage
# ================================================================

@dataclass
class WeatherForecast:
    """NOAA weather forecast for a specific location and date."""
    location: str
    date: datetime
    temp_high_f: float
    temp_low_f: float
    temp_mean_f: float
    precipitation_pct: float
    wind_mph: float
    confidence: float  # Forecast confidence (0-1)


class WeatherArbitrageStrategy(BaseStrategy):
    """
    Compare NOAA weather forecasts to Polymarket weather market prices.

    NOAA short-range forecasts (1-3 days) are >90% accurate for temperature.
    Weather markets on Polymarket are often mispriced by retail traders who
    don't check official forecasts.

    Logic:
    1. Fetch NOAA forecast for target location/date
    2. Find matching Polymarket weather markets
    3. If the correct temperature bucket is priced < entry_threshold, BUY
    4. Exit when price rises above exit_threshold or market resolves

    Config:
        entry_threshold: Max price to buy (default $0.15 = 15c)
        exit_threshold: Min price to sell (default $0.45 = 45c)
        locations: List of cities to track
    """

    def __init__(
        self,
        client: PolymarketClient,
        config: StrategyConfig,
        entry_threshold: float = 0.15,
        exit_threshold: float = 0.45,
        locations: Optional[List[str]] = None,
    ):
        super().__init__(client, config)
        self.entry_threshold = entry_threshold
        self.exit_threshold = exit_threshold
        self.locations = locations or ["NYC", "Chicago", "Seattle", "Atlanta", "Dallas"]
        self._forecasts: Dict[str, WeatherForecast] = {}  # location -> latest forecast

    @property
    def name(self) -> str:
        return "weather_arb"

    def update_forecasts(self, forecasts: Dict[str, WeatherForecast]):
        """Update cached forecasts from NOAA data source."""
        self._forecasts = forecasts
        logger.info(f"[WEATHER] Updated forecasts for {len(forecasts)} locations")

    def scan(self, markets: List[Market]) -> List[ScanResult]:
        """
        Scan weather markets for mispriced temperature buckets.

        Looks for markets where:
        - The NOAA forecast predicts a specific temperature range
        - That range's outcome is priced below entry_threshold
        - The forecast confidence is high enough
        """
        results = []
        if not self._forecasts:
            return results

        # Filter to weather-related markets
        weather_markets = [
            m for m in markets
            if m.active and not m.closed
            and any(kw in m.question.lower()
                    for kw in ["temperature", "weather", "degrees", "°f", "°c"])
        ]

        for market in weather_markets:
            for location, forecast in self._forecasts.items():
                if location.lower() not in market.question.lower():
                    continue

                # Find the outcome that matches the forecast
                for i, outcome in enumerate(market.outcomes):
                    temp_range = self._parse_temp_range(outcome.label)
                    if temp_range is None:
                        continue

                    low, high = temp_range
                    # Check if NOAA forecast falls in this range
                    if low <= forecast.temp_mean_f <= high:
                        # This is the correct bucket per NOAA
                        if outcome.price < self.entry_threshold:
                            edge = (1.0 - outcome.price) * forecast.confidence - outcome.price
                            if edge > self.config.min_edge:
                                results.append(ScanResult(
                                    market=market,
                                    strategy=self.name,
                                    outcome_idx=i,
                                    side="BUY",
                                    entry_price=outcome.price,
                                    expected_value=1.0 * forecast.confidence,
                                    edge=edge,
                                    confidence=forecast.confidence,
                                    reason=(
                                        f"NOAA forecasts {forecast.temp_mean_f:.0f}°F for {location}, "
                                        f"bucket [{low}-{high}°F] priced at only ${outcome.price:.2f} "
                                        f"(forecast confidence: {forecast.confidence:.0%})"
                                    ),
                                ))
        return results

    def _parse_temp_range(self, label: str) -> Optional[tuple]:
        """Parse temperature range from outcome label like '40-45°F'."""
        import re
        match = re.search(r'(\d+)\s*[-–]\s*(\d+)', label)
        if match:
            return (float(match.group(1)), float(match.group(2)))
        # Single temp: "Above 50°F"
        match = re.search(r'[Aa]bove\s+(\d+)', label)
        if match:
            return (float(match.group(1)), 200.0)
        match = re.search(r'[Bb]elow\s+(\d+)', label)
        if match:
            return (-50.0, float(match.group(1)))
        return None


# ================================================================
# Strategy 2: Near-Certainty Harvester
# ================================================================

class NearCertaintyStrategy(BaseStrategy):
    """
    Buy outcomes priced at 95-99c for near-certain events.

    The "endgame sweep" strategy: when an event has effectively already
    occurred but hasn't formally resolved, the winning outcome trades at
    95-99c. Buy it, wait for resolution, collect $1.00.

    Profit per trade: $0.01-0.05 (1-5%)
    Volume needed: Thousands of trades
    Risk: Rare reversal (~1% of cases) loses 95c+ per share

    Safeguards:
    - Only trade markets ending within 72h (imminent resolution)
    - Require minimum volume (active markets less likely to reverse)
    - Cap position size (limit downside on any single reversal)
    - Diversify across many markets (law of large numbers)
    """

    def __init__(
        self,
        client: PolymarketClient,
        config: StrategyConfig,
        min_price: float = 0.95,
        max_price: float = 0.99,
        min_volume: float = 50000,
        max_hours_to_resolution: int = 72,
    ):
        super().__init__(client, config)
        self.min_price = min_price
        self.max_price = max_price
        self.min_volume = min_volume
        self.max_hours_to_resolution = max_hours_to_resolution

    @property
    def name(self) -> str:
        return "near_certainty"

    def scan(self, markets: List[Market]) -> List[ScanResult]:
        """
        Find near-certain outcomes trading below $1.00.

        Looks for:
        - Active, non-closed binary markets
        - At least one outcome priced 95-99c
        - Market ends within 72 hours
        - Sufficient volume (liquid = less likely to reverse)
        """
        results = []
        now = datetime.now(timezone.utc)

        for market in markets:
            if not market.active or market.closed:
                continue
            if not market.is_binary:
                continue
            if market.total_volume < self.min_volume:
                continue

            # Check time to resolution
            if market.end_date:
                hours_left = (market.end_date - now).total_seconds() / 3600
                if hours_left > self.max_hours_to_resolution or hours_left < 0:
                    continue
            else:
                continue  # Skip markets without end dates

            for i, outcome in enumerate(market.outcomes):
                if self.min_price <= outcome.price <= self.max_price:
                    profit_per_share = 1.0 - outcome.price
                    # Assume ~2% chance of reversal (conservative)
                    reversal_risk = 0.02
                    expected_value = (1.0 - reversal_risk) * profit_per_share - reversal_risk * outcome.price
                    edge = expected_value / outcome.price

                    if edge > 0 and self.can_open_position():
                        results.append(ScanResult(
                            market=market,
                            strategy=self.name,
                            outcome_idx=i,
                            side="BUY",
                            entry_price=outcome.price,
                            expected_value=1.0 - reversal_risk,
                            edge=edge,
                            confidence=1.0 - reversal_risk,
                            reason=(
                                f"Near-certain: \"{outcome.label}\" at ${outcome.price:.3f} "
                                f"({profit_per_share*100:.1f}c profit/share, "
                                f"vol=${market.total_volume:,.0f}, "
                                f"{hours_left:.0f}h to resolution)"
                            ),
                        ))
        return results


# ================================================================
# Strategy 3: Same-Market Arbitrage
# ================================================================

class SameMarketArbitrageStrategy(BaseStrategy):
    """
    Exploit YES + NO < $1.00 within a single binary market.

    In a correctly priced binary market, YES + NO should equal $1.00 (minus fees).
    When the sum drops below $0.98, buying both guarantees a profit.

    Warning: These windows typically last milliseconds. This strategy is more
    useful for monitoring market efficiency than for execution.

    With Polymarket's ~2% winner fee, the sum must be < $0.98 to profit.
    """

    def __init__(
        self,
        client: PolymarketClient,
        config: StrategyConfig,
        min_discount: float = 0.025,  # Sum must be < $0.975 (2.5% discount)
    ):
        super().__init__(client, config)
        self.min_discount = min_discount

    @property
    def name(self) -> str:
        return "same_market_arb"

    def scan(self, markets: List[Market]) -> List[ScanResult]:
        """Find binary markets where YES + NO < $1.00 - fees."""
        results = []

        for market in markets:
            if not market.active or market.closed:
                continue
            if not market.is_binary:
                continue
            if market.liquidity < self.config.min_liquidity:
                continue

            price_sum = sum(o.price for o in market.outcomes)
            discount = 1.0 - price_sum

            if discount >= self.min_discount:
                edge = discount - 0.02  # Subtract ~2% winner fee
                if edge > 0:
                    results.append(ScanResult(
                        market=market,
                        strategy=self.name,
                        outcome_idx=-1,  # Buy ALL outcomes
                        side="BUY",
                        entry_price=price_sum,
                        expected_value=1.0,
                        edge=edge,
                        confidence=0.99,  # Near-certain (market structure)
                        reason=(
                            f"Arb: YES({market.outcomes[0].price:.3f}) + "
                            f"NO({market.outcomes[1].price:.3f}) = "
                            f"${price_sum:.3f} (discount={discount*100:.1f}%, "
                            f"edge after fees={edge*100:.1f}%)"
                        ),
                    ))

        # Also check multi-outcome markets
        for market in markets:
            if not market.active or market.closed:
                continue
            if not market.is_multi:
                continue
            if market.liquidity < self.config.min_liquidity:
                continue

            price_sum = sum(o.price for o in market.outcomes)
            discount = 1.0 - price_sum

            if discount >= self.min_discount:
                edge = discount - 0.02
                if edge > 0:
                    prices_str = " + ".join(f"{o.label}({o.price:.2f})" for o in market.outcomes[:5])
                    results.append(ScanResult(
                        market=market,
                        strategy=self.name,
                        outcome_idx=-1,
                        side="BUY",
                        entry_price=price_sum,
                        expected_value=1.0,
                        edge=edge,
                        confidence=0.99,
                        reason=(
                            f"Multi-outcome arb: {prices_str} = "
                            f"${price_sum:.3f} (edge={edge*100:.1f}%)"
                        ),
                    ))
        return results


# ================================================================
# Strategy 4: Cross-Market Arbitrage
# ================================================================

@dataclass
class ImplicationRule:
    """A logical implication: if market A resolves YES, then market B must resolve YES."""
    parent_keyword: str      # Keyword to match the broader market (e.g., "win election")
    child_keyword: str       # Keyword to match the narrower market (e.g., "win pennsylvania")
    direction: str           # "implies" (P(parent) <= P(child)) or "excludes"
    category: str = ""       # Restrict to a category

# Built-in implication rules for common prediction market patterns.
# Rule: If parent resolves YES, child must also resolve YES ⟹ P(parent) ≤ P(child).
# When the market violates this, buy the cheaper side.
_IMPLICATION_RULES: List[ImplicationRule] = [
    # Politics: winning the election implies winning swing states
    ImplicationRule("win election", "win pennsylvania", "implies", "Politics"),
    ImplicationRule("win election", "win michigan", "implies", "Politics"),
    ImplicationRule("win election", "win wisconsin", "implies", "Politics"),
    ImplicationRule("win election", "win georgia", "implies", "Politics"),
    ImplicationRule("win election", "win arizona", "implies", "Politics"),
    ImplicationRule("win election", "win nevada", "implies", "Politics"),
    ImplicationRule("win popular vote", "win election", "implies", "Politics"),
    ImplicationRule("republican sweep", "win election", "implies", "Politics"),
    ImplicationRule("republican sweep", "win senate", "implies", "Politics"),
    ImplicationRule("democratic sweep", "win election", "implies", "Politics"),
    ImplicationRule("democratic sweep", "win senate", "implies", "Politics"),
    # Economics: rate cuts imply lower rates
    ImplicationRule("rate cut", "rates below", "implies", "Economics"),
    ImplicationRule("recession", "gdp negative", "implies", "Economics"),
    ImplicationRule("inflation above 4", "inflation above 3", "implies", "Economics"),
    ImplicationRule("inflation above 5", "inflation above 4", "implies", "Economics"),
    # Crypto: BTC > 150k implies BTC > 100k
    ImplicationRule("btc above 150", "btc above 100", "implies", "Crypto"),
    ImplicationRule("btc above 200", "btc above 150", "implies", "Crypto"),
    ImplicationRule("eth above 10", "eth above 5", "implies", "Crypto"),
    # Sports: winning championship implies winning conference/division
    ImplicationRule("win super bowl", "win conference", "implies", "Sports"),
    ImplicationRule("win world series", "win pennant", "implies", "Sports"),
]


class CrossMarketArbitrageStrategy(BaseStrategy):
    """
    Find logical inconsistencies across related markets.

    Uses two approaches:
    1. Structured implication rules (high confidence) — domain-specific
       relationships like "winning election implies winning swing state"
    2. Keyword overlap heuristic (lower confidence) — for discovering
       new relationships automatically

    When P(A) > P(B) but A implies B (A can't happen without B),
    the cheap side is mispriced.
    """

    def __init__(
        self,
        client: PolymarketClient,
        config: StrategyConfig,
        min_inconsistency: float = 0.10,  # 10% probability gap
        custom_rules: Optional[List[ImplicationRule]] = None,
    ):
        super().__init__(client, config)
        self.min_inconsistency = min_inconsistency
        self._related_markets: Dict[str, List[str]] = {}  # market_id -> [related_ids]
        self.rules = list(_IMPLICATION_RULES) + (custom_rules or [])

    @property
    def name(self) -> str:
        return "cross_market_arb"

    def add_rule(self, rule: ImplicationRule):
        """Add a custom implication rule at runtime."""
        self.rules.append(rule)

    def set_related_markets(self, relations: Dict[str, List[str]]):
        """Define which markets are logically related."""
        self._related_markets = relations

    def _match_rule(self, keyword: str, question: str) -> bool:
        """Check if a market question matches a rule keyword."""
        q = question.lower()
        return keyword.lower() in q

    def scan(self, markets: List[Market]) -> List[ScanResult]:
        """
        Find probability inconsistencies across related markets.

        Phase 1: Check structured implication rules (high confidence).
        Phase 2: Keyword overlap heuristic (lower confidence).
        """
        results = []
        active_markets = [m for m in markets if m.active and not m.closed and m.is_binary]

        # ── Phase 1: Structured implication rules ──
        for rule in self.rules:
            parents = [m for m in active_markets if self._match_rule(rule.parent_keyword, m.question)]
            children = [m for m in active_markets if self._match_rule(rule.child_keyword, m.question)]

            for parent in parents:
                for child in children:
                    if parent.id == child.id:
                        continue
                    # Category filter
                    if rule.category:
                        if parent.category != rule.category and child.category != rule.category:
                            continue

                    p_parent = parent.outcomes[0].price
                    p_child = child.outcomes[0].price

                    if rule.direction == "implies":
                        # P(parent) should be <= P(child). If violated, arb exists.
                        if p_parent > p_child + self.min_inconsistency:
                            gap = p_parent - p_child
                            results.append(ScanResult(
                                market=child,
                                strategy=self.name,
                                outcome_idx=0,
                                side="BUY",
                                entry_price=p_child,
                                expected_value=p_parent,
                                edge=gap,
                                confidence=0.85,
                                reason=(
                                    f"IMPLICATION VIOLATION: \"{parent.question[:50]}\" "
                                    f"({p_parent:.0%}) implies \"{child.question[:50]}\" "
                                    f"({p_child:.0%}) — buy child at {p_child:.0%}, "
                                    f"gap={gap*100:.1f}%"
                                ),
                            ))
                    elif rule.direction == "excludes":
                        # P(A) + P(B) should be <= 1.0
                        total = p_parent + p_child
                        if total > 1.0 + self.min_inconsistency:
                            gap = total - 1.0
                            # Sell the more expensive one
                            sell_market = parent if p_parent > p_child else child
                            sell_price = max(p_parent, p_child)
                            results.append(ScanResult(
                                market=sell_market,
                                strategy=self.name,
                                outcome_idx=0,
                                side="SELL",
                                entry_price=sell_price,
                                expected_value=sell_price - gap,
                                edge=gap,
                                confidence=0.80,
                                reason=(
                                    f"EXCLUSION VIOLATION: \"{parent.question[:50]}\" "
                                    f"({p_parent:.0%}) + \"{child.question[:50]}\" "
                                    f"({p_child:.0%}) = {total:.0%} > 100%"
                                ),
                            ))

        # ── Phase 2: Keyword overlap heuristic ──
        skip = {"will", "the", "a", "an", "in", "on", "at", "to", "of", "by", "be", "is"}
        keyword_groups: Dict[str, List[Market]] = {}
        for market in active_markets:
            words = set(market.question.lower().split())
            for word in words - skip:
                if len(word) > 3:
                    if word not in keyword_groups:
                        keyword_groups[word] = []
                    keyword_groups[word].append(market)

        checked = set()
        for keyword, group in keyword_groups.items():
            if len(group) < 2:
                continue

            for i, m1 in enumerate(group):
                for m2 in group[i + 1:]:
                    pair_key = tuple(sorted([m1.id, m2.id]))
                    if pair_key in checked:
                        continue
                    checked.add(pair_key)

                    if m1.is_binary and m2.is_binary:
                        p1 = m1.outcomes[0].price
                        p2 = m2.outcomes[0].price
                        gap = abs(p1 - p2)

                        if gap >= self.min_inconsistency:
                            shared_words = (
                                set(m1.question.lower().split())
                                & set(m2.question.lower().split())
                                - skip
                            )
                            if len(shared_words) >= 3:
                                results.append(ScanResult(
                                    market=m1 if p1 < p2 else m2,
                                    strategy=self.name,
                                    outcome_idx=0,
                                    side="BUY" if p1 < p2 else "SELL",
                                    entry_price=min(p1, p2),
                                    expected_value=max(p1, p2),
                                    edge=gap,
                                    confidence=0.60,
                                    reason=(
                                        f"Cross-market gap: \"{m1.question[:60]}\" "
                                        f"({p1:.0%}) vs \"{m2.question[:60]}\" "
                                        f"({p2:.0%}) — {gap*100:.1f}% inconsistency"
                                    ),
                                ))
        return results


# ================================================================
# Strategy 5: Market Making (Swisstony: $5 → $3.7M)
# ================================================================

class MarketMakingStrategy(BaseStrategy):
    """
    Provide liquidity on both sides of a market, capturing the bid-ask spread.

    Uses the Avellaneda-Stoikov (2008) framework for optimal quote placement:
    - Reservation price adjusts for inventory risk (logit-space PDE)
    - Optimal spread compensates for adverse selection + inventory risk
    - VPIN toxicity detection widens/withdraws when informed flow detected

    Q-score formula (determines reward share):
        Score = ((max_spread - order_spread) / max_spread)^2 * order_size
        - Two-sided liquidity scores ~3x single-sided

    Risk: Inventory risk — news events can make one side worthless.
    Mitigation: Avoid short-duration/high-volatility markets.
    """

    def __init__(
        self,
        client: PolymarketClient,
        config: StrategyConfig,
        target_spread: float = 0.02,      # 2c spread per side
        max_spread: float = 0.03,          # 3c max from midpoint for Q-score
        min_liquidity: float = 10000,      # Minimum market liquidity
        max_volatility: float = 0.10,      # Skip markets with >10% daily price swings
        rebalance_threshold: float = 0.60, # Rebalance when inventory >60% one-sided
    ):
        super().__init__(client, config)
        self.target_spread = target_spread
        self.max_spread = max_spread
        self.min_liquidity = min_liquidity
        self.max_volatility = max_volatility
        self.rebalance_threshold = rebalance_threshold
        self.inventory: Dict[str, Dict[str, float]] = {}  # market_id -> {yes: qty, no: qty}

        # Avellaneda-Stoikov model + VPIN toxicity tracker
        from .quant_models import AvellanedaStoikovModel, VPINTracker
        self._as_model = AvellanedaStoikovModel()
        self._vpin = VPINTracker()

    @property
    def name(self) -> str:
        return "market_making"

    def record_trade(self, token_id: str, price: float, size: float):
        """Record a trade for A-S volatility estimation and VPIN tracking."""
        self._as_model.record_price(token_id, price)
        self._vpin.record_trade(token_id, price, size)

    def get_optimal_quotes(
        self, token_id: str, mid_price: float, inventory: float,
        time_to_resolution_hours: float,
    ) -> Tuple[float, float, dict]:
        """Get Avellaneda-Stoikov optimal bid/ask for a market."""
        return self._as_model.compute_quotes(
            token_id, mid_price, inventory, time_to_resolution_hours,
        )

    def scan(self, markets: List[Market]) -> List[ScanResult]:
        """
        Find markets suitable for market making.

        Uses Avellaneda-Stoikov for quote placement diagnostics.
        Checks VPIN for each candidate — toxic markets are skipped.
        """
        results = []

        for market in markets:
            if not market.active or market.closed:
                continue
            if not market.is_binary:
                continue
            if market.liquidity < self.min_liquidity:
                continue

            # Skip extreme probability markets (hard to provide two-sided liquidity)
            yes_price = market.outcomes[0].price if market.outcomes else 0.5
            if yes_price < 0.10 or yes_price > 0.90:
                continue

            # Skip crypto short-duration markets (too volatile for MM)
            question_lower = market.question.lower()
            if any(kw in question_lower for kw in ["15 min", "15-min", "1 hour", "1-hour"]):
                continue

            # VPIN toxicity check — skip if informed flow detected
            token_id = market.outcomes[0].token_id if market.outcomes else ""
            if token_id:
                toxic, vpin_val = self._vpin.is_toxic(token_id)
                if toxic:
                    logger.info(
                        f"[MM] Skipping {market.question[:40]} — "
                        f"VPIN={vpin_val:.2f} (toxic flow detected)"
                    )
                    continue

            # Run Avellaneda-Stoikov for diagnostics
            as_info = ""
            if token_id:
                inv = self.inventory.get(market.id, {})
                net_inventory = inv.get("yes", 0) - inv.get("no", 0)
                hours_left = 168.0
                if market.end_date:
                    hours_left = max(1, (market.end_date - datetime.now(timezone.utc)).total_seconds() / 3600)
                bid, ask, diag = self._as_model.compute_quotes(
                    token_id, yes_price, net_inventory, hours_left,
                )
                as_info = (
                    f"A-S: bid={bid:.3f} ask={ask:.3f} "
                    f"resv={diag['reservation_price']:.3f} σ={diag['sigma']:.3f}"
                )

            # Calculate potential spread revenue
            spread = market.spread
            if spread > self.target_spread:
                q_score = ((self.max_spread - self.target_spread) / self.max_spread) ** 2

                reason_parts = [
                    f"MM: {market.question[:50]}",
                    f"spread={spread*100:.1f}c",
                    f"liq=${market.liquidity:,.0f}",
                    f"Q={q_score:.2f}",
                ]
                if as_info:
                    reason_parts.append(as_info)

                results.append(ScanResult(
                    market=market,
                    strategy=self.name,
                    outcome_idx=-1,  # Both sides
                    side="BUY",  # Market making = both sides
                    entry_price=yes_price,
                    expected_value=yes_price + spread / 2,
                    edge=spread,
                    confidence=0.80,
                    reason=" | ".join(reason_parts),
                ))

        return results


# ================================================================
# Strategy 6: Flash Crash Detector (0x8dxd: $313 → $438K)
# ================================================================

class FlashCrashStrategy(BaseStrategy):
    """
    Detect and exploit flash crashes on BTC/crypto short-duration markets.

    When BTC moves sharply, the losing side of 15-minute Up/Down markets
    crashes to near-zero before the market resolves. The bot buys BOTH
    the crashed side AND the opposite side (which hasn't fully repriced yet),
    locking in guaranteed profit when YES + NO < $1.00.

    0x8dxd turned $313 into $438K in one month with 98% win rate.

    Two-leg execution:
    Leg 1: When token crashes >15% in seconds, buy the crashed side immediately
    Leg 2: Buy the opposite side IF combined cost < $0.97 (3% profit after fees)
    If both legs fill: guaranteed profit = $1.00 - total_cost

    Risk: Leg 1 fills but Leg 2 never triggers (directional exposure).
    Mitigation: Only complete Leg 2 if spread is profitable. Abandon if not.

    Best timing: Final 30-40 seconds of each 15-minute round (direction clearest).
    Note: Polymarket added dynamic taker fees (up to ~3.15%) on these markets
    in January 2026, reducing but not eliminating profitability.
    """

    def __init__(
        self,
        client: PolymarketClient,
        config: StrategyConfig,
        crash_threshold: float = 0.15,        # 15% price drop = flash crash
        max_combined_cost: float = 0.97,       # Both legs must cost < $0.97
        min_volume: float = 5000,              # Skip illiquid markets
    ):
        super().__init__(client, config)
        self.crash_threshold = crash_threshold
        self.max_combined_cost = max_combined_cost
        self.min_volume = min_volume
        self._price_history: Dict[str, List[float]] = {}  # token_id -> recent prices

    @property
    def name(self) -> str:
        return "flash_crash"

    def update_prices(self, token_id: str, price: float):
        """Record a price tick for crash detection."""
        if token_id not in self._price_history:
            self._price_history[token_id] = []
        self._price_history[token_id].append(price)
        # Keep last 60 ticks (5 minutes at 5-second intervals)
        if len(self._price_history[token_id]) > 60:
            self._price_history[token_id] = self._price_history[token_id][-60:]

    def _detect_crash(self, token_id: str) -> Optional[float]:
        """Check if token has crashed. Returns drop magnitude or None."""
        history = self._price_history.get(token_id, [])
        if len(history) < 3:
            return None
        recent_high = max(history[-10:]) if len(history) >= 10 else max(history)
        current = history[-1]
        if recent_high > 0:
            drop = (recent_high - current) / recent_high
            if drop >= self.crash_threshold:
                return drop
        return None

    def scan(self, markets: List[Market]) -> List[ScanResult]:
        """
        Find flash crash opportunities on crypto short-duration markets.

        Scans BTC/ETH/SOL 15-minute and 1-hour Up/Down markets for
        tokens that have crashed significantly. If buying both sides
        costs less than $0.97, it's a guaranteed profit opportunity.
        """
        results = []

        for market in markets:
            if not market.active or market.closed:
                continue
            if not market.is_binary:
                continue
            if market.total_volume < self.min_volume:
                continue

            # Filter to crypto short-duration markets
            question_lower = market.question.lower()
            is_crypto_short = any(
                kw in question_lower
                for kw in ["btc", "bitcoin", "eth", "ethereum", "sol", "solana"]
            ) and any(
                kw in question_lower
                for kw in ["15 min", "1 hour", "up or down", "above", "below"]
            )
            if not is_crypto_short:
                continue

            # Check for flash crash on either outcome
            for i, outcome in enumerate(market.outcomes):
                crash_magnitude = self._detect_crash(outcome.token_id)
                if crash_magnitude is not None:
                    # Crashed side price
                    crashed_price = outcome.price
                    # Opposite side price
                    other_idx = 1 - i
                    other_price = market.outcomes[other_idx].price if other_idx < len(market.outcomes) else 1.0

                    combined_cost = crashed_price + other_price
                    if combined_cost < self.max_combined_cost:
                        profit = 1.0 - combined_cost
                        # Account for ~2% taker fee on the winning side
                        net_profit = profit - 0.02
                        if net_profit > 0:
                            results.append(ScanResult(
                                market=market,
                                strategy=self.name,
                                outcome_idx=-1,  # Buy BOTH sides
                                side="BUY",
                                entry_price=combined_cost,
                                expected_value=1.0,
                                edge=net_profit,
                                confidence=0.95,  # Near-certain if both legs fill
                                reason=(
                                    f"FLASH CRASH: {outcome.label} crashed "
                                    f"{crash_magnitude*100:.0f}% to ${crashed_price:.3f} | "
                                    f"Both sides: ${combined_cost:.3f} → "
                                    f"${net_profit*100:.1f}% net profit"
                                ),
                            ))

        return results


# ================================================================
# Strategy 7: Whale Copy Trading (top 7.6% of wallets)
# ================================================================

class WhaleCopyTradingStrategy(BaseStrategy):
    """
    Follow trades from the most profitable Polymarket wallets.

    Only 7.6% of Polymarket wallets are profitable. Only 0.51% earn >$1K.
    By identifying and mirroring these "sharp" wallets, we gain an indirect
    information edge. Uses on-chain Polygon data to detect whale trades.

    Known top wallets (as of Feb 2026):
    - Theo4: $22M profit, 88.9% win rate
    - Fredi9999: $16.6M profit
    - Len9311238: $8.7M profit, 100% win rate
    - SeriouslySirius: $3.8M profit on sports

    Advanced "Wallet Basket" approach:
    1. Track 5-10 proven profitable wallets
    2. Wait for 80%+ of the basket to enter same outcome
    3. Ensure purchases in tight price band (not stale signals)
    4. Only act if market spread is still favorable
    5. This "consensus" approach reduces single-whale risk

    Risks:
    - Whales sometimes use decoy trades across multiple wallets
    - By the time you copy, price may have moved (slippage)
    - Top whales actively counter copy-traders
    """

    def __init__(
        self,
        client: PolymarketClient,
        config: StrategyConfig,
        min_trade_size: float = 1000,       # Only copy trades >$1K
        max_entry_odds: float = 0.80,       # Don't copy above 80c (limited upside)
        position_scale: float = 0.01,       # 1% of whale position size
        basket_consensus: float = 0.80,     # 80% of basket must agree
        # Exit parameters
        trailing_stop_pct: float = 0.15,    # Trailing stop at 15% from peak
        time_exit_hours: float = 72.0,      # Force exit after 72 hours
        profit_target_pct: float = 0.30,    # Take profit at 30% gain
        whale_exit_trigger: bool = True,    # Exit if whales start selling
    ):
        super().__init__(client, config)
        self.min_trade_size = min_trade_size
        self.max_entry_odds = max_entry_odds
        self.position_scale = position_scale
        self.basket_consensus = basket_consensus
        self.trailing_stop_pct = trailing_stop_pct
        self.time_exit_hours = time_exit_hours
        self.profit_target_pct = profit_target_pct
        self.whale_exit_trigger = whale_exit_trigger
        self.tracked_wallets: Dict[str, dict] = {}  # address -> {name, pnl, win_rate, trades}
        self._recent_whale_trades: List[dict] = []
        # Exit tracking: token_id -> {peak_price, entry_time, entry_price}
        self._position_tracking: Dict[str, dict] = {}

    @property
    def name(self) -> str:
        return "whale_copy"

    def add_wallet(self, address: str, name: str = "", pnl: float = 0, win_rate: float = 0):
        """Add a wallet to track."""
        self.tracked_wallets[address.lower()] = {
            "name": name or address[:8],
            "pnl": pnl,
            "win_rate": win_rate,
            "trades": [],
        }
        logger.info(f"[WHALE] Tracking {name or address[:8]} (PnL: ${pnl:,.0f}, WR: {win_rate:.0%})")

    def record_trade(self, wallet: str, market_id: str, outcome: str, side: str, price: float, size: float):
        """Record a detected whale trade for analysis."""
        trade = {
            "wallet": wallet.lower(),
            "market_id": market_id,
            "outcome": outcome,
            "side": side,
            "price": price,
            "size": size,
            "timestamp": datetime.now(timezone.utc),
        }
        self._recent_whale_trades.append(trade)
        # Keep last 500 trades
        if len(self._recent_whale_trades) > 500:
            self._recent_whale_trades = self._recent_whale_trades[-500:]

        if wallet.lower() in self.tracked_wallets:
            self.tracked_wallets[wallet.lower()]["trades"].append(trade)

    def scan(self, markets: List[Market]) -> List[ScanResult]:
        """
        Scan recent whale trades for copy opportunities.

        Uses the "Wallet Basket" approach: only generates signals when
        multiple tracked whales enter the same market in the same direction
        within a tight time window.
        """
        results = []
        if not self._recent_whale_trades:
            return results

        # Group recent trades by market
        from collections import defaultdict
        market_trades: Dict[str, List[dict]] = defaultdict(list)
        cutoff = datetime.now(timezone.utc)

        for trade in self._recent_whale_trades:
            age = (cutoff - trade["timestamp"]).total_seconds()
            if age < 3600:  # Only trades from last hour
                market_trades[trade["market_id"]].append(trade)

        # Find consensus trades (multiple whales, same direction)
        market_lookup = {m.id: m for m in markets}

        for market_id, trades in market_trades.items():
            if len(trades) < 2:
                continue  # Need at least 2 whales

            # Count direction consensus
            buy_wallets = set()
            sell_wallets = set()
            buy_outcomes = {}
            total_size = 0

            for t in trades:
                if t["side"] == "BUY":
                    buy_wallets.add(t["wallet"])
                    buy_outcomes[t["outcome"]] = buy_outcomes.get(t["outcome"], 0) + 1
                    total_size += t["size"]
                else:
                    sell_wallets.add(t["wallet"])

            n_tracked = len(self.tracked_wallets)
            if n_tracked == 0:
                continue

            buy_consensus = len(buy_wallets) / n_tracked

            if buy_consensus >= self.basket_consensus and buy_outcomes:
                # Strong consensus — whales are buying
                top_outcome = max(buy_outcomes, key=buy_outcomes.get)
                market = market_lookup.get(market_id)
                if not market:
                    continue

                # Find the outcome index
                outcome_idx = next(
                    (i for i, o in enumerate(market.outcomes) if o.label == top_outcome),
                    0
                )
                entry_price = market.outcomes[outcome_idx].price

                if entry_price > self.max_entry_odds:
                    continue  # Too expensive, limited upside

                whale_names = [
                    self.tracked_wallets.get(w, {}).get("name", w[:8])
                    for w in buy_wallets
                ]

                results.append(ScanResult(
                    market=market,
                    strategy=self.name,
                    outcome_idx=outcome_idx,
                    side="BUY",
                    entry_price=entry_price,
                    expected_value=entry_price * 1.15,  # Estimate 15% edge from whale alpha
                    edge=0.15,
                    confidence=min(0.90, buy_consensus),
                    reason=(
                        f"WHALE CONSENSUS: {len(buy_wallets)}/{n_tracked} tracked wallets "
                        f"buying \"{top_outcome}\" at ${entry_price:.2f} | "
                        f"Whales: {', '.join(whale_names[:3])} | "
                        f"Total size: ${total_size:,.0f}"
                    ),
                ))

                # Track position for exit management
                token_id = market.outcomes[outcome_idx].token_id
                if token_id not in self._position_tracking:
                    self._position_tracking[token_id] = {
                        "peak_price": entry_price,
                        "entry_time": datetime.now(timezone.utc),
                        "entry_price": entry_price,
                        "market_id": market_id,
                    }

        return results

    def track_price_update(self, token_id: str, current_price: float):
        """Update peak price for trailing stop calculation."""
        if token_id in self._position_tracking:
            tracking = self._position_tracking[token_id]
            if current_price > tracking["peak_price"]:
                tracking["peak_price"] = current_price

    def check_exits(self, markets: List[Market]) -> List[ScanResult]:
        """
        Check all open whale-copy positions for exit signals.

        Exit triggers (any one fires):
        1. Trailing stop: price drops > trailing_stop_pct from peak
        2. Time exit: position held longer than time_exit_hours
        3. Profit target: unrealized gain exceeds profit_target_pct
        4. Whale exit: tracked whales start selling the same token

        Returns SELL ScanResults for positions that should be closed.
        """
        exits = []
        now = datetime.now(timezone.utc)
        market_lookup = {m.id: m for m in markets}

        for token_id, tracking in list(self._position_tracking.items()):
            entry_price = tracking["entry_price"]
            peak_price = tracking["peak_price"]
            entry_time = tracking["entry_time"]
            market_id = tracking["market_id"]

            market = market_lookup.get(market_id)
            if not market:
                continue

            # Find current price for this token
            current_price = None
            outcome_idx = -1
            for i, o in enumerate(market.outcomes):
                if o.token_id == token_id:
                    current_price = o.price
                    outcome_idx = i
                    break
            if current_price is None:
                continue

            # Update peak
            self.track_price_update(token_id, current_price)
            exit_reason = None

            # 1. Trailing stop
            if peak_price > 0:
                drawdown = (peak_price - current_price) / peak_price
                if drawdown >= self.trailing_stop_pct:
                    exit_reason = (
                        f"TRAILING STOP: {drawdown:.1%} drop from peak "
                        f"${peak_price:.3f} → ${current_price:.3f}"
                    )

            # 2. Time exit
            if not exit_reason:
                hours_held = (now - entry_time).total_seconds() / 3600
                if hours_held >= self.time_exit_hours:
                    exit_reason = (
                        f"TIME EXIT: held {hours_held:.0f}h "
                        f"(limit={self.time_exit_hours:.0f}h)"
                    )

            # 3. Profit target
            if not exit_reason and entry_price > 0:
                gain = (current_price - entry_price) / entry_price
                if gain >= self.profit_target_pct:
                    exit_reason = (
                        f"PROFIT TARGET: +{gain:.1%} gain "
                        f"(${entry_price:.3f} → ${current_price:.3f})"
                    )

            # 4. Whale exit signal
            if not exit_reason and self.whale_exit_trigger:
                sell_count = sum(
                    1 for t in self._recent_whale_trades
                    if t["market_id"] == market_id
                    and t["side"] == "SELL"
                    and t["wallet"] in self.tracked_wallets
                    and (now - t["timestamp"]).total_seconds() < 3600
                )
                if sell_count >= 2:
                    exit_reason = (
                        f"WHALE EXIT: {sell_count} tracked wallets selling"
                    )

            if exit_reason:
                exits.append(ScanResult(
                    market=market,
                    strategy=self.name,
                    outcome_idx=outcome_idx,
                    side="SELL",
                    entry_price=current_price,
                    expected_value=current_price,
                    edge=0.0,
                    confidence=0.80,
                    reason=f"[EXIT] {exit_reason}",
                ))
                # Remove from tracking
                del self._position_tracking[token_id]

        return exits


# ================================================================
# Strategy 8: Cross-Exchange Arbitrage (Polymarket vs Kalshi)
# ================================================================

@dataclass
class MatchedMarketPair:
    """A pair of markets from different exchanges covering the same event."""
    poly_market: Market
    kalshi_market: Market
    match_score: float       # 0-1 similarity score
    match_method: str        # "ticker_map", "keyword", "category_keyword"
    category: str


# Known mappings between Kalshi event tickers and Polymarket keywords.
# Kalshi uses structured tickers; Polymarket uses free-form text.
_TICKER_KEYWORD_MAP = {
    # Crypto
    "KXBTC": ["bitcoin", "btc"],
    "KXETH": ["ethereum", "eth"],
    "KXSOL": ["solana", "sol"],
    # Economics
    "CPI": ["cpi", "inflation", "consumer price"],
    "NFP": ["nonfarm", "non-farm", "payroll", "jobs report"],
    "GDP": ["gdp", "gross domestic"],
    "FED": ["fed", "federal reserve", "interest rate", "fomc"],
    # Stocks
    "INX": ["s&p 500", "s&p500", "sp500"],
    "SPY": ["s&p 500", "s&p500", "spy"],
    "NASDAQ": ["nasdaq"],
    "SP500": ["s&p 500", "s&p500", "sp500"],
}

# Categories where both exchanges are likely to list the same events
_CROSS_EXCHANGE_CATEGORIES = {"Crypto", "Economics", "Weather", "Stocks", "Politics"}


class CrossExchangeArbitrageStrategy(BaseStrategy):
    """
    Find price discrepancies for the same event across Polymarket and Kalshi.

    When both exchanges list a market on the same underlying event, prices can
    diverge because of different user bases, fee structures, and liquidity.
    If the gap exceeds fees on both sides, it's a risk-free arbitrage.

    Execution (two legs):
    1. BUY the cheaper YES on Exchange A
    2. SELL (or BUY NO on) Exchange B at the higher price
    3. Wait for resolution — one leg pays $1, the other pays $0
    4. Net profit = price gap - fees on both exchanges

    Fee model:
    - Polymarket: ~2% taker fee + 2% winner fee = ~4% round-trip
    - Kalshi: ~1% per side (CFTC-regulated, lower fees) = ~2% round-trip
    - Minimum gross spread needed: ~6% to clear both fee structures

    This strategy is read-only (detection only). Actual cross-exchange order
    placement requires auth on both exchanges.
    """

    def __init__(
        self,
        client: PolymarketClient,
        config: StrategyConfig,
        kalshi_client=None,
        min_spread: float = 0.06,          # 6% minimum gross spread (covers fees)
        match_threshold: float = 0.50,     # Minimum similarity to consider a match
        polymarket_fee: float = 0.04,      # ~2% taker + 2% winner
        kalshi_fee: float = 0.02,          # ~1% each side
    ):
        super().__init__(client, config)
        self.kalshi_client = kalshi_client
        self.min_spread = min_spread
        self.match_threshold = match_threshold
        self.polymarket_fee = polymarket_fee
        self.kalshi_fee = kalshi_fee
        self._match_cache: Dict[str, MatchedMarketPair] = {}

    @property
    def name(self) -> str:
        return "cross_exchange_arb"

    def set_kalshi_client(self, kalshi_client):
        """Set or update the Kalshi client."""
        self.kalshi_client = kalshi_client

    def _normalize_question(self, text: str) -> str:
        """Normalize market question for comparison."""
        text = text.lower().strip()
        # Remove common filler words
        for word in ["will", "the", "a", "an", "be", "is", "to", "of", "in", "on", "at", "by"]:
            text = re.sub(rf'\b{word}\b', '', text)
        # Collapse whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    def _extract_numeric_threshold(self, text: str) -> Optional[Tuple[str, float]]:
        """Extract price/temp threshold from market question.

        Returns (direction, value) like ("above", 100000) or ("below", 45).
        """
        text_lower = text.lower()
        # "above $100,000" or "above 100K" or "> 50°F"
        match = re.search(r'(above|over|higher than|greater than|>)\s*\$?([\d,]+\.?\d*)\s*([kmb])?', text_lower)
        if match:
            val = float(match.group(2).replace(',', ''))
            suffix = match.group(3)
            if suffix == 'k':
                val *= 1000
            elif suffix == 'm':
                val *= 1_000_000
            elif suffix == 'b':
                val *= 1_000_000_000
            return ("above", val)

        match = re.search(r'(below|under|lower than|less than|<)\s*\$?([\d,]+\.?\d*)\s*([kmb])?', text_lower)
        if match:
            val = float(match.group(2).replace(',', ''))
            suffix = match.group(3)
            if suffix == 'k':
                val *= 1000
            elif suffix == 'm':
                val *= 1_000_000
            elif suffix == 'b':
                val *= 1_000_000_000
            return ("below", val)

        return None

    def _compute_match_score(self, poly: Market, kalshi: Market) -> Tuple[float, str]:
        """Compute similarity score between a Polymarket and Kalshi market.

        Returns (score, method) where score is 0-1 and method describes how
        the match was determined.
        """
        # Method 1: Ticker-keyword mapping (highest confidence)
        kalshi_event = kalshi.condition_id.upper()  # event_ticker stored here
        poly_q = poly.question.lower()

        for ticker_prefix, keywords in _TICKER_KEYWORD_MAP.items():
            if ticker_prefix in kalshi_event:
                if any(kw in poly_q for kw in keywords):
                    # Check if numeric thresholds also match
                    poly_thresh = self._extract_numeric_threshold(poly.question)
                    kalshi_thresh = self._extract_numeric_threshold(kalshi.question)
                    if poly_thresh and kalshi_thresh:
                        if poly_thresh[0] == kalshi_thresh[0]:
                            # Same direction — check if value is close
                            ratio = min(poly_thresh[1], kalshi_thresh[1]) / max(poly_thresh[1], kalshi_thresh[1]) if max(poly_thresh[1], kalshi_thresh[1]) > 0 else 0
                            if ratio > 0.95:
                                return (0.95, "ticker_map+threshold")
                            elif ratio > 0.80:
                                return (0.70, "ticker_map+similar_threshold")
                        return (0.30, "ticker_map+diff_threshold")
                    # No threshold to compare — moderate confidence from ticker match
                    return (0.60, "ticker_map")

        # Method 2: Category + keyword overlap
        if poly.category and kalshi.category:
            if poly.category.lower() == kalshi.category.lower():
                # Same category — check keyword overlap
                poly_words = set(self._normalize_question(poly.question).split())
                kalshi_words = set(self._normalize_question(kalshi.question).split())
                # Remove very short words
                poly_words = {w for w in poly_words if len(w) > 2}
                kalshi_words = {w for w in kalshi_words if len(w) > 2}

                if poly_words and kalshi_words:
                    overlap = poly_words & kalshi_words
                    union = poly_words | kalshi_words
                    jaccard = len(overlap) / len(union) if union else 0

                    if jaccard > 0.40:
                        return (min(0.85, jaccard + 0.30), "category_keyword")
                    elif jaccard > 0.20:
                        return (jaccard + 0.15, "category_keyword_weak")

        # Method 3: Pure keyword overlap (lowest confidence)
        poly_words = set(self._normalize_question(poly.question).split())
        kalshi_words = set(self._normalize_question(kalshi.question).split())
        poly_words = {w for w in poly_words if len(w) > 3}
        kalshi_words = {w for w in kalshi_words if len(w) > 3}

        if poly_words and kalshi_words:
            overlap = poly_words & kalshi_words
            if len(overlap) >= 3:
                jaccard = len(overlap) / len(poly_words | kalshi_words)
                return (min(0.60, jaccard + 0.10), "keyword_overlap")

        return (0.0, "no_match")

    def match_markets(
        self, poly_markets: List[Market], kalshi_markets: List[Market]
    ) -> List[MatchedMarketPair]:
        """Find matching market pairs across exchanges.

        Compares every Polymarket market against Kalshi markets in
        overlapping categories. Returns pairs above the match threshold,
        sorted by match score (best first).
        """
        pairs = []
        # Pre-filter to relevant categories
        kalshi_by_cat: Dict[str, List[Market]] = {}
        for km in kalshi_markets:
            cat = km.category or "General"
            if cat not in kalshi_by_cat:
                kalshi_by_cat[cat] = []
            kalshi_by_cat[cat].append(km)

        for pm in poly_markets:
            if not pm.active or pm.closed:
                continue
            # Check against same-category Kalshi markets + General
            candidate_cats = {pm.category, "General"} if pm.category else {"General"}
            # Also check all cross-exchange categories
            for cat in _CROSS_EXCHANGE_CATEGORIES:
                candidate_cats.add(cat)

            checked_kalshi = set()
            for cat in candidate_cats:
                for km in kalshi_by_cat.get(cat, []):
                    if km.id in checked_kalshi:
                        continue
                    checked_kalshi.add(km.id)

                    if not km.active or km.closed:
                        continue

                    score, method = self._compute_match_score(pm, km)
                    if score >= self.match_threshold:
                        pairs.append(MatchedMarketPair(
                            poly_market=pm,
                            kalshi_market=km,
                            match_score=score,
                            match_method=method,
                            category=cat,
                        ))

        pairs.sort(key=lambda p: p.match_score, reverse=True)
        return pairs

    def scan(self, markets: List[Market]) -> List[ScanResult]:
        """
        Scan for cross-exchange arbitrage between Polymarket and Kalshi.

        The `markets` arg contains Polymarket markets (from the scanner).
        Kalshi markets are fetched separately via self.kalshi_client.
        """
        results = []
        if not self.kalshi_client:
            logger.warning("[CROSS_EXCHANGE] No Kalshi client configured — skipping")
            return results

        # Fetch Kalshi markets
        try:
            kalshi_markets = []
            for offset in range(0, 400, 200):
                batch = self.kalshi_client.get_markets(limit=200, offset=offset)
                kalshi_markets.extend(batch)
                if len(batch) < 200:
                    break
            logger.info(f"[CROSS_EXCHANGE] Fetched {len(kalshi_markets)} Kalshi markets")
        except Exception as e:
            logger.error(f"[CROSS_EXCHANGE] Kalshi fetch failed: {e}")
            return results

        if not kalshi_markets:
            return results

        # Match markets across exchanges
        pairs = self.match_markets(markets, kalshi_markets)
        logger.info(f"[CROSS_EXCHANGE] Found {len(pairs)} matched pairs")

        for pair in pairs:
            pm = pair.poly_market
            km = pair.kalshi_market

            # Get YES prices from both
            poly_yes = pm.outcomes[0].price if pm.outcomes else 0.5
            kalshi_yes = km.outcomes[0].price if km.outcomes else 0.5

            spread = abs(poly_yes - kalshi_yes)
            total_fees = self.polymarket_fee + self.kalshi_fee
            net_edge = spread - total_fees

            if spread < self.min_spread:
                continue

            # Determine direction: buy cheap side, sell expensive side
            if poly_yes < kalshi_yes:
                buy_exchange = "Polymarket"
                sell_exchange = "Kalshi"
                buy_price = poly_yes
                sell_price = kalshi_yes
                signal_market = pm  # The market to act on
            else:
                buy_exchange = "Kalshi"
                sell_exchange = "Polymarket"
                buy_price = kalshi_yes
                sell_price = poly_yes
                signal_market = km

            # Only report if net edge is positive (profitable after fees)
            if net_edge > 0:
                confidence = pair.match_score * 0.90  # Discount by match quality
                results.append(ScanResult(
                    market=signal_market,
                    strategy=self.name,
                    outcome_idx=0,
                    side="BUY",
                    entry_price=buy_price,
                    expected_value=sell_price,
                    edge=net_edge,
                    confidence=confidence,
                    reason=(
                        f"CROSS-EXCHANGE ARB: Buy YES on {buy_exchange} @ "
                        f"${buy_price:.3f}, sell on {sell_exchange} @ "
                        f"${sell_price:.3f} | spread={spread*100:.1f}% | "
                        f"fees={total_fees*100:.1f}% | "
                        f"net={net_edge*100:.1f}% | "
                        f"match={pair.match_score:.0%} ({pair.match_method}) | "
                        f"Poly: \"{pm.question[:50]}\" vs "
                        f"Kalshi: \"{km.question[:50]}\""
                    ),
                ))
            elif spread >= self.min_spread * 0.5:
                # Near-miss: spread exists but fees eat it. Log for monitoring.
                logger.debug(
                    f"[CROSS_EXCHANGE] Near-miss: {pm.question[:40]} vs "
                    f"{km.question[:40]} spread={spread:.1%} < fees={total_fees:.1%}"
                )

        return results


# ================================================================
# Scanner (runs all strategies)
# ================================================================

class PredictionMarketScanner:
    """
    Orchestrates all prediction market strategies.

    Usage:
        client = PolymarketClient()
        scanner = PredictionMarketScanner(client)
        scanner.add_strategy(NearCertaintyStrategy(client, config))
        scanner.add_strategy(WeatherArbitrageStrategy(client, config, ...))

        # Run scan
        opportunities = scanner.scan()
        for opp in opportunities:
            print(f"[{opp.strategy}] {opp.reason} (edge={opp.edge:.1%})")
    """

    def __init__(self, client: PolymarketClient):
        self.client = client
        self.strategies: List[BaseStrategy] = []
        self.scan_history: List[ScanResult] = []
        self.total_scans: int = 0

    def add_strategy(self, strategy: BaseStrategy):
        """Register a strategy."""
        self.strategies.append(strategy)
        logger.info(f"[SCANNER] Registered strategy: {strategy.name}")

    def scan(self, market_limit: int = 200) -> List[ScanResult]:
        """
        Run all strategies against current markets.

        Returns list of opportunities sorted by edge (highest first).
        """
        self.total_scans += 1
        logger.info(f"[SCANNER] Scan #{self.total_scans} — fetching markets...")

        # Fetch markets
        all_markets = []
        for offset in range(0, market_limit, 100):
            batch = self.client.get_markets(limit=100, offset=offset)
            all_markets.extend(batch)
            if len(batch) < 100:
                break

        logger.info(f"[SCANNER] Found {len(all_markets)} active markets")

        # Run each strategy
        all_results = []
        for strategy in self.strategies:
            if not strategy.config.enabled:
                continue
            try:
                results = strategy.scan(all_markets)
                all_results.extend(results)
                if results:
                    logger.info(
                        f"[SCANNER] {strategy.name}: {len(results)} opportunities found"
                    )
            except Exception as e:
                logger.error(f"[SCANNER] {strategy.name} failed: {e}")

        # Sort by edge (highest first)
        all_results.sort(key=lambda r: r.edge, reverse=True)
        self.scan_history.extend(all_results)

        # Keep history manageable
        if len(self.scan_history) > 10000:
            self.scan_history = self.scan_history[-5000:]

        logger.info(
            f"[SCANNER] Scan complete: {len(all_results)} total opportunities "
            f"(best edge: {all_results[0].edge:.1%})" if all_results
            else "[SCANNER] Scan complete: no opportunities"
        )
        return all_results
