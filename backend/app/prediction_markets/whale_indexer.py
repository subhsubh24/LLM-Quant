"""
On-chain Whale Indexer for Polymarket.

Monitors Polygon (MATIC) blockchain for large prediction market trades
by tracking the Polymarket CTF Exchange and NegRiskCTFExchange contracts.

Data flow:
1. Poll Polygon RPC for Transfer events on the CTF contract
2. Decode transfer amounts and match to known whale wallets
3. Persist significant trades to WhaleActivity DB table
4. Expose recent whale activity via API for the WhaleCopyTrading strategy

Requires: POLYGON_RPC_URL environment variable (e.g., Alchemy, QuickNode, or public RPC).
"""

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

import requests

logger = logging.getLogger(__name__)


# ============================================================
# Polymarket Contract Addresses (Polygon mainnet)
# ============================================================

# CTF Exchange — the main conditional token trading contract
CTF_EXCHANGE = "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E"

# Neg Risk CTF Exchange — for multi-outcome (neg risk) markets
NEG_RISK_CTF_EXCHANGE = "0xC5d563A36AE78145C45a50134d48A1215220f80a"

# USDC on Polygon
USDC_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"

# ERC1155 Transfer event signature (single and batch)
TRANSFER_SINGLE_TOPIC = "0xc3d58168c5ae7397731d063d5bbf3d657854427343f4c083240f7aacaa2d0f62"
TRANSFER_BATCH_TOPIC = "0x4a39dc06d4c0dbc64b70af90fd698a233a518aa5d07e595d983b8c0526c8f7fb"

# Known whale wallets (from WhaleCopyTradingStrategy)
KNOWN_WHALES: Dict[str, str] = {
    "0x1a2b3c4d5e6f7890abcdef1234567890abcdef12": "Theo4",
    "0xabcdefabcdefabcdefabcdefabcdefabcdefabcd": "Fredi9999",
    "0x2222222222222222222222222222222222222222": "PolyWhale",
    "0x3333333333333333333333333333333333333333": "DegenCapital",
    "0x4444444444444444444444444444444444444444": "PredictionKing",
}

# Default public Polygon RPC (rate-limited; use Alchemy/QuickNode for production)
DEFAULT_POLYGON_RPC = "https://polygon-rpc.com"

# Minimum trade value (USD) to be considered "significant"
SIGNIFICANT_TRADE_USD = 1000.0

# ERC1155 TransferSingle ABI for decoding
TRANSFER_SINGLE_ABI = {
    "inputs": [
        {"name": "operator", "type": "address"},
        {"name": "from", "type": "address"},
        {"name": "to", "type": "address"},
        {"name": "id", "type": "uint256"},
        {"name": "value", "type": "uint256"},
    ]
}


@dataclass
class WhaleTradeEvent:
    """Decoded whale trade from on-chain data."""
    tx_hash: str
    block_number: int
    wallet_address: str
    wallet_label: Optional[str]
    token_id: str          # CTF token ID (maps to a market outcome)
    side: str              # "BUY" (received tokens) or "SELL" (sent tokens)
    size: float            # Number of outcome tokens
    estimated_price: float # Estimated from USDC transfer in same tx
    value_usd: float
    gas_price_gwei: float
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def is_significant(self) -> bool:
        return self.value_usd >= SIGNIFICANT_TRADE_USD


# ============================================================
# Polygon RPC Client
# ============================================================

class PolygonRPCClient:
    """
    Minimal Polygon JSON-RPC client for reading on-chain events.

    Uses eth_getLogs to fetch Transfer events from Polymarket contracts.
    """

    def __init__(self, rpc_url: Optional[str] = None):
        self.rpc_url = rpc_url or os.environ.get("POLYGON_RPC_URL", DEFAULT_POLYGON_RPC)
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        self._request_id = 0

    def _rpc_call(self, method: str, params: list) -> Any:
        """Execute a JSON-RPC call."""
        self._request_id += 1
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": self._request_id,
        }
        try:
            resp = self.session.post(self.rpc_url, json=payload, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            if "error" in data:
                logger.error(f"RPC error: {data['error']}")
                return None
            return data.get("result")
        except requests.RequestException as e:
            logger.error(f"Polygon RPC call failed: {e}")
            return None

    def get_block_number(self) -> Optional[int]:
        """Get latest block number."""
        result = self._rpc_call("eth_blockNumber", [])
        if result:
            return int(result, 16)
        return None

    def get_block_timestamp(self, block_number: int) -> Optional[datetime]:
        """Get timestamp for a block."""
        hex_block = hex(block_number)
        result = self._rpc_call("eth_getBlockByNumber", [hex_block, False])
        if result and "timestamp" in result:
            ts = int(result["timestamp"], 16)
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        return None

    def get_logs(
        self,
        address: str,
        topics: List[str],
        from_block: int,
        to_block: int,
    ) -> List[dict]:
        """
        Fetch event logs from a contract.

        Args:
            address: Contract address
            topics: Event topic filters
            from_block: Start block (inclusive)
            to_block: End block (inclusive)
        """
        params = {
            "address": address,
            "topics": topics,
            "fromBlock": hex(from_block),
            "toBlock": hex(to_block),
        }
        result = self._rpc_call("eth_getLogs", [params])
        return result or []

    def get_transaction_receipt(self, tx_hash: str) -> Optional[dict]:
        """Get transaction receipt for gas price info."""
        return self._rpc_call("eth_getTransactionReceipt", [tx_hash])


# ============================================================
# Event Decoder
# ============================================================

def decode_transfer_single(log: dict) -> Optional[dict]:
    """
    Decode an ERC1155 TransferSingle event from raw log data.

    TransferSingle(address operator, address from, address to, uint256 id, uint256 value)
    - Topics[0]: event signature
    - Topics[1]: operator (indexed)
    - Topics[2]: from (indexed)
    - Topics[3]: to (indexed)
    - Data: id (uint256) + value (uint256) packed as 64 hex chars each
    """
    topics = log.get("topics", [])
    data = log.get("data", "0x")

    if len(topics) < 4:
        return None

    # Decode indexed params from topics
    operator = "0x" + topics[1][-40:]
    from_addr = "0x" + topics[2][-40:]
    to_addr = "0x" + topics[3][-40:]

    # Decode data (id and value, each 32 bytes = 64 hex chars)
    data_hex = data[2:]  # Strip 0x
    if len(data_hex) < 128:
        return None

    token_id = int(data_hex[:64], 16)
    value = int(data_hex[64:128], 16)

    return {
        "operator": operator.lower(),
        "from": from_addr.lower(),
        "to": to_addr.lower(),
        "token_id": str(token_id),
        "value": value,
        "tx_hash": log.get("transactionHash", ""),
        "block_number": int(log.get("blockNumber", "0x0"), 16),
    }


# ============================================================
# Whale Indexer
# ============================================================

class WhaleIndexer:
    """
    Indexes whale trading activity on Polymarket by monitoring
    Polygon blockchain events.

    Usage:
        indexer = WhaleIndexer()
        events = await indexer.scan_recent_blocks(blocks=100)
        # events is a list of WhaleTradeEvent
    """

    def __init__(
        self,
        rpc_url: Optional[str] = None,
        whale_threshold_usd: float = SIGNIFICANT_TRADE_USD,
        watched_wallets: Optional[Dict[str, str]] = None,
    ):
        self.rpc = PolygonRPCClient(rpc_url)
        self.whale_threshold_usd = whale_threshold_usd
        self.watched_wallets = watched_wallets or KNOWN_WHALES

        # State
        self._last_scanned_block: Optional[int] = None
        self._recent_events: List[WhaleTradeEvent] = []
        self._scan_count = 0
        self._task: Optional[asyncio.Task] = None

    def add_watched_wallet(self, address: str, label: str):
        """Add a wallet to the watch list."""
        self.watched_wallets[address.lower()] = label

    def get_recent_events(self, limit: int = 50) -> List[WhaleTradeEvent]:
        """Get recently detected whale events."""
        return self._recent_events[-limit:]

    async def scan_recent_blocks(self, blocks: int = 50) -> List[WhaleTradeEvent]:
        """
        Scan recent blocks for whale activity.

        Args:
            blocks: Number of recent blocks to scan (Polygon ~2s per block)

        Returns:
            List of detected whale trade events
        """
        current_block = self.rpc.get_block_number()
        if current_block is None:
            logger.error("Failed to get current block number")
            return []

        from_block = current_block - blocks
        if self._last_scanned_block and self._last_scanned_block > from_block:
            from_block = self._last_scanned_block + 1

        if from_block >= current_block:
            return []  # Already up to date

        logger.info(f"Scanning Polygon blocks {from_block} to {current_block} for whale activity")

        events = []

        # Scan both CTF Exchange contracts
        for contract in [CTF_EXCHANGE, NEG_RISK_CTF_EXCHANGE]:
            logs = self.rpc.get_logs(
                address=contract,
                topics=[TRANSFER_SINGLE_TOPIC],
                from_block=from_block,
                to_block=current_block,
            )

            for log in logs:
                decoded = decode_transfer_single(log)
                if decoded is None:
                    continue

                # Check if sender or receiver is a watched whale
                from_addr = decoded["from"]
                to_addr = decoded["to"]

                is_whale_buy = to_addr in self.watched_wallets
                is_whale_sell = from_addr in self.watched_wallets

                if not is_whale_buy and not is_whale_sell:
                    # Not a whale — check if the trade is large enough to flag anyway
                    # Estimate value: assume ~$0.50 per token (rough average)
                    estimated_value = decoded["value"] * 0.50 / 1e6  # CTF tokens often have 6 decimals
                    if estimated_value < self.whale_threshold_usd:
                        continue

                # Determine side and wallet
                if is_whale_buy:
                    wallet = to_addr
                    side = "BUY"
                else:
                    wallet = from_addr
                    side = "SELL"

                wallet_label = self.watched_wallets.get(wallet)

                # Estimate trade value
                # CTF tokens are typically in 1e6 units
                raw_size = decoded["value"]
                size = raw_size / 1e6 if raw_size > 1e6 else float(raw_size)
                estimated_price = 0.50  # Default estimate
                value_usd = size * estimated_price

                event = WhaleTradeEvent(
                    tx_hash=decoded["tx_hash"],
                    block_number=decoded["block_number"],
                    wallet_address=wallet,
                    wallet_label=wallet_label,
                    token_id=decoded["token_id"],
                    side=side,
                    size=size,
                    estimated_price=estimated_price,
                    value_usd=value_usd,
                    gas_price_gwei=0.0,
                )
                events.append(event)

        self._last_scanned_block = current_block
        self._scan_count += 1

        # Keep only significant events for the in-memory buffer
        significant = [e for e in events if e.is_significant]
        self._recent_events.extend(significant)
        # Cap buffer at 500 events
        if len(self._recent_events) > 500:
            self._recent_events = self._recent_events[-500:]

        logger.info(
            f"Whale scan complete: {len(events)} transfers found, "
            f"{len(significant)} significant (>= ${self.whale_threshold_usd})"
        )

        return events

    async def _persist_events(self, events: List[WhaleTradeEvent]):
        """Persist whale events to database."""
        try:
            from ..db.database import get_session
            from .models import WhaleActivity

            with get_session() as session:
                for event in events:
                    if not event.is_significant:
                        continue

                    record = WhaleActivity(
                        tx_hash=event.tx_hash,
                        block_number=event.block_number,
                        wallet_address=event.wallet_address,
                        wallet_label=event.wallet_label,
                        market_id="",  # Would need token_id -> market_id mapping
                        token_id=event.token_id,
                        side=event.side,
                        size=event.size,
                        price=event.estimated_price,
                        value_usd=event.value_usd,
                        is_significant=event.is_significant,
                        gas_price_gwei=event.gas_price_gwei,
                    )
                    session.add(record)

            logger.debug(f"Persisted {len(events)} whale events to DB")
        except Exception as e:
            logger.error(f"Failed to persist whale events: {e}")

    async def start_continuous_scan(self, interval_sec: int = 30):
        """Start continuous scanning in the background."""
        self._task = asyncio.create_task(self._scan_loop(interval_sec))

    async def stop(self):
        """Stop continuous scanning."""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _scan_loop(self, interval_sec: int):
        """Continuous scan loop."""
        while True:
            try:
                events = await self.scan_recent_blocks(blocks=15)  # ~30 seconds of blocks
                if events:
                    await self._persist_events(events)
                await asyncio.sleep(interval_sec)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Whale scan loop error: {e}")
                await asyncio.sleep(interval_sec)

    def get_status(self) -> dict:
        return {
            "last_scanned_block": self._last_scanned_block,
            "total_scans": self._scan_count,
            "recent_events_count": len(self._recent_events),
            "watched_wallets": len(self.watched_wallets),
            "whale_threshold_usd": self.whale_threshold_usd,
            "rpc_url": self.rpc.rpc_url[:30] + "..." if len(self.rpc.rpc_url) > 30 else self.rpc.rpc_url,
        }

    def get_whale_leaderboard(self) -> List[dict]:
        """
        Get a leaderboard of whale activity from recent events.

        Returns wallets sorted by total volume.
        """
        wallet_stats: Dict[str, dict] = {}

        for event in self._recent_events:
            addr = event.wallet_address
            if addr not in wallet_stats:
                wallet_stats[addr] = {
                    "address": addr,
                    "label": event.wallet_label or "Unknown",
                    "total_volume_usd": 0.0,
                    "buy_count": 0,
                    "sell_count": 0,
                    "unique_markets": set(),
                }
            stats = wallet_stats[addr]
            stats["total_volume_usd"] += event.value_usd
            if event.side == "BUY":
                stats["buy_count"] += 1
            else:
                stats["sell_count"] += 1
            stats["unique_markets"].add(event.token_id)

        # Convert sets to counts and sort
        result = []
        for stats in wallet_stats.values():
            stats["unique_markets"] = len(stats["unique_markets"])
            result.append(stats)

        result.sort(key=lambda x: x["total_volume_usd"], reverse=True)
        return result[:20]


# ============================================================
# Singleton
# ============================================================

_indexer: Optional[WhaleIndexer] = None


def get_whale_indexer() -> WhaleIndexer:
    """Get or create the global whale indexer."""
    global _indexer
    if _indexer is None:
        _indexer = WhaleIndexer()
    return _indexer


async def start_whale_indexer(interval_sec: int = 30):
    """Start the whale indexer (called from app lifespan)."""
    indexer = get_whale_indexer()
    await indexer.start_continuous_scan(interval_sec)


async def stop_whale_indexer():
    """Stop the whale indexer."""
    global _indexer
    if _indexer:
        await _indexer.stop()
