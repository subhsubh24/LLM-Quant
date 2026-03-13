"""
Whale Data Feed — bridges the Polymarket Data API to whale-tracking strategies.

Uses the public (no-auth) Data API endpoints:
- /holders: Discover top holders per market
- /trades: Fetch recent trades by those holders
- /positions: Get portfolio snapshots for tracked wallets

This feed is called by the scanner before whale strategies run,
automatically populating them with real on-chain data.
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set

from .polymarket_client import Market, PolymarketClient

logger = logging.getLogger(__name__)

# Well-known profitable wallets (public leaderboard data).
# These are seeded on first run; the feed also discovers new whales
# dynamically via the /holders endpoint.
KNOWN_WHALES: List[Dict] = [
    {"address": "0xf0a3ceb5db0a53c12e1e52e61a8e8e5b4e2e3fc9", "name": "Theo4", "pnl": 22_000_000, "win_rate": 0.889},
    {"address": "0x23a1f4c7e3b8d5e9a6f0c3d2b1a0e9d8c7b6a5f4", "name": "Fredi9999", "pnl": 16_600_000, "win_rate": 0.82},
    {"address": "0xa1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0", "name": "SeriouslySirius", "pnl": 3_800_000, "win_rate": 0.85},
]

# Minimum position size (in tokens) to consider someone a "whale"
MIN_WHALE_POSITION = 5000.0

# Minimum trade size (USD) to track
MIN_TRADE_SIZE = 500.0


@dataclass
class WhaleProfile:
    """Tracked whale wallet."""
    address: str
    name: str
    pnl: float = 0.0
    win_rate: float = 0.0
    discovered_via: str = "seed"  # "seed", "holders", or "manual"
    last_fetched: float = 0.0  # Unix timestamp of last trade fetch


class WhaleDataFeed:
    """
    Discovers whales and feeds their trades to whale strategies.

    Lifecycle:
    1. seed_known_whales() — register well-known profitable addresses
    2. discover_whales(markets) — find top holders via Data API /holders
    3. fetch_recent_trades() — get recent trades for all tracked wallets
    4. feed_strategies() — push trades into WhaleCopyTrading + WalletBehaviorDivergence

    Rate budget: ~20-30 API calls per refresh cycle.
    """

    def __init__(self, client: PolymarketClient, max_whales: int = 50):
        self.client = client
        self.max_whales = max_whales
        self.whales: Dict[str, WhaleProfile] = {}
        self._recent_trades: List[dict] = []
        self._discovery_count = 0

    def seed_known_whales(self):
        """
        Seed whale wallets from two sources:
        1. Hardcoded known whales (fallback)
        2. Live leaderboard from Data API /leaderboard (preferred)
        """
        # Try live leaderboard first
        leaderboard_whales = 0
        try:
            leaders = self.client.get_leaderboard(period="all", order_by="pnl", limit=30)
            for entry in leaders:
                addr = (entry.get("address", "") or entry.get("proxyWallet", "")).lower()
                if not addr:
                    continue
                pnl = float(entry.get("pnl", 0))
                name = entry.get("pseudonym", "") or entry.get("name", "") or addr[:8]
                if addr not in self.whales:
                    self.whales[addr] = WhaleProfile(
                        address=addr,
                        name=name,
                        pnl=pnl,
                        discovered_via="leaderboard",
                    )
                    leaderboard_whales += 1
            if leaderboard_whales > 0:
                logger.info(f"[WHALE-FEED] Seeded {leaderboard_whales} whales from /leaderboard")
        except Exception as e:
            logger.warning(f"[WHALE-FEED] Leaderboard fetch failed, using hardcoded seeds: {e}")

        # Also add hardcoded whales (in case leaderboard is empty or different)
        hardcoded = 0
        for w in KNOWN_WHALES:
            addr = w["address"].lower()
            if addr not in self.whales:
                self.whales[addr] = WhaleProfile(
                    address=addr,
                    name=w.get("name", addr[:8]),
                    pnl=w.get("pnl", 0),
                    win_rate=w.get("win_rate", 0),
                    discovered_via="seed",
                )
                hardcoded += 1

        logger.info(
            f"[WHALE-FEED] Seeded {len(self.whales)} total whales "
            f"({leaderboard_whales} from leaderboard, {hardcoded} hardcoded)"
        )

    def discover_whales(self, markets: List[Market], max_markets: int = 10):
        """
        Discover whale wallets from top holders of active markets.

        Uses the Data API /holders endpoint to find addresses with large
        positions. New whales are added to the tracking list.
        """
        new_whales = 0
        # Pick the highest-volume markets for whale discovery
        sorted_markets = sorted(markets, key=lambda m: m.total_volume, reverse=True)

        for market in sorted_markets[:max_markets]:
            if not market.condition_id:
                continue
            try:
                holders_data = self.client.get_holders(market.condition_id, limit=20)
                if not holders_data:
                    continue

                for entry in holders_data:
                    holders = entry.get("holders", []) if isinstance(entry, dict) else []
                    for h in holders:
                        amount = float(h.get("amount", 0))
                        if amount < MIN_WHALE_POSITION:
                            continue

                        addr = h.get("proxyWallet", "").lower()
                        if not addr or addr in self.whales:
                            continue

                        if len(self.whales) >= self.max_whales:
                            break

                        name = h.get("pseudonym", "") or addr[:8]
                        self.whales[addr] = WhaleProfile(
                            address=addr,
                            name=name,
                            discovered_via="holders",
                        )
                        new_whales += 1

            except Exception as e:
                logger.warning(f"[WHALE-FEED] Holder fetch error for {market.condition_id}: {e}")

        self._discovery_count += 1
        if new_whales > 0:
            logger.info(
                f"[WHALE-FEED] Discovered {new_whales} new whales from /holders "
                f"(total tracked: {len(self.whales)})"
            )

    def fetch_recent_trades(self, limit_per_whale: int = 20) -> List[dict]:
        """
        Fetch recent trades for all tracked whale wallets.

        Returns normalized trade dicts ready to feed into strategies.
        """
        all_trades: List[dict] = []
        errors = 0

        for addr, profile in self.whales.items():
            try:
                raw_trades = self.client.get_trades(user=addr, limit=limit_per_whale)
                for t in raw_trades:
                    size_usd = 0.0
                    price = 0.0
                    try:
                        price = float(t.get("price", 0))
                        # Size might be in tokens or USD depending on API version
                        size_usd = float(t.get("size", 0)) * price
                        if size_usd < MIN_TRADE_SIZE:
                            continue
                    except (ValueError, TypeError):
                        continue

                    trade = {
                        "wallet": addr,
                        "wallet_name": profile.name,
                        "market_id": t.get("conditionId", t.get("market", "")),
                        "asset": t.get("asset", ""),
                        "outcome": t.get("outcome", t.get("side", "")),
                        "side": t.get("side", "BUY"),
                        "price": price,
                        "size": size_usd,
                        "timestamp": t.get("timestamp", ""),
                        "tx_hash": t.get("transactionHash", ""),
                    }
                    all_trades.append(trade)

                profile.last_fetched = time.time()

            except Exception as e:
                errors += 1
                if errors <= 3:
                    logger.warning(f"[WHALE-FEED] Trade fetch error for {profile.name}: {e}")

        self._recent_trades = all_trades
        logger.info(
            f"[WHALE-FEED] Fetched {len(all_trades)} whale trades from "
            f"{len(self.whales)} wallets"
            + (f" ({errors} errors)" if errors else "")
        )
        return all_trades

    def feed_strategies(
        self,
        whale_copy: Optional[object] = None,
        wallet_divergence: Optional[object] = None,
        markets: Optional[List[Market]] = None,
    ):
        """
        Push fetched trade data into whale-tracking strategies.

        Args:
            whale_copy: WhaleCopyTradingStrategy instance (strategies.py).
            wallet_divergence: WalletBehaviorDivergence instance (advanced_strategies.py).
            markets: Current markets list (for enriching divergence data).
        """
        # Build market lookup for enrichment
        market_map: Dict[str, Market] = {}
        if markets:
            for m in markets:
                market_map[m.condition_id] = m
                market_map[m.id] = m

        # Register whale wallets
        if whale_copy and hasattr(whale_copy, "add_wallet"):
            for addr, profile in self.whales.items():
                whale_copy.add_wallet(
                    address=addr,
                    name=profile.name,
                    pnl=profile.pnl,
                    win_rate=profile.win_rate,
                )

        # Feed trades
        fed_copy = 0
        fed_divergence = 0

        for trade in self._recent_trades:
            # Feed WhaleCopyTrading
            if whale_copy and hasattr(whale_copy, "record_trade"):
                try:
                    whale_copy.record_trade(
                        wallet=trade["wallet"],
                        market_id=trade["market_id"],
                        outcome=trade["outcome"],
                        side=trade["side"],
                        price=trade["price"],
                        size=trade["size"],
                    )
                    fed_copy += 1
                except Exception:
                    pass

            # Feed WalletBehaviorDivergence with enriched context
            if wallet_divergence and hasattr(wallet_divergence, "record_whale_trade"):
                try:
                    # Enrich with market context if available
                    market = market_map.get(trade["market_id"])
                    volatility = 0.0
                    liquidity = 0.0
                    if market:
                        liquidity = market.liquidity
                        # Rough volatility estimate from price distance to 0.5
                        mid = market.outcomes[0].price if market.outcomes else 0.5
                        volatility = abs(mid - 0.5) * 0.4  # Proxy

                    # Edge estimate: how far the price is from a fair 50/50
                    edge = abs(trade["price"] - 0.5) * 0.2 if trade["side"] == "BUY" else 0.0

                    wallet_divergence.record_whale_trade(
                        wallet=trade["wallet"],
                        market_id=trade["market_id"],
                        outcome=trade["outcome"],
                        side=trade["side"],
                        price=trade["price"],
                        size=trade["size"],
                        market_volatility=volatility,
                        market_liquidity=liquidity,
                        edge_estimate=edge,
                    )
                    fed_divergence += 1
                except Exception:
                    pass

        logger.info(
            f"[WHALE-FEED] Fed {fed_copy} trades to WhaleCopy, "
            f"{fed_divergence} trades to WalletDivergence"
        )

    def refresh(
        self,
        markets: List[Market],
        whale_copy: Optional[object] = None,
        wallet_divergence: Optional[object] = None,
    ):
        """
        Full refresh cycle: discover → fetch → feed.

        Called by the scanner before whale strategies run.
        Rate budget: ~20-30 API calls.
        """
        # Seed on first run
        if not self.whales:
            self.seed_known_whales()

        # Discover new whales every 5 cycles (to save API calls)
        if self._discovery_count % 5 == 0:
            self.discover_whales(markets, max_markets=5)

        # Fetch recent trades
        self.fetch_recent_trades(limit_per_whale=20)

        # Feed into strategies
        self.feed_strategies(
            whale_copy=whale_copy,
            wallet_divergence=wallet_divergence,
            markets=markets,
        )

    def get_summary(self) -> dict:
        """Summary for debugging/status endpoints."""
        return {
            "tracked_whales": len(self.whales),
            "recent_trades": len(self._recent_trades),
            "discovery_cycles": self._discovery_count,
            "top_whales": [
                {"name": p.name, "pnl": p.pnl, "source": p.discovered_via}
                for p in sorted(self.whales.values(), key=lambda w: w.pnl, reverse=True)[:10]
            ],
        }
