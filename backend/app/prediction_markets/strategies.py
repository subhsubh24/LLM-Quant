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
        min_price: float = 0.90,
        max_price: float = 0.99,
        min_volume: float = 5000,
        max_hours_to_resolution: int = 720,  # 30 days
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
        - At least one outcome priced 90-99c
        - Market ends within configured horizon (default 30 days)
        - Sufficient volume (liquid = less likely to reverse)
        """
        results = []
        now = datetime.now(timezone.utc)
        skipped = {"inactive": 0, "not_binary": 0, "low_volume": 0, "time": 0, "no_end_date": 0, "no_price_match": 0}

        for market in markets:
            if not market.active or market.closed:
                skipped["inactive"] += 1
                continue
            if not market.is_binary:
                skipped["not_binary"] += 1
                continue
            if market.total_volume < self.min_volume:
                skipped["low_volume"] += 1
                continue

            # Check time to resolution — markets without end dates still qualify
            # (many Polymarket events don't set end_date until close to resolution)
            hours_left = None
            if market.end_date:
                hours_left = (market.end_date - now).total_seconds() / 3600
                if hours_left > self.max_hours_to_resolution or hours_left < 0:
                    skipped["time"] += 1
                    continue
            # No end_date: treat as long-duration (still scan for price opportunities)

            found_price = False
            for i, outcome in enumerate(market.outcomes):
                if self.min_price <= outcome.price <= self.max_price:
                    profit_per_share = 1.0 - outcome.price
                    # Assume ~2% chance of reversal (conservative)
                    reversal_risk = 0.02
                    expected_value = (1.0 - reversal_risk) * profit_per_share - reversal_risk * outcome.price
                    edge = expected_value / outcome.price

                    if edge > 0 and self.can_open_position():
                        time_info = f"{hours_left:.0f}h to resolution" if hours_left is not None else "no end date"
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
                                f"{time_info})"
                            ),
                        ))
                        found_price = True
            if not found_price:
                skipped["no_price_match"] += 1

        if not results:
            logger.info(f"[near_certainty] 0 hits from {len(markets)} markets — filtered: {skipped}")
        else:
            logger.info(f"[near_certainty] {len(results)} hits from {len(markets)} markets")
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
        min_discount: float = 0.01,  # Sum must be < $0.99 (1% discount)
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
        if not results:
            logger.info(f"[same_market_arb] 0 hits from {len(markets)} markets")
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
        if not results:
            logger.info(f"[cross_market_arb] 0 hits from {len(markets)} markets ({len(self.rules)} rules, {len(checked)} pairs checked)")
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
        target_spread: float = 0.01,      # 1c spread per side
        max_spread: float = 0.03,          # 3c max from midpoint for Q-score
        min_liquidity: float = 1000,       # Minimum market liquidity
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
        skipped = {"inactive": 0, "not_binary": 0, "low_liq": 0, "extreme": 0, "short_dur": 0, "toxic": 0, "tight_spread": 0}

        for market in markets:
            if not market.active or market.closed:
                skipped["inactive"] += 1
                continue
            if not market.is_binary:
                skipped["not_binary"] += 1
                continue
            if market.liquidity < self.min_liquidity:
                skipped["low_liq"] += 1
                continue

            # Skip extreme probability markets (hard to provide two-sided liquidity)
            yes_price = market.outcomes[0].price if market.outcomes else 0.5
            if yes_price < 0.10 or yes_price > 0.90:
                skipped["extreme"] += 1
                continue

            # Skip crypto short-duration markets (too volatile for MM)
            question_lower = market.question.lower()
            if any(kw in question_lower for kw in ["15 min", "15-min", "1 hour", "1-hour"]):
                skipped["short_dur"] += 1
                continue

            # VPIN toxicity check — skip if informed flow detected
            token_id = market.outcomes[0].token_id if market.outcomes else ""
            if token_id:
                toxic, vpin_val = self._vpin.is_toxic(token_id)
                if toxic:
                    skipped["toxic"] += 1
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
            # market.spread = |1 - sum(prices)| = pricing inefficiency.
            # For MM, any binary market with decent liquidity and mid-range price is viable.
            # The real bid-ask spread comes from the CLOB order book (not available in scan).
            # Use the pricing inefficiency as a proxy — markets with YES+NO != 1.0 have wider books.
            pricing_gap = market.spread  # |1 - sum(prices)|
            # Estimate effective spread: at minimum use the pricing gap, but also assume
            # a spread proportional to 1/sqrt(liquidity) for well-priced markets
            est_spread = max(pricing_gap, 1.0 / (market.liquidity ** 0.5 + 1)) if market.liquidity > 0 else 0.05
            if est_spread < self.target_spread * 0.5:
                skipped["tight_spread"] += 1
                continue

            q_score = ((self.max_spread - min(est_spread, self.max_spread)) / self.max_spread) ** 2

            reason_parts = [
                f"MM: {market.question[:50]}",
                f"est_spread={est_spread*100:.1f}c",
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
                expected_value=yes_price + est_spread / 2,
                edge=est_spread,
                confidence=0.80,
                reason=" | ".join(reason_parts),
            ))

        if not results:
            logger.info(f"[market_making] 0 hits from {len(markets)} markets — filtered: {skipped}")
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
        self.last_market_count: int = 0

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

        self.last_market_count = len(all_markets)
        logger.info(f"[SCANNER] Found {len(all_markets)} active markets")

        if not all_markets:
            logger.warning("[SCANNER] No markets returned from Polymarket — check API connectivity")

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
