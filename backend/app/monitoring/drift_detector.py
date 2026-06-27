"""
Production Model Monitoring — Drift Detection & Staleness.

Detects when:
1. Feature distributions shift (Kolmogorov-Smirnov test)
2. Prediction distributions shift (model output drift)
3. Model becomes stale (performance decay over time)
4. Automatic retraining triggers

References:
- Rabanser et al. (2019) "Failing Loudly: An Empirical Study of Methods for Detecting Dataset Shift"
- Lipton et al. (2018) "Detecting and Correcting for Label Shift"
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from collections import deque
import numpy as np
import pandas as pd
import logging

logger = logging.getLogger(__name__)


@dataclass
class DriftEvent:
    """A detected distribution drift event."""
    timestamp: datetime
    drift_type: str  # "feature", "prediction", "performance"
    feature_name: Optional[str]  # Which feature drifted (for feature drift)
    ks_statistic: float  # KS test statistic
    p_value: float  # KS test p-value
    severity: str  # "low", "medium", "high", "critical"
    description: str


@dataclass
class StalenessReport:
    """Model staleness assessment."""
    model_age_days: int
    last_retrain_date: Optional[datetime]
    recent_ic: float  # Recent Information Coefficient
    baseline_ic: float  # IC at time of training
    ic_decay_pct: float  # How much IC has decayed
    is_stale: bool
    recommended_action: str  # "ok", "monitor", "retrain_soon", "retrain_now"


class DistributionDriftDetector:
    """
    Detect distribution shifts in features and predictions using
    the two-sample Kolmogorov-Smirnov test.

    Maintains a reference distribution (from training time) and compares
    recent data against it. When KS statistic exceeds threshold, drift
    is flagged.
    """

    def __init__(
        self,
        reference_window: int = 252,
        test_window: int = 63,
        ks_threshold: float = 0.05,  # p-value threshold for significance
        max_features_to_track: int = 50,
    ):
        self.reference_window = reference_window
        self.test_window = test_window
        self.ks_threshold = ks_threshold
        self.max_features_to_track = max_features_to_track

        self._reference_data: Dict[str, np.ndarray] = {}
        self._recent_data: Dict[str, deque] = {}
        self._drift_events: List[DriftEvent] = []

    def set_reference(self, X: pd.DataFrame) -> None:
        """
        Set reference distributions from training data.

        Args:
            X: Training feature DataFrame
        """
        # Track top features by variance (most informative for drift)
        variances = X.var().sort_values(ascending=False)
        features_to_track = variances.index[:self.max_features_to_track].tolist()

        for col in features_to_track:
            values = X[col].dropna().values
            if len(values) > 0:
                self._reference_data[col] = values[-self.reference_window:]
                self._recent_data[col] = deque(maxlen=self.test_window)

        logger.info(f"Drift detector: tracking {len(self._reference_data)} features")

    def add_observation(self, features: pd.Series) -> List[DriftEvent]:
        """
        Add a new observation and check for drift.

        Args:
            features: Single observation (row) of features

        Returns:
            List of any drift events detected
        """
        events = []

        for col in self._reference_data:
            if col in features.index and not np.isnan(features[col]):
                self._recent_data[col].append(features[col])

        # Only check when we have enough recent data
        sample_col = next(iter(self._recent_data), None)
        if sample_col and len(self._recent_data[sample_col]) >= self.test_window:
            events = self.check_drift()

        return events

    def check_drift(self) -> List[DriftEvent]:
        """
        Run KS test on all tracked features.

        Returns:
            List of DriftEvent for any features with significant drift
        """
        from scipy.stats import ks_2samp

        events = []
        n_drifted = 0

        for col, ref_data in self._reference_data.items():
            recent = np.array(self._recent_data[col])
            if len(recent) < 20:
                continue

            ks_stat, p_value = ks_2samp(ref_data, recent)

            if p_value < self.ks_threshold:
                n_drifted += 1
                severity = self._classify_severity(ks_stat, p_value)

                event = DriftEvent(
                    timestamp=datetime.now(),
                    drift_type="feature",
                    feature_name=col,
                    ks_statistic=ks_stat,
                    p_value=p_value,
                    severity=severity,
                    description=(
                        f"Feature '{col}' distribution shifted: "
                        f"KS={ks_stat:.3f}, p={p_value:.4f}"
                    ),
                )
                events.append(event)
                self._drift_events.append(event)

        if n_drifted > 0:
            logger.warning(
                f"Distribution drift detected in {n_drifted}/{len(self._reference_data)} features"
            )

        return events

    def _classify_severity(self, ks_stat: float, p_value: float) -> str:
        """Classify drift severity based on KS statistic magnitude."""
        if ks_stat > 0.3 or p_value < 0.001:
            return "critical"
        elif ks_stat > 0.2 or p_value < 0.01:
            return "high"
        elif ks_stat > 0.1:
            return "medium"
        return "low"

    def get_drift_summary(self) -> Dict:
        """Get summary of recent drift events."""
        recent = [e for e in self._drift_events
                  if e.timestamp > datetime.now() - timedelta(days=7)]

        if not recent:
            return {
                "status": "stable",
                "n_drifted_features": 0,
                "recommendation": "No action needed",
            }

        critical = [e for e in recent if e.severity in ("critical", "high")]

        return {
            "status": "drifting" if critical else "minor_drift",
            "n_drifted_features": len(set(e.feature_name for e in recent)),
            "worst_drift": max(recent, key=lambda e: e.ks_statistic).feature_name,
            "worst_ks": max(e.ks_statistic for e in recent),
            "recommendation": (
                "Retrain model immediately" if len(critical) > 5
                else "Monitor closely" if critical
                else "No action needed"
            ),
        }


class ModelStalenessTracker:
    """
    Track model staleness by monitoring IC decay over time.

    A model becomes stale when its predictive power (measured by
    Information Coefficient = rank correlation with forward returns)
    degrades below a threshold relative to its training-time IC.
    """

    def __init__(
        self,
        ic_decay_threshold: float = 0.5,  # Retrain when IC decays by 50%
        max_age_days: int = 90,  # Force retrain after 90 days
        monitoring_window: int = 21,  # Days of recent IC to average
    ):
        self.ic_decay_threshold = ic_decay_threshold
        self.max_age_days = max_age_days
        self.monitoring_window = monitoring_window

        self._train_date: Optional[datetime] = None
        self._baseline_ic: float = 0.0
        self._ic_history: deque = deque(maxlen=252)

    def register_model(self, train_date: datetime, baseline_ic: float) -> None:
        """Register a newly trained model."""
        self._train_date = train_date
        self._baseline_ic = baseline_ic
        self._ic_history.clear()
        logger.info(
            f"Registered model trained on {train_date.date()}, baseline IC={baseline_ic:.4f}"
        )

    def add_ic_observation(self, ic: float) -> None:
        """Add a daily IC observation."""
        self._ic_history.append(ic)

    def assess_staleness(self) -> StalenessReport:
        """Assess whether the model needs retraining."""
        if self._train_date is None:
            return StalenessReport(
                model_age_days=0, last_retrain_date=None,
                recent_ic=0.0, baseline_ic=0.0, ic_decay_pct=0.0,
                is_stale=True, recommended_action="retrain_now",
            )

        age_days = (datetime.now() - self._train_date).days

        # Recent IC
        if len(self._ic_history) >= self.monitoring_window:
            recent_ic = float(np.mean(list(self._ic_history)[-self.monitoring_window:]))
        elif len(self._ic_history) > 0:
            recent_ic = float(np.mean(list(self._ic_history)))
        else:
            recent_ic = self._baseline_ic

        # IC decay
        if abs(self._baseline_ic) > 1e-6:
            ic_decay_pct = max(0, 1 - recent_ic / self._baseline_ic)
        else:
            ic_decay_pct = 0.0

        # Decision logic
        is_stale = False
        action = "ok"

        if age_days > self.max_age_days:
            is_stale = True
            action = "retrain_now"
        elif ic_decay_pct > self.ic_decay_threshold:
            is_stale = True
            action = "retrain_now"
        elif ic_decay_pct > self.ic_decay_threshold * 0.6:
            action = "retrain_soon"
        elif ic_decay_pct > self.ic_decay_threshold * 0.3:
            action = "monitor"

        report = StalenessReport(
            model_age_days=age_days,
            last_retrain_date=self._train_date,
            recent_ic=recent_ic,
            baseline_ic=self._baseline_ic,
            ic_decay_pct=ic_decay_pct,
            is_stale=is_stale,
            recommended_action=action,
        )

        if is_stale:
            logger.warning(
                f"Model is STALE: age={age_days}d, IC decay={ic_decay_pct:.1%}, action={action}"
            )

        return report


class PnLAttributionEngine:
    """
    Attribute P&L to different sources: alpha, beta, costs, timing.

    Decomposes total portfolio return into:
    - Market beta return (passive exposure)
    - Alpha return (model skill)
    - Transaction cost drag
    - Timing effect (rebalance timing)
    """

    def __init__(self):
        self._daily_records: List[Dict] = []

    def record_daily(
        self,
        portfolio_return: float,
        market_return: float,
        portfolio_beta: float,
        transaction_costs: float,
        n_trades: int,
    ) -> Dict[str, float]:
        """
        Record and decompose a single day's P&L.

        Returns:
            Attribution dict with {beta_return, alpha_return, cost_drag, total}
        """
        beta_return = portfolio_beta * market_return
        alpha_return = portfolio_return - beta_return + transaction_costs
        cost_drag = -transaction_costs

        attribution = {
            "total_return": portfolio_return,
            "beta_return": beta_return,
            "alpha_return": alpha_return,
            "cost_drag": cost_drag,
            "market_return": market_return,
            "n_trades": n_trades,
        }

        self._daily_records.append(attribution)
        return attribution

    def get_cumulative_attribution(self, lookback_days: int = 252) -> Dict[str, float]:
        """Get cumulative P&L attribution over a period."""
        records = self._daily_records[-lookback_days:] if self._daily_records else []

        if not records:
            return {
                "total_return": 0.0,
                "beta_return": 0.0,
                "alpha_return": 0.0,
                "cost_drag": 0.0,
                "alpha_sharpe": 0.0,
            }

        total = sum(r["total_return"] for r in records)
        beta = sum(r["beta_return"] for r in records)
        alpha = sum(r["alpha_return"] for r in records)
        costs = sum(r["cost_drag"] for r in records)

        # Alpha Sharpe (annualized)
        alpha_daily = [r["alpha_return"] for r in records]
        alpha_mean = np.mean(alpha_daily)
        alpha_std = np.std(alpha_daily) + 1e-8
        alpha_sharpe = (alpha_mean * 252) / (alpha_std * np.sqrt(252))

        return {
            "total_return": total,
            "beta_return": beta,
            "alpha_return": alpha,
            "cost_drag": costs,
            "alpha_sharpe": float(alpha_sharpe),
            "n_days": len(records),
        }


class ProductionMonitor:
    """
    Master production monitoring system combining all detectors.

    Provides a single interface for:
    - Feature drift detection
    - Model staleness tracking
    - P&L attribution
    - Retraining triggers
    - Alert notifications (webhook, Slack, email via NotificationDispatcher)
    """

    def __init__(self, notification_dispatcher=None):
        self.drift_detector = DistributionDriftDetector()
        self.staleness_tracker = ModelStalenessTracker()
        self.pnl_engine = PnLAttributionEngine()
        self._alerts: List[str] = []
        self._dispatcher = notification_dispatcher  # Optional NotificationDispatcher

    def initialize_from_training(
        self,
        X_train: pd.DataFrame,
        baseline_ic: float,
        train_date: Optional[datetime] = None,
    ) -> None:
        """Initialize monitors after model training."""
        self.drift_detector.set_reference(X_train)
        self.staleness_tracker.register_model(
            train_date or datetime.now(), baseline_ic
        )
        logger.info("Production monitor initialized from training data")

    def daily_check(
        self,
        features: Optional[pd.Series] = None,
        daily_ic: Optional[float] = None,
        portfolio_return: float = 0.0,
        market_return: float = 0.0,
        portfolio_beta: float = 1.0,
        transaction_costs: float = 0.0,
        n_trades: int = 0,
    ) -> Dict:
        """
        Run all daily monitoring checks.

        Returns:
            Combined status report
        """
        alerts = []

        # 1. Check feature drift
        drift_events = []
        if features is not None:
            drift_events = self.drift_detector.add_observation(features)
            if drift_events:
                alerts.append(
                    f"Feature drift detected in {len(drift_events)} features"
                )

        # 2. Check model staleness
        if daily_ic is not None:
            self.staleness_tracker.add_ic_observation(daily_ic)
        staleness = self.staleness_tracker.assess_staleness()
        if staleness.is_stale:
            alerts.append(
                f"Model is stale: age={staleness.model_age_days}d, "
                f"IC decay={staleness.ic_decay_pct:.1%}"
            )

        # 3. P&L attribution
        attribution = self.pnl_engine.record_daily(
            portfolio_return, market_return,
            portfolio_beta, transaction_costs, n_trades
        )

        self._alerts = alerts

        # Dispatch notifications if dispatcher is configured
        if self._dispatcher and alerts:
            self._dispatch_alerts(alerts, drift_events, staleness)

        return {
            "timestamp": datetime.now().isoformat(),
            "drift": self.drift_detector.get_drift_summary(),
            "staleness": {
                "model_age_days": staleness.model_age_days,
                "ic_decay_pct": staleness.ic_decay_pct,
                "is_stale": staleness.is_stale,
                "action": staleness.recommended_action,
            },
            "daily_attribution": attribution,
            "cumulative_attribution": self.pnl_engine.get_cumulative_attribution(),
            "alerts": alerts,
            "needs_retrain": staleness.is_stale or len(drift_events) > 10,
        }

    def _dispatch_alerts(self, alerts, drift_events, staleness):
        """Send detected issues to notification channels."""
        try:
            from .notifications import Notification, Severity

            for alert_msg in alerts:
                # Determine severity based on content
                if staleness.is_stale and staleness.recommended_action == "retrain_now":
                    severity = Severity.CRITICAL
                elif "drift" in alert_msg.lower() and len(drift_events) > 5:
                    severity = Severity.CRITICAL
                elif "stale" in alert_msg.lower() or "drift" in alert_msg.lower():
                    severity = Severity.WARNING
                else:
                    severity = Severity.INFO

                notification = Notification(
                    title="Production Monitor Alert",
                    message=alert_msg,
                    severity=severity,
                    source="production_monitor",
                    metadata={
                        "model_age_days": str(staleness.model_age_days),
                        "ic_decay_pct": f"{staleness.ic_decay_pct:.1%}",
                        "n_drift_events": str(len(drift_events)),
                    },
                )
                self._dispatcher.dispatch(notification)
        except Exception as e:
            logger.error(f"Failed to dispatch notifications: {e}")
