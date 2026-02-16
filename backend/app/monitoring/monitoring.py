"""
Real-Time Monitoring & Alerting System

Provides operational observability:
- Live P&L tracking (daily, cumulative)
- Risk metric monitoring (volatility, drawdown, VaR)
- Trade execution logging
- Alert system (threshold-based)
- Performance dashboards
- Health checks

This is critical for paper trading to catch issues early.

References:
- Operational Risk management best practices
- Real-time monitoring patterns
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any, Callable
from datetime import datetime, date, timedelta
from enum import Enum
import numpy as np
import pandas as pd
import logging
import json

logger = logging.getLogger(__name__)


class AlertLevel(Enum):
    """Alert severity levels."""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertType(Enum):
    """Alert types."""
    LOSS_THRESHOLD = "loss_threshold"
    VOLATILITY_SPIKE = "volatility_spike"
    DRAWDOWN_WARNING = "drawdown_warning"
    POSITION_LIMIT = "position_limit"
    EXECUTION_FAILURE = "execution_failure"
    MODEL_DEGRADATION = "model_degradation"
    DATA_QUALITY = "data_quality"


@dataclass
class Alert:
    """Single alert."""
    timestamp: datetime
    alert_type: AlertType
    level: AlertLevel
    message: str
    metrics: Dict[str, float] = field(default_factory=dict)
    recommended_action: str = ""

    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "type": self.alert_type.name,
            "level": self.level.name,
            "message": self.message,
            "metrics": {k: round(v, 4) if isinstance(v, float) else v
                       for k, v in self.metrics.items()},
            "recommended_action": self.recommended_action,
        }


@dataclass
class DailyMetrics:
    """Daily performance metrics."""
    date: date
    opening_value: float
    closing_value: float
    daily_pnl: float
    daily_return_pct: float
    cumulative_return_pct: float
    volatility_annualized: float
    max_drawdown: float
    sharpe_ratio: float
    var_95: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    avg_trade_size: float
    largest_win: float
    largest_loss: float

    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return {
            "date": self.date.isoformat(),
            "opening_value": round(self.opening_value, 2),
            "closing_value": round(self.closing_value, 2),
            "daily_pnl": round(self.daily_pnl, 2),
            "daily_return_pct": round(self.daily_return_pct, 4),
            "cumulative_return_pct": round(self.cumulative_return_pct, 4),
            "volatility": round(self.volatility_annualized, 4),
            "max_drawdown": round(self.max_drawdown, 4),
            "sharpe_ratio": round(self.sharpe_ratio, 2),
            "var_95": round(self.var_95, 4),
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "win_rate": round(self.win_rate, 4),
            "avg_trade_size": round(self.avg_trade_size, 2),
            "largest_win": round(self.largest_win, 2),
            "largest_loss": round(self.largest_loss, 2),
        }


class AlertManager:
    """
    Manages alert generation and delivery.

    Monitors key metrics and triggers alerts when thresholds are breached.
    """

    def __init__(
        self,
        daily_loss_threshold_pct: float = 5.0,
        weekly_loss_threshold_pct: float = 10.0,
        volatility_spike_threshold: float = 2.0,  # Multiples of normal vol
        max_drawdown_warning: float = 0.10,
        execution_failure_threshold: float = 0.05,  # 5% of intended
    ):
        """
        Initialize alert manager.

        Args:
            daily_loss_threshold_pct: Alert if daily loss > this %
            weekly_loss_threshold_pct: Alert if weekly loss > this %
            volatility_spike_threshold: Alert if vol > normal_vol * this
            max_drawdown_warning: Alert if drawdown exceeds this
            execution_failure_threshold: Alert if execution deviation > this
        """
        self.daily_loss_threshold_pct = daily_loss_threshold_pct
        self.weekly_loss_threshold_pct = weekly_loss_threshold_pct
        self.volatility_spike_threshold = volatility_spike_threshold
        self.max_drawdown_warning = max_drawdown_warning
        self.execution_failure_threshold = execution_failure_threshold

        self.alerts: List[Alert] = []
        self.last_volatility_baseline: Optional[float] = None

    def check_daily_loss(
        self,
        daily_pnl: float,
        portfolio_value: float,
    ) -> Optional[Alert]:
        """Check for daily loss threshold breach."""
        daily_loss_pct = abs(daily_pnl) / (portfolio_value + 1e-10)

        if daily_loss_pct > self.daily_loss_threshold_pct / 100:
            alert = Alert(
                timestamp=datetime.now(),
                alert_type=AlertType.LOSS_THRESHOLD,
                level=AlertLevel.CRITICAL,
                message=f"Daily loss of {daily_loss_pct:.2%} exceeds threshold "
                f"({self.daily_loss_threshold_pct}%)",
                metrics={
                    "daily_pnl": daily_pnl,
                    "daily_loss_pct": daily_loss_pct,
                    "threshold_pct": self.daily_loss_threshold_pct / 100,
                },
                recommended_action="Review trades and consider reducing exposure",
            )
            self.alerts.append(alert)
            return alert

        return None

    def check_volatility_spike(
        self,
        current_volatility: float,
        normal_volatility: float = 0.15,
    ) -> Optional[Alert]:
        """Check for volatility spike."""
        if normal_volatility == 0:
            return None

        vol_ratio = current_volatility / normal_volatility

        if vol_ratio > self.volatility_spike_threshold:
            alert = Alert(
                timestamp=datetime.now(),
                alert_type=AlertType.VOLATILITY_SPIKE,
                level=AlertLevel.WARNING,
                message=f"Volatility spike detected: {current_volatility:.2%} "
                f"(normal: {normal_volatility:.2%})",
                metrics={
                    "current_vol": current_volatility,
                    "normal_vol": normal_volatility,
                    "ratio": vol_ratio,
                },
                recommended_action="Consider reducing position sizes or leverage",
            )
            self.alerts.append(alert)
            return alert

        self.last_volatility_baseline = normal_volatility
        return None

    def check_drawdown(self, current_drawdown: float) -> Optional[Alert]:
        """Check for excessive drawdown."""
        if current_drawdown < -self.max_drawdown_warning:
            alert = Alert(
                timestamp=datetime.now(),
                alert_type=AlertType.DRAWDOWN_WARNING,
                level=AlertLevel.WARNING,
                message=f"Drawdown of {current_drawdown:.2%} exceeds warning "
                f"threshold ({-self.max_drawdown_warning:.2%})",
                metrics={"current_drawdown": current_drawdown},
                recommended_action="Monitor closely, prepare risk reduction plan",
            )
            self.alerts.append(alert)
            return alert

        return None

    def get_alerts(
        self,
        since: Optional[datetime] = None,
        level: Optional[AlertLevel] = None,
    ) -> List[Alert]:
        """
        Get alerts (optionally filtered).

        Args:
            since: Only return alerts after this time
            level: Only return alerts of this level or higher

        Returns:
            List of alerts
        """
        filtered = self.alerts

        if since:
            filtered = [a for a in filtered if a.timestamp >= since]

        if level:
            level_order = {
                AlertLevel.INFO: 0,
                AlertLevel.WARNING: 1,
                AlertLevel.CRITICAL: 2,
            }
            min_level = level_order[level]
            filtered = [
                a for a in filtered
                if level_order.get(a.level, 0) >= min_level
            ]

        return filtered

    def get_recent_alerts(self, hours: int = 24) -> List[Alert]:
        """Get alerts from last N hours."""
        cutoff = datetime.now() - timedelta(hours=hours)
        return self.get_alerts(since=cutoff)


class PerformanceTracker:
    """
    Tracks portfolio performance metrics.

    Computes daily and cumulative metrics for monitoring and reporting.
    """

    def __init__(
        self,
        initial_capital: float,
        benchmark_returns: Optional[pd.Series] = None,
    ):
        """
        Initialize performance tracker.

        Args:
            initial_capital: Starting capital
            benchmark_returns: Optional benchmark returns for comparison
        """
        self.initial_capital = initial_capital
        self.benchmark_returns = benchmark_returns
        self.daily_metrics: List[DailyMetrics] = []
        self.equity_curve: pd.Series = pd.Series(dtype=float)
        self.daily_pnls: pd.Series = pd.Series(dtype=float)

    def add_daily_result(
        self,
        date: date,
        opening_value: float,
        closing_value: float,
        trades: List[Dict],
    ) -> DailyMetrics:
        """
        Record daily results.

        Args:
            date: Trading date
            opening_value: Portfolio value at open
            closing_value: Portfolio value at close
            trades: List of trades executed

        Returns:
            DailyMetrics for this day
        """
        daily_pnl = closing_value - opening_value
        daily_return = daily_pnl / (opening_value + 1e-10)
        cumulative_return = (closing_value - self.initial_capital) / self.initial_capital

        # Trade stats
        winning_trades = [t for t in trades if t.get("pnl", 0) > 0]
        losing_trades = [t for t in trades if t.get("pnl", 0) < 0]
        win_rate = len(winning_trades) / (len(trades) + 1e-10) if trades else 0

        pnls = [abs(t.get("pnl", 0)) for t in trades]
        avg_trade_size = np.mean(pnls) if pnls else 0
        largest_win = max([t.get("pnl", 0) for t in trades], default=0)
        largest_loss = min([t.get("pnl", 0) for t in trades], default=0)

        # Add to equity curve
        self.equity_curve[date] = closing_value
        self.daily_pnls[date] = daily_return

        # Compute metrics
        if len(self.daily_pnls) > 1:
            volatility = self.daily_pnls.std() * np.sqrt(252)
        else:
            volatility = 0

        if len(self.equity_curve) > 1:
            running_max = np.maximum.accumulate(self.equity_curve.values)
            drawdown = (self.equity_curve.iloc[-1] - running_max[-1]) / running_max[-1]
        else:
            drawdown = 0

        # BUG FIX #26: Add risk-free rate to Sharpe ratio calculation (proper formula)
        # Sharpe = (return - risk_free_rate) / volatility
        # Using 2% annual risk-free rate
        risk_free_rate = 0.02
        sharpe = (cumulative_return - risk_free_rate) / (volatility + 1e-10) if volatility > 1e-10 else 0
        var_95 = np.percentile(self.daily_pnls.values, 5) if len(self.daily_pnls) > 1 else 0

        metrics = DailyMetrics(
            date=date,
            opening_value=opening_value,
            closing_value=closing_value,
            daily_pnl=daily_pnl,
            daily_return_pct=daily_return,
            cumulative_return_pct=cumulative_return,
            volatility_annualized=volatility,
            max_drawdown=drawdown,
            sharpe_ratio=sharpe,
            var_95=var_95,
            total_trades=len(trades),
            winning_trades=len(winning_trades),
            losing_trades=len(losing_trades),
            win_rate=win_rate,
            avg_trade_size=avg_trade_size,
            largest_win=largest_win,
            largest_loss=largest_loss,
        )

        self.daily_metrics.append(metrics)
        logger.info(
            f"Daily result: {date} | "
            f"PnL: ${daily_pnl:+,.0f} ({daily_return:+.2%}) | "
            f"Trades: {len(trades)} | "
            f"Cumulative: {cumulative_return:+.2%}"
        )

        return metrics

    def get_summary_metrics(self) -> Dict[str, float]:
        """Get summary metrics over all tracked days."""
        if not self.daily_metrics:
            return {}

        returns = pd.Series([m.daily_return_pct for m in self.daily_metrics])
        cumulative_return = self.daily_metrics[-1].cumulative_return_pct

        return {
            "total_return_pct": cumulative_return * 100,
            "annualized_return_pct": ((1 + cumulative_return) ** (252 / len(returns)) - 1) * 100
            if len(returns) > 0
            else 0,
            "volatility_annualized_pct": returns.std() * np.sqrt(252) * 100,
            "sharpe_ratio": self.daily_metrics[-1].sharpe_ratio,
            "max_drawdown_pct": self.daily_metrics[-1].max_drawdown * 100,
            "win_rate_pct": np.mean([m.win_rate for m in self.daily_metrics]) * 100,
            "total_trades": sum(m.total_trades for m in self.daily_metrics),
            "avg_daily_pnl": np.mean([m.daily_pnl for m in self.daily_metrics]),
        }

    def get_period_summary(self, days: int = 30) -> Dict[str, Any]:
        """Get summary for last N days."""
        if not self.daily_metrics:
            return {}

        recent = self.daily_metrics[-days:] if len(self.daily_metrics) >= days else self.daily_metrics

        if not recent:
            return {}

        returns = pd.Series([m.daily_return_pct for m in recent])

        return {
            "period_days": len(recent),
            # BUG FIX #4: Subtract cumulative returns, not daily from cumulative (wrong formula)
            "period_return_pct": (recent[-1].cumulative_return_pct - recent[0].cumulative_return_pct) * 100,
            "period_volatility_pct": returns.std() * np.sqrt(252) * 100,
            "period_sharpe": recent[-1].sharpe_ratio,
            "total_trades": sum(m.total_trades for m in recent),
            "avg_trade_size": np.mean([m.avg_trade_size for m in recent]),
        }

    def export_metrics(self, filepath: str) -> None:
        """Export metrics to JSON file."""
        data = {
            "summary": self.get_summary_metrics(),
            "daily_metrics": [m.to_dict() for m in self.daily_metrics],
        }

        with open(filepath, "w") as f:
            json.dump(data, f, indent=2)

        logger.info(f"Metrics exported to {filepath}")


class DashboardData:
    """
    Structures data for dashboard visualization.

    Provides real-time and historical data in formats suitable for dashboards.
    """

    def __init__(
        self,
        performance_tracker: PerformanceTracker,
        alert_manager: AlertManager,
    ):
        """Initialize dashboard data provider."""
        self.performance_tracker = performance_tracker
        self.alert_manager = alert_manager

    def get_overview(self) -> Dict[str, Any]:
        """Get high-level portfolio overview."""
        if not self.performance_tracker.daily_metrics:
            return {}

        latest = self.performance_tracker.daily_metrics[-1]

        return {
            "current_date": latest.date.isoformat(),
            "portfolio_value": latest.closing_value,
            "daily_pnl": latest.daily_pnl,
            "daily_return_pct": latest.daily_return_pct * 100,
            "cumulative_return_pct": latest.cumulative_return_pct * 100,
            "sharpe_ratio": latest.sharpe_ratio,
            "max_drawdown_pct": latest.max_drawdown * 100,
            "volatility_pct": latest.volatility_annualized * 100,
        }

    def get_equity_curve(self) -> Dict[str, Any]:
        """Get equity curve data."""
        if self.performance_tracker.equity_curve.empty:
            return {"dates": [], "values": []}

        return {
            "dates": self.performance_tracker.equity_curve.index.strftime("%Y-%m-%d").tolist(),
            "values": self.performance_tracker.equity_curve.values.tolist(),
        }

    def get_recent_trades(self, n: int = 20) -> List[Dict]:
        """Get most recent trades (placeholder - would be filled by paper trader)."""
        return []

    def get_alerts_summary(self) -> Dict[str, Any]:
        """Get alert summary."""
        recent_alerts = self.alert_manager.get_recent_alerts(hours=24)

        by_level = {
            AlertLevel.CRITICAL: [a for a in recent_alerts if a.level == AlertLevel.CRITICAL],
            AlertLevel.WARNING: [a for a in recent_alerts if a.level == AlertLevel.WARNING],
            AlertLevel.INFO: [a for a in recent_alerts if a.level == AlertLevel.INFO],
        }

        return {
            "total_24h": len(recent_alerts),
            "critical": len(by_level[AlertLevel.CRITICAL]),
            "warnings": len(by_level[AlertLevel.WARNING]),
            "info": len(by_level[AlertLevel.INFO]),
            "recent": [a.to_dict() for a in recent_alerts[-5:]],
        }

    def get_dashboard_json(self) -> str:
        """Get complete dashboard data as JSON."""
        dashboard = {
            "overview": self.get_overview(),
            "equity_curve": self.get_equity_curve(),
            "alerts": self.get_alerts_summary(),
            "recent_trades": self.get_recent_trades(),
            "timestamp": datetime.now().isoformat(),
        }

        return json.dumps(dashboard, indent=2)
