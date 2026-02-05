"""
Monitoring & Health System - Phase 8

Real-time system health tracking with alerts:
1. Strategy Health Scoring: Performance, Sharpe, drawdown tracking
2. Model Degradation Alerts: Accuracy, calibration, concept drift
3. Correlation Monitoring: Portfolio concentration, correlation spikes
4. Execution Quality: Slippage, cost tracking, failure rate
5. Latency Monitoring: Response time, P99 latency
6. Data Feed Health: Staleness, gaps, quality metrics

EXPECTED IMPACT: 0 Sharpe (operational, non-trading)
But enables faster problem detection and reduces crisis response time.
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class HealthStatus(Enum):
    """System health status levels."""
    HEALTHY = "healthy"
    CAUTION = "caution"
    WARNING = "warning"
    CRITICAL = "critical"
    OFFLINE = "offline"


class AlertLevel(Enum):
    """Alert severity levels."""
    INFO = "info"
    WARNING = "warning"
    ALERT = "alert"
    CRITICAL = "critical"


@dataclass
class HealthAlert:
    """Single health alert."""
    component: str  # 'strategy', 'model', 'execution', etc.
    level: AlertLevel
    timestamp: datetime
    message: str
    metric_value: float
    threshold: float
    extra_info: Dict = field(default_factory=dict)


@dataclass
class ComponentHealth:
    """Health status of single component."""
    name: str
    status: HealthStatus
    score: float  # 0-100
    timestamp: datetime
    last_check: datetime
    alerts: List[HealthAlert] = field(default_factory=list)
    metrics: Dict[str, float] = field(default_factory=dict)


class StrategyHealthMonitor:
    """Monitor strategy performance and health."""

    def __init__(self, lookback_windows: Dict[str, int] = None):
        """Initialize strategy health monitor.

        Args:
            lookback_windows: {'daily': 1, 'weekly': 5, 'monthly': 20}
        """
        self.lookback_windows = lookback_windows or {
            'daily': 1,
            'weekly': 5,
            'monthly': 20,
        }
        self.strategy_returns: Dict[str, List[float]] = {}
        self.strategy_trades: Dict[str, List[Dict]] = {}

    def record_return(self, strategy_id: str, daily_return: float):
        """Record daily return for strategy."""
        if strategy_id not in self.strategy_returns:
            self.strategy_returns[strategy_id] = []

        self.strategy_returns[strategy_id].append(daily_return)

        # Keep last 252 days
        if len(self.strategy_returns[strategy_id]) > 252:
            self.strategy_returns[strategy_id].pop(0)

    def record_trade(self, strategy_id: str, trade: Dict):
        """Record trade for strategy."""
        if strategy_id not in self.strategy_trades:
            self.strategy_trades[strategy_id] = []

        self.strategy_trades[strategy_id].append({
            'timestamp': datetime.now(),
            **trade,
        })

        # Keep last 1000 trades
        if len(self.strategy_trades[strategy_id]) > 1000:
            self.strategy_trades[strategy_id].pop(0)

    def compute_health_score(self, strategy_id: str) -> ComponentHealth:
        """Compute strategy health score.

        Factors:
        - Sharpe ratio (0-30 points)
        - Win rate (0-20 points)
        - Max drawdown (0-20 points)
        - Trade frequency (0-15 points)
        - Consistency (0-15 points)
        """
        returns = self.strategy_returns.get(strategy_id, [])

        if len(returns) < 20:
            return ComponentHealth(
                name=strategy_id,
                status=HealthStatus.CAUTION,
                score=0.0,
                timestamp=datetime.now(),
                last_check=datetime.now(),
                metrics={'insufficient_data': True},
            )

        # Compute Sharpe ratio (0-30 points)
        mean_return = np.mean(returns)
        std_return = np.std(returns)
        sharpe = (mean_return / max(std_return, 1e-10)) * np.sqrt(252)
        sharpe_score = min(30, max(0, sharpe * 5))  # Scale to 0-30

        # Compute max drawdown (0-20 points)
        cumulative = np.cumprod(1 + np.array(returns))
        running_max = np.maximum.accumulate(cumulative)
        drawdown = np.min((cumulative - running_max) / running_max)
        dd_score = max(0, 20 + drawdown * 100)  # Max -100% = 0 points

        # Compute win rate (0-20 points)
        wins = sum(1 for r in returns if r > 0)
        win_rate = wins / len(returns) if returns else 0
        wr_score = win_rate * 20

        # Compute consistency (0-15 points)
        # Low volatility = consistent = higher score
        cv = std_return / max(abs(mean_return), 1e-10)
        consistency_score = max(0, 15 - cv * 5)

        # Trade frequency (0-15 points)
        trades = self.strategy_trades.get(strategy_id, [])
        trades_per_day = len(trades) / max(len(returns), 1)

        # Optimal: 0.5-2 trades per day
        if 0.5 <= trades_per_day <= 2.0:
            freq_score = 15
        elif 0 <= trades_per_day <= 0.5 or 2.0 < trades_per_day <= 5.0:
            freq_score = 10
        else:
            freq_score = 5

        # Total score
        total_score = sharpe_score + dd_score + wr_score + consistency_score + freq_score

        # Determine status
        if total_score >= 85:
            status = HealthStatus.HEALTHY
        elif total_score >= 70:
            status = HealthStatus.CAUTION
        elif total_score >= 50:
            status = HealthStatus.WARNING
        else:
            status = HealthStatus.CRITICAL

        return ComponentHealth(
            name=strategy_id,
            status=status,
            score=float(total_score),
            timestamp=datetime.now(),
            last_check=datetime.now(),
            metrics={
                'sharpe_ratio': float(sharpe),
                'max_drawdown': float(drawdown),
                'win_rate': float(win_rate),
                'consistency': float(1 / cv if cv > 0 else 1),
                'trades_per_day': float(trades_per_day),
            },
        )


class ModelDegradationMonitor:
    """Monitor ML model performance and degradation."""

    def __init__(self, degradation_threshold: float = 0.1):
        """Initialize model degradation monitor.

        Args:
            degradation_threshold: Sharpe drop % to trigger alert
        """
        self.degradation_threshold = degradation_threshold
        self.model_accuracy: Dict[str, List[float]] = {}
        self.model_predictions: Dict[str, List[Dict]] = {}

    def record_prediction(
        self,
        model_id: str,
        prediction: float,
        actual: float,
        confidence: float,
    ):
        """Record model prediction for comparison."""
        if model_id not in self.model_predictions:
            self.model_predictions[model_id] = []

        self.model_predictions[model_id].append({
            'timestamp': datetime.now(),
            'prediction': prediction,
            'actual': actual,
            'confidence': confidence,
            'error': abs(prediction - actual),
        })

        # Keep last 1000 predictions
        if len(self.model_predictions[model_id]) > 1000:
            self.model_predictions[model_id].pop(0)

    def compute_health_score(self, model_id: str) -> ComponentHealth:
        """Compute model health score.

        Factors:
        - Prediction accuracy (0-40 points)
        - Calibration (0-30 points)
        - Stability (0-20 points)
        - Drift detection (0-10 points)
        """
        predictions = self.model_predictions.get(model_id, [])

        if len(predictions) < 50:
            return ComponentHealth(
                name=model_id,
                status=HealthStatus.CAUTION,
                score=50.0,
                timestamp=datetime.now(),
                last_check=datetime.now(),
                metrics={'insufficient_predictions': True},
            )

        # Recent vs older accuracy
        recent = predictions[-50:]
        older = predictions[-100:-50] if len(predictions) > 100 else predictions[-50:]

        recent_errors = [p['error'] for p in recent]
        older_errors = [p['error'] for p in older]

        recent_accuracy = 1.0 - (np.mean(recent_errors) / 2.0)  # Max error = 2.0
        older_accuracy = 1.0 - (np.mean(older_errors) / 2.0)

        # Accuracy score (0-40)
        accuracy_score = recent_accuracy * 40

        # Degradation detection (0-10)
        accuracy_drop = older_accuracy - recent_accuracy
        if accuracy_drop > self.degradation_threshold:
            degradation_score = 0  # Alert!
        else:
            degradation_score = 10 - (accuracy_drop / self.degradation_threshold * 10)

        # Calibration: confidence vs accuracy (0-30)
        confidences = [p['confidence'] for p in recent]
        avg_confidence = np.mean(confidences)

        # Calibration: confidence should match accuracy
        calibration_error = abs(avg_confidence - recent_accuracy)
        calibration_score = max(0, 30 - calibration_error * 50)

        # Stability: consistency of predictions (0-20)
        recent_preds = [p['prediction'] for p in recent]
        pred_std = np.std(recent_preds)
        pred_mean = np.mean(recent_preds)

        # Lower std = more stable
        stability = 1.0 / (1.0 + pred_std / max(abs(pred_mean), 1e-10))
        stability_score = stability * 20

        # Total score
        total_score = (
            accuracy_score + degradation_score + calibration_score + stability_score
        )

        # Determine status
        if total_score >= 85:
            status = HealthStatus.HEALTHY
        elif total_score >= 70:
            status = HealthStatus.CAUTION
        elif total_score >= 50:
            status = HealthStatus.WARNING
        else:
            status = HealthStatus.CRITICAL

        return ComponentHealth(
            name=model_id,
            status=status,
            score=float(total_score),
            timestamp=datetime.now(),
            last_check=datetime.now(),
            metrics={
                'recent_accuracy': float(recent_accuracy),
                'accuracy_trend': float(recent_accuracy - older_accuracy),
                'calibration_error': float(calibration_error),
                'stability': float(stability),
            },
        )


class CorrelationMonitor:
    """Monitor portfolio correlation and concentration."""

    def __init__(self, correlation_alert_threshold: float = 0.85):
        """Initialize correlation monitor.

        Args:
            correlation_alert_threshold: Alert when avg correlation exceeds this
        """
        self.correlation_alert_threshold = correlation_alert_threshold
        self.correlation_history: List[Tuple[datetime, float]] = []

    def update_correlation(self, corr_matrix: pd.DataFrame):
        """Update with new correlation matrix."""
        if corr_matrix is None or corr_matrix.empty:
            return

        # Get off-diagonal correlations
        mask = ~np.eye(len(corr_matrix), dtype=bool)
        off_diag = corr_matrix.values[mask]

        avg_corr = float(np.mean(off_diag))
        max_corr = float(np.max(off_diag))

        self.correlation_history.append((datetime.now(), avg_corr))

        # Keep last 252 days
        cutoff = datetime.now() - timedelta(days=252)
        self.correlation_history = [
            (ts, corr) for ts, corr in self.correlation_history
            if ts >= cutoff
        ]

    def compute_health_score(self) -> ComponentHealth:
        """Compute correlation health score.

        Good: avg < 0.40 (diversified)
        Caution: 0.40-0.60
        Warning: 0.60-0.80
        Critical: > 0.80 (concentrated)
        """
        if not self.correlation_history:
            return ComponentHealth(
                name='correlation',
                status=HealthStatus.CAUTION,
                score=50.0,
                timestamp=datetime.now(),
                last_check=datetime.now(),
            )

        recent_corrs = [c for _, c in self.correlation_history[-20:]]
        avg_corr = np.mean(recent_corrs)
        trend = recent_corrs[-1] - recent_corrs[0] if len(recent_corrs) > 1 else 0

        # Score based on correlation level
        if avg_corr < 0.40:
            score = 100 - (avg_corr / 0.40 * 20)  # 80-100
            status = HealthStatus.HEALTHY
        elif avg_corr < 0.60:
            score = 60 + (0.60 - avg_corr) / 0.20 * 20  # 60-80
            status = HealthStatus.CAUTION
        elif avg_corr < 0.80:
            score = 40 + (0.80 - avg_corr) / 0.20 * 20  # 40-60
            status = HealthStatus.WARNING
        else:
            score = max(20, 40 - (avg_corr - 0.80) / 0.20 * 20)  # <40
            status = HealthStatus.CRITICAL

        return ComponentHealth(
            name='correlation',
            status=status,
            score=float(score),
            timestamp=datetime.now(),
            last_check=datetime.now(),
            metrics={
                'avg_correlation': float(avg_corr),
                'correlation_trend': float(trend),
            },
        )


class ExecutionQualityMonitor:
    """Monitor execution quality and costs."""

    def __init__(self):
        """Initialize execution quality monitor."""
        self.executions: List[Dict] = []
        self.failed_executions: List[Dict] = []

    def record_execution(
        self,
        order_id: str,
        expected_cost_bps: float,
        actual_cost_bps: float,
        fill_percentage: float,
        latency_ms: float,
    ):
        """Record execution metrics."""
        self.executions.append({
            'timestamp': datetime.now(),
            'order_id': order_id,
            'expected_cost': expected_cost_bps,
            'actual_cost': actual_cost_bps,
            'cost_slippage': actual_cost_bps - expected_cost_bps,
            'fill_percentage': fill_percentage,
            'latency_ms': latency_ms,
        })

        # Keep last 5000 executions
        if len(self.executions) > 5000:
            self.executions.pop(0)

    def record_failure(self, order_id: str, reason: str, retry_count: int):
        """Record execution failure."""
        self.failed_executions.append({
            'timestamp': datetime.now(),
            'order_id': order_id,
            'reason': reason,
            'retry_count': retry_count,
        })

        # Keep last 1000 failures
        if len(self.failed_executions) > 1000:
            self.failed_executions.pop(0)

    def compute_health_score(self) -> ComponentHealth:
        """Compute execution quality score.

        Factors:
        - Fill rate (0-30 points)
        - Cost efficiency (0-30 points)
        - Latency (0-20 points)
        - Failure rate (0-20 points)
        """
        if len(self.executions) < 10:
            return ComponentHealth(
                name='execution',
                status=HealthStatus.CAUTION,
                score=50.0,
                timestamp=datetime.now(),
                last_check=datetime.now(),
            )

        # Recent executions
        recent = self.executions[-100:]

        # Fill rate (0-30 points)
        avg_fill = np.mean([e['fill_percentage'] for e in recent])
        fill_score = avg_fill * 30

        # Cost efficiency (0-30 points)
        cost_slippage = np.mean([e['cost_slippage'] for e in recent])
        # Good: 0-2 bps slippage, Bad: >10 bps
        cost_score = max(0, 30 - cost_slippage * 3)

        # Latency (0-20 points)
        avg_latency = np.mean([e['latency_ms'] for e in recent])
        # Good: <100ms, Bad: >500ms
        if avg_latency < 100:
            latency_score = 20
        elif avg_latency < 500:
            latency_score = 20 - (avg_latency - 100) / 400 * 15
        else:
            latency_score = 5

        # Failure rate (0-20 points)
        recent_failures = sum(
            1 for f in self.failed_executions
            if f['timestamp'] > datetime.now() - timedelta(hours=1)
        )
        failure_rate = recent_failures / max(len(recent), 1)
        failure_score = max(0, 20 - failure_rate * 100)

        # Total score
        total_score = fill_score + cost_score + latency_score + failure_score

        # Determine status
        if total_score >= 85:
            status = HealthStatus.HEALTHY
        elif total_score >= 70:
            status = HealthStatus.CAUTION
        elif total_score >= 50:
            status = HealthStatus.WARNING
        else:
            status = HealthStatus.CRITICAL

        return ComponentHealth(
            name='execution',
            status=status,
            score=float(total_score),
            timestamp=datetime.now(),
            last_check=datetime.now(),
            metrics={
                'avg_fill_percentage': float(avg_fill),
                'avg_cost_slippage_bps': float(cost_slippage),
                'avg_latency_ms': float(avg_latency),
                'failure_rate': float(failure_rate),
            },
        )


class LatencyMonitor:
    """Monitor system latency and response times."""

    def __init__(self):
        """Initialize latency monitor."""
        self.latencies: Dict[str, List[float]] = {}

    def record_latency(self, operation: str, latency_ms: float):
        """Record operation latency."""
        if operation not in self.latencies:
            self.latencies[operation] = []

        self.latencies[operation].append(latency_ms)

        # Keep last 10000 measurements
        if len(self.latencies[operation]) > 10000:
            self.latencies[operation].pop(0)

    def compute_p99(self, operation: str) -> float:
        """Compute P99 latency for operation."""
        latencies = self.latencies.get(operation, [])

        if not latencies:
            return 0.0

        return float(np.percentile(latencies, 99))

    def compute_health_score(self) -> ComponentHealth:
        """Compute latency health score."""
        if not self.latencies:
            return ComponentHealth(
                name='latency',
                status=HealthStatus.CAUTION,
                score=50.0,
                timestamp=datetime.now(),
                last_check=datetime.now(),
            )

        # Compute P99 for each operation
        p99_values = []
        for op in self.latencies:
            p99 = self.compute_p99(op)
            p99_values.append(p99)

        avg_p99 = np.mean(p99_values)

        # Score based on P99
        # Good: <100ms, Caution: 100-200ms, Warning: 200-500ms, Critical: >500ms
        if avg_p99 < 100:
            score = 100.0
            status = HealthStatus.HEALTHY
        elif avg_p99 < 200:
            score = 80.0
            status = HealthStatus.CAUTION
        elif avg_p99 < 500:
            score = 50.0
            status = HealthStatus.WARNING
        else:
            score = 30.0
            status = HealthStatus.CRITICAL

        return ComponentHealth(
            name='latency',
            status=status,
            score=float(score),
            timestamp=datetime.now(),
            last_check=datetime.now(),
            metrics={
                'p99_latency_ms': float(avg_p99),
                'operations_monitored': len(self.latencies),
            },
        )


class DataFeedHealthMonitor:
    """Monitor data feed quality and freshness."""

    def __init__(self, max_staleness_seconds: float = 300):
        """Initialize data feed monitor.

        Args:
            max_staleness_seconds: Max age before alert
        """
        self.max_staleness_seconds = max_staleness_seconds
        self.last_update: Dict[str, datetime] = {}
        self.gaps: Dict[str, List[Tuple[datetime, datetime]]] = {}

    def record_update(self, feed_id: str, timestamp: datetime = None):
        """Record data feed update."""
        if timestamp is None:
            timestamp = datetime.now()

        self.last_update[feed_id] = timestamp

    def record_gap(self, feed_id: str, start: datetime, end: datetime):
        """Record data feed gap."""
        if feed_id not in self.gaps:
            self.gaps[feed_id] = []

        self.gaps[feed_id].append((start, end))

        # Keep last 100 gaps
        if len(self.gaps[feed_id]) > 100:
            self.gaps[feed_id].pop(0)

    def compute_health_score(self) -> ComponentHealth:
        """Compute data feed health score.

        Factors:
        - Staleness (0-40 points)
        - Gap frequency (0-30 points)
        - Gap duration (0-30 points)
        """
        if not self.last_update:
            return ComponentHealth(
                name='data_feed',
                status=HealthStatus.CAUTION,
                score=50.0,
                timestamp=datetime.now(),
                last_check=datetime.now(),
            )

        now = datetime.now()

        # Staleness score (0-40)
        staleness_scores = []
        for feed_id, last_ts in self.last_update.items():
            staleness = (now - last_ts).total_seconds()

            if staleness < 60:
                score = 40
            elif staleness < self.max_staleness_seconds:
                score = 40 - (staleness / self.max_staleness_seconds) * 30
            else:
                score = 10

            staleness_scores.append(score)

        avg_staleness_score = np.mean(staleness_scores)

        # Gap analysis (0-30 + 0-30)
        total_gap_duration = 0
        gap_frequencies = []

        for feed_id, gaps in self.gaps.items():
            if gaps:
                gap_frequencies.append(len(gaps))
                for start, end in gaps:
                    total_gap_duration += (end - start).total_seconds()

        if gap_frequencies:
            avg_gap_frequency = np.mean(gap_frequencies)
            gap_freq_score = max(0, 30 - avg_gap_frequency * 2)
        else:
            gap_freq_score = 30

        # Duration score (max 5 minutes per gap)
        avg_gap_duration = (total_gap_duration / len(self.gaps) if self.gaps else 0)
        if avg_gap_duration < 60:
            gap_duration_score = 30
        elif avg_gap_duration < 300:
            gap_duration_score = 30 - (avg_gap_duration / 300) * 20
        else:
            gap_duration_score = 10

        # Total score
        total_score = avg_staleness_score + gap_freq_score + gap_duration_score

        # Determine status
        if total_score >= 85:
            status = HealthStatus.HEALTHY
        elif total_score >= 70:
            status = HealthStatus.CAUTION
        elif total_score >= 50:
            status = HealthStatus.WARNING
        else:
            status = HealthStatus.CRITICAL

        return ComponentHealth(
            name='data_feed',
            status=status,
            score=float(total_score),
            timestamp=datetime.now(),
            last_check=datetime.now(),
            metrics={
                'avg_staleness_score': float(avg_staleness_score),
                'gap_frequency_score': float(gap_freq_score),
                'gap_duration_score': float(gap_duration_score),
            },
        )


class SystemHealthDashboard:
    """Master health dashboard aggregating all components."""

    def __init__(self):
        """Initialize system health dashboard."""
        self.strategy_monitor = StrategyHealthMonitor()
        self.model_monitor = ModelDegradationMonitor()
        self.correlation_monitor = CorrelationMonitor()
        self.execution_monitor = ExecutionQualityMonitor()
        self.latency_monitor = LatencyMonitor()
        self.data_monitor = DataFeedHealthMonitor()
        self.alerts: List[HealthAlert] = []

    def compute_system_health(self) -> Dict[str, any]:
        """Compute overall system health.

        Returns: {
            'overall_status': HealthStatus,
            'overall_score': float (0-100),
            'components': [ComponentHealth],
            'critical_alerts': [HealthAlert],
        }
        """
        components = [
            self.strategy_monitor.compute_health_score('default'),
            self.model_monitor.compute_health_score('default'),
            self.correlation_monitor.compute_health_score(),
            self.execution_monitor.compute_health_score(),
            self.latency_monitor.compute_health_score(),
            self.data_monitor.compute_health_score(),
        ]

        # Compute overall score
        scores = [c.score for c in components if c.score > 0]
        overall_score = float(np.mean(scores)) if scores else 50.0

        # Determine overall status
        statuses = [c.status for c in components]
        if any(s == HealthStatus.CRITICAL for s in statuses):
            overall_status = HealthStatus.CRITICAL
        elif any(s == HealthStatus.WARNING for s in statuses):
            overall_status = HealthStatus.WARNING
        elif any(s == HealthStatus.CAUTION for s in statuses):
            overall_status = HealthStatus.CAUTION
        else:
            overall_status = HealthStatus.HEALTHY

        # Collect critical alerts
        critical_alerts = [a for a in self.alerts if a.level == AlertLevel.CRITICAL]

        return {
            'overall_status': overall_status.value,
            'overall_score': overall_score,
            'components': [
                {
                    'name': c.name,
                    'status': c.status.value,
                    'score': c.score,
                    'metrics': c.metrics,
                }
                for c in components
            ],
            'critical_alerts': len(critical_alerts),
            'timestamp': datetime.now().isoformat(),
        }
