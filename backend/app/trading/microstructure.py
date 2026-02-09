"""
Market Microstructure Analysis Module

Extracts institutional-level trading signals from order book and volume data:
- Bid-ask spreads (liquidity)
- Order book imbalance (buy/sell pressure)
- Large order detection (whale activity)
- Volume at price levels (support/resistance)
- Order flow imbalance (buying vs selling pressure)
- Market depth analysis

This is what Renaissance Technologies actually uses for alpha generation.
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class OrderBook:
    """Order book snapshot"""
    bids: List[Tuple[float, float]]  # [(price, size), ...]
    asks: List[Tuple[float, float]]  # [(price, size), ...]
    timestamp: float


class MicrostructureExtractor:
    """
    Extract microstructure features from order book data.

    Features extracted:
    1. Bid-Ask Spread - liquidity indicator
    2. Order Book Imbalance - buy vs sell pressure
    3. Order Book Depth - market depth at each level
    4. Volume Imbalance - unusual volume patterns
    5. Large Order Presence - whale activity
    6. Order Flow - institutional buying/selling
    """

    def __init__(self, lookback: int = 20):
        """
        Initialize microstructure extractor.

        Args:
            lookback: Number of previous candles to use for analysis
        """
        self.lookback = lookback
        self.order_book_history: List[OrderBook] = []

    def add_order_book(self, order_book: OrderBook):
        """Add order book snapshot to history."""
        self.order_book_history.append(order_book)
        # Keep only recent history
        if len(self.order_book_history) > self.lookback * 2:
            self.order_book_history = self.order_book_history[-self.lookback * 2:]

    def extract_features(self) -> Dict[str, float]:
        """
        Extract all microstructure features from current order book.

        Returns:
            Dictionary of feature values
        """
        if not self.order_book_history:
            return self._empty_features()

        current_ob = self.order_book_history[-1]
        features = {}

        # 1. Bid-Ask Spread
        features["bid_ask_spread"] = self._calculate_spread(current_ob)
        features["spread_bps"] = features["bid_ask_spread"] * 10000  # In basis points

        # 2. Order Book Imbalance
        features["ob_imbalance"] = self._calculate_ob_imbalance(current_ob)

        # 3. Order Book Depth
        depth_features = self._calculate_depth_features(current_ob)
        features.update(depth_features)

        # 4. Volume Imbalance
        vol_features = self._calculate_volume_imbalance()
        features.update(vol_features)

        # 5. Large Order Detection
        features["large_buy_presence"] = self._detect_large_orders(current_ob, side="bid")
        features["large_sell_presence"] = self._detect_large_orders(current_ob, side="ask")

        # 6. Order Flow
        features["order_flow_imbalance"] = self._calculate_order_flow()

        return features

    def _calculate_spread(self, ob: OrderBook) -> float:
        """Calculate bid-ask spread as percentage."""
        if not ob.bids or not ob.asks:
            return 0.0

        best_bid = ob.bids[0][0]
        best_ask = ob.asks[0][0]
        mid = (best_bid + best_ask) / 2

        spread = (best_ask - best_bid) / mid if mid > 0 else 0
        return max(0, spread)  # Spread can't be negative

    def _calculate_ob_imbalance(self, ob: OrderBook) -> float:
        """
        Calculate order book imbalance (buy vs sell pressure).

        Positive = more buy volume
        Negative = more sell volume
        """
        if not ob.bids or not ob.asks:
            return 0.0

        # Top 5 levels on each side
        bid_volume = sum(size for _, size in ob.bids[:5])
        ask_volume = sum(size for _, size in ob.asks[:5])

        total = bid_volume + ask_volume
        if total == 0:
            return 0.0

        # Normalized: -1 to +1 scale
        imbalance = (bid_volume - ask_volume) / total
        return np.clip(imbalance, -1, 1)

    def _calculate_depth_features(self, ob: OrderBook) -> Dict[str, float]:
        """Calculate order book depth features."""
        features = {}

        if ob.bids and ob.asks:
            # Cumulative volume at different levels
            bid_depth_5 = sum(size for _, size in ob.bids[:5])
            ask_depth_5 = sum(size for _, size in ob.asks[:5])
            bid_depth_10 = sum(size for _, size in ob.bids[:10])
            ask_depth_10 = sum(size for _, size in ob.asks[:10])

            features["bid_depth_5"] = bid_depth_5
            features["ask_depth_5"] = ask_depth_5
            features["bid_depth_10"] = bid_depth_10
            features["ask_depth_10"] = ask_depth_10

            # Depth imbalance
            total_depth = bid_depth_5 + ask_depth_5
            if total_depth > 0:
                features["depth_imbalance_5"] = (bid_depth_5 - ask_depth_5) / total_depth
            else:
                features["depth_imbalance_5"] = 0
        else:
            features["bid_depth_5"] = 0
            features["ask_depth_5"] = 0
            features["bid_depth_10"] = 0
            features["ask_depth_10"] = 0
            features["depth_imbalance_5"] = 0

        return features

    def _calculate_volume_imbalance(self) -> Dict[str, float]:
        """Calculate volume imbalance from recent order books."""
        features = {}

        if len(self.order_book_history) < 2:
            return {
                "volume_imbalance_recent": 0.0,
                "volume_trend": 0.0,
            }

        recent_obs = self.order_book_history[-5:]  # Last 5 snapshots

        # Calculate volume imbalance for each snapshot
        imbalances = []
        for ob in recent_obs:
            imb = self._calculate_ob_imbalance(ob)
            imbalances.append(imb)

        # Average recent imbalance
        features["volume_imbalance_recent"] = np.mean(imbalances)

        # Trend (is imbalance increasing or decreasing?)
        if len(imbalances) >= 2:
            features["volume_trend"] = imbalances[-1] - imbalances[0]
        else:
            features["volume_trend"] = 0.0

        return features

    def _detect_large_orders(self, ob: OrderBook, side: str = "bid") -> float:
        """
        Detect presence of large orders (whale activity).

        Returns: 0-1 score indicating likelihood of large order
        """
        levels = ob.bids if side == "bid" else ob.asks

        if not levels:
            return 0.0

        sizes = [size for _, size in levels[:10]]
        if not sizes:
            return 0.0

        # If one order is >3x median, likely a large order
        median_size = np.median(sizes)
        max_size = np.max(sizes)

        if median_size == 0:
            return 0.0

        size_ratio = max_size / median_size
        # Scale: 3x = 0.5, 5x = 0.8, 10x = 1.0
        return min(1.0, max(0, (size_ratio - 3) / 7))

    def _calculate_order_flow(self) -> float:
        """
        Calculate order flow imbalance from price and volume.

        Positive = buying pressure
        Negative = selling pressure
        """
        if len(self.order_book_history) < 2:
            return 0.0

        recent_obs = self.order_book_history[-5:]

        flow = 0.0
        for i in range(1, len(recent_obs)):
            prev_ob = recent_obs[i - 1]
            curr_ob = recent_obs[i]

            if prev_ob.bids and curr_ob.bids and prev_ob.asks and curr_ob.asks:
                # If bid side grew more than ask side, it's buying pressure
                prev_bid_vol = sum(size for _, size in prev_ob.bids[:5])
                curr_bid_vol = sum(size for _, size in curr_ob.bids[:5])
                prev_ask_vol = sum(size for _, size in prev_ob.asks[:5])
                curr_ask_vol = sum(size for _, size in curr_ob.asks[:5])

                bid_growth = curr_bid_vol - prev_bid_vol
                ask_growth = curr_ask_vol - prev_ask_vol

                flow += bid_growth - ask_growth

        return np.tanh(flow / 1000) if flow != 0 else 0.0  # Normalize to -1 to 1

    def _empty_features(self) -> Dict[str, float]:
        """Return empty feature dictionary."""
        return {
            "bid_ask_spread": 0.0,
            "spread_bps": 0.0,
            "ob_imbalance": 0.0,
            "bid_depth_5": 0.0,
            "ask_depth_5": 0.0,
            "bid_depth_10": 0.0,
            "ask_depth_10": 0.0,
            "depth_imbalance_5": 0.0,
            "volume_imbalance_recent": 0.0,
            "volume_trend": 0.0,
            "large_buy_presence": 0.0,
            "large_sell_presence": 0.0,
            "order_flow_imbalance": 0.0,
        }


class OrderBookFetcher:
    """
    Fetch real-time order book data from exchanges.

    Supports: Binance, Coinbase, Kraken
    """

    def __init__(self, exchange: str = "binance"):
        """
        Initialize order book fetcher.

        Args:
            exchange: 'binance', 'binance_us', 'coinbase', or 'kraken'
        """
        self.exchange = exchange.lower()
        self.session = None

    async def fetch_order_book(
        self, symbol: str, depth: int = 20
    ) -> Optional[OrderBook]:
        """
        Fetch order book for symbol.

        Args:
            symbol: Trading symbol (e.g., 'BTC/USD')
            depth: Order book depth (5, 10, 20, 50, etc.)

        Returns:
            OrderBook object or None if fetch fails
        """
        try:
            if self.exchange in ("binance", "binance_us"):
                return await self._fetch_binance(symbol, depth, is_us=self.exchange == "binance_us")
            elif self.exchange == "coinbase":
                return await self._fetch_coinbase(symbol, depth)
            elif self.exchange == "kraken":
                return await self._fetch_kraken(symbol, depth)
            else:
                logger.error(f"Unknown exchange: {self.exchange}")
                return None
        except Exception as e:
            logger.warning(f"Failed to fetch order book for {symbol}: {e}")
            return None

    async def _fetch_binance(self, symbol: str, depth: int, is_us: bool = False) -> Optional[OrderBook]:
        """Fetch from Binance or Binance US."""
        try:
            import aiohttp
            from datetime import datetime

            # Convert symbol format (BTC/USD -> BTCUSDT)
            symbol = symbol.replace("/", "").upper()
            if not symbol.endswith(("USDT", "BUSD", "USDC")):
                symbol += "USDT"

            # Use Binance US endpoint if requested, otherwise use global Binance
            api_domain = "api.binance.us" if is_us else "api.binance.com"
            url = f"https://{api_domain}/api/v3/depth?symbol={symbol}&limit={depth}"

            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=5) as resp:
                    if resp.status == 200:
                        data = await resp.json()

                        bids = [
                            (float(price), float(qty))
                            for price, qty in data["bids"][:depth]
                        ]
                        asks = [
                            (float(price), float(qty))
                            for price, qty in data["asks"][:depth]
                        ]

                        return OrderBook(
                            bids=bids,
                            asks=asks,
                            timestamp=datetime.now().timestamp(),
                        )
        except Exception as e:
            logger.debug(f"Binance fetch error: {e}")
            return None

    async def _fetch_coinbase(self, symbol: str, depth: int) -> Optional[OrderBook]:
        """Fetch from Coinbase."""
        try:
            import aiohttp
            from datetime import datetime

            # Convert symbol format (BTC/USD stays same)
            symbol = symbol.replace("/", "-").upper()

            url = f"https://api.exchange.coinbase.com/products/{symbol}/book?level=2"

            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=5) as resp:
                    if resp.status == 200:
                        data = await resp.json()

                        bids = [
                            (float(price), float(qty))
                            for price, qty in data["bids"][:depth]
                        ]
                        asks = [
                            (float(price), float(qty))
                            for price, qty in data["asks"][:depth]
                        ]

                        return OrderBook(
                            bids=bids,
                            asks=asks,
                            timestamp=datetime.now().timestamp(),
                        )
        except Exception as e:
            logger.debug(f"Coinbase fetch error: {e}")
            return None

    async def _fetch_kraken(self, symbol: str, depth: int) -> Optional[OrderBook]:
        """Fetch from Kraken."""
        try:
            import aiohttp
            from datetime import datetime

            # Convert symbol format for Kraken
            symbol = symbol.replace("/", "").upper()

            url = f"https://api.kraken.com/0/public/Depth?pair={symbol}&count={depth}"

            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=5) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        result = data.get("result", {})

                        # Find the symbol key in result
                        for key, value in result.items():
                            if "bids" in value and "asks" in value:
                                bids = [
                                    (float(price), float(qty))
                                    for price, qty in value["bids"][:depth]
                                ]
                                asks = [
                                    (float(price), float(qty))
                                    for price, qty in value["asks"][:depth]
                                ]

                                return OrderBook(
                                    bids=bids,
                                    asks=asks,
                                    timestamp=datetime.now().timestamp(),
                                )
        except Exception as e:
            logger.debug(f"Kraken fetch error: {e}")
            return None
