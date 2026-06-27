"""
Trade Audit Trail — Persistent compliance logging.

Every trade, rebalance, and risk event is logged to a JSON-lines file
with timestamps, providing a complete audit trail for:
- Regulatory compliance
- Performance attribution
- Post-mortem analysis
- Position reconciliation

Format: One JSON object per line (JSONL), append-only, timestamped.
"""

import json
import os
import logging
from datetime import datetime, date
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from pathlib import Path

logger = logging.getLogger(__name__)

# Default audit log location
_DEFAULT_AUDIT_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "audit_logs"
)


@dataclass
class AuditRecord:
    """A single audit trail record."""
    timestamp: str
    event_type: str  # "trade", "rebalance", "risk_event", "model_retrain", "position_reconcile"
    details: Dict[str, Any]
    session_id: str = ""
    model_version: str = ""


class TradeAuditTrail:
    """
    Persistent, append-only trade audit trail.

    Writes to JSONL files (one per day), providing:
    - Complete trade history with timestamps
    - Risk event logging
    - Model retraining records
    - Position reconciliation results
    """

    def __init__(self, audit_dir: Optional[str] = None):
        self.audit_dir = audit_dir or _DEFAULT_AUDIT_DIR
        os.makedirs(self.audit_dir, exist_ok=True)
        self._session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._model_version = ""

    def set_model_version(self, version: str) -> None:
        """Set the current model version for audit records."""
        self._model_version = version

    def _get_log_path(self) -> str:
        """Get today's audit log file path."""
        today = date.today().isoformat()
        return os.path.join(self.audit_dir, f"audit_{today}.jsonl")

    def _write_record(self, record: AuditRecord) -> None:
        """Append a record to the audit log."""
        path = self._get_log_path()
        try:
            with open(path, "a") as f:
                f.write(json.dumps(asdict(record), default=str) + "\n")
        except Exception as e:
            logger.error(f"Failed to write audit record: {e}")

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
        record = AuditRecord(
            timestamp=datetime.now().isoformat(),
            event_type="trade",
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
            session_id=self._session_id,
            model_version=self._model_version,
        )
        self._write_record(record)
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
        record = AuditRecord(
            timestamp=datetime.now().isoformat(),
            event_type="rebalance",
            details={
                "old_weights": old_weights,
                "new_weights": new_weights,
                "turnover": turnover,
                "n_trades": n_trades,
                "total_cost_bps": total_cost_bps,
                "positions_added": [
                    s for s in new_weights if s not in old_weights
                ],
                "positions_removed": [
                    s for s in old_weights if s not in new_weights
                ],
            },
            session_id=self._session_id,
            model_version=self._model_version,
        )
        self._write_record(record)
        logger.info(f"Audit: rebalance, turnover={turnover:.1%}, trades={n_trades}")

    def log_risk_event(
        self,
        event_type: str,
        severity: str,
        details: Dict[str, Any],
    ) -> None:
        """Log a risk event (circuit breaker, limit breach, etc.)."""
        record = AuditRecord(
            timestamp=datetime.now().isoformat(),
            event_type="risk_event",
            details={
                "risk_event_type": event_type,
                "severity": severity,
                **details,
            },
            session_id=self._session_id,
            model_version=self._model_version,
        )
        self._write_record(record)
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
        record = AuditRecord(
            timestamp=datetime.now().isoformat(),
            event_type="model_retrain",
            details={
                "old_version": old_version,
                "new_version": new_version,
                "reason": reason,
                "validation_score": validation_score,
                "oos_score": oos_score,
                "n_features": n_features,
            },
            session_id=self._session_id,
            model_version=new_version,
        )
        self._write_record(record)
        self._model_version = new_version
        logger.info(f"Audit: model retrain {old_version} → {new_version}")

    def log_reconciliation(
        self,
        expected_positions: Dict[str, float],
        actual_positions: Dict[str, float],
        discrepancies: List[Dict[str, Any]],
    ) -> None:
        """Log a position reconciliation result."""
        record = AuditRecord(
            timestamp=datetime.now().isoformat(),
            event_type="position_reconcile",
            details={
                "expected_positions": expected_positions,
                "actual_positions": actual_positions,
                "n_discrepancies": len(discrepancies),
                "discrepancies": discrepancies,
                "is_reconciled": len(discrepancies) == 0,
            },
            session_id=self._session_id,
            model_version=self._model_version,
        )
        self._write_record(record)
        if discrepancies:
            logger.warning(f"Audit: reconciliation found {len(discrepancies)} discrepancies")
        else:
            logger.info("Audit: positions reconciled successfully")

    def read_audit_log(
        self, target_date: Optional[date] = None, event_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Read audit log records.

        Args:
            target_date: Date to read (default: today)
            event_type: Filter by event type

        Returns:
            List of audit record dicts
        """
        d = target_date or date.today()
        path = os.path.join(self.audit_dir, f"audit_{d.isoformat()}.jsonl")

        if not os.path.exists(path):
            return []

        records = []
        try:
            with open(path, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    record = json.loads(line)
                    if event_type and record.get("event_type") != event_type:
                        continue
                    records.append(record)
        except Exception as e:
            logger.error(f"Failed to read audit log: {e}")

        return records

    def get_daily_summary(self, target_date: Optional[date] = None) -> Dict[str, Any]:
        """Get summary of today's audit activity."""
        records = self.read_audit_log(target_date)

        trades = [r for r in records if r.get("event_type") == "trade"]
        risk_events = [r for r in records if r.get("event_type") == "risk_event"]

        total_notional = sum(
            r.get("details", {}).get("notional", 0) for r in trades
        )

        return {
            "date": (target_date or date.today()).isoformat(),
            "total_records": len(records),
            "n_trades": len(trades),
            "n_risk_events": len(risk_events),
            "total_notional": total_notional,
            "has_discrepancies": any(
                r.get("event_type") == "position_reconcile"
                and r.get("details", {}).get("n_discrepancies", 0) > 0
                for r in records
            ),
        }


class PositionReconciler:
    """
    Reconcile model-expected positions with actual broker positions.

    Catches:
    - Partial fills (model thinks order filled, broker shows partial)
    - Phantom positions (position exists at broker but not in model)
    - Missing positions (model expects position, broker doesn't have it)
    - Quantity mismatches
    """

    def __init__(self, tolerance_pct: float = 0.02):
        """
        Args:
            tolerance_pct: Allow this % difference before flagging (2% default)
        """
        self.tolerance_pct = tolerance_pct

    def reconcile(
        self,
        expected: Dict[str, float],
        actual: Dict[str, float],
    ) -> List[Dict[str, Any]]:
        """
        Compare expected vs actual positions.

        Args:
            expected: Dict of symbol -> expected quantity
            actual: Dict of symbol -> actual quantity at broker

        Returns:
            List of discrepancy dicts
        """
        discrepancies = []
        all_symbols = set(expected.keys()) | set(actual.keys())

        for symbol in all_symbols:
            exp_qty = expected.get(symbol, 0.0)
            act_qty = actual.get(symbol, 0.0)

            if exp_qty == 0 and act_qty == 0:
                continue

            # Check for meaningful difference
            if abs(exp_qty) > 0:
                diff_pct = abs(act_qty - exp_qty) / abs(exp_qty)
            else:
                diff_pct = 1.0  # Phantom position

            if diff_pct > self.tolerance_pct:
                disc_type = "missing"
                if exp_qty == 0:
                    disc_type = "phantom"
                elif act_qty == 0:
                    disc_type = "missing"
                elif abs(act_qty) < abs(exp_qty):
                    disc_type = "partial_fill"
                else:
                    disc_type = "quantity_mismatch"

                discrepancies.append({
                    "symbol": symbol,
                    "type": disc_type,
                    "expected_qty": exp_qty,
                    "actual_qty": act_qty,
                    "difference": act_qty - exp_qty,
                    "difference_pct": diff_pct,
                })

        return discrepancies
