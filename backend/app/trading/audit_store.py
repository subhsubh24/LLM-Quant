"""
SQLite-backed Audit Store — Production-grade persistent audit trail.

Upgrades from JSONL to SQLite for:
- Fast indexed queries by date, event_type, session, symbol
- Concurrent read/write access (WAL mode)
- Atomic writes (no partial records)
- Aggregate queries (total notional, trade counts, etc.)
- Backward compatibility: can import existing JSONL files

Usage:
    store = AuditStore("audit.db")
    store.log_trade(symbol="AAPL", side="buy", qty=100, price=150.0)
    records = store.query(event_type="trade", symbol="AAPL", limit=50)
"""

import json
import os
import sqlite3
import logging
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional

logger = logging.getLogger(__name__)

_DEFAULT_DB_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "audit_logs"
)


class AuditStore:
    """
    SQLite-backed audit trail with full query support.

    Uses WAL mode for concurrent reads and a single-writer pattern.
    All records are immutable (append-only).
    """

    def __init__(self, db_path: Optional[str] = None):
        """
        Args:
            db_path: Path to SQLite database file. Defaults to audit_logs/audit.db.
        """
        os.makedirs(_DEFAULT_DB_DIR, exist_ok=True)
        self.db_path = db_path or os.path.join(_DEFAULT_DB_DIR, "audit.db")
        self._session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._model_version = ""
        self._init_db()

    def _init_db(self) -> None:
        """Create tables and indexes if they don't exist."""
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS audit_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    event_date TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    session_id TEXT NOT NULL DEFAULT '',
                    model_version TEXT NOT NULL DEFAULT '',
                    symbol TEXT DEFAULT '',
                    details TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
            """)

            # Indexes for common query patterns
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_audit_date
                ON audit_records(event_date)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_audit_type
                ON audit_records(event_type)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_audit_symbol
                ON audit_records(symbol)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_audit_session
                ON audit_records(session_id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_audit_type_date
                ON audit_records(event_type, event_date)
            """)

            # Enable WAL mode for concurrent reads
            conn.execute("PRAGMA journal_mode=WAL")

            conn.commit()

        logger.info(f"Audit store initialized at {self.db_path}")

    @contextmanager
    def _connect(self) -> Generator[sqlite3.Connection, None, None]:
        """Context manager for database connections."""
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def set_model_version(self, version: str) -> None:
        """Set the current model version for audit records."""
        self._model_version = version

    def _insert_record(
        self,
        event_type: str,
        details: Dict[str, Any],
        symbol: str = "",
    ) -> None:
        """Insert a single audit record."""
        now = datetime.now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO audit_records
                    (timestamp, event_date, event_type, session_id, model_version, symbol, details)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    now.isoformat(),
                    now.date().isoformat(),
                    event_type,
                    self._session_id,
                    self._model_version,
                    symbol,
                    json.dumps(details, default=str),
                ),
            )
            conn.commit()

    # ── Trade logging ────────────────────────────────────────────

    def log_trade(
        self,
        symbol: str,
        side: str,
        qty: float,
        price: float,
        order_type: str = "market",
        commission_bps: float = 0.0,
        slippage_bps: float = 0.0,
        signal_strength: float = 0.0,
        strategy: str = "",
    ) -> None:
        """Log a trade execution."""
        self._insert_record(
            event_type="trade",
            symbol=symbol,
            details={
                "symbol": symbol,
                "side": side,
                "qty": qty,
                "price": price,
                "notional": qty * price,
                "order_type": order_type,
                "commission_bps": commission_bps,
                "slippage_bps": slippage_bps,
                "total_cost_bps": commission_bps + slippage_bps,
                "signal_strength": signal_strength,
                "strategy": strategy,
            },
        )
        logger.debug(f"Audit: {side} {qty} {symbol} @ {price}")

    def log_rebalance(
        self,
        old_weights: Dict[str, float],
        new_weights: Dict[str, float],
        turnover: float,
        n_trades: int,
        total_cost_bps: float,
    ) -> None:
        """Log a portfolio rebalance."""
        self._insert_record(
            event_type="rebalance",
            details={
                "old_weights": old_weights,
                "new_weights": new_weights,
                "turnover": turnover,
                "n_trades": n_trades,
                "total_cost_bps": total_cost_bps,
                "positions_added": [s for s in new_weights if s not in old_weights],
                "positions_removed": [s for s in old_weights if s not in new_weights],
            },
        )
        logger.info(f"Audit: rebalance, turnover={turnover:.1%}, trades={n_trades}")

    def log_risk_event(
        self,
        event_type: str,
        severity: str,
        details: Dict[str, Any],
    ) -> None:
        """Log a risk event (circuit breaker, limit breach, etc.)."""
        self._insert_record(
            event_type="risk_event",
            details={
                "risk_event_type": event_type,
                "severity": severity,
                **details,
            },
        )
        logger.warning(f"Audit: risk event [{severity}] {event_type}")

    def log_model_retrain(
        self,
        old_version: str,
        new_version: str,
        reason: str,
        validation_score: float,
        oos_score: float,
        n_features: int,
    ) -> None:
        """Log a model retraining event."""
        self._insert_record(
            event_type="model_retrain",
            details={
                "old_version": old_version,
                "new_version": new_version,
                "reason": reason,
                "validation_score": validation_score,
                "oos_score": oos_score,
                "n_features": n_features,
            },
        )
        self._model_version = new_version
        logger.info(f"Audit: model retrain {old_version} -> {new_version}")

    def log_reconciliation(
        self,
        expected_positions: Dict[str, float],
        actual_positions: Dict[str, float],
        discrepancies: List[Dict[str, Any]],
    ) -> None:
        """Log a position reconciliation result."""
        self._insert_record(
            event_type="position_reconcile",
            details={
                "expected_positions": expected_positions,
                "actual_positions": actual_positions,
                "n_discrepancies": len(discrepancies),
                "discrepancies": discrepancies,
                "is_reconciled": len(discrepancies) == 0,
            },
        )
        if discrepancies:
            logger.warning(f"Audit: reconciliation found {len(discrepancies)} discrepancies")
        else:
            logger.info("Audit: positions reconciled successfully")

    # ── Query interface ──────────────────────────────────────────

    def query(
        self,
        event_type: Optional[str] = None,
        symbol: Optional[str] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        session_id: Optional[str] = None,
        limit: int = 500,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """
        Query audit records with flexible filters.

        Args:
            event_type: Filter by event type
            symbol: Filter by symbol
            start_date: Records on or after this date
            end_date: Records on or before this date
            session_id: Filter by session
            limit: Max records to return
            offset: Skip first N records

        Returns:
            List of audit record dicts
        """
        conditions = []
        params: List[Any] = []

        if event_type:
            conditions.append("event_type = ?")
            params.append(event_type)
        if symbol:
            conditions.append("symbol = ?")
            params.append(symbol)
        if start_date:
            conditions.append("event_date >= ?")
            params.append(start_date.isoformat())
        if end_date:
            conditions.append("event_date <= ?")
            params.append(end_date.isoformat())
        if session_id:
            conditions.append("session_id = ?")
            params.append(session_id)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        sql = f"""
            SELECT timestamp, event_type, session_id, model_version, symbol, details
            FROM audit_records
            {where}
            ORDER BY id DESC
            LIMIT ? OFFSET ?
        """
        params.extend([limit, offset])

        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()

        results = []
        for row in rows:
            record = {
                "timestamp": row["timestamp"],
                "event_type": row["event_type"],
                "session_id": row["session_id"],
                "model_version": row["model_version"],
                "symbol": row["symbol"],
                "details": json.loads(row["details"]),
            }
            results.append(record)

        return results

    def get_daily_summary(self, target_date: Optional[date] = None) -> Dict[str, Any]:
        """Get aggregate summary for a given date."""
        d = target_date or date.today()

        with self._connect() as conn:
            # Total records
            total = conn.execute(
                "SELECT COUNT(*) as cnt FROM audit_records WHERE event_date = ?",
                (d.isoformat(),),
            ).fetchone()["cnt"]

            # By event type
            type_counts = conn.execute(
                """
                SELECT event_type, COUNT(*) as cnt
                FROM audit_records WHERE event_date = ?
                GROUP BY event_type
                """,
                (d.isoformat(),),
            ).fetchall()

            type_map = {row["event_type"]: row["cnt"] for row in type_counts}

            # Total notional for trades
            trades = self.query(event_type="trade", start_date=d, end_date=d, limit=10000)
            total_notional = sum(
                t.get("details", {}).get("notional", 0) for t in trades
            )

            # Check for discrepancies
            reconciliations = self.query(
                event_type="position_reconcile", start_date=d, end_date=d
            )
            has_discrepancies = any(
                r.get("details", {}).get("n_discrepancies", 0) > 0
                for r in reconciliations
            )

        return {
            "date": d.isoformat(),
            "total_records": total,
            "n_trades": type_map.get("trade", 0),
            "n_risk_events": type_map.get("risk_event", 0),
            "n_rebalances": type_map.get("rebalance", 0),
            "n_retrains": type_map.get("model_retrain", 0),
            "total_notional": total_notional,
            "has_discrepancies": has_discrepancies,
        }

    def get_trade_summary(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> Dict[str, Any]:
        """Get aggregate trade statistics over a period."""
        trades = self.query(
            event_type="trade",
            start_date=start_date,
            end_date=end_date,
            limit=100000,
        )

        if not trades:
            return {"n_trades": 0, "total_notional": 0.0, "symbols_traded": []}

        notionals = [t["details"].get("notional", 0) for t in trades]
        costs = [t["details"].get("total_cost_bps", 0) for t in trades]
        symbols = list(set(t["symbol"] for t in trades if t["symbol"]))

        return {
            "n_trades": len(trades),
            "total_notional": sum(notionals),
            "avg_notional": sum(notionals) / len(notionals) if notionals else 0,
            "avg_cost_bps": sum(costs) / len(costs) if costs else 0,
            "symbols_traded": sorted(symbols),
            "n_symbols": len(symbols),
        }

    def count(
        self,
        event_type: Optional[str] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> int:
        """Count records matching filters."""
        conditions = []
        params: List[Any] = []

        if event_type:
            conditions.append("event_type = ?")
            params.append(event_type)
        if start_date:
            conditions.append("event_date >= ?")
            params.append(start_date.isoformat())
        if end_date:
            conditions.append("event_date <= ?")
            params.append(end_date.isoformat())

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        sql = f"SELECT COUNT(*) as cnt FROM audit_records {where}"

        with self._connect() as conn:
            return conn.execute(sql, params).fetchone()["cnt"]

    # ── JSONL migration ──────────────────────────────────────────

    def import_jsonl(self, jsonl_path: str) -> int:
        """
        Import records from an existing JSONL audit file.

        Args:
            jsonl_path: Path to a JSONL audit file

        Returns:
            Number of records imported
        """
        if not os.path.exists(jsonl_path):
            logger.warning(f"JSONL file not found: {jsonl_path}")
            return 0

        imported = 0
        with open(jsonl_path, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    ts = record.get("timestamp", datetime.now().isoformat())
                    event_type = record.get("event_type", "unknown")
                    details = record.get("details", {})
                    symbol = details.get("symbol", "")
                    session_id = record.get("session_id", "")
                    model_version = record.get("model_version", "")

                    # Parse date from timestamp
                    try:
                        event_date = datetime.fromisoformat(ts).date().isoformat()
                    except (ValueError, TypeError):
                        event_date = date.today().isoformat()

                    with self._connect() as conn:
                        conn.execute(
                            """
                            INSERT INTO audit_records
                                (timestamp, event_date, event_type, session_id,
                                 model_version, symbol, details)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                ts, event_date, event_type, session_id,
                                model_version, symbol, json.dumps(details, default=str),
                            ),
                        )
                        conn.commit()
                    imported += 1
                except (json.JSONDecodeError, Exception) as e:
                    logger.warning(f"Skipped malformed JSONL record: {e}")

        logger.info(f"Imported {imported} records from {jsonl_path}")
        return imported

    def import_all_jsonl(self, audit_dir: Optional[str] = None) -> int:
        """Import all JSONL files from the audit_logs directory."""
        directory = audit_dir or _DEFAULT_DB_DIR
        total = 0

        if not os.path.isdir(directory):
            return 0

        for filename in sorted(os.listdir(directory)):
            if filename.endswith(".jsonl"):
                path = os.path.join(directory, filename)
                total += self.import_jsonl(path)

        logger.info(f"Total imported from all JSONL files: {total}")
        return total
