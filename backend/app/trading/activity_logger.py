"""
Bot Activity Logger - Comprehensive activity logging for the trading bot.

Provides structured logging of all significant bot events to the database
for monitoring, debugging, and audit purposes.

Event Types:
- lifecycle: Bot start, stop, restart, heartbeat
- broker: Connection, disconnection, authentication
- trade: Order submission, fill, cancel, reject
- scan: Market scanning, opportunity detection
- ml: Model training, prediction, regime detection
- error: Exceptions, failures, warnings
- position: Position open, close, update
- config: Configuration changes
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from dataclasses import dataclass

from ..db.database import get_session
from ..db.models import BotActivityLog

logger = logging.getLogger(__name__)


class EventType(str, Enum):
    """Top-level event categories."""
    LIFECYCLE = "lifecycle"
    BROKER = "broker"
    TRADE = "trade"
    SCAN = "scan"
    ML = "ml"
    ERROR = "error"
    POSITION = "position"
    CONFIG = "config"
    DATA = "data"


class EventSubtype(str, Enum):
    """Event subtypes for detailed classification."""
    # Lifecycle
    START = "start"
    STOP = "stop"
    RESTART = "restart"
    HEARTBEAT = "heartbeat"

    # Broker
    CONNECT = "connect"
    DISCONNECT = "disconnect"
    AUTH_SUCCESS = "auth_success"
    AUTH_FAILURE = "auth_failure"
    RECONNECT = "reconnect"

    # Trade
    SUBMIT = "submit"
    FILL = "fill"
    PARTIAL_FILL = "partial_fill"
    CANCEL = "cancel"
    REJECT = "reject"
    EXPIRE = "expire"

    # Scan
    SCAN_START = "scan_start"
    SCAN_COMPLETE = "scan_complete"
    OPPORTUNITY_FOUND = "opportunity_found"
    NO_OPPORTUNITIES = "no_opportunities"

    # ML
    TRAIN_START = "train_start"
    TRAIN_COMPLETE = "train_complete"
    PREDICTION = "prediction"
    REGIME_CHANGE = "regime_change"
    MODEL_UPDATE = "model_update"

    # Error
    EXCEPTION = "exception"
    TIMEOUT = "timeout"
    RATE_LIMIT = "rate_limit"
    VALIDATION = "validation"

    # Position
    OPEN = "open"
    CLOSE = "close"
    UPDATE = "update"
    STOP_TRIGGERED = "stop_triggered"
    TARGET_HIT = "target_hit"

    # Config
    CHANGE = "change"
    LOAD = "load"

    # Data
    FETCH_START = "fetch_start"
    FETCH_COMPLETE = "fetch_complete"
    FETCH_ERROR = "fetch_error"
    CACHE_HIT = "cache_hit"
    CACHE_MISS = "cache_miss"


class Severity(str, Enum):
    """Log severity levels."""
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class ActivityLogEntry:
    """Structured activity log entry."""
    event_type: EventType
    event_subtype: EventSubtype
    message: str
    severity: Severity = Severity.INFO
    symbol: Optional[str] = None
    asset_class: Optional[str] = None
    broker: Optional[str] = None
    details: Optional[Dict[str, Any]] = None
    value: Optional[float] = None
    duration_ms: Optional[int] = None
    correlation_id: Optional[str] = None


class BotActivityLogger:
    """
    Centralized activity logger for the trading bot.

    Features:
    - Async database persistence
    - In-memory buffer for recent logs
    - Session tracking
    - Correlation IDs for related events
    - Configurable log levels
    """

    def __init__(self, buffer_size: int = 1000):
        self.session_id = str(uuid.uuid4())[:12]
        self.buffer_size = buffer_size
        self._buffer: List[Dict[str, Any]] = []
        self._started_at = datetime.now()
        self._log_count = 0

        # Log bot startup
        self._log_sync(ActivityLogEntry(
            event_type=EventType.LIFECYCLE,
            event_subtype=EventSubtype.START,
            message=f"Bot activity logger initialized (session: {self.session_id})",
            details={"started_at": self._started_at.isoformat()}
        ))

        logger.info(f"BotActivityLogger initialized - session: {self.session_id}")

    def _log_sync(self, entry: ActivityLogEntry):
        """Synchronously log an entry (for startup/shutdown)."""
        try:
            log_record = BotActivityLog(
                event_type=entry.event_type.value if isinstance(entry.event_type, Enum) else entry.event_type,
                event_subtype=entry.event_subtype.value if isinstance(entry.event_subtype, Enum) else entry.event_subtype,
                severity=entry.severity.value if isinstance(entry.severity, Enum) else entry.severity,
                symbol=entry.symbol,
                asset_class=entry.asset_class,
                broker=entry.broker,
                message=entry.message,
                details_json=json.dumps(entry.details) if entry.details else None,
                value=entry.value,
                duration_ms=entry.duration_ms,
                session_id=self.session_id,
                correlation_id=entry.correlation_id,
            )

            with get_session() as session:
                session.add(log_record)

            # Also add to buffer
            self._add_to_buffer(log_record)
            self._log_count += 1

        except Exception as e:
            logger.error(f"Failed to log activity: {e}")

    async def log(self, entry: ActivityLogEntry):
        """Asynchronously log an activity entry."""
        try:
            log_record = BotActivityLog(
                event_type=entry.event_type.value if isinstance(entry.event_type, Enum) else entry.event_type,
                event_subtype=entry.event_subtype.value if isinstance(entry.event_subtype, Enum) else entry.event_subtype,
                severity=entry.severity.value if isinstance(entry.severity, Enum) else entry.severity,
                symbol=entry.symbol,
                asset_class=entry.asset_class,
                broker=entry.broker,
                message=entry.message,
                details_json=json.dumps(entry.details) if entry.details else None,
                value=entry.value,
                duration_ms=entry.duration_ms,
                session_id=self.session_id,
                correlation_id=entry.correlation_id,
            )

            # Run DB write in executor to not block async loop
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._persist_log, log_record)

            # Add to buffer
            self._add_to_buffer(log_record)
            self._log_count += 1

        except Exception as e:
            logger.error(f"Failed to log activity: {e}")

    def _persist_log(self, log_record: BotActivityLog):
        """Persist log record to database."""
        try:
            with get_session() as session:
                session.add(log_record)
        except Exception as e:
            logger.error(f"Database error logging activity: {e}")

    def _add_to_buffer(self, log_record: BotActivityLog):
        """Add log record to in-memory buffer."""
        record_dict = {
            "id": log_record.id,
            "event_type": log_record.event_type,
            "event_subtype": log_record.event_subtype,
            "severity": log_record.severity,
            "symbol": log_record.symbol,
            "asset_class": log_record.asset_class,
            "broker": log_record.broker,
            "message": log_record.message,
            "details": log_record.get_details() if log_record.details_json else None,
            "value": log_record.value,
            "duration_ms": log_record.duration_ms,
            "session_id": log_record.session_id,
            "correlation_id": log_record.correlation_id,
            "created_at": log_record.created_at.isoformat() if log_record.created_at else datetime.now().isoformat(),
        }

        self._buffer.append(record_dict)

        # Trim buffer if needed
        if len(self._buffer) > self.buffer_size:
            self._buffer = self._buffer[-self.buffer_size:]

    # ========== Convenience methods for common events ==========

    async def log_lifecycle(
        self,
        subtype: EventSubtype,
        message: str,
        details: Optional[Dict] = None,
    ):
        """Log a lifecycle event."""
        await self.log(ActivityLogEntry(
            event_type=EventType.LIFECYCLE,
            event_subtype=subtype,
            message=message,
            details=details,
        ))

    async def log_broker(
        self,
        subtype: EventSubtype,
        broker: str,
        message: str,
        success: bool = True,
        details: Optional[Dict] = None,
    ):
        """Log a broker event."""
        await self.log(ActivityLogEntry(
            event_type=EventType.BROKER,
            event_subtype=subtype,
            message=message,
            broker=broker,
            severity=Severity.INFO if success else Severity.ERROR,
            details=details,
        ))

    async def log_trade(
        self,
        subtype: EventSubtype,
        symbol: str,
        asset_class: str,
        message: str,
        broker: Optional[str] = None,
        value: Optional[float] = None,
        details: Optional[Dict] = None,
    ):
        """Log a trade event."""
        await self.log(ActivityLogEntry(
            event_type=EventType.TRADE,
            event_subtype=subtype,
            message=message,
            symbol=symbol,
            asset_class=asset_class,
            broker=broker,
            value=value,
            details=details,
        ))

    async def log_scan(
        self,
        subtype: EventSubtype,
        message: str,
        symbol: Optional[str] = None,
        asset_class: Optional[str] = None,
        duration_ms: Optional[int] = None,
        details: Optional[Dict] = None,
    ):
        """Log a market scanning event."""
        await self.log(ActivityLogEntry(
            event_type=EventType.SCAN,
            event_subtype=subtype,
            message=message,
            symbol=symbol,
            asset_class=asset_class,
            duration_ms=duration_ms,
            details=details,
        ))

    async def log_ml(
        self,
        subtype: EventSubtype,
        message: str,
        symbol: Optional[str] = None,
        value: Optional[float] = None,
        details: Optional[Dict] = None,
    ):
        """Log an ML model event."""
        await self.log(ActivityLogEntry(
            event_type=EventType.ML,
            event_subtype=subtype,
            message=message,
            symbol=symbol,
            value=value,
            details=details,
        ))

    async def log_error(
        self,
        subtype: EventSubtype,
        message: str,
        symbol: Optional[str] = None,
        broker: Optional[str] = None,
        details: Optional[Dict] = None,
    ):
        """Log an error event."""
        await self.log(ActivityLogEntry(
            event_type=EventType.ERROR,
            event_subtype=subtype,
            message=message,
            symbol=symbol,
            broker=broker,
            severity=Severity.ERROR,
            details=details,
        ))

    async def log_position(
        self,
        subtype: EventSubtype,
        symbol: str,
        asset_class: str,
        message: str,
        value: Optional[float] = None,
        details: Optional[Dict] = None,
    ):
        """Log a position event."""
        await self.log(ActivityLogEntry(
            event_type=EventType.POSITION,
            event_subtype=subtype,
            message=message,
            symbol=symbol,
            asset_class=asset_class,
            value=value,
            details=details,
        ))

    async def log_data(
        self,
        subtype: EventSubtype,
        message: str,
        symbol: Optional[str] = None,
        broker: Optional[str] = None,
        duration_ms: Optional[int] = None,
        details: Optional[Dict] = None,
    ):
        """Log a data fetch event."""
        await self.log(ActivityLogEntry(
            event_type=EventType.DATA,
            event_subtype=subtype,
            message=message,
            symbol=symbol,
            broker=broker,
            duration_ms=duration_ms,
            details=details,
        ))

    # ========== Query methods ==========

    def get_recent_logs(self, limit: int = 100) -> List[Dict]:
        """Get recent logs from the in-memory buffer."""
        return list(reversed(self._buffer[-limit:]))

    def get_logs_by_type(self, event_type: str, limit: int = 100) -> List[Dict]:
        """Get logs filtered by event type."""
        filtered = [
            log for log in reversed(self._buffer)
            if log.get("event_type") == event_type
        ]
        return filtered[:limit]

    def get_logs_by_symbol(self, symbol: str, limit: int = 100) -> List[Dict]:
        """Get logs filtered by symbol."""
        filtered = [
            log for log in reversed(self._buffer)
            if log.get("symbol") == symbol
        ]
        return filtered[:limit]

    def get_error_logs(self, limit: int = 50) -> List[Dict]:
        """Get error logs from the buffer."""
        filtered = [
            log for log in reversed(self._buffer)
            if log.get("severity") in ["error", "critical", "warning"]
        ]
        return filtered[:limit]

    def get_stats(self) -> Dict[str, Any]:
        """Get logging statistics."""
        return {
            "session_id": self.session_id,
            "started_at": self._started_at.isoformat(),
            "uptime_seconds": (datetime.now() - self._started_at).total_seconds(),
            "total_logs": self._log_count,
            "buffer_size": len(self._buffer),
            "logs_by_type": self._count_by_type(),
            "logs_by_severity": self._count_by_severity(),
        }

    def _count_by_type(self) -> Dict[str, int]:
        """Count logs by event type."""
        counts = {}
        for log in self._buffer:
            event_type = log.get("event_type", "unknown")
            counts[event_type] = counts.get(event_type, 0) + 1
        return counts

    def _count_by_severity(self) -> Dict[str, int]:
        """Count logs by severity."""
        counts = {}
        for log in self._buffer:
            severity = log.get("severity", "unknown")
            counts[severity] = counts.get(severity, 0) + 1
        return counts


# Singleton instance
_activity_logger: Optional[BotActivityLogger] = None


def get_activity_logger() -> BotActivityLogger:
    """Get or create the singleton activity logger."""
    global _activity_logger
    if _activity_logger is None:
        _activity_logger = BotActivityLogger()
    return _activity_logger


def reset_activity_logger():
    """Reset the activity logger (useful for testing)."""
    global _activity_logger
    _activity_logger = None
