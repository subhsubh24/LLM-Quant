"""
Prediction Market Trading Strategies.

Each strategy scans markets and returns ScanResult objects when it finds
opportunities. The scanner runs these periodically (configurable interval).

Strategies:
1. WeatherArbitrage: Compare NOAA forecasts to weather market prices
2. NearCertaintyHarvester: Buy 95c+ outcomes for penny profits at scale
3. SameMarketArbitrage: Exploit YES + NO < $1.00 within a single market
4. CrossMarketArbitrage: Find logical inconsistencies across related markets
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

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

class CrossMarketArbitrageStrategy(BaseStrategy):
    """
    Find logical inconsistencies across related markets.

    Example: If "Will candidate X win the election?" = 60%
    but "Will candidate X win key state Y?" = 40%,
    that's an inconsistency worth exploiting.

    This strategy maintains a graph of related markets and checks
    for probability violations (e.g., P(A) > P(B) when A implies B).
    """

    def __init__(
        self,
        client: PolymarketClient,
        config: StrategyConfig,
        min_inconsistency: float = 0.10,  # 10% probability gap
    ):
        super().__init__(client, config)
        self.min_inconsistency = min_inconsistency
        self._related_markets: Dict[str, List[str]] = {}  # market_id -> [related_ids]

    @property
    def name(self) -> str:
        return "cross_market_arb"

    def set_related_markets(self, relations: Dict[str, List[str]]):
        """Define which markets are logically related."""
        self._related_markets = relations

    def scan(self, markets: List[Market]) -> List[ScanResult]:
        """
        Find probability inconsistencies across related markets.

        For now, uses a simple heuristic: if two markets share keywords
        and their probabilities are inconsistent, flag it.
        """
        results = []
        active_markets = [m for m in markets if m.active and not m.closed]

        # Build keyword index
        keyword_groups: Dict[str, List[Market]] = {}
        for market in active_markets:
            words = set(market.question.lower().split())
            # Use significant words as keys (skip common words)
            skip = {"will", "the", "a", "an", "in", "on", "at", "to", "of", "by", "be", "is"}
            for word in words - skip:
                if len(word) > 3:
                    if word not in keyword_groups:
                        keyword_groups[word] = []
                    keyword_groups[word].append(market)

        # Check each group for inconsistencies
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

                    # Check if probabilities are inconsistent
                    # Simple heuristic: if one market implies another
                    # (e.g., "X wins election" implies "X wins state"),
                    # then P(election) should be <= P(state) for any given state
                    # This is a simplification — real cross-market arb needs
                    # domain-specific logic
                    if m1.is_binary and m2.is_binary:
                        p1 = m1.outcomes[0].price  # YES price for m1
                        p2 = m2.outcomes[0].price  # YES price for m2
                        gap = abs(p1 - p2)

                        if gap >= self.min_inconsistency:
                            # Check if the gap represents a real inconsistency
                            # (not just different questions)
                            shared_words = (
                                set(m1.question.lower().split())
                                & set(m2.question.lower().split())
                                - skip
                            )
                            if len(shared_words) >= 3:  # Strongly related
                                results.append(ScanResult(
                                    market=m1 if p1 < p2 else m2,
                                    strategy=self.name,
                                    outcome_idx=0,
                                    side="BUY" if p1 < p2 else "SELL",
                                    entry_price=min(p1, p2),
                                    expected_value=max(p1, p2),
                                    edge=gap,
                                    confidence=0.60,  # Lower confidence (heuristic)
                                    reason=(
                                        f"Cross-market gap: \"{m1.question[:60]}\" "
                                        f"({p1:.0%}) vs \"{m2.question[:60]}\" "
                                        f"({p2:.0%}) — {gap*100:.1f}% inconsistency"
                                    ),
                                ))
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
