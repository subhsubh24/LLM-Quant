"""
Order Execution Layer for Prediction Markets.

Supports:
- Polymarket: via py-clob-client (Polygon/CLOB, wallet-based auth)

All execution goes through a unified interface so strategies don't
need to know the exchange internals.

IMPORTANT: Start with dry_run=True to validate logic before real money.
"""

import hashlib
import hmac
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

import requests

from .polymarket_client import (
    CLOB_API,
    Market,
    OrderBook,
    Outcome,
    PolymarketClient,
)

logger = logging.getLogger(__name__)


# ============================================================
# Shared Types
# ============================================================

class Exchange(Enum):
    POLYMARKET = "polymarket"


class OrderSide(Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    GTC = "GTC"  # Good til cancelled (Polymarket)
    FOK = "FOK"  # Fill or kill


class OrderStatus(Enum):
    PENDING = "pending"
    OPEN = "open"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"


@dataclass
class OrderRequest:
    """Request to place an order on a prediction market."""
    exchange: Exchange
    market_id: str           # Polymarket condition_id
    token_id: str            # Polymarket token_id
    side: OrderSide
    order_type: OrderType
    size: float              # Number of contracts
    price: Optional[float]   # Limit price (0.01 - 0.99). None for market orders
    strategy: str = ""       # Strategy that generated this order
    scan_result_id: str = "" # Link back to the scan result

    @property
    def notional(self) -> float:
        """Estimated cost in USD."""
        p = self.price if self.price else 0.50
        return self.size * p


@dataclass
class OrderResult:
    """Result of an order placement attempt."""
    order_id: str
    exchange: Exchange
    market_id: str
    token_id: str
    side: OrderSide
    order_type: OrderType
    size: float
    price: Optional[float]
    status: OrderStatus
    filled_size: float = 0.0
    filled_price: float = 0.0
    fees: float = 0.0
    error: Optional[str] = None
    raw_response: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def is_success(self) -> bool:
        return self.status in (OrderStatus.OPEN, OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED)

    @property
    def net_cost(self) -> float:
        """Total cost including fees."""
        return self.filled_size * self.filled_price + self.fees


@dataclass
class Position:
    """A live position on an exchange."""
    exchange: Exchange
    market_id: str
    token_id: str
    market_question: str
    outcome_label: str
    side: str              # "long" or "short"
    size: float            # Number of contracts held
    avg_entry_price: float
    current_price: float
    unrealized_pnl: float
    realized_pnl: float
    strategy: str = ""
    opened_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def market_value(self) -> float:
        return self.size * self.current_price

    @property
    def cost_basis(self) -> float:
        return self.size * self.avg_entry_price

    @property
    def total_pnl(self) -> float:
        return self.unrealized_pnl + self.realized_pnl


# ============================================================
# Polymarket Executor
# ============================================================

class PolymarketExecutor:
    """
    Order execution for Polymarket via the CLOB API.

    Authentication requires:
    - A Polygon wallet (private key)
    - API key + secret + passphrase from Polymarket

    For read-only operations, no auth is needed.
    For order placement, set credentials via environment variables:
        POLYMARKET_API_KEY, POLYMARKET_API_SECRET, POLYMARKET_PASSPHRASE, POLYMARKET_PRIVATE_KEY
    """

    def __init__(
        self,
        api_key: str = "",
        api_secret: str = "",
        passphrase: str = "",
        private_key: str = "",
        funder: str = "",
    ):
        self.api_key = api_key
        self.api_secret = api_secret
        self.passphrase = passphrase
        self.private_key = private_key
        self.funder = funder
        self._client = None  # Lazy py-clob-client ClobClient
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "LLM-Quant/1.0",
            "Accept": "application/json",
        })

    @property
    def is_authenticated(self) -> bool:
        return bool(self.api_key and self.api_secret and self.passphrase)

    def _get_clob_client(self):
        """Lazy-init py-clob-client if available."""
        if self._client is not None:
            return self._client

        if not self.is_authenticated:
            raise RuntimeError(
                "Polymarket auth not configured. Set POLYMARKET_API_KEY, "
                "POLYMARKET_API_SECRET, POLYMARKET_PASSPHRASE env vars."
            )

        try:
            from py_clob_client.client import ClobClient
            from py_clob_client.clob_types import ApiCreds

            creds = ApiCreds(
                api_key=self.api_key,
                api_secret=self.api_secret,
                api_passphrase=self.passphrase,
            )
            self._client = ClobClient(
                host=CLOB_API,
                chain_id=137,  # Polygon mainnet
                key=self.private_key if self.private_key else None,
                creds=creds,
                funder=self.funder if self.funder else None,
            )
            logger.info("Polymarket CLOB client initialized")
            return self._client
        except ImportError:
            raise RuntimeError(
                "py-clob-client not installed. Run: pip install py-clob-client"
            )

    def _build_auth_headers(self, method: str, path: str, body: str = "") -> dict:
        """Build L2 authentication headers for CLOB API."""
        timestamp = str(int(time.time()))
        message = timestamp + method.upper() + path + body
        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        return {
            "POLY_API_KEY": self.api_key,
            "POLY_SIGNATURE": signature,
            "POLY_TIMESTAMP": timestamp,
            "POLY_PASSPHRASE": self.passphrase,
        }

    def place_order(self, req: OrderRequest) -> OrderResult:
        """
        Place an order on Polymarket.

        Uses py-clob-client if available, falls back to raw CLOB API.
        """
        try:
            client = self._get_clob_client()
        except RuntimeError:
            client = None

        if client is not None:
            return self._place_via_clob_client(client, req)
        else:
            return self._place_via_rest(req)

    def _place_via_clob_client(self, client, req: OrderRequest) -> OrderResult:
        """Place order using py-clob-client library."""
        try:
            from py_clob_client.order_builder.constants import BUY, SELL

            side_const = BUY if req.side == OrderSide.BUY else SELL

            order_args = {
                "token_id": req.token_id,
                "price": req.price if req.price else 0.50,
                "size": req.size,
                "side": side_const,
            }

            if req.order_type == OrderType.GTC:
                order_args["expiration"] = 0  # GTC = no expiration
            elif req.order_type == OrderType.FOK:
                order_args["order_type"] = "FOK"

            signed_order = client.create_and_sign_order(order_args)
            resp = client.post_order(signed_order)

            order_id = resp.get("orderID", resp.get("id", str(uuid.uuid4())))
            status = OrderStatus.OPEN
            if resp.get("status") == "matched":
                status = OrderStatus.FILLED

            return OrderResult(
                order_id=order_id,
                exchange=Exchange.POLYMARKET,
                market_id=req.market_id,
                token_id=req.token_id,
                side=req.side,
                order_type=req.order_type,
                size=req.size,
                price=req.price,
                status=status,
                filled_size=float(resp.get("matchedAmount", 0)),
                filled_price=req.price or 0.50,
                raw_response=resp,
            )
        except Exception as e:
            logger.error(f"Polymarket order failed: {e}")
            return OrderResult(
                order_id=str(uuid.uuid4()),
                exchange=Exchange.POLYMARKET,
                market_id=req.market_id,
                token_id=req.token_id,
                side=req.side,
                order_type=req.order_type,
                size=req.size,
                price=req.price,
                status=OrderStatus.REJECTED,
                error=str(e),
            )

    def _place_via_rest(self, req: OrderRequest) -> OrderResult:
        """Place order using raw CLOB REST API (fallback)."""
        if not self.is_authenticated:
            return OrderResult(
                order_id=str(uuid.uuid4()),
                exchange=Exchange.POLYMARKET,
                market_id=req.market_id,
                token_id=req.token_id,
                side=req.side,
                order_type=req.order_type,
                size=req.size,
                price=req.price,
                status=OrderStatus.REJECTED,
                error="Polymarket credentials not configured",
            )

        path = "/order"
        body = json.dumps({
            "tokenID": req.token_id,
            "price": str(req.price or 0.50),
            "size": str(req.size),
            "side": req.side.value,
            "type": "GTC" if req.order_type == OrderType.GTC else "FOK",
        })

        headers = self._build_auth_headers("POST", path, body)
        headers["Content-Type"] = "application/json"

        try:
            resp = self.session.post(
                f"{CLOB_API}{path}",
                data=body,
                headers=headers,
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()

            return OrderResult(
                order_id=data.get("orderID", str(uuid.uuid4())),
                exchange=Exchange.POLYMARKET,
                market_id=req.market_id,
                token_id=req.token_id,
                side=req.side,
                order_type=req.order_type,
                size=req.size,
                price=req.price,
                status=OrderStatus.OPEN,
                raw_response=data,
            )
        except requests.RequestException as e:
            logger.error(f"Polymarket REST order failed: {e}")
            return OrderResult(
                order_id=str(uuid.uuid4()),
                exchange=Exchange.POLYMARKET,
                market_id=req.market_id,
                token_id=req.token_id,
                side=req.side,
                order_type=req.order_type,
                size=req.size,
                price=req.price,
                status=OrderStatus.REJECTED,
                error=str(e),
            )

    def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order."""
        try:
            client = self._get_clob_client()
            resp = client.cancel(order_id)
            return resp.get("canceled", False) or resp.get("success", False)
        except Exception as e:
            logger.error(f"Polymarket cancel failed: {e}")
            return False

    def get_open_orders(self) -> List[dict]:
        """Get all open orders."""
        try:
            client = self._get_clob_client()
            return client.get_orders() or []
        except Exception as e:
            logger.error(f"Polymarket get_orders failed: {e}")
            return []

    def get_balances(self) -> Dict[str, float]:
        """Get USDC balance on Polygon."""
        try:
            client = self._get_clob_client()
            balance = client.get_balance_allowance()
            return {"USDC": float(balance.get("balance", 0)) / 1e6}
        except Exception as e:
            logger.error(f"Polymarket balance check failed: {e}")
            return {"USDC": 0.0}


# ============================================================
# Unified Executor (routes both exchanges through one interface)
# ============================================================

class PredictionMarketExecutor:
    """
    Unified order execution for Polymarket.

    Handles:
    - Order routing to Polymarket
    - Position tracking (in-memory + DB persistence)
    - Risk checks (max position size, max portfolio exposure)
    - Dry-run mode for paper trading
    """

    def __init__(
        self,
        polymarket: Optional[PolymarketExecutor] = None,
        dry_run: bool = True,
        max_position_usd: float = 50.0,
        max_portfolio_usd: float = 500.0,
    ):
        self.polymarket = polymarket or PolymarketExecutor()
        self.dry_run = dry_run
        self.max_position_usd = max_position_usd
        self.max_portfolio_usd = max_portfolio_usd

        # In-memory state
        self.positions: Dict[str, Position] = {}  # token_id -> Position
        self.order_history: List[OrderResult] = []
        self.total_fees: float = 0.0

        # Kill switch: when True, ALL order placement is blocked immediately.
        # This is the hard emergency stop — override everything, cancel all pending.
        self._kill_switch_active: bool = False
        self._kill_switch_reason: str = ""
        self._kill_switch_time: Optional[datetime] = None

    @property
    def total_exposure(self) -> float:
        """Total USD exposed across all positions."""
        return sum(p.market_value for p in self.positions.values())

    @property
    def total_pnl(self) -> float:
        """Total P&L across all positions."""
        return sum(p.total_pnl for p in self.positions.values())

    @property
    def kill_switch_active(self) -> bool:
        return self._kill_switch_active

    def activate_kill_switch(self, reason: str = "manual"):
        """
        Emergency kill switch — blocks ALL new orders immediately.

        Call this on: VPIN spike, connection loss, unexpected error,
        or manual intervention. Unlike the circuit breaker in risk_manager
        (which has a cooldown), the kill switch stays active until
        explicitly deactivated.
        """
        self._kill_switch_active = True
        self._kill_switch_reason = reason
        self._kill_switch_time = datetime.now(timezone.utc)
        logger.critical(
            f"[KILL SWITCH] ACTIVATED — reason: {reason} | "
            f"Positions: {len(self.positions)} | Exposure: ${self.total_exposure:.2f}"
        )

    def deactivate_kill_switch(self):
        """Re-enable trading after kill switch was activated."""
        if self._kill_switch_active:
            logger.info(
                f"[KILL SWITCH] Deactivated (was active since "
                f"{self._kill_switch_time.isoformat() if self._kill_switch_time else 'unknown'})"
            )
        self._kill_switch_active = False
        self._kill_switch_reason = ""
        self._kill_switch_time = None

    def _check_risk(self, req: OrderRequest) -> Optional[str]:
        """Pre-trade risk checks. Returns error message or None if OK."""
        # Kill switch overrides everything
        if self._kill_switch_active:
            return f"KILL SWITCH ACTIVE: {self._kill_switch_reason}"

        notional = req.notional

        if notional > self.max_position_usd:
            return f"Order notional ${notional:.2f} exceeds max position ${self.max_position_usd:.2f}"

        if self.total_exposure + notional > self.max_portfolio_usd:
            return (
                f"Portfolio exposure would be ${self.total_exposure + notional:.2f}, "
                f"exceeds max ${self.max_portfolio_usd:.2f}"
            )

        return None

    def execute(self, req: OrderRequest) -> OrderResult:
        """
        Execute an order with risk checks.

        In dry_run mode, simulates the fill without touching any exchange.
        """
        # Risk check
        risk_error = self._check_risk(req)
        if risk_error:
            logger.warning(f"Risk check failed: {risk_error}")
            return OrderResult(
                order_id=str(uuid.uuid4()),
                exchange=req.exchange,
                market_id=req.market_id,
                token_id=req.token_id,
                side=req.side,
                order_type=req.order_type,
                size=req.size,
                price=req.price,
                status=OrderStatus.REJECTED,
                error=f"Risk check: {risk_error}",
            )

        if self.dry_run:
            result = self._simulate_fill(req)
        elif req.exchange == Exchange.POLYMARKET:
            result = self.polymarket.place_order(req)
        else:
            result = OrderResult(
                order_id=str(uuid.uuid4()),
                exchange=req.exchange,
                market_id=req.market_id,
                token_id=req.token_id,
                side=req.side,
                order_type=req.order_type,
                size=req.size,
                price=req.price,
                status=OrderStatus.REJECTED,
                error=f"Unknown exchange: {req.exchange}",
            )

        # Track result
        self.order_history.append(result)
        if result.is_success:
            self._update_position(req, result)
            self.total_fees += result.fees

        return result

    def _simulate_fill(self, req: OrderRequest) -> OrderResult:
        """Simulate a fill for dry-run / paper trading mode."""
        fill_price = req.price or 0.50

        # Simulate realistic slippage: 0.5% for market orders
        if req.order_type == OrderType.MARKET:
            slippage = 0.005
            if req.side == OrderSide.BUY:
                fill_price = min(fill_price * (1 + slippage), 0.99)
            else:
                fill_price = max(fill_price * (1 - slippage), 0.01)

        # Simulate fees (Polymarket ~2%)
        fees = req.size * fill_price * 0.02

        return OrderResult(
            order_id=f"sim_{uuid.uuid4().hex[:12]}",
            exchange=req.exchange,
            market_id=req.market_id,
            token_id=req.token_id,
            side=req.side,
            order_type=req.order_type,
            size=req.size,
            price=req.price,
            status=OrderStatus.FILLED,
            filled_size=req.size,
            filled_price=fill_price,
            fees=fees,
            raw_response={"simulated": True, "dry_run": True},
        )

    def _update_position(self, req: OrderRequest, result: OrderResult):
        """Update in-memory position after a fill."""
        key = result.token_id

        if key in self.positions:
            pos = self.positions[key]
            if req.side == OrderSide.BUY:
                # Add to position
                total_cost = pos.avg_entry_price * pos.size + result.filled_price * result.filled_size
                pos.size += result.filled_size
                pos.avg_entry_price = total_cost / pos.size if pos.size > 0 else 0
            else:
                # Reduce position
                pnl = (result.filled_price - pos.avg_entry_price) * result.filled_size
                pos.realized_pnl += pnl
                pos.size -= result.filled_size
                if pos.size <= 0.001:
                    # Position closed
                    del self.positions[key]
                    return
            pos.current_price = result.filled_price
            pos.unrealized_pnl = (pos.current_price - pos.avg_entry_price) * pos.size
            pos.updated_at = datetime.now(timezone.utc)
        else:
            # New position
            self.positions[key] = Position(
                exchange=req.exchange,
                market_id=req.market_id,
                token_id=req.token_id,
                market_question="",
                outcome_label="",
                side="long" if req.side == OrderSide.BUY else "short",
                size=result.filled_size,
                avg_entry_price=result.filled_price,
                current_price=result.filled_price,
                unrealized_pnl=0.0,
                realized_pnl=0.0,
                strategy=req.strategy,
            )

    def cancel_order(self, order_id: str, exchange: Exchange) -> bool:
        """Cancel an order on the specified exchange."""
        if self.dry_run:
            return True
        if exchange == Exchange.POLYMARKET:
            return self.polymarket.cancel_order(order_id)
        return False

    def get_portfolio_summary(self) -> dict:
        """Get a summary of all positions and P&L."""
        positions_list = []
        for pos in self.positions.values():
            positions_list.append({
                "exchange": pos.exchange.value,
                "market_id": pos.market_id,
                "token_id": pos.token_id,
                "side": pos.side,
                "size": pos.size,
                "avg_entry_price": pos.avg_entry_price,
                "current_price": pos.current_price,
                "market_value": pos.market_value,
                "unrealized_pnl": pos.unrealized_pnl,
                "realized_pnl": pos.realized_pnl,
                "total_pnl": pos.total_pnl,
                "strategy": pos.strategy,
                "opened_at": pos.opened_at.isoformat(),
            })

        return {
            "total_positions": len(self.positions),
            "total_exposure": self.total_exposure,
            "total_pnl": self.total_pnl,
            "total_fees": self.total_fees,
            "total_orders": len(self.order_history),
            "dry_run": self.dry_run,
            "positions": positions_list,
        }

    def get_order_history(self, limit: int = 50) -> List[dict]:
        """Get recent order history."""
        return [
            {
                "order_id": o.order_id,
                "exchange": o.exchange.value,
                "market_id": o.market_id,
                "token_id": o.token_id,
                "side": o.side.value,
                "order_type": o.order_type.value,
                "size": o.size,
                "price": o.price,
                "status": o.status.value,
                "filled_size": o.filled_size,
                "filled_price": o.filled_price,
                "fees": o.fees,
                "error": o.error,
                "timestamp": o.timestamp.isoformat(),
            }
            for o in reversed(self.order_history[-limit:])
        ]


# ============================================================
# Singleton accessor
# ============================================================

_executor: Optional[PredictionMarketExecutor] = None


def get_executor(
    dry_run: bool = True,
    max_position_usd: float = 50.0,
    max_portfolio_usd: float = 500.0,
) -> PredictionMarketExecutor:
    """Get or create the global prediction market executor."""
    global _executor
    if _executor is None:
        import os

        poly = PolymarketExecutor(
            api_key=os.environ.get("POLYMARKET_API_KEY", ""),
            api_secret=os.environ.get("POLYMARKET_API_SECRET", ""),
            passphrase=os.environ.get("POLYMARKET_PASSPHRASE", ""),
            private_key=os.environ.get("POLYMARKET_PRIVATE_KEY", ""),
            funder=os.environ.get("POLYMARKET_FUNDER", ""),
        )
        _executor = PredictionMarketExecutor(
            polymarket=poly,
            dry_run=dry_run,
            max_position_usd=max_position_usd,
            max_portfolio_usd=max_portfolio_usd,
        )
    return _executor
