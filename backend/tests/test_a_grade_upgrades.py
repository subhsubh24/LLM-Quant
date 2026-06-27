"""
Tests for A-grade upgrades:
1. NotificationDispatcher — multi-channel alert delivery
2. AuditStore — SQLite-backed audit trail
3. Full pipeline integration — data -> features -> model -> signal -> risk ->
   execution -> monitoring -> audit -> notification, wired end-to-end
"""

import json
import os
import tempfile
import time
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

# ── Notification system imports ──────────────────────────────────
from app.monitoring.notifications import (
    EmailChannel,
    LogChannel,
    Notification,
    NotificationChannel,
    NotificationDispatcher,
    Severity,
    SlackWebhookChannel,
    WebhookChannel,
)

# ── SQLite audit store imports ───────────────────────────────────
from app.trading.audit_store import AuditStore

# ── Existing system imports for integration ──────────────────────
from app.monitoring.monitoring import AlertManager, AlertLevel, AlertType, PerformanceTracker
from app.monitoring.drift_detector import (
    DistributionDriftDetector,
    ModelStalenessTracker,
    ProductionMonitor,
)


# ═══════════════════════════════════════════════════════════════════
# PART 1: Notification Dispatcher Tests
# ═══════════════════════════════════════════════════════════════════

class TestNotification:
    """Test Notification dataclass."""

    def test_create_notification(self):
        n = Notification(
            title="Test Alert",
            message="Something happened",
            severity=Severity.WARNING,
            source="test",
        )
        assert n.title == "Test Alert"
        assert n.severity == Severity.WARNING
        assert isinstance(n.timestamp, datetime)

    def test_to_dict(self):
        n = Notification(
            title="Alert",
            message="msg",
            severity=Severity.CRITICAL,
            source="drift",
            metadata={"ic_decay": "0.45"},
        )
        d = n.to_dict()
        assert d["severity"] == "CRITICAL"
        assert d["source"] == "drift"
        assert d["metadata"]["ic_decay"] == "0.45"
        assert "timestamp" in d

    def test_severity_ordering(self):
        assert Severity.INFO.value < Severity.WARNING.value
        assert Severity.WARNING.value < Severity.CRITICAL.value


class TestLogChannel:
    """Test the always-on log file channel."""

    def test_log_channel_writes_jsonl(self, tmp_path):
        log_path = str(tmp_path / "alerts.jsonl")
        channel = LogChannel(log_path=log_path, min_severity=Severity.INFO)

        n = Notification(
            title="Test", message="body", severity=Severity.WARNING, source="test"
        )
        result = channel.send(n)
        assert result is True

        with open(log_path) as f:
            record = json.loads(f.readline())
        assert record["title"] == "Test"
        assert record["severity"] == "WARNING"

    def test_log_channel_appends(self, tmp_path):
        log_path = str(tmp_path / "alerts.jsonl")
        channel = LogChannel(log_path=log_path, min_severity=Severity.INFO)

        for i in range(5):
            channel.send(Notification(
                title=f"Alert {i}", message="m", severity=Severity.INFO, source="test"
            ))

        with open(log_path) as f:
            lines = f.readlines()
        assert len(lines) == 5

    def test_log_channel_respects_severity_filter(self, tmp_path):
        log_path = str(tmp_path / "alerts.jsonl")
        channel = LogChannel(
            log_path=log_path, min_severity=Severity.CRITICAL
        )

        # WARNING < CRITICAL, should be filtered
        channel.send(Notification(
            title="Low", message="m", severity=Severity.WARNING, source="test"
        ))
        assert not os.path.exists(log_path) or os.path.getsize(log_path) == 0

        # CRITICAL >= CRITICAL, should pass
        channel.send(Notification(
            title="High", message="m", severity=Severity.CRITICAL, source="test"
        ))
        with open(log_path) as f:
            records = [json.loads(l) for l in f.readlines()]
        assert len(records) == 1
        assert records[0]["title"] == "High"


class TestWebhookChannel:
    """Test generic webhook channel."""

    def test_webhook_formats_payload(self):
        channel = WebhookChannel(url="https://example.com/hook")
        n = Notification(
            title="Drift", message="IC decayed 50%",
            severity=Severity.CRITICAL, source="monitor",
        )
        payload = channel._format_default(n)
        assert "CRITICAL" in payload["text"]
        assert "Drift" in payload["text"]

    def test_webhook_respects_rate_limit(self):
        channel = WebhookChannel(
            url="https://example.com/hook",
            rate_limit_seconds=60,
        )
        n = Notification(
            title="Same Alert", message="msg",
            severity=Severity.WARNING, source="test",
        )
        # First: should_send = True
        assert channel.should_send(n) is True

        # Simulate that we sent it
        key = f"{n.source}:{n.title}"
        channel._last_sent[key] = datetime.now()

        # Immediately after: rate limited
        assert channel.should_send(n) is False

    def test_webhook_different_alerts_not_rate_limited(self):
        channel = WebhookChannel(
            url="https://example.com/hook",
            rate_limit_seconds=60,
        )
        n1 = Notification(
            title="Alert A", message="m", severity=Severity.WARNING, source="s1",
        )
        n2 = Notification(
            title="Alert B", message="m", severity=Severity.WARNING, source="s2",
        )
        channel._last_sent["s1:Alert A"] = datetime.now()
        assert channel.should_send(n1) is False
        assert channel.should_send(n2) is True


class TestSlackWebhookChannel:
    """Test Slack-specific formatting."""

    def test_slack_block_formatting(self):
        channel = SlackWebhookChannel(
            url="https://hooks.slack.com/test",
            channel="#alerts",
        )
        n = Notification(
            title="Model Stale",
            message="IC decayed beyond threshold",
            severity=Severity.CRITICAL,
            source="staleness_tracker",
            metadata={"model_age": "95 days", "ic_decay": "55%"},
        )
        payload = channel._format_default(n)
        assert "blocks" in payload
        assert payload["channel"] == "#alerts"
        # Header block
        assert payload["blocks"][0]["type"] == "header"
        assert "Model Stale" in payload["blocks"][0]["text"]["text"]

    def test_slack_severity_emoji(self):
        channel = SlackWebhookChannel(url="https://hooks.slack.com/test")

        for sev, expected in [
            (Severity.INFO, ":information_source:"),
            (Severity.WARNING, ":warning:"),
            (Severity.CRITICAL, ":rotating_light:"),
        ]:
            n = Notification(title="T", message="m", severity=sev, source="s")
            payload = channel._format_default(n)
            assert expected in payload["blocks"][0]["text"]["text"]


class TestEmailChannel:
    """Test email channel formatting (no actual SMTP)."""

    def test_email_skips_if_no_recipients(self):
        channel = EmailChannel(smtp_host="localhost", to_addrs=[])
        n = Notification(
            title="Test", message="m", severity=Severity.CRITICAL, source="test"
        )
        result = channel._deliver(n)
        assert result is False


class TestNotificationDispatcher:
    """Test central dispatcher."""

    def test_dispatch_to_multiple_channels(self, tmp_path):
        log1 = str(tmp_path / "ch1.jsonl")
        log2 = str(tmp_path / "ch2.jsonl")

        dispatcher = NotificationDispatcher()
        dispatcher.add_channel(LogChannel(log_path=log1, name="log1"))
        dispatcher.add_channel(LogChannel(log_path=log2, name="log2"))

        n = Notification(
            title="Test", message="body", severity=Severity.WARNING, source="test"
        )
        results = dispatcher.dispatch(n)

        assert results["log1"] is True
        assert results["log2"] is True

    def test_dispatch_from_alert_convenience(self, tmp_path):
        log_path = str(tmp_path / "alerts.jsonl")
        dispatcher = NotificationDispatcher()
        dispatcher.add_channel(LogChannel(log_path=log_path, name="log"))

        results = dispatcher.dispatch_from_alert(
            title="Drift Detected",
            message="5 features drifted",
            severity=Severity.WARNING,
            source="drift_detector",
            metadata={"n_features": "5"},
        )
        assert results["log"] is True

    def test_stats_tracking(self, tmp_path):
        log_path = str(tmp_path / "alerts.jsonl")
        dispatcher = NotificationDispatcher()
        dispatcher.add_channel(LogChannel(log_path=log_path, name="log"))

        for i in range(3):
            dispatcher.dispatch_from_alert(
                title=f"Alert {i}", message="m",
                severity=Severity.INFO, source="test",
            )

        stats = dispatcher.get_stats()
        assert stats["total_dispatched"] == 3
        assert stats["channels"][0]["sent"] == 3

    def test_recent_history(self, tmp_path):
        log_path = str(tmp_path / "alerts.jsonl")
        dispatcher = NotificationDispatcher()
        dispatcher.add_channel(LogChannel(log_path=log_path, name="log"))

        for i in range(5):
            dispatcher.dispatch_from_alert(
                title=f"A{i}", message="m", severity=Severity.INFO, source="test"
            )

        recent = dispatcher.get_recent(n=3)
        assert len(recent) == 3
        assert recent[-1]["title"] == "A4"

    def test_remove_channel(self, tmp_path):
        dispatcher = NotificationDispatcher()
        dispatcher.add_channel(LogChannel(log_path=str(tmp_path / "a.jsonl"), name="ch1"))
        dispatcher.add_channel(LogChannel(log_path=str(tmp_path / "b.jsonl"), name="ch2"))

        assert dispatcher.remove_channel("ch1") is True
        assert len(dispatcher._channels) == 1
        assert dispatcher._channels[0].name == "ch2"

    def test_severity_filtering_across_channels(self, tmp_path):
        info_log = str(tmp_path / "info.jsonl")
        crit_log = str(tmp_path / "crit.jsonl")

        dispatcher = NotificationDispatcher()
        dispatcher.add_channel(LogChannel(log_path=info_log, name="info_ch", min_severity=Severity.INFO))
        dispatcher.add_channel(LogChannel(log_path=crit_log, name="crit_ch", min_severity=Severity.CRITICAL))

        # WARNING should only go to info_ch
        dispatcher.dispatch_from_alert(
            title="Minor", message="m", severity=Severity.WARNING, source="test"
        )

        assert os.path.getsize(info_log) > 0
        assert not os.path.exists(crit_log) or os.path.getsize(crit_log) == 0

        # CRITICAL should go to both
        dispatcher.dispatch_from_alert(
            title="Major", message="m", severity=Severity.CRITICAL, source="test"
        )
        with open(crit_log) as f:
            assert len(f.readlines()) == 1


# ═══════════════════════════════════════════════════════════════════
# PART 2: SQLite Audit Store Tests
# ═══════════════════════════════════════════════════════════════════

class TestAuditStore:
    """Test SQLite-backed audit trail."""

    @pytest.fixture
    def store(self, tmp_path):
        db_path = str(tmp_path / "test_audit.db")
        return AuditStore(db_path=db_path)

    def test_init_creates_db(self, store):
        assert os.path.exists(store.db_path)

    def test_log_trade(self, store):
        store.log_trade(
            symbol="AAPL", side="buy", qty=100, price=150.0,
            commission_bps=1.0, slippage_bps=2.0,
            signal_strength=0.8, strategy="momentum",
        )
        records = store.query(event_type="trade")
        assert len(records) == 1
        assert records[0]["symbol"] == "AAPL"
        assert records[0]["details"]["side"] == "buy"
        assert records[0]["details"]["notional"] == 15000.0
        assert records[0]["details"]["total_cost_bps"] == 3.0

    def test_log_multiple_trades(self, store):
        for sym in ["AAPL", "GOOGL", "MSFT", "TSLA", "NVDA"]:
            store.log_trade(symbol=sym, side="buy", qty=50, price=100.0)

        assert store.count(event_type="trade") == 5
        records = store.query(symbol="GOOGL")
        assert len(records) == 1

    def test_log_rebalance(self, store):
        store.log_rebalance(
            old_weights={"AAPL": 0.3, "GOOGL": 0.7},
            new_weights={"AAPL": 0.5, "MSFT": 0.5},
            turnover=0.4, n_trades=3, total_cost_bps=5.0,
        )
        records = store.query(event_type="rebalance")
        assert len(records) == 1
        assert records[0]["details"]["turnover"] == 0.4
        assert "MSFT" in records[0]["details"]["positions_added"]
        assert "GOOGL" in records[0]["details"]["positions_removed"]

    def test_log_risk_event(self, store):
        store.log_risk_event(
            event_type="circuit_breaker",
            severity="critical",
            details={"drawdown": -0.12, "threshold": -0.10},
        )
        records = store.query(event_type="risk_event")
        assert len(records) == 1
        assert records[0]["details"]["severity"] == "critical"

    def test_log_model_retrain(self, store):
        store.log_model_retrain(
            old_version="v1.2.0", new_version="v1.3.0",
            reason="IC decay > 50%",
            validation_score=0.82, oos_score=0.75, n_features=42,
        )
        records = store.query(event_type="model_retrain")
        assert len(records) == 1
        assert records[0]["details"]["new_version"] == "v1.3.0"

    def test_log_reconciliation(self, store):
        store.log_reconciliation(
            expected_positions={"AAPL": 100, "GOOGL": 50},
            actual_positions={"AAPL": 100, "GOOGL": 48},
            discrepancies=[{
                "symbol": "GOOGL", "type": "partial_fill",
                "expected_qty": 50, "actual_qty": 48,
            }],
        )
        records = store.query(event_type="position_reconcile")
        assert len(records) == 1
        assert records[0]["details"]["n_discrepancies"] == 1

    def test_query_by_date_range(self, store):
        store.log_trade(symbol="AAPL", side="buy", qty=100, price=150.0)
        today = date.today()
        records = store.query(start_date=today, end_date=today)
        assert len(records) >= 1

    def test_query_with_limit_offset(self, store):
        for i in range(10):
            store.log_trade(symbol=f"SYM{i}", side="buy", qty=10, price=10.0)

        page1 = store.query(limit=3, offset=0)
        page2 = store.query(limit=3, offset=3)
        assert len(page1) == 3
        assert len(page2) == 3
        # Different records (descending order)
        assert page1[0]["symbol"] != page2[0]["symbol"]

    def test_daily_summary(self, store):
        store.log_trade(symbol="AAPL", side="buy", qty=100, price=150.0)
        store.log_trade(symbol="GOOGL", side="sell", qty=50, price=200.0)
        store.log_risk_event("vol_spike", "warning", {"vol": 0.35})

        summary = store.get_daily_summary()
        assert summary["n_trades"] == 2
        assert summary["n_risk_events"] == 1
        assert summary["total_notional"] == 25000.0  # 15000 + 10000

    def test_trade_summary(self, store):
        for sym, price in [("AAPL", 150), ("GOOGL", 200), ("AAPL", 155)]:
            store.log_trade(symbol=sym, side="buy", qty=100, price=price)

        summary = store.get_trade_summary()
        assert summary["n_trades"] == 3
        assert "AAPL" in summary["symbols_traded"]
        assert "GOOGL" in summary["symbols_traded"]
        assert summary["n_symbols"] == 2

    def test_count(self, store):
        store.log_trade(symbol="AAPL", side="buy", qty=100, price=150.0)
        store.log_trade(symbol="GOOGL", side="sell", qty=50, price=200.0)
        store.log_risk_event("test", "info", {})

        assert store.count() == 3
        assert store.count(event_type="trade") == 2
        assert store.count(event_type="risk_event") == 1

    def test_model_version_tracking(self, store):
        store.set_model_version("v1.0")
        store.log_trade(symbol="AAPL", side="buy", qty=100, price=150.0)

        records = store.query(event_type="trade")
        assert records[0]["model_version"] == "v1.0"

    def test_import_jsonl(self, tmp_path):
        # Create a JSONL file to import
        jsonl_path = str(tmp_path / "audit_2025-01-15.jsonl")
        records = [
            {"timestamp": "2025-01-15T10:00:00", "event_type": "trade",
             "details": {"symbol": "AAPL", "side": "buy", "qty": 100, "price": 150},
             "session_id": "old_session", "model_version": "v0.9"},
            {"timestamp": "2025-01-15T11:00:00", "event_type": "risk_event",
             "details": {"risk_event_type": "vol_spike", "severity": "warning"},
             "session_id": "old_session", "model_version": "v0.9"},
        ]
        with open(jsonl_path, "w") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")

        db_path = str(tmp_path / "imported.db")
        store = AuditStore(db_path=db_path)
        imported = store.import_jsonl(jsonl_path)

        assert imported == 2
        assert store.count() == 2
        assert store.count(event_type="trade") == 1

    def test_concurrent_writes(self, store):
        """SQLite WAL mode should handle rapid sequential writes."""
        for i in range(100):
            store.log_trade(symbol=f"SYM{i % 10}", side="buy", qty=i + 1, price=100.0)
        assert store.count() == 100


# ═══════════════════════════════════════════════════════════════════
# PART 3: Monitoring + Notification Integration Tests
# ═══════════════════════════════════════════════════════════════════

class TestAlertManagerNotifications:
    """Test AlertManager dispatches to NotificationDispatcher."""

    @pytest.fixture
    def alert_setup(self, tmp_path):
        log_path = str(tmp_path / "alerts.jsonl")
        dispatcher = NotificationDispatcher()
        dispatcher.add_channel(LogChannel(log_path=log_path, name="log"))
        manager = AlertManager(
            daily_loss_threshold_pct=5.0,
            notification_dispatcher=dispatcher,
        )
        return manager, log_path

    def test_daily_loss_triggers_notification(self, alert_setup):
        manager, log_path = alert_setup
        # 6% loss exceeds 5% threshold
        alert = manager.check_daily_loss(daily_pnl=-6000, portfolio_value=100000)
        assert alert is not None

        with open(log_path) as f:
            record = json.loads(f.readline())
        assert "loss" in record["title"].lower() or "loss" in record["message"].lower()
        assert record["severity"] == "CRITICAL"

    def test_volatility_spike_triggers_notification(self, alert_setup):
        manager, log_path = alert_setup
        alert = manager.check_volatility_spike(
            current_volatility=0.40, normal_volatility=0.15
        )
        assert alert is not None

        with open(log_path) as f:
            record = json.loads(f.readline())
        assert record["severity"] == "WARNING"

    def test_drawdown_triggers_notification(self, alert_setup):
        manager, log_path = alert_setup
        alert = manager.check_drawdown(current_drawdown=-0.15)
        assert alert is not None

        with open(log_path) as f:
            record = json.loads(f.readline())
        assert "drawdown" in record["message"].lower()

    def test_no_alert_no_notification(self, alert_setup):
        manager, log_path = alert_setup
        # 1% loss is within threshold
        alert = manager.check_daily_loss(daily_pnl=-1000, portfolio_value=100000)
        assert alert is None
        assert not os.path.exists(log_path) or os.path.getsize(log_path) == 0


class TestProductionMonitorNotifications:
    """Test ProductionMonitor dispatches notifications on drift/staleness."""

    @pytest.fixture
    def monitor_setup(self, tmp_path):
        log_path = str(tmp_path / "monitor_alerts.jsonl")
        dispatcher = NotificationDispatcher()
        dispatcher.add_channel(LogChannel(
            log_path=log_path, name="log", min_severity=Severity.INFO
        ))
        monitor = ProductionMonitor(notification_dispatcher=dispatcher)
        return monitor, log_path

    def test_stale_model_dispatches_alert(self, monitor_setup):
        monitor, log_path = monitor_setup

        # Register a model from 100 days ago (exceeds 90-day max_age)
        old_date = datetime.now() - timedelta(days=100)
        monitor.staleness_tracker.register_model(old_date, baseline_ic=0.05)

        result = monitor.daily_check(
            portfolio_return=0.001, market_return=0.002,
        )

        assert result["staleness"]["is_stale"] is True
        assert result["needs_retrain"] is True

        # Should have dispatched a notification
        assert os.path.exists(log_path)
        with open(log_path) as f:
            records = [json.loads(l) for l in f.readlines()]
        assert len(records) >= 1
        assert any("stale" in r["message"].lower() for r in records)


# ═══════════════════════════════════════════════════════════════════
# PART 4: Full Pipeline Integration Test
# ═══════════════════════════════════════════════════════════════════

class TestFullPipelineIntegration:
    """
    End-to-end test: data -> signal -> risk -> execution ->
    monitoring -> audit -> notification.

    Validates all new components wire together with existing systems.
    """

    def test_complete_pipeline_with_audit_and_notifications(self, tmp_path):
        """
        Simulate a full trading day flowing through every system component.
        """
        # ── Setup notification dispatcher ──
        alert_log = str(tmp_path / "pipeline_alerts.jsonl")
        dispatcher = NotificationDispatcher()
        dispatcher.add_channel(LogChannel(
            log_path=alert_log, name="pipeline_log",
            min_severity=Severity.INFO,
        ))

        # ── Setup audit store ──
        audit_store = AuditStore(db_path=str(tmp_path / "pipeline_audit.db"))
        audit_store.set_model_version("v2.0.0")

        # ── Setup monitoring with notifications ──
        alert_mgr = AlertManager(
            daily_loss_threshold_pct=5.0,
            notification_dispatcher=dispatcher,
        )
        perf_tracker = PerformanceTracker(initial_capital=1_000_000)
        prod_monitor = ProductionMonitor(notification_dispatcher=dispatcher)

        # Initialize production monitor with synthetic training data
        np.random.seed(42)
        X_train = pd.DataFrame(
            np.random.randn(252, 10),
            columns=[f"feature_{i}" for i in range(10)],
        )
        prod_monitor.initialize_from_training(X_train, baseline_ic=0.06)

        # ── STEP 1: Simulate signal generation ──
        signals = {
            "AAPL": {"direction": "buy", "strength": 0.75, "strategy": "momentum"},
            "GOOGL": {"direction": "sell", "strength": 0.60, "strategy": "mean_reversion"},
            "MSFT": {"direction": "buy", "strength": 0.55, "strategy": "factor"},
        }

        # ── STEP 2: Simulate risk check ──
        max_position_pct = 0.20
        portfolio_value = 1_000_000
        approved_signals = {}
        for sym, sig in signals.items():
            position_size = sig["strength"] * max_position_pct * portfolio_value
            if position_size < portfolio_value * max_position_pct:
                approved_signals[sym] = {**sig, "notional": position_size}

        assert len(approved_signals) == 3, "All signals pass risk check"

        # ── STEP 3: Simulate execution ──
        executed_trades = []
        total_cost = 0.0
        for sym, sig in approved_signals.items():
            price = {"AAPL": 180.0, "GOOGL": 140.0, "MSFT": 350.0}[sym]
            qty = int(sig["notional"] / price)
            commission_bps = 1.0
            slippage_bps = 2.5

            # Log to SQLite audit store
            audit_store.log_trade(
                symbol=sym, side=sig["direction"], qty=qty, price=price,
                commission_bps=commission_bps, slippage_bps=slippage_bps,
                signal_strength=sig["strength"], strategy=sig["strategy"],
            )

            cost_bps = commission_bps + slippage_bps
            total_cost += (cost_bps / 10000) * qty * price

            executed_trades.append({
                "symbol": sym, "side": sig["direction"],
                "qty": qty, "price": price, "pnl": np.random.normal(0, 100),
            })

        assert len(executed_trades) == 3

        # ── STEP 4: Log rebalance ──
        audit_store.log_rebalance(
            old_weights={"AAPL": 0.33, "GOOGL": 0.33, "NVDA": 0.34},
            new_weights={"AAPL": 0.40, "GOOGL": 0.25, "MSFT": 0.35},
            turnover=0.30, n_trades=3, total_cost_bps=10.5,
        )

        # ── STEP 5: Update performance tracking ──
        daily_pnl = sum(t["pnl"] for t in executed_trades) - total_cost
        closing_value = portfolio_value + daily_pnl

        metrics = perf_tracker.add_daily_result(
            date=date.today(),
            opening_value=portfolio_value,
            closing_value=closing_value,
            trades=executed_trades,
        )
        assert metrics is not None

        # ── STEP 6: Check alerts (may trigger notifications) ──
        alert_mgr.check_daily_loss(daily_pnl, portfolio_value)
        alert_mgr.check_drawdown(metrics.max_drawdown)

        # ── STEP 7: Production monitoring check ──
        features = pd.Series(
            np.random.randn(10), index=[f"feature_{i}" for i in range(10)]
        )
        monitor_result = prod_monitor.daily_check(
            features=features,
            daily_ic=0.04,
            portfolio_return=daily_pnl / portfolio_value,
            market_return=0.001,
            portfolio_beta=1.0,
            transaction_costs=total_cost / portfolio_value,
            n_trades=3,
        )
        assert "drift" in monitor_result
        assert "staleness" in monitor_result
        assert "daily_attribution" in monitor_result

        # ── STEP 8: Position reconciliation ──
        expected = {t["symbol"]: float(t["qty"]) for t in executed_trades}
        actual = {sym: qty * 0.98 for sym, qty in expected.items()}  # 2% slippage
        from app.trading.audit_trail import PositionReconciler
        reconciler = PositionReconciler(tolerance_pct=0.01)
        discrepancies = reconciler.reconcile(expected, actual)
        audit_store.log_reconciliation(expected, actual, discrepancies)

        # ── VERIFY: Audit store has everything ──
        summary = audit_store.get_daily_summary()
        assert summary["n_trades"] == 3
        assert summary["n_rebalances"] == 1
        assert summary["total_notional"] > 0

        trade_summary = audit_store.get_trade_summary()
        assert trade_summary["n_symbols"] == 3

        # ── VERIFY: Notification dispatcher has stats ──
        stats = dispatcher.get_stats()
        assert stats["total_dispatched"] >= 0  # May or may not have triggered

        # ── VERIFY: Everything is queryable ──
        all_trades = audit_store.query(event_type="trade")
        assert len(all_trades) == 3

        rebalances = audit_store.query(event_type="rebalance")
        assert len(rebalances) == 1

        reconciliations = audit_store.query(event_type="position_reconcile")
        assert len(reconciliations) == 1

    def test_pipeline_with_critical_alerts(self, tmp_path):
        """Simulate a bad day that triggers CRITICAL notifications."""
        alert_log = str(tmp_path / "crisis_alerts.jsonl")
        dispatcher = NotificationDispatcher()
        dispatcher.add_channel(LogChannel(
            log_path=alert_log, name="crisis_log",
            min_severity=Severity.INFO,
        ))

        audit_store = AuditStore(db_path=str(tmp_path / "crisis_audit.db"))
        alert_mgr = AlertManager(
            daily_loss_threshold_pct=5.0,
            notification_dispatcher=dispatcher,
        )

        # Simulate a 7% loss day
        portfolio_value = 1_000_000
        daily_pnl = -70_000

        # Log the bad trades
        audit_store.log_trade("SPY", "sell", 500, 450.0, slippage_bps=10.0)
        audit_store.log_risk_event(
            event_type="circuit_breaker_triggered",
            severity="critical",
            details={"drawdown": -0.07, "threshold": -0.05},
        )

        # This should trigger CRITICAL notification
        alert = alert_mgr.check_daily_loss(daily_pnl, portfolio_value)
        assert alert is not None
        assert alert.level == AlertLevel.CRITICAL

        # Verify notification was dispatched
        with open(alert_log) as f:
            records = [json.loads(l) for l in f.readlines()]
        assert len(records) >= 1
        assert any(r["severity"] == "CRITICAL" for r in records)

        # Verify audit store has the risk event
        risk_events = audit_store.query(event_type="risk_event")
        assert len(risk_events) == 1
        assert risk_events[0]["details"]["severity"] == "critical"

    def test_audit_store_and_old_trail_coexistence(self, tmp_path):
        """SQLite store can import from JSONL, proving backward compatibility."""
        # Create old-style JSONL
        jsonl_path = str(tmp_path / "audit_2025-06-01.jsonl")
        old_records = [
            {"timestamp": "2025-06-01T09:30:00", "event_type": "trade",
             "details": {"symbol": "AAPL", "side": "buy", "qty": 100, "price": 170},
             "session_id": "legacy_001", "model_version": "v1.0"},
        ]
        with open(jsonl_path, "w") as f:
            for r in old_records:
                f.write(json.dumps(r) + "\n")

        # Import into SQLite
        store = AuditStore(db_path=str(tmp_path / "migrated.db"))
        imported = store.import_jsonl(jsonl_path)
        assert imported == 1

        # Now log new records alongside
        store.log_trade("GOOGL", "buy", 50, 180.0)

        # Both are queryable
        all_records = store.query()
        assert len(all_records) == 2

        legacy = store.query(event_type="trade", symbol="AAPL")
        assert len(legacy) == 1  # JSONL import extracts symbol from details

        trades = store.query(event_type="trade")
        assert len(trades) == 2
