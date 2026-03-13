"""
Advanced Prediction Market Trading Strategies.

Extends the base strategy set with more sophisticated approaches:
1. NOPositionScanner: Buy cheap NO positions on near-certain YES outcomes
2. LogicalImplicationDetector: Graph-based transitive implication detection
3. WalletBehaviorDivergence: Detect whale vs public alpha divergence
4. AdaptiveBuySignalThreshold: Dynamic per-horizon entry thresholds
"""

import logging
import math
import re
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from .polymarket_client import Market, OrderBook, PolymarketClient, ScanResult
from .strategies import BaseStrategy, StrategyConfig

logger = logging.getLogger(__name__)


# ================================================================
# Strategy 1: NO Position Scanner
# ================================================================

@dataclass
class ReversalEstimate:
    """Bayesian reversal probability estimate for a near-certain market."""
    base_rate: float          # Category base reversal rate
    time_decay_factor: float  # Multiplier from time-to-resolution
    adjusted_rate: float      # Final reversal probability
    edge: float               # Kelly edge: P(reversal) * (1/NO_price - 1) - (1 - P(reversal))
    kelly_fraction: float     # Optimal Kelly fraction


# Category-specific base reversal rates.
# Markets closer to resolution with YES > 95c rarely flip, but the rate
# varies by domain.  Crypto markets reverse more often due to volatility;
# political markets are stickier once near-certain.
_CATEGORY_REVERSAL_RATES: Dict[str, float] = {
    "politics": 0.02,
    "economics": 0.03,
    "sports": 0.05,
    "crypto": 0.08,
    "weather": 0.03,
    "science": 0.02,
    "entertainment": 0.04,
    "default": 0.03,
}


class NOPositionScanner(BaseStrategy):
    """
    Systematically scan for near-zero probability outcomes and buy NO positions.

    Targets outcomes where YES is priced very high (>95c), meaning NO is cheap
    (<5c).  Unlike NearCertaintyHarvester (which buys the expensive YES side for
    penny profits), this strategy BUYS the cheap NO side when the estimated true
    probability of reversal exceeds what the NO price implies.

    The key insight: markets occasionally misprice tail risk.  A NO token at 2c
    implies a 2% reversal chance, but Bayesian estimation adjusted for category,
    time-to-resolution decay, and liquidity can reveal spots where the true
    reversal probability is higher (e.g., 5-8% for crypto markets).

    Uses:
    - Bayesian reversal probability estimation with category-specific base rates
    - Time-to-resolution decay: outcomes closer to resolution with NO still >2c
      have higher implied mispricing
    - Kelly-optimal sizing for asymmetric payoffs

    Filters: binary markets only, min liquidity, min volume, NO priced 1-10c.
    """

    def __init__(
        self,
        client: PolymarketClient,
        config: StrategyConfig,
        min_yes_price: float = 0.90,      # YES must be priced above this
        max_no_price: float = 0.15,        # NO must be priced below this
        min_no_price: float = 0.01,        # NO must be priced above this (avoid dust)
        min_volume: float = 1000,          # Minimum market volume
        min_liquidity: float = 500,        # Minimum market liquidity
        max_hours_to_resolution: int = 720,  # 30 days
        category_rates: Optional[Dict[str, float]] = None,
    ):
        super().__init__(client, config)
        self.min_yes_price = min_yes_price
        self.max_no_price = max_no_price
        self.min_no_price = min_no_price
        self.min_volume = min_volume
        self.min_liquidity = min_liquidity
        self.max_hours_to_resolution = max_hours_to_resolution
        self._category_rates = dict(_CATEGORY_REVERSAL_RATES)
        if category_rates:
            self._category_rates.update(category_rates)

    @property
    def name(self) -> str:
        return "no_position_scanner"

    def _get_reversal_rate(self, category: str) -> float:
        """Get base reversal rate for a market category."""
        cat = category.lower().strip()
        return self._category_rates.get(cat, self._category_rates["default"])

    def _estimate_reversal(
        self,
        no_price: float,
        category: str,
        hours_to_resolution: float,
    ) -> ReversalEstimate:
        """
        Bayesian reversal probability estimation.

        The base rate adjusts by category, then a time-decay factor increases
        estimated reversal probability for markets where NO is still priced
        above dust even close to resolution.  If a market resolves in 6 hours
        and NO is still at 3c, someone is holding for a reason.

        Kelly edge = P(reversal) * (1/NO_price - 1) - (1 - P(reversal))
        """
        base_rate = self._get_reversal_rate(category)

        # Time decay factor: closer to resolution = more informative pricing.
        # Markets far from resolution have higher uncertainty, so we trust the
        # base rate less and the market price more.
        # At 720h (30d): factor = 1.0 (use base rate as-is)
        # At 24h: factor = ~1.8 (amplify — if NO is still >2c, it's meaningful)
        # At 1h: factor = ~3.0 (strongly amplify)
        if hours_to_resolution > 0:
            time_decay_factor = 1.0 + math.log1p(720.0 / max(hours_to_resolution, 0.5)) / 3.0
        else:
            time_decay_factor = 3.0

        # Clamp factor to [1.0, 4.0]
        time_decay_factor = max(1.0, min(time_decay_factor, 4.0))

        # Adjusted reversal probability
        adjusted_rate = min(base_rate * time_decay_factor, 0.50)

        # Kelly edge for asymmetric bet:
        # Win: pay NO_price, receive $1.00 → profit = (1/NO_price - 1) per dollar
        # Lose: lose entire NO_price
        # Edge = P(win) * payout_ratio - P(lose)
        if no_price > 0:
            payout_ratio = (1.0 / no_price) - 1.0
            edge = adjusted_rate * payout_ratio - (1.0 - adjusted_rate)
        else:
            edge = 0.0
            payout_ratio = 0.0

        # Kelly fraction: f* = edge / payout_ratio (simplified for binary)
        if payout_ratio > 0 and edge > 0:
            kelly_fraction = edge / payout_ratio
        else:
            kelly_fraction = 0.0

        return ReversalEstimate(
            base_rate=base_rate,
            time_decay_factor=time_decay_factor,
            adjusted_rate=adjusted_rate,
            edge=edge,
            kelly_fraction=max(0.0, min(kelly_fraction, 0.25)),
        )

    def scan(self, markets: List[Market]) -> List[ScanResult]:
        """
        Scan for cheap NO positions where reversal probability is underpriced.

        Looks for:
        - Active binary markets with YES > 95c (NO < 5c)
        - NO priced between 1c and 10c
        - Sufficient volume and liquidity
        - Bayesian edge > min_edge after Kelly calculation
        """
        results = []
        now = datetime.now(timezone.utc)
        skipped = {
            "inactive": 0, "not_binary": 0, "low_volume": 0,
            "low_liquidity": 0, "time": 0,
            "no_price_match": 0, "no_edge": 0,
        }

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
            if market.liquidity < self.min_liquidity:
                skipped["low_liquidity"] += 1
                continue

            # Check time to resolution
            if not market.end_date:
                # No end date: assume mid-range horizon so strategy still considers it
                hours_left = self.max_hours_to_resolution / 2.0
            else:
                hours_left = (market.end_date - now).total_seconds() / 3600
                if hours_left > self.max_hours_to_resolution or hours_left < 0:
                    skipped["time"] += 1
                    continue

            # Find the NO side (outcome where YES is expensive)
            found = False
            for i, outcome in enumerate(market.outcomes):
                # Identify the YES side by label convention or high price
                is_yes_side = outcome.label.lower() in ("yes", "y")
                if not is_yes_side and outcome.price >= self.min_yes_price:
                    is_yes_side = True

                if is_yes_side and outcome.price >= self.min_yes_price:
                    # The opposite outcome is the NO side we want to buy
                    no_idx = 1 - i
                    if no_idx < 0 or no_idx >= len(market.outcomes):
                        continue
                    no_outcome = market.outcomes[no_idx]
                    no_price = no_outcome.price

                    if not (self.min_no_price <= no_price <= self.max_no_price):
                        continue

                    # Estimate reversal probability
                    estimate = self._estimate_reversal(
                        no_price=no_price,
                        category=market.category,
                        hours_to_resolution=hours_left,
                    )

                    if estimate.edge > self.config.min_edge:
                        found = True
                        results.append(ScanResult(
                            market=market,
                            strategy=self.name,
                            outcome_idx=no_idx,
                            side="BUY",
                            entry_price=no_price,
                            expected_value=estimate.adjusted_rate * 1.0,
                            edge=estimate.edge,
                            confidence=min(estimate.adjusted_rate * 2.0, 0.95),
                            reason=(
                                f"NO at ${no_price:.3f} (YES={outcome.price:.3f}) | "
                                f"P(reversal)={estimate.adjusted_rate:.1%} "
                                f"(base={estimate.base_rate:.1%}, "
                                f"time_factor={estimate.time_decay_factor:.2f}) | "
                                f"edge={estimate.edge:.1%}, "
                                f"kelly_f={estimate.kelly_fraction:.3f} | "
                                f"{hours_left:.0f}h left, "
                                f"cat={market.category or 'unknown'}"
                            ),
                        ))
                        break  # One signal per market

            if not found:
                if any(o.price >= self.min_yes_price for o in market.outcomes):
                    skipped["no_edge"] += 1
                else:
                    skipped["no_price_match"] += 1

        if not results:
            logger.info(
                f"[no_position_scanner] 0 hits from {len(markets)} markets — "
                f"filtered: {skipped}"
            )
        else:
            logger.info(
                f"[no_position_scanner] {len(results)} hits from {len(markets)} markets"
            )
        return results


# ================================================================
# Strategy 2: Logical Implication Detector
# ================================================================

@dataclass
class MarketRelationship:
    """A directed relationship between two markets."""
    source_id: str
    target_id: str
    relation_type: str   # "implies", "excludes", "exhaustive"
    confidence: float    # How confident we are in this relationship (0-1)
    reason: str          # Why this relationship exists


class _ImplicationGraph:
    """
    Directed graph of market relationships for transitive implication detection.

    Nodes are market IDs.  Edges carry relationship type and confidence.
    Supports efficient transitive closure queries: if A->B and B->C, yields A->C.
    """

    def __init__(self):
        # adjacency list: source_id -> [(target_id, relation_type, confidence)]
        self._edges: Dict[str, List[Tuple[str, str, float]]] = defaultdict(list)
        self._relationships: List[MarketRelationship] = []

    def add_relationship(self, rel: MarketRelationship):
        """Add a directed relationship to the graph."""
        self._edges[rel.source_id].append(
            (rel.target_id, rel.relation_type, rel.confidence)
        )
        self._relationships.append(rel)

    def clear(self):
        """Clear all relationships."""
        self._edges.clear()
        self._relationships.clear()

    @property
    def edge_count(self) -> int:
        return sum(len(v) for v in self._edges.values())

    @property
    def node_count(self) -> int:
        nodes: Set[str] = set()
        for src, targets in self._edges.items():
            nodes.add(src)
            for tgt, _, _ in targets:
                nodes.add(tgt)
        return len(nodes)

    def get_transitive_implications(
        self, source_id: str, max_depth: int = 4,
    ) -> List[Tuple[str, float]]:
        """
        Find all markets transitively implied by source_id.

        Returns list of (target_id, compounded_confidence).
        Uses BFS with confidence decay along the chain.
        """
        visited: Set[str] = {source_id}
        queue: List[Tuple[str, float, int]] = [(source_id, 1.0, 0)]
        results: List[Tuple[str, float]] = []

        while queue:
            current, conf, depth = queue.pop(0)
            if depth >= max_depth:
                continue

            for target_id, rel_type, edge_conf in self._edges.get(current, []):
                if rel_type != "implies":
                    continue
                if target_id in visited:
                    continue
                visited.add(target_id)

                # Compound confidence decays along the chain
                chain_conf = conf * edge_conf
                if chain_conf < 0.30:
                    continue  # Prune low-confidence chains

                results.append((target_id, chain_conf))
                queue.append((target_id, chain_conf, depth + 1))

        return results

    def get_exclusion_pairs(self) -> List[Tuple[str, str, float]]:
        """Get all pairs of mutually exclusive markets."""
        pairs = []
        for src, targets in self._edges.items():
            for tgt, rel_type, conf in targets:
                if rel_type == "excludes":
                    pairs.append((src, tgt, conf))
        return pairs

    def get_exhaustive_groups(self) -> List[Tuple[str, str, float]]:
        """Get all pairs that form exhaustive groups."""
        groups = []
        for src, targets in self._edges.items():
            for tgt, rel_type, conf in targets:
                if rel_type == "exhaustive":
                    groups.append((src, tgt, conf))
        return groups


# Keywords for NLP-based relationship extraction.
_ENTITY_PATTERNS = [
    # Political figures
    r"\b(trump|biden|harris|desantis|newsom|obama)\b",
    # Crypto assets
    r"\b(bitcoin|btc|ethereum|eth|solana|sol)\b",
    # Economic indicators
    r"\b(gdp|inflation|fed|interest rate|unemployment)\b",
    # Sports teams/events
    r"\b(super bowl|world series|nba finals|champions league)\b",
]


class LogicalImplicationDetector(BaseStrategy):
    """
    Graph-based logical implication detector for cross-market arbitrage.

    Goes beyond CrossMarketArbitrage by:
    1. Building a directed graph of market relationships
    2. Detecting TRANSITIVE implications: A->B and B->C yields A->C
    3. Detecting PROBABILITY BOUNDS: exhaustive/exclusive pairs must sum to ~1.0
    4. Using NLP keyword extraction to auto-discover relationships
    5. Maintaining a persistent relationship graph across scans

    The key insight: when markets haven't repriced after a related market moves,
    the transitive implication chain reveals mispricing faster than direct
    pair-wise comparison.
    """

    def __init__(
        self,
        client: PolymarketClient,
        config: StrategyConfig,
        min_gap: float = 0.08,          # Minimum probability gap to signal
        max_sum_deviation: float = 0.08,  # Max deviation from 1.0 for exhaustive sets
        nlp_confidence: float = 0.55,    # Confidence for NLP-discovered relationships
        transitive_max_depth: int = 4,   # Max depth for transitive implication search
    ):
        super().__init__(client, config)
        self.min_gap = min_gap
        self.max_sum_deviation = max_sum_deviation
        self.nlp_confidence = nlp_confidence
        self.transitive_max_depth = transitive_max_depth
        self._graph = _ImplicationGraph()
        self._market_cache: Dict[str, Market] = {}
        self._entity_patterns = [re.compile(p, re.IGNORECASE) for p in _ENTITY_PATTERNS]

    @property
    def name(self) -> str:
        return "logical_implication"

    def _extract_entities(self, text: str) -> Set[str]:
        """Extract named entities from market question text."""
        entities: Set[str] = set()
        for pattern in self._entity_patterns:
            for match in pattern.finditer(text):
                entities.add(match.group(0).lower())
        return entities

    def _extract_keywords(self, question: str) -> Set[str]:
        """Extract meaningful keywords from a market question."""
        stop_words = {
            "will", "the", "a", "an", "in", "on", "at", "to", "of", "by",
            "be", "is", "it", "do", "or", "and", "for", "this", "that",
            "with", "from", "not", "but", "what", "when", "who", "how",
            "has", "have", "been", "was", "were", "are", "does", "did",
            "before", "after", "above", "below", "more", "than", "yes", "no",
        }
        words = set(re.findall(r'\b[a-z]{3,}\b', question.lower()))
        return words - stop_words

    def _discover_relationships(self, markets: List[Market]):
        """
        Auto-discover relationships between markets using NLP heuristics.

        Looks for:
        - Shared entities (same person/asset across markets)
        - Temporal ordering (A must happen before B)
        - Threshold implications (BTC > 150k implies BTC > 100k)
        - Multi-outcome exhaustive groups (all outcomes in one event)
        """
        self._graph.clear()
        self._market_cache = {m.id: m for m in markets}

        # Index markets by entity
        entity_markets: Dict[str, List[Market]] = defaultdict(list)
        keyword_markets: Dict[str, List[Market]] = defaultdict(list)

        for market in markets:
            if not market.active or market.closed:
                continue

            entities = self._extract_entities(market.question)
            for entity in entities:
                entity_markets[entity].append(market)

            keywords = self._extract_keywords(market.question)
            for kw in keywords:
                keyword_markets[kw].append(market)

        # Detect threshold implications (e.g., "BTC above 150k" implies "BTC above 100k")
        threshold_pattern = re.compile(
            r'(above|over|exceed|reach|hit)\s+\$?([\d,.]+)', re.IGNORECASE
        )
        for entity, group in entity_markets.items():
            if len(group) < 2:
                continue

            # Extract thresholds for each market
            threshold_markets: List[Tuple[Market, float]] = []
            for m in group:
                match = threshold_pattern.search(m.question)
                if match:
                    try:
                        val = float(match.group(2).replace(",", ""))
                        threshold_markets.append((m, val))
                    except ValueError:
                        continue

            # Sort by threshold value — higher threshold implies lower thresholds
            threshold_markets.sort(key=lambda x: x[1])
            for i in range(len(threshold_markets) - 1):
                lower_market, lower_val = threshold_markets[i]
                for j in range(i + 1, len(threshold_markets)):
                    higher_market, higher_val = threshold_markets[j]
                    if higher_val > lower_val:
                        self._graph.add_relationship(MarketRelationship(
                            source_id=higher_market.id,
                            target_id=lower_market.id,
                            relation_type="implies",
                            confidence=0.90,
                            reason=(
                                f"{entity} above {higher_val} implies "
                                f"{entity} above {lower_val}"
                            ),
                        ))

        # Detect shared-entity relationships via keyword overlap
        checked_pairs: Set[Tuple[str, str]] = set()
        for entity, group in entity_markets.items():
            if len(group) < 2:
                continue
            for i, m1 in enumerate(group):
                for m2 in group[i + 1:]:
                    pair = tuple(sorted([m1.id, m2.id]))
                    if pair in checked_pairs:
                        continue
                    checked_pairs.add(pair)

                    kw1 = self._extract_keywords(m1.question)
                    kw2 = self._extract_keywords(m2.question)
                    shared = kw1 & kw2
                    if len(shared) >= 3:
                        self._graph.add_relationship(MarketRelationship(
                            source_id=m1.id,
                            target_id=m2.id,
                            relation_type="implies",
                            confidence=self.nlp_confidence,
                            reason=(
                                f"Shared keywords: {', '.join(sorted(shared)[:5])}"
                            ),
                        ))

        # Detect multi-outcome exhaustive groups
        # Markets with the same slug prefix or identical tags are often
        # mutually exclusive outcomes of the same event.
        slug_groups: Dict[str, List[Market]] = defaultdict(list)
        for market in markets:
            if not market.active or market.closed:
                continue
            if market.is_multi:
                # Multi-outcome markets are internally exhaustive
                continue
            # Group by slug prefix (first 3 segments)
            slug_prefix = "-".join(market.slug.split("-")[:4]) if market.slug else ""
            if slug_prefix:
                slug_groups[slug_prefix].append(market)

        for prefix, group in slug_groups.items():
            if len(group) < 2:
                continue
            # Mark all pairs as exhaustive candidates
            for i, m1 in enumerate(group):
                for m2 in group[i + 1:]:
                    self._graph.add_relationship(MarketRelationship(
                        source_id=m1.id,
                        target_id=m2.id,
                        relation_type="exhaustive",
                        confidence=0.70,
                        reason=f"Shared slug prefix: {prefix}",
                    ))

        logger.info(
            f"[logical_implication] Graph built: {self._graph.node_count} nodes, "
            f"{self._graph.edge_count} edges"
        )

    def scan(self, markets: List[Market]) -> List[ScanResult]:
        """
        Scan for mispricing via transitive implications and probability bounds.

        Phase 1: Rebuild relationship graph from current markets.
        Phase 2: Check transitive implication chains for probability violations.
        Phase 3: Check exhaustive groups where outcome sums deviate from 1.0.
        Phase 4: Check multi-outcome markets where internal sums are off.
        """
        results = []
        active_markets = [m for m in markets if m.active and not m.closed]

        if not active_markets:
            return results

        # Phase 1: Build relationship graph
        self._discover_relationships(active_markets)

        # Phase 2: Transitive implication violations
        binary_markets = [m for m in active_markets if m.is_binary]
        market_prices: Dict[str, float] = {}
        for m in binary_markets:
            if m.outcomes:
                market_prices[m.id] = m.outcomes[0].price

        for market in binary_markets:
            if market.id not in market_prices:
                continue
            p_source = market_prices[market.id]

            implications = self._graph.get_transitive_implications(
                market.id, max_depth=self.transitive_max_depth,
            )

            for target_id, chain_conf in implications:
                if target_id not in market_prices:
                    continue
                p_target = market_prices[target_id]
                target_market = self._market_cache.get(target_id)
                if not target_market:
                    continue

                # If source implies target, then P(source) <= P(target).
                # Violation: P(source) > P(target) + gap
                if p_source > p_target + self.min_gap:
                    gap = p_source - p_target
                    edge = gap * chain_conf

                    if edge > self.config.min_edge:
                        results.append(ScanResult(
                            market=target_market,
                            strategy=self.name,
                            outcome_idx=0,
                            side="BUY",
                            entry_price=p_target,
                            expected_value=p_source,
                            edge=edge,
                            confidence=chain_conf,
                            reason=(
                                f"TRANSITIVE IMPLICATION: "
                                f"\"{market.question[:40]}\" ({p_source:.0%}) → "
                                f"\"{target_market.question[:40]}\" ({p_target:.0%}) | "
                                f"gap={gap:.1%}, chain_conf={chain_conf:.0%}"
                            ),
                        ))

        # Phase 3: Exhaustive group probability bounds
        for src_id, tgt_id, conf in self._graph.get_exhaustive_groups():
            src = self._market_cache.get(src_id)
            tgt = self._market_cache.get(tgt_id)
            if not src or not tgt:
                continue
            if not src.is_binary or not tgt.is_binary:
                continue

            p_src = src.outcomes[0].price if src.outcomes else 0.5
            p_tgt = tgt.outcomes[0].price if tgt.outcomes else 0.5
            total = p_src + p_tgt
            deviation = abs(total - 1.0)

            if deviation > self.max_sum_deviation:
                if total < 1.0:
                    # Both underpriced — buy the cheaper one
                    buy_market = src if p_src < p_tgt else tgt
                    buy_price = min(p_src, p_tgt)
                    edge = (deviation / 2.0) * conf
                    if edge > self.config.min_edge:
                        results.append(ScanResult(
                            market=buy_market,
                            strategy=self.name,
                            outcome_idx=0,
                            side="BUY",
                            entry_price=buy_price,
                            expected_value=buy_price + deviation / 2.0,
                            edge=edge,
                            confidence=conf,
                            reason=(
                                f"EXHAUSTIVE UNDERPRICED: "
                                f"\"{src.question[:40]}\" ({p_src:.0%}) + "
                                f"\"{tgt.question[:40]}\" ({p_tgt:.0%}) = "
                                f"{total:.0%} (should be ~100%, dev={deviation:.1%})"
                            ),
                        ))
                else:
                    # Both overpriced — sell the more expensive one
                    sell_market = src if p_src > p_tgt else tgt
                    sell_price = max(p_src, p_tgt)
                    edge = (deviation / 2.0) * conf
                    if edge > self.config.min_edge:
                        results.append(ScanResult(
                            market=sell_market,
                            strategy=self.name,
                            outcome_idx=0,
                            side="SELL",
                            entry_price=sell_price,
                            expected_value=sell_price - deviation / 2.0,
                            edge=edge,
                            confidence=conf,
                            reason=(
                                f"EXHAUSTIVE OVERPRICED: "
                                f"\"{src.question[:40]}\" ({p_src:.0%}) + "
                                f"\"{tgt.question[:40]}\" ({p_tgt:.0%}) = "
                                f"{total:.0%} (should be ~100%, dev={deviation:.1%})"
                            ),
                        ))

        # Phase 4: Multi-outcome markets where internal outcome sums deviate
        for market in active_markets:
            if not market.is_multi or len(market.outcomes) < 3:
                continue
            if market.liquidity < self.config.min_liquidity:
                continue

            price_sum = sum(o.price for o in market.outcomes)
            deviation = abs(price_sum - 1.0)

            if deviation > self.max_sum_deviation:
                if price_sum < 1.0:
                    # Outcomes underpriced — buy the cheapest with the best ratio
                    cheapest_idx = min(
                        range(len(market.outcomes)),
                        key=lambda j: market.outcomes[j].price,
                    )
                    cheapest = market.outcomes[cheapest_idx]
                    edge = deviation / len(market.outcomes)
                    if edge > self.config.min_edge and cheapest.price > 0.01:
                        results.append(ScanResult(
                            market=market,
                            strategy=self.name,
                            outcome_idx=cheapest_idx,
                            side="BUY",
                            entry_price=cheapest.price,
                            expected_value=cheapest.price + edge,
                            edge=edge,
                            confidence=0.75,
                            reason=(
                                f"MULTI-OUTCOME SUM: {len(market.outcomes)} outcomes "
                                f"sum to {price_sum:.3f} (should be ~1.0, "
                                f"dev={deviation:.1%}) | "
                                f"buy \"{cheapest.label}\" at ${cheapest.price:.3f}"
                            ),
                        ))
                else:
                    # Outcomes overpriced — sell the most expensive
                    expensive_idx = max(
                        range(len(market.outcomes)),
                        key=lambda j: market.outcomes[j].price,
                    )
                    expensive = market.outcomes[expensive_idx]
                    edge = deviation / len(market.outcomes)
                    if edge > self.config.min_edge:
                        results.append(ScanResult(
                            market=market,
                            strategy=self.name,
                            outcome_idx=expensive_idx,
                            side="SELL",
                            entry_price=expensive.price,
                            expected_value=expensive.price - edge,
                            edge=edge,
                            confidence=0.75,
                            reason=(
                                f"MULTI-OUTCOME SUM: {len(market.outcomes)} outcomes "
                                f"sum to {price_sum:.3f} (should be ~1.0, "
                                f"dev={deviation:.1%}) | "
                                f"sell \"{expensive.label}\" at ${expensive.price:.3f}"
                            ),
                        ))

        if results:
            logger.info(
                f"[logical_implication] {len(results)} hits from {len(markets)} markets "
                f"(graph: {self._graph.node_count} nodes, {self._graph.edge_count} edges)"
            )
        else:
            logger.info(
                f"[logical_implication] 0 hits from {len(markets)} markets "
                f"(graph: {self._graph.node_count} nodes, {self._graph.edge_count} edges)"
            )
        return results


# ================================================================
# Strategy 3: Wallet Behavior Divergence
# ================================================================

@dataclass
class PublicAlpha:
    """A publicly known strategy pattern (from articles, tweets, etc.)."""
    name: str
    description: str
    category: str             # "threshold", "volatility", "timing", "sizing"
    expected_behavior: str    # What public alpha recommends
    parameter_name: str       # The parameter being compared
    parameter_value: float    # The public recommendation value
    source: str               # Where this was published


@dataclass
class DivergenceSignal:
    """A detected divergence between whale behavior and public alpha."""
    alpha: PublicAlpha
    whale_value: float        # What whales actually do
    public_value: float       # What articles recommend
    divergence_pct: float     # Magnitude of divergence
    whale_count: int          # Number of whales showing this behavior
    historical_accuracy: float  # How accurate past divergence signals were


# Built-in registry of common public alpha patterns that are widely shared
# in articles and social media.  Whales who consistently outperform often
# deviate from these public recommendations.
_DEFAULT_PUBLIC_ALPHA: List[PublicAlpha] = [
    PublicAlpha(
        name="mispricing_threshold",
        description="Wait for 5% mispricing before entering",
        category="threshold",
        expected_behavior="Enter only when edge > 5%",
        parameter_name="min_edge",
        parameter_value=0.05,
        source="Common prediction market guides",
    ),
    PublicAlpha(
        name="avoid_volatility",
        description="Avoid markets with high recent price swings",
        category="volatility",
        expected_behavior="Skip markets with >10% daily volatility",
        parameter_name="max_volatility",
        parameter_value=0.10,
        source="Risk management articles",
    ),
    PublicAlpha(
        name="conservative_sizing",
        description="Start with small positions and scale up slowly",
        category="timing",
        expected_behavior="Initial position = 1% of bankroll",
        parameter_name="position_pct",
        parameter_value=0.01,
        source="Kelly criterion tutorials",
    ),
    PublicAlpha(
        name="certainty_entry",
        description="Buy near-certain outcomes above 95c",
        category="threshold",
        expected_behavior="Only buy when outcome > 95c",
        parameter_name="min_certainty",
        parameter_value=0.95,
        source="Near-certainty harvesting guides",
    ),
    PublicAlpha(
        name="liquidity_floor",
        description="Only trade markets with >$10K liquidity",
        category="threshold",
        expected_behavior="Require $10,000 minimum liquidity",
        parameter_name="min_liquidity",
        parameter_value=10000.0,
        source="Market making articles",
    ),
    PublicAlpha(
        name="compounding_rate",
        description="Compound gains at 1-2% per trade",
        category="timing",
        expected_behavior="Target 1-2% per trade compounding",
        parameter_name="compound_rate",
        parameter_value=0.015,
        source="Prediction market bot guides",
    ),
]


class WalletBehaviorDivergence(BaseStrategy):
    """
    Detect divergence between top wallet behavior and publicly recommended strategies.

    Maintains a registry of "public alpha" — known strategy patterns published
    in articles and tweets — and tracks actual whale behavior from the existing
    WhaleCopyTrading infrastructure.  When whales consistently trade AGAINST
    publicly recommended strategies, this generates a signal to follow the
    whale behavior.

    Three divergence types:
    a. Threshold divergence: public says "wait for 5% mispricing" but whales
       enter at 2.3% — trade the whale threshold
    b. Volatility divergence: public says "avoid volatile markets" but whales
       profit during volatility spikes — trade into volatility
    c. Timing divergence: public says "start small" but successful bots
       compound at 3-6% per trade — use whale sizing patterns

    Confidence is based on: number of whales diverging, historical accuracy
    of past divergence signals, and magnitude of divergence.
    """

    def __init__(
        self,
        client: PolymarketClient,
        config: StrategyConfig,
        min_whale_count: int = 2,          # Min whales diverging to signal
        min_divergence_pct: float = 0.30,  # Min 30% divergence from public alpha
        public_alpha: Optional[List[PublicAlpha]] = None,
    ):
        super().__init__(client, config)
        self.min_whale_count = min_whale_count
        self.min_divergence_pct = min_divergence_pct
        self._public_alpha = list(public_alpha or _DEFAULT_PUBLIC_ALPHA)
        self._whale_trades: List[dict] = []
        self._divergence_history: List[DivergenceSignal] = []
        self._whale_stats: Dict[str, dict] = {}  # wallet -> aggregate stats
        # Historical accuracy tracking: alpha_name -> (correct, total)
        self._signal_accuracy: Dict[str, Tuple[int, int]] = {}

    @property
    def name(self) -> str:
        return "wallet_divergence"

    def add_public_alpha(self, alpha: PublicAlpha):
        """Register a new public alpha pattern."""
        self._public_alpha.append(alpha)
        logger.info(f"[wallet_divergence] Added public alpha: {alpha.name}")

    def record_whale_trade(
        self,
        wallet: str,
        market_id: str,
        outcome: str,
        side: str,
        price: float,
        size: float,
        market_volatility: float = 0.0,
        market_liquidity: float = 0.0,
        edge_estimate: float = 0.0,
    ):
        """
        Record a whale trade for divergence analysis.

        Called by the WhaleCopyTrading infrastructure when a tracked wallet
        makes a trade.  Enriches the trade with market context for divergence
        detection.
        """
        trade = {
            "wallet": wallet.lower(),
            "market_id": market_id,
            "outcome": outcome,
            "side": side,
            "price": price,
            "size": size,
            "market_volatility": market_volatility,
            "market_liquidity": market_liquidity,
            "edge_estimate": edge_estimate,
            "timestamp": datetime.now(timezone.utc),
        }
        self._whale_trades.append(trade)

        # Keep last 1000 trades
        if len(self._whale_trades) > 1000:
            self._whale_trades = self._whale_trades[-1000:]

        # Update per-wallet stats
        wallet_key = wallet.lower()
        if wallet_key not in self._whale_stats:
            self._whale_stats[wallet_key] = {
                "trade_count": 0,
                "avg_edge": 0.0,
                "avg_size_pct": 0.0,
                "volatility_trades": 0,
                "low_liquidity_trades": 0,
            }
        stats = self._whale_stats[wallet_key]
        stats["trade_count"] += 1
        # Running average of edge
        n = stats["trade_count"]
        stats["avg_edge"] = stats["avg_edge"] * (n - 1) / n + edge_estimate / n
        if market_volatility > 0.10:
            stats["volatility_trades"] += 1
        if market_liquidity < 10000:
            stats["low_liquidity_trades"] += 1

    def record_signal_outcome(self, alpha_name: str, was_profitable: bool):
        """Record whether a divergence signal was profitable for accuracy tracking."""
        if alpha_name not in self._signal_accuracy:
            self._signal_accuracy[alpha_name] = (0, 0)
        correct, total = self._signal_accuracy[alpha_name]
        if was_profitable:
            correct += 1
        self._signal_accuracy[alpha_name] = (correct, total + 1)

    def _get_historical_accuracy(self, alpha_name: str) -> float:
        """Get historical accuracy of divergence signals for a given alpha."""
        if alpha_name not in self._signal_accuracy:
            return 0.50  # No history — use prior of 50%
        correct, total = self._signal_accuracy[alpha_name]
        if total == 0:
            return 0.50
        # Laplace smoothing: (correct + 1) / (total + 2)
        return (correct + 1) / (total + 2)

    def _detect_threshold_divergence(
        self, recent_trades: List[dict],
    ) -> List[DivergenceSignal]:
        """Detect when whales enter at thresholds different from public alpha."""
        signals = []
        threshold_alphas = [a for a in self._public_alpha if a.category == "threshold"]

        for alpha in threshold_alphas:
            if alpha.parameter_name == "min_edge":
                # Check if whales are entering at lower edge thresholds
                whale_edges = [
                    t["edge_estimate"] for t in recent_trades
                    if t["edge_estimate"] > 0 and t["side"] == "BUY"
                ]
                if len(whale_edges) < self.min_whale_count:
                    continue
                avg_whale_edge = sum(whale_edges) / len(whale_edges)
                if avg_whale_edge < alpha.parameter_value:
                    div_pct = (alpha.parameter_value - avg_whale_edge) / alpha.parameter_value
                    if div_pct >= self.min_divergence_pct:
                        unique_wallets = len(set(
                            t["wallet"] for t in recent_trades
                            if t["edge_estimate"] > 0 and t["side"] == "BUY"
                        ))
                        signals.append(DivergenceSignal(
                            alpha=alpha,
                            whale_value=avg_whale_edge,
                            public_value=alpha.parameter_value,
                            divergence_pct=div_pct,
                            whale_count=unique_wallets,
                            historical_accuracy=self._get_historical_accuracy(alpha.name),
                        ))

            elif alpha.parameter_name == "min_liquidity":
                # Check if whales trade in lower-liquidity markets
                whale_liqs = [
                    t["market_liquidity"] for t in recent_trades
                    if t["market_liquidity"] > 0
                ]
                if len(whale_liqs) < self.min_whale_count:
                    continue
                avg_whale_liq = sum(whale_liqs) / len(whale_liqs)
                if avg_whale_liq < alpha.parameter_value:
                    div_pct = (alpha.parameter_value - avg_whale_liq) / alpha.parameter_value
                    if div_pct >= self.min_divergence_pct:
                        unique_wallets = len(set(
                            t["wallet"] for t in recent_trades
                            if t["market_liquidity"] > 0
                        ))
                        signals.append(DivergenceSignal(
                            alpha=alpha,
                            whale_value=avg_whale_liq,
                            public_value=alpha.parameter_value,
                            divergence_pct=div_pct,
                            whale_count=unique_wallets,
                            historical_accuracy=self._get_historical_accuracy(alpha.name),
                        ))

        return signals

    def _detect_volatility_divergence(
        self, recent_trades: List[dict],
    ) -> List[DivergenceSignal]:
        """Detect when whales trade INTO volatile markets that public alpha avoids."""
        signals = []
        vol_alphas = [a for a in self._public_alpha if a.category == "volatility"]

        for alpha in vol_alphas:
            # Count whales trading in high-volatility markets
            high_vol_trades = [
                t for t in recent_trades
                if t["market_volatility"] > alpha.parameter_value
            ]
            if len(high_vol_trades) < self.min_whale_count:
                continue

            unique_wallets = len(set(t["wallet"] for t in high_vol_trades))
            if unique_wallets < self.min_whale_count:
                continue

            avg_vol = sum(t["market_volatility"] for t in high_vol_trades) / len(high_vol_trades)
            div_pct = (avg_vol - alpha.parameter_value) / alpha.parameter_value

            if div_pct >= self.min_divergence_pct:
                signals.append(DivergenceSignal(
                    alpha=alpha,
                    whale_value=avg_vol,
                    public_value=alpha.parameter_value,
                    divergence_pct=div_pct,
                    whale_count=unique_wallets,
                    historical_accuracy=self._get_historical_accuracy(alpha.name),
                ))

        return signals

    def _detect_timing_divergence(
        self, recent_trades: List[dict],
    ) -> List[DivergenceSignal]:
        """Detect when whales use different sizing/compounding than public alpha."""
        signals = []
        timing_alphas = [a for a in self._public_alpha if a.category == "timing"]

        for alpha in timing_alphas:
            if alpha.parameter_name == "compound_rate":
                # Check if whales compound at higher rates
                whale_edges = [
                    t["edge_estimate"] for t in recent_trades
                    if t["edge_estimate"] > 0
                ]
                if len(whale_edges) < self.min_whale_count:
                    continue
                avg_edge = sum(whale_edges) / len(whale_edges)
                if avg_edge > alpha.parameter_value:
                    div_pct = (avg_edge - alpha.parameter_value) / alpha.parameter_value
                    if div_pct >= self.min_divergence_pct:
                        unique_wallets = len(set(
                            t["wallet"] for t in recent_trades
                            if t["edge_estimate"] > 0
                        ))
                        signals.append(DivergenceSignal(
                            alpha=alpha,
                            whale_value=avg_edge,
                            public_value=alpha.parameter_value,
                            divergence_pct=div_pct,
                            whale_count=unique_wallets,
                            historical_accuracy=self._get_historical_accuracy(alpha.name),
                        ))

        return signals

    def _compute_confidence(self, signal: DivergenceSignal) -> float:
        """
        Compute confidence score for a divergence signal.

        Based on:
        1. Number of whales diverging (more = higher confidence)
        2. Historical accuracy of this divergence type
        3. Magnitude of divergence (larger = higher confidence, with diminishing returns)
        """
        # Whale count factor: [0.3, 0.9] based on 2-10 whales
        whale_factor = min(0.3 + 0.1 * signal.whale_count, 0.9)

        # Historical accuracy factor
        accuracy_factor = signal.historical_accuracy

        # Divergence magnitude factor (diminishing returns)
        magnitude_factor = min(0.5 + 0.5 * math.tanh(signal.divergence_pct), 0.95)

        # Weighted combination
        confidence = 0.40 * whale_factor + 0.35 * accuracy_factor + 0.25 * magnitude_factor
        return max(0.0, min(confidence, 0.95))

    def scan(self, markets: List[Market]) -> List[ScanResult]:
        """
        Scan for divergence between whale behavior and public alpha.

        Analyzes recent whale trades against each public alpha pattern.
        When divergence is detected, generates signals aligned with whale
        behavior rather than public recommendations.
        """
        results = []

        # Get recent trades (last 4 hours)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=4)
        recent_trades = [
            t for t in self._whale_trades
            if t["timestamp"] > cutoff
        ]

        if len(recent_trades) < self.min_whale_count:
            logger.debug(
                f"[wallet_divergence] Insufficient recent trades: "
                f"{len(recent_trades)} < {self.min_whale_count}"
            )
            return results

        # Detect all divergence types
        all_signals: List[DivergenceSignal] = []
        all_signals.extend(self._detect_threshold_divergence(recent_trades))
        all_signals.extend(self._detect_volatility_divergence(recent_trades))
        all_signals.extend(self._detect_timing_divergence(recent_trades))

        if not all_signals:
            return results

        # Store for history
        self._divergence_history.extend(all_signals)
        if len(self._divergence_history) > 500:
            self._divergence_history = self._divergence_history[-500:]

        # Convert divergence signals into trade signals
        # Group recent whale trades by market to find specific trade opportunities
        market_lookup = {m.id: m for m in markets if m.active and not m.closed}
        market_whale_trades: Dict[str, List[dict]] = defaultdict(list)
        for trade in recent_trades:
            if trade["market_id"] in market_lookup:
                market_whale_trades[trade["market_id"]].append(trade)

        for market_id, trades in market_whale_trades.items():
            market = market_lookup[market_id]
            if len(trades) < self.min_whale_count:
                continue

            # Determine whale consensus direction
            buy_count = sum(1 for t in trades if t["side"] == "BUY")
            sell_count = len(trades) - buy_count

            if buy_count == sell_count:
                continue  # No consensus

            side = "BUY" if buy_count > sell_count else "SELL"
            consensus_trades = [t for t in trades if t["side"] == side]
            avg_price = sum(t["price"] for t in consensus_trades) / len(consensus_trades)
            avg_edge = sum(t["edge_estimate"] for t in consensus_trades) / len(consensus_trades)

            # Find which divergence signals apply to this market's context
            relevant_signals = []
            for sig in all_signals:
                if sig.alpha.category == "threshold" and avg_edge < sig.alpha.parameter_value:
                    relevant_signals.append(sig)
                elif sig.alpha.category == "volatility":
                    market_vol = max(t.get("market_volatility", 0) for t in trades)
                    if market_vol > sig.alpha.parameter_value:
                        relevant_signals.append(sig)
                elif sig.alpha.category == "timing":
                    relevant_signals.append(sig)

            if not relevant_signals:
                continue

            # Compute aggregate confidence from relevant signals
            best_signal = max(relevant_signals, key=lambda s: self._compute_confidence(s))
            confidence = self._compute_confidence(best_signal)
            edge = max(avg_edge, self.config.min_edge + 0.01)

            # Find the outcome index
            outcome_idx = 0
            if market.is_binary and side == "SELL":
                outcome_idx = 0
            elif market.is_binary:
                # Match by price proximity
                for i, o in enumerate(market.outcomes):
                    if abs(o.price - avg_price) < 0.10:
                        outcome_idx = i
                        break

            unique_wallets = len(set(t["wallet"] for t in consensus_trades))
            divergence_reasons = [
                f"{s.alpha.name}: whale={s.whale_value:.3f} vs public={s.public_value:.3f} "
                f"({s.divergence_pct:.0%} div)"
                for s in relevant_signals[:3]
            ]

            results.append(ScanResult(
                market=market,
                strategy=self.name,
                outcome_idx=outcome_idx,
                side=side,
                entry_price=avg_price,
                expected_value=avg_price + edge if side == "BUY" else avg_price - edge,
                edge=edge,
                confidence=confidence,
                reason=(
                    f"WHALE DIVERGENCE: {unique_wallets} whales {side} at "
                    f"${avg_price:.3f} against public alpha | "
                    f"{'; '.join(divergence_reasons)}"
                ),
            ))

        if results:
            logger.info(
                f"[wallet_divergence] {len(results)} divergence signals from "
                f"{len(recent_trades)} recent whale trades"
            )
        else:
            logger.info(
                f"[wallet_divergence] 0 signals ({len(all_signals)} divergences detected, "
                f"no actionable market opportunities)"
            )
        return results


# ================================================================
# Strategy 4: Adaptive Buy Signal Threshold
# ================================================================

@dataclass
class HorizonBucket:
    """Statistics for a single time-horizon bucket."""
    label: str              # "1d", "1w", "1m", "3m", "6m"
    min_hours: float        # Lower bound of bucket (inclusive)
    max_hours: float        # Upper bound of bucket (exclusive)
    returns: List[float] = field(default_factory=list)  # Historical returns
    mean_return: float = 0.0
    std_return: float = 0.0
    threshold: float = 0.0   # mean + 2 * std
    sample_count: int = 0

    def update_stats(self):
        """Recalculate mean, std, and threshold from return history."""
        self.sample_count = len(self.returns)
        if self.sample_count < 2:
            # Conservative defaults until enough data accumulates
            self.mean_return = 0.0
            self.std_return = 0.10  # Assume 10% std
            self.threshold = 0.20   # Conservative 20% threshold
            return

        self.mean_return = sum(self.returns) / self.sample_count
        variance = sum((r - self.mean_return) ** 2 for r in self.returns) / (self.sample_count - 1)
        self.std_return = math.sqrt(variance)

        # Threshold = mean + 2*sigma
        self.threshold = self.mean_return + 2.0 * self.std_return

        # Floor: never go below min_edge equivalent
        self.threshold = max(self.threshold, 0.03)


# Default time-horizon buckets.
_DEFAULT_BUCKETS = [
    HorizonBucket(label="1d", min_hours=0, max_hours=24),
    HorizonBucket(label="1w", min_hours=24, max_hours=168),
    HorizonBucket(label="1m", min_hours=168, max_hours=720),
    HorizonBucket(label="3m", min_hours=720, max_hours=2160),
    HorizonBucket(label="6m", min_hours=2160, max_hours=4380),
]


class AdaptiveBuySignalThreshold(BaseStrategy):
    """
    Dynamic buy signal thresholding per time horizon.

    A 1-day contract and a 6-month contract don't play by the same rules.
    Without adaptive thresholds, the model buys everything that looks slightly
    positive.  This strategy wraps other strategies' scan results and filters
    them through per-horizon thresholds.

    For each contract duration bucket (1-day, 1-week, 1-month, 3-month,
    6-month), maintains separate statistics:
        threshold = mean_return + 2 * std_return

    New contracts get a conservative default threshold (20%) until enough
    data accumulates (minimum 10 observations).

    Usage:
        # Wrap other strategies
        adaptive = AdaptiveBuySignalThreshold(client, config)
        adaptive.add_inner_strategy(near_certainty)
        adaptive.add_inner_strategy(cross_market_arb)

        # Scan returns only opportunities that pass adaptive thresholds
        results = adaptive.scan(markets)

        # After trade resolution, feed back results
        adaptive.record_return(market_id, return_pct, hours_to_resolution)
    """

    def __init__(
        self,
        client: PolymarketClient,
        config: StrategyConfig,
        min_observations: int = 10,   # Min data points before trusting stats
        sigma_multiplier: float = 2.0,  # Number of std devs above mean
        default_threshold: float = 0.20,  # Default until enough data
        buckets: Optional[List[HorizonBucket]] = None,
    ):
        super().__init__(client, config)
        self.min_observations = min_observations
        self.sigma_multiplier = sigma_multiplier
        self.default_threshold = default_threshold
        self._buckets = [
            HorizonBucket(
                label=b.label,
                min_hours=b.min_hours,
                max_hours=b.max_hours,
            )
            for b in (buckets or _DEFAULT_BUCKETS)
        ]
        self._inner_strategies: List[BaseStrategy] = []
        # Track which markets we've already seen, to avoid duplicate signals
        self._seen_market_ids: Set[str] = set()

    @property
    def name(self) -> str:
        return "adaptive_threshold"

    def add_inner_strategy(self, strategy: BaseStrategy):
        """Add a strategy whose results will be filtered through adaptive thresholds."""
        self._inner_strategies.append(strategy)
        logger.info(
            f"[adaptive_threshold] Wrapping strategy: {strategy.name}"
        )

    def _get_bucket(self, hours_to_resolution: float) -> Optional[HorizonBucket]:
        """Find the time-horizon bucket for a given duration."""
        for bucket in self._buckets:
            if bucket.min_hours <= hours_to_resolution < bucket.max_hours:
                return bucket
        # Beyond 6 months — use the last bucket
        if hours_to_resolution >= self._buckets[-1].max_hours:
            return self._buckets[-1]
        return None

    def get_threshold(self, hours_to_resolution: float) -> float:
        """
        Get the entry threshold for a given time horizon.

        Returns the adaptive threshold if enough data has accumulated,
        otherwise the conservative default.
        """
        bucket = self._get_bucket(hours_to_resolution)
        if bucket is None:
            return self.default_threshold

        if bucket.sample_count < self.min_observations:
            return self.default_threshold

        return bucket.threshold

    def record_return(
        self,
        market_id: str,
        return_pct: float,
        hours_to_resolution: float,
    ):
        """
        Record a realized return for updating bucket statistics.

        Called when a trade resolves.  The return updates the relevant
        time-horizon bucket's statistics and adjusts the threshold.

        Args:
            market_id: Market identifier
            return_pct: Realized return as decimal (e.g., 0.05 = 5%)
            hours_to_resolution: How long the contract lasted
        """
        bucket = self._get_bucket(hours_to_resolution)
        if bucket is None:
            logger.debug(
                f"[adaptive_threshold] No bucket for {hours_to_resolution:.0f}h, "
                f"skipping return record"
            )
            return

        bucket.returns.append(return_pct)

        # Keep last 500 observations per bucket to prevent stale data
        if len(bucket.returns) > 500:
            bucket.returns = bucket.returns[-500:]

        bucket.update_stats()

        logger.debug(
            f"[adaptive_threshold] Recorded return {return_pct:.1%} in bucket "
            f"{bucket.label} (n={bucket.sample_count}, "
            f"threshold={bucket.threshold:.1%})"
        )

    def get_bucket_stats(self) -> List[dict]:
        """Get statistics for all time-horizon buckets."""
        return [
            {
                "label": b.label,
                "min_hours": b.min_hours,
                "max_hours": b.max_hours,
                "sample_count": b.sample_count,
                "mean_return": b.mean_return,
                "std_return": b.std_return,
                "threshold": b.threshold,
            }
            for b in self._buckets
        ]

    def scan(self, markets: List[Market]) -> List[ScanResult]:
        """
        Scan markets through inner strategies, then filter via adaptive thresholds.

        1. Run all inner strategies to get candidate opportunities.
        2. For each opportunity, determine the contract's time horizon.
        3. Only pass through opportunities whose edge exceeds the adaptive
           threshold for that horizon bucket.
        """
        results = []
        now = datetime.now(timezone.utc)

        if not self._inner_strategies:
            logger.warning("[adaptive_threshold] No inner strategies configured")
            return results

        # Collect candidates from all inner strategies
        all_candidates: List[ScanResult] = []
        for strategy in self._inner_strategies:
            try:
                candidates = strategy.scan(markets)
                all_candidates.extend(candidates)
            except Exception as e:
                logger.error(
                    f"[adaptive_threshold] Inner strategy {strategy.name} failed: {e}"
                )

        if not all_candidates:
            return results

        # Filter through adaptive thresholds
        passed = 0
        filtered = 0
        no_end_date = 0

        for candidate in all_candidates:
            market = candidate.market

            # Determine time horizon
            if market.end_date:
                hours_left = (market.end_date - now).total_seconds() / 3600
                if hours_left < 0:
                    filtered += 1
                    continue
            else:
                # No end date — use default threshold
                hours_left = 720.0  # Assume 30 days
                no_end_date += 1

            threshold = self.get_threshold(hours_left)

            if candidate.edge >= threshold:
                # Rewrite strategy name to show it passed adaptive filtering
                results.append(ScanResult(
                    market=candidate.market,
                    strategy=self.name,
                    outcome_idx=candidate.outcome_idx,
                    side=candidate.side,
                    entry_price=candidate.entry_price,
                    expected_value=candidate.expected_value,
                    edge=candidate.edge,
                    confidence=candidate.confidence,
                    reason=(
                        f"[{candidate.strategy}→adaptive] {candidate.reason} | "
                        f"threshold={threshold:.1%} "
                        f"(bucket={self._get_bucket(hours_left).label if self._get_bucket(hours_left) else '?'}, "
                        f"edge={candidate.edge:.1%})"
                    ),
                ))
                passed += 1
            else:
                filtered += 1

        logger.info(
            f"[adaptive_threshold] {passed} passed / {filtered} filtered "
            f"from {len(all_candidates)} candidates "
            f"({len(self._inner_strategies)} inner strategies, "
            f"{no_end_date} missing end dates)"
        )

        # Log bucket stats periodically
        for bucket in self._buckets:
            if bucket.sample_count > 0:
                logger.debug(
                    f"[adaptive_threshold] Bucket {bucket.label}: "
                    f"n={bucket.sample_count}, mean={bucket.mean_return:.1%}, "
                    f"std={bucket.std_return:.1%}, threshold={bucket.threshold:.1%}"
                )

        return results
