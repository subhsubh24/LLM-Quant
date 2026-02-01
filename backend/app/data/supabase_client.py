"""
Supabase Integration for Portfolio Tracking & Persistence.

Provides:
- Trade history storage
- Position tracking
- Price snapshots for historical analysis
- Bot state persistence (resume trading sessions)
- Portfolio analytics over time
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
import json
import httpx

logger = logging.getLogger(__name__)


@dataclass
class SupabaseConfig:
    """Supabase configuration."""
    project_url: str
    api_key: str

    @property
    def rest_url(self) -> str:
        return f"{self.project_url}/rest/v1"

    @property
    def headers(self) -> Dict[str, str]:
        return {
            "apikey": self.api_key,
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }


class SupabaseClient:
    """
    Supabase REST API client for portfolio tracking.

    Tables (create these in Supabase dashboard):
    - portfolios: User portfolios and settings
    - positions: Current open positions
    - trades: Trade history (opened and closed)
    - price_snapshots: Historical price data
    - bot_states: Bot state for session resumption
    - daily_pnl: Daily P&L tracking
    """

    def __init__(self, config: SupabaseConfig):
        self.config = config
        self._client: Optional[httpx.AsyncClient] = None
        self._connected = False

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                headers=self.config.headers,
                timeout=30.0,
            )
        return self._client

    async def connect(self) -> bool:
        """Test connection to Supabase."""
        try:
            client = await self._get_client()
            # Test with a simple query
            response = await client.get(
                f"{self.config.rest_url}/portfolios",
                params={"limit": 1}
            )

            if response.status_code in (200, 404):  # 404 means table doesn't exist yet
                self._connected = True
                logger.info("✅ Supabase connected successfully")
                return True
            else:
                logger.warning(f"Supabase connection test: {response.status_code}")
                return False

        except Exception as e:
            logger.error(f"Supabase connection failed: {e}")
            return False

    async def disconnect(self):
        """Close the client."""
        if self._client:
            await self._client.aclose()
            self._client = None
        self._connected = False

    # =========================================================================
    # PORTFOLIO MANAGEMENT
    # =========================================================================

    async def get_or_create_portfolio(
        self,
        user_id: str = "default",
        initial_capital: float = 100000.0,
    ) -> Optional[Dict]:
        """Get existing portfolio or create new one."""
        client = await self._get_client()

        # Try to get existing
        response = await client.get(
            f"{self.config.rest_url}/portfolios",
            params={"user_id": f"eq.{user_id}", "limit": 1}
        )

        if response.status_code == 200:
            data = response.json()
            if data:
                return data[0]

        # Create new portfolio
        portfolio = {
            "user_id": user_id,
            "initial_capital": initial_capital,
            "current_capital": initial_capital,
            "total_pnl": 0,
            "total_trades": 0,
            "win_rate": 0,
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
        }

        response = await client.post(
            f"{self.config.rest_url}/portfolios",
            json=portfolio,
        )

        if response.status_code in (200, 201):
            logger.info(f"Created new portfolio for user {user_id}")
            return response.json()[0] if response.json() else portfolio

        logger.error(f"Failed to create portfolio: {response.text}")
        return None

    async def update_portfolio(
        self,
        user_id: str,
        updates: Dict[str, Any],
    ) -> bool:
        """Update portfolio fields."""
        client = await self._get_client()

        updates["updated_at"] = datetime.utcnow().isoformat()

        response = await client.patch(
            f"{self.config.rest_url}/portfolios",
            params={"user_id": f"eq.{user_id}"},
            json=updates,
        )

        return response.status_code in (200, 204)

    # =========================================================================
    # POSITION TRACKING
    # =========================================================================

    async def save_position(self, position: Dict) -> bool:
        """Save or update a position."""
        client = await self._get_client()

        position["updated_at"] = datetime.utcnow().isoformat()

        # Upsert based on position_id
        response = await client.post(
            f"{self.config.rest_url}/positions",
            json=position,
            headers={**self.config.headers, "Prefer": "resolution=merge-duplicates"},
        )

        return response.status_code in (200, 201)

    async def get_positions(self, user_id: str = "default") -> List[Dict]:
        """Get all open positions for a user."""
        client = await self._get_client()

        response = await client.get(
            f"{self.config.rest_url}/positions",
            params={
                "user_id": f"eq.{user_id}",
                "is_open": "eq.true",
                "order": "opened_at.desc",
            }
        )

        if response.status_code == 200:
            return response.json()
        return []

    async def close_position(
        self,
        position_id: str,
        close_price: float,
        pnl: float,
        reason: str = "",
    ) -> bool:
        """Close a position."""
        client = await self._get_client()

        response = await client.patch(
            f"{self.config.rest_url}/positions",
            params={"position_id": f"eq.{position_id}"},
            json={
                "is_open": False,
                "close_price": close_price,
                "realized_pnl": pnl,
                "close_reason": reason,
                "closed_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat(),
            },
        )

        return response.status_code in (200, 204)

    # =========================================================================
    # TRADE HISTORY
    # =========================================================================

    async def log_trade(self, trade: Dict) -> bool:
        """Log a trade to history."""
        client = await self._get_client()

        trade["timestamp"] = trade.get("timestamp", datetime.utcnow().isoformat())

        response = await client.post(
            f"{self.config.rest_url}/trades",
            json=trade,
        )

        if response.status_code in (200, 201):
            logger.debug(f"Trade logged: {trade.get('symbol')} {trade.get('action')}")
            return True

        logger.error(f"Failed to log trade: {response.text}")
        return False

    async def get_trades(
        self,
        user_id: str = "default",
        limit: int = 100,
        offset: int = 0,
        symbol: Optional[str] = None,
    ) -> List[Dict]:
        """Get trade history."""
        client = await self._get_client()

        params = {
            "user_id": f"eq.{user_id}",
            "order": "timestamp.desc",
            "limit": limit,
            "offset": offset,
        }

        if symbol:
            params["symbol"] = f"eq.{symbol}"

        response = await client.get(
            f"{self.config.rest_url}/trades",
            params=params,
        )

        if response.status_code == 200:
            return response.json()
        return []

    # =========================================================================
    # PRICE SNAPSHOTS (Historical Tracking)
    # =========================================================================

    async def save_price_snapshot(
        self,
        symbol: str,
        price: float,
        source: str = "websocket",
        metadata: Optional[Dict] = None,
    ) -> bool:
        """Save a price snapshot for historical tracking."""
        client = await self._get_client()

        snapshot = {
            "symbol": symbol,
            "price": price,
            "source": source,
            "timestamp": datetime.utcnow().isoformat(),
            "metadata": json.dumps(metadata) if metadata else None,
        }

        response = await client.post(
            f"{self.config.rest_url}/price_snapshots",
            json=snapshot,
        )

        return response.status_code in (200, 201)

    async def get_price_history(
        self,
        symbol: str,
        hours: int = 24,
        interval_minutes: int = 5,
    ) -> List[Dict]:
        """Get price history for a symbol."""
        client = await self._get_client()

        since = (datetime.utcnow() - timedelta(hours=hours)).isoformat()

        response = await client.get(
            f"{self.config.rest_url}/price_snapshots",
            params={
                "symbol": f"eq.{symbol}",
                "timestamp": f"gte.{since}",
                "order": "timestamp.asc",
            }
        )

        if response.status_code == 200:
            return response.json()
        return []

    # =========================================================================
    # BOT STATE PERSISTENCE
    # =========================================================================

    async def save_bot_state(
        self,
        bot_id: str,
        state: Dict,
        user_id: str = "default",
    ) -> bool:
        """Save bot state for session resumption."""
        client = await self._get_client()

        bot_state = {
            "bot_id": bot_id,
            "user_id": user_id,
            "state": json.dumps(state),
            "updated_at": datetime.utcnow().isoformat(),
        }

        # Upsert
        response = await client.post(
            f"{self.config.rest_url}/bot_states",
            json=bot_state,
            headers={**self.config.headers, "Prefer": "resolution=merge-duplicates"},
        )

        return response.status_code in (200, 201)

    async def get_bot_state(
        self,
        bot_id: str,
        user_id: str = "default",
    ) -> Optional[Dict]:
        """Get saved bot state."""
        client = await self._get_client()

        response = await client.get(
            f"{self.config.rest_url}/bot_states",
            params={
                "bot_id": f"eq.{bot_id}",
                "user_id": f"eq.{user_id}",
                "limit": 1,
            }
        )

        if response.status_code == 200:
            data = response.json()
            if data:
                state_json = data[0].get("state")
                if state_json:
                    return json.loads(state_json)
        return None

    # =========================================================================
    # DAILY P&L TRACKING
    # =========================================================================

    async def log_daily_pnl(
        self,
        user_id: str,
        date: str,
        pnl: float,
        portfolio_value: float,
        trades_count: int = 0,
    ) -> bool:
        """Log daily P&L for performance tracking."""
        client = await self._get_client()

        record = {
            "user_id": user_id,
            "date": date,
            "pnl": pnl,
            "portfolio_value": portfolio_value,
            "trades_count": trades_count,
            "created_at": datetime.utcnow().isoformat(),
        }

        response = await client.post(
            f"{self.config.rest_url}/daily_pnl",
            json=record,
            headers={**self.config.headers, "Prefer": "resolution=merge-duplicates"},
        )

        return response.status_code in (200, 201)

    async def get_pnl_history(
        self,
        user_id: str = "default",
        days: int = 30,
    ) -> List[Dict]:
        """Get P&L history for charting."""
        client = await self._get_client()

        since = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")

        response = await client.get(
            f"{self.config.rest_url}/daily_pnl",
            params={
                "user_id": f"eq.{user_id}",
                "date": f"gte.{since}",
                "order": "date.asc",
            }
        )

        if response.status_code == 200:
            return response.json()
        return []

    def get_status(self) -> Dict:
        """Get connection status."""
        return {
            "connected": self._connected,
            "project_url": self.config.project_url,
        }


# =============================================================================
# SINGLETON & INITIALIZATION
# =============================================================================

_supabase_client: Optional[SupabaseClient] = None


def get_supabase_client() -> Optional[SupabaseClient]:
    """Get singleton Supabase client."""
    return _supabase_client


async def init_supabase(project_url: str, api_key: str) -> SupabaseClient:
    """Initialize Supabase client."""
    global _supabase_client

    config = SupabaseConfig(
        project_url=project_url,
        api_key=api_key,
    )

    _supabase_client = SupabaseClient(config)
    await _supabase_client.connect()

    return _supabase_client


# =============================================================================
# SQL SCHEMA (Run this in Supabase SQL Editor)
# =============================================================================

SUPABASE_SCHEMA = """
-- Portfolios table
CREATE TABLE IF NOT EXISTS portfolios (
    id SERIAL PRIMARY KEY,
    user_id TEXT UNIQUE NOT NULL DEFAULT 'default',
    initial_capital DECIMAL(18, 2) NOT NULL DEFAULT 100000,
    current_capital DECIMAL(18, 2) NOT NULL DEFAULT 100000,
    total_pnl DECIMAL(18, 2) DEFAULT 0,
    total_trades INTEGER DEFAULT 0,
    win_rate DECIMAL(5, 2) DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Positions table
CREATE TABLE IF NOT EXISTS positions (
    id SERIAL PRIMARY KEY,
    position_id TEXT UNIQUE NOT NULL,
    user_id TEXT NOT NULL DEFAULT 'default',
    symbol TEXT NOT NULL,
    asset_class TEXT,
    strategy TEXT,
    side TEXT CHECK (side IN ('long', 'short')),
    quantity DECIMAL(18, 8),
    entry_price DECIMAL(18, 8),
    current_price DECIMAL(18, 8),
    unrealized_pnl DECIMAL(18, 2),
    realized_pnl DECIMAL(18, 2) DEFAULT 0,
    close_price DECIMAL(18, 8),
    close_reason TEXT,
    is_open BOOLEAN DEFAULT TRUE,
    opened_at TIMESTAMPTZ DEFAULT NOW(),
    closed_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    metadata JSONB
);

-- Trades history table
CREATE TABLE IF NOT EXISTS trades (
    id SERIAL PRIMARY KEY,
    trade_id TEXT UNIQUE,
    user_id TEXT NOT NULL DEFAULT 'default',
    symbol TEXT NOT NULL,
    action TEXT CHECK (action IN ('BUY', 'SELL', 'OPEN', 'CLOSE')),
    quantity DECIMAL(18, 8),
    price DECIMAL(18, 8),
    pnl DECIMAL(18, 2),
    fees DECIMAL(18, 4) DEFAULT 0,
    strategy TEXT,
    rationale TEXT,
    broker TEXT,
    is_live BOOLEAN DEFAULT FALSE,
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    metadata JSONB
);

-- Price snapshots for historical tracking
CREATE TABLE IF NOT EXISTS price_snapshots (
    id SERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    price DECIMAL(18, 8) NOT NULL,
    source TEXT DEFAULT 'websocket',
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    metadata JSONB
);

-- Create index for efficient queries
CREATE INDEX IF NOT EXISTS idx_price_snapshots_symbol_time
ON price_snapshots(symbol, timestamp DESC);

-- Bot states for session resumption
CREATE TABLE IF NOT EXISTS bot_states (
    id SERIAL PRIMARY KEY,
    bot_id TEXT NOT NULL,
    user_id TEXT NOT NULL DEFAULT 'default',
    state JSONB NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(bot_id, user_id)
);

-- Daily P&L tracking
CREATE TABLE IF NOT EXISTS daily_pnl (
    id SERIAL PRIMARY KEY,
    user_id TEXT NOT NULL DEFAULT 'default',
    date DATE NOT NULL,
    pnl DECIMAL(18, 2),
    portfolio_value DECIMAL(18, 2),
    trades_count INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, date)
);

-- Enable Row Level Security (optional but recommended)
ALTER TABLE portfolios ENABLE ROW LEVEL SECURITY;
ALTER TABLE positions ENABLE ROW LEVEL SECURITY;
ALTER TABLE trades ENABLE ROW LEVEL SECURITY;
ALTER TABLE bot_states ENABLE ROW LEVEL SECURITY;
ALTER TABLE daily_pnl ENABLE ROW LEVEL SECURITY;

-- Create policies for anon access (for development)
CREATE POLICY "Allow all for portfolios" ON portfolios FOR ALL USING (true);
CREATE POLICY "Allow all for positions" ON positions FOR ALL USING (true);
CREATE POLICY "Allow all for trades" ON trades FOR ALL USING (true);
CREATE POLICY "Allow all for bot_states" ON bot_states FOR ALL USING (true);
CREATE POLICY "Allow all for daily_pnl" ON daily_pnl FOR ALL USING (true);
CREATE POLICY "Allow all for price_snapshots" ON price_snapshots FOR ALL USING (true);
"""
