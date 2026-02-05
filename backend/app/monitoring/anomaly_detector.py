"""
Anomaly Detection - Phase 15

Advanced monitoring with:
1. Statistical anomaly detection (3-sigma methodology)
2. Feature importance tracking (which factors matter most)
3. Cost attribution analysis (where money is lost/made)
4. Real-time alerts and escalation

Expected improvements:
- Early warning for market regime changes
- Tracking of alpha contributors
- Cost transparency and optimization
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime, timedelta
from collections import deque
import logging

logger = logging.getLogger(__name__)


@dataclass
class AnomalyEvent:
    """Statistical anomaly event."""
    timestamp: datetime
    metric_name: str
    value: float
    threshold_upper: float
    threshold_lower: float
    severity: float  # 0-1
    description: str


@dataclass
class CostAttribution:
    """Cost attribution breakdown."""
    total_cost_bps: float
    spread_cost_bps: float
    participation_cost_bps: float
    market_impact_bps: float
    slippage_cost_bps: float
    vix_premium_bps: float


class StatisticalAnomalyDetector:
    """Detect anomalies using 3-sigma statistical methodology."""

    def __init__(
        self,
        lookback_window: int = 252,
        num_sigmas: float = 3.0,
        min_history: int = 30,
    ):
        """Initialize anomaly detector.

        Args:
            lookback_window: Days of history for baseline
            num_sigmas: Number of standard deviations for thresholds
            min_history: Minimum samples required before detection
        """
        self.lookback_window = lookback_window
        self.num_sigmas = num_sigmas
        self.min_history = min_history
        self.metric_history = {}  # metric_name -> deque of values

    def add_observation(
        self,
        metric_name: str,
        value: float,
        timestamp: Optional[datetime] = None,
    ):
        """Add observation to history.

        Args:
            metric_name: Name of metric
            value: Metric value
            timestamp: Observation timestamp
        """
        if metric_name not in self.metric_history:
            self.metric_history[metric_name] = deque(maxlen=self.lookback_window)

        self.metric_history[metric_name].append(value)

    def detect_anomaly(self, metric_name: str, value: float) -> Optional[AnomalyEvent]:
        """Detect if value is anomalous.

        Args:
            metric_name: Name of metric
            value: Current value

        Returns:
            AnomalyEvent if anomaly detected, else None
        """
        if metric_name not in self.metric_history:
            return None

        history = list(self.metric_history[metric_name])
        if len(history) < self.min_history:
            return None

        # Compute statistics (ignoring current value)
        mean = np.mean(history)
        std = np.std(history)

        if std < 1e-10:
            # No variation, no anomalies possible
            return None

        # 3-sigma thresholds
        threshold_upper = mean + self.num_sigmas * std
        threshold_lower = mean - self.num_sigmas * std

        # Check if anomalous
        if value > threshold_upper:
            z_score = (value - mean) / std
            severity = min((z_score - self.num_sigmas) / self.num_sigmas, 1.0)

            return AnomalyEvent(
                timestamp=datetime.now(),
                metric_name=metric_name,
                value=value,
                threshold_upper=threshold_upper,
                threshold_lower=threshold_lower,
                severity=severity,
                description=f"{metric_name} abnormally high: {value:.2f} (threshold: {threshold_upper:.2f})",
            )

        elif value < threshold_lower:
            z_score = (mean - value) / std
            severity = min((z_score - self.num_sigmas) / self.num_sigmas, 1.0)

            return AnomalyEvent(
                timestamp=datetime.now(),
                metric_name=metric_name,
                value=value,
                threshold_upper=threshold_upper,
                threshold_lower=threshold_lower,
                severity=severity,
                description=f"{metric_name} abnormally low: {value:.2f} (threshold: {threshold_lower:.2f})",
            )

        return None

    def get_thresholds(self, metric_name: str) -> Optional[Dict]:
        """Get current thresholds for metric.

        Args:
            metric_name: Name of metric

        Returns:
            Dict with mean, std, upper, lower thresholds
        """
        if metric_name not in self.metric_history:
            return None

        history = list(self.metric_history[metric_name])
        if len(history) < self.min_history:
            return None

        mean = np.mean(history)
        std = np.std(history)

        return {
            'mean': float(mean),
            'std': float(std),
            'upper_threshold': float(mean + self.num_sigmas * std),
            'lower_threshold': float(mean - self.num_sigmas * std),
        }


class FeatureImportanceTracker:
    """Track feature importance over time."""

    def __init__(self, window_size: int = 63):
        """Initialize feature importance tracker.

        Args:
            window_size: Days in rolling window
        """
        self.window_size = window_size
        self.importance_history = {}  # feature_name -> list of importances
        self.timestamps = []

    def add_importances(
        self,
        importances: Dict[str, float],
        timestamp: Optional[datetime] = None,
    ):
        """Add feature importance snapshot.

        Args:
            importances: Dict of feature -> importance
            timestamp: Timestamp of snapshot
        """
        if timestamp is None:
            timestamp = datetime.now()

        self.timestamps.append(timestamp)

        for feature, importance in importances.items():
            if feature not in self.importance_history:
                self.importance_history[feature] = []

            self.importance_history[feature].append(importance)

    def get_average_importance(self) -> Dict[str, float]:
        """Get average feature importance across window.

        Returns:
            Dict of feature -> average importance
        """
        averages = {}
        for feature, importances in self.importance_history.items():
            # Use recent window
            recent = importances[-self.window_size:]
            averages[feature] = float(np.mean(recent))

        return dict(sorted(averages.items(), key=lambda x: x[1], reverse=True))

    def detect_importance_shift(self, threshold: float = 0.2) -> List[Dict]:
        """Detect significant shifts in feature importance.

        Args:
            threshold: Relative change threshold (20% = 0.2)

        Returns:
            List of {feature, old_importance, new_importance, change_pct}
        """
        shifts = []

        for feature, importances in self.importance_history.items():
            if len(importances) >= 2:
                old_importance = np.mean(importances[:-self.window_size // 2])
                new_importance = np.mean(importances[-self.window_size // 2:])

                if old_importance > 1e-6:
                    change_pct = abs(new_importance - old_importance) / old_importance

                    if change_pct > threshold:
                        shifts.append({
                            'feature': feature,
                            'old_importance': float(old_importance),
                            'new_importance': float(new_importance),
                            'change_pct': float(change_pct),
                            'direction': 'increasing' if new_importance > old_importance else 'decreasing',
                        })

        return sorted(shifts, key=lambda x: x['change_pct'], reverse=True)

    def get_top_features(self, n: int = 10) -> List[Tuple[str, float]]:
        """Get top N important features.

        Args:
            n: Number of top features

        Returns:
            List of (feature, importance) tuples
        """
        avg_importance = self.get_average_importance()
        return list(avg_importance.items())[:n]


class CostAttributionEngine:
    """Analyze and attribute trading costs."""

    def __init__(self, window_size: int = 63):
        """Initialize cost attribution engine.

        Args:
            window_size: Days in rolling window
        """
        self.window_size = window_size
        self.cost_history = []  # List of CostAttribution

    def add_execution_costs(
        self,
        total_cost_bps: float,
        spread_cost_bps: float,
        participation_cost_bps: float,
        market_impact_bps: float,
        slippage_cost_bps: float,
        vix_premium_bps: float,
    ):
        """Record execution costs.

        Args:
            total_cost_bps: Total cost in basis points
            spread_cost_bps: Half-spread component
            participation_cost_bps: Participation cost component
            market_impact_bps: Market impact component
            slippage_cost_bps: Slippage component
            vix_premium_bps: VIX premium component
        """
        cost = CostAttribution(
            total_cost_bps=total_cost_bps,
            spread_cost_bps=spread_cost_bps,
            participation_cost_bps=participation_cost_bps,
            market_impact_bps=market_impact_bps,
            slippage_cost_bps=slippage_cost_bps,
            vix_premium_bps=vix_premium_bps,
        )

        self.cost_history.append(cost)

        # Keep only recent window
        if len(self.cost_history) > self.window_size:
            self.cost_history = self.cost_history[-self.window_size:]

    def get_cost_breakdown(self) -> Dict[str, float]:
        """Get breakdown of average costs.

        Returns:
            Average costs by component
        """
        if not self.cost_history:
            return {}

        components = {
            'total_cost_bps': [],
            'spread_cost_bps': [],
            'participation_cost_bps': [],
            'market_impact_bps': [],
            'slippage_cost_bps': [],
            'vix_premium_bps': [],
        }

        for cost in self.cost_history:
            components['total_cost_bps'].append(cost.total_cost_bps)
            components['spread_cost_bps'].append(cost.spread_cost_bps)
            components['participation_cost_bps'].append(cost.participation_cost_bps)
            components['market_impact_bps'].append(cost.market_impact_bps)
            components['slippage_cost_bps'].append(cost.slippage_cost_bps)
            components['vix_premium_bps'].append(cost.vix_premium_bps)

        return {k: float(np.mean(v)) for k, v in components.items()}

    def get_cost_trends(self) -> Dict:
        """Get trends in execution costs.

        Returns:
            Cost trends {component: mean, trend_direction, trend_pct}
        """
        if len(self.cost_history) < 2:
            return {}

        trends = {}

        # Total cost trend
        recent_costs = [c.total_cost_bps for c in self.cost_history[-self.window_size // 2:]]
        older_costs = [c.total_cost_bps for c in self.cost_history[:self.window_size // 2]]

        if older_costs:
            old_mean = np.mean(older_costs)
            new_mean = np.mean(recent_costs)
            trend_pct = (new_mean - old_mean) / max(old_mean, 0.01) * 100

            trends['total_cost'] = {
                'recent_mean': float(new_mean),
                'older_mean': float(old_mean),
                'trend_pct': float(trend_pct),
                'trend_direction': 'increasing' if trend_pct > 0 else 'decreasing',
            }

        # Spread cost trend
        recent_spreads = [c.spread_cost_bps for c in self.cost_history[-self.window_size // 2:]]
        older_spreads = [c.spread_cost_bps for c in self.cost_history[:self.window_size // 2]]

        if older_spreads:
            old_spread = np.mean(older_spreads)
            new_spread = np.mean(recent_spreads)
            spread_trend = (new_spread - old_spread) / max(old_spread, 0.01) * 100

            trends['spread_cost'] = {
                'recent_mean': float(new_spread),
                'older_mean': float(old_spread),
                'trend_pct': float(spread_trend),
            }

        return trends

    def identify_cost_drivers(self) -> List[Dict]:
        """Identify which costs are driving total cost highest.

        Returns:
            Ranked list of cost components
        """
        breakdown = self.get_cost_breakdown()

        components = [
            {'component': 'spread', 'cost_bps': breakdown.get('spread_cost_bps', 0)},
            {'component': 'participation', 'cost_bps': breakdown.get('participation_cost_bps', 0)},
            {'component': 'market_impact', 'cost_bps': breakdown.get('market_impact_bps', 0)},
            {'component': 'slippage', 'cost_bps': breakdown.get('slippage_cost_bps', 0)},
            {'component': 'vix_premium', 'cost_bps': breakdown.get('vix_premium_bps', 0)},
        ]

        return sorted(components, key=lambda x: x['cost_bps'], reverse=True)


class ComprehensiveAnomalyMonitor:
    """Master anomaly detector combining all techniques."""

    def __init__(self):
        """Initialize comprehensive monitor."""
        self.statistical_detector = StatisticalAnomalyDetector()
        self.feature_tracker = FeatureImportanceTracker()
        self.cost_analyzer = CostAttributionEngine()
        self.anomalies = []

    def monitor_sharpe_ratio(self, sharpe: float):
        """Monitor Sharpe ratio for anomalies.

        Args:
            sharpe: Current Sharpe ratio
        """
        self.statistical_detector.add_observation('sharpe_ratio', sharpe)
        anomaly = self.statistical_detector.detect_anomaly('sharpe_ratio', sharpe)
        if anomaly:
            self.anomalies.append(anomaly)

    def monitor_drawdown(self, drawdown: float):
        """Monitor drawdown for anomalies.

        Args:
            drawdown: Current drawdown (negative)
        """
        self.statistical_detector.add_observation('drawdown', drawdown)
        anomaly = self.statistical_detector.detect_anomaly('drawdown', drawdown)
        if anomaly:
            self.anomalies.append(anomaly)

    def monitor_volatility(self, volatility: float):
        """Monitor realized volatility.

        Args:
            volatility: Current realized volatility
        """
        self.statistical_detector.add_observation('volatility', volatility)
        anomaly = self.statistical_detector.detect_anomaly('volatility', volatility)
        if anomaly:
            self.anomalies.append(anomaly)

    def monitor_correlation(self, correlation: float):
        """Monitor portfolio correlation.

        Args:
            correlation: Current correlation
        """
        self.statistical_detector.add_observation('correlation', correlation)
        anomaly = self.statistical_detector.detect_anomaly('correlation', correlation)
        if anomaly:
            self.anomalies.append(anomaly)

    def monitor_execution_cost(self, cost_bps: float):
        """Monitor execution costs.

        Args:
            cost_bps: Execution cost in basis points
        """
        self.statistical_detector.add_observation('execution_cost', cost_bps)
        anomaly = self.statistical_detector.detect_anomaly('execution_cost', cost_bps)
        if anomaly:
            self.anomalies.append(anomaly)

    def get_health_status(self) -> Dict:
        """Get overall system health status.

        Returns:
            Health status {anomaly_count, severity, recommendations}
        """
        # Keep only recent anomalies (last 100)
        self.anomalies = self.anomalies[-100:]

        if not self.anomalies:
            return {
                'status': 'HEALTHY',
                'anomaly_count': 0,
                'avg_severity': 0.0,
            }

        # Compute statistics
        anomaly_count = len(self.anomalies)
        severities = [a.severity for a in self.anomalies]
        avg_severity = np.mean(severities)

        # Determine status
        if avg_severity > 0.8 or anomaly_count > 20:
            status = 'CRITICAL'
        elif avg_severity > 0.5 or anomaly_count > 10:
            status = 'WARNING'
        elif avg_severity > 0.3 or anomaly_count > 5:
            status = 'CAUTION'
        else:
            status = 'HEALTHY'

        # Get recommendations
        recommendations = []
        high_severity = [a for a in self.anomalies if a.severity > 0.7]

        if high_severity:
            metrics = [a.metric_name for a in high_severity]
            recommendations.append(f"High anomalies detected in: {', '.join(set(metrics))}")

        return {
            'status': status,
            'anomaly_count': anomaly_count,
            'avg_severity': float(avg_severity),
            'high_severity_count': len(high_severity),
            'recommendations': recommendations,
        }

    def get_alert_summary(self, max_alerts: int = 5) -> List[Dict]:
        """Get most severe recent alerts.

        Args:
            max_alerts: Maximum number of alerts to return

        Returns:
            List of alert dictionaries
        """
        # Sort by severity and timestamp
        sorted_anomalies = sorted(
            self.anomalies,
            key=lambda a: (a.severity, a.timestamp),
            reverse=True,
        )

        return [
            {
                'timestamp': a.timestamp.isoformat(),
                'metric': a.metric_name,
                'value': float(a.value),
                'severity': float(a.severity),
                'description': a.description,
            }
            for a in sorted_anomalies[:max_alerts]
        ]
