"""
Alert Notification Dispatcher — Multi-channel alert delivery.

Turns detect-only monitoring into detect-and-alert by dispatching
notifications through configurable channels:
- Webhook (Slack, Discord, generic HTTP POST)
- Email (SMTP)
- Log file (structured JSON, always-on fallback)

Each channel can be independently enabled/disabled and configured
with severity filters (e.g., only CRITICAL alerts go to Slack).

Usage:
    dispatcher = NotificationDispatcher()
    dispatcher.add_channel(SlackWebhookChannel(url="https://hooks.slack.com/..."))
    dispatcher.add_channel(EmailChannel(smtp_host="smtp.gmail.com", ...))
    dispatcher.dispatch(alert)
"""

import json
import logging
import smtplib
import urllib.request
import urllib.error
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set
from collections import deque

logger = logging.getLogger(__name__)


class Severity(Enum):
    """Alert severity levels, ordered by importance."""
    INFO = 0
    WARNING = 1
    CRITICAL = 2


@dataclass
class Notification:
    """A notification to be dispatched."""
    title: str
    message: str
    severity: Severity
    source: str  # e.g., "drift_detector", "staleness_tracker", "risk_controls"
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "message": self.message,
            "severity": self.severity.name,
            "source": self.source,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata,
        }


class NotificationChannel(ABC):
    """Base class for notification delivery channels."""

    def __init__(
        self,
        name: str,
        min_severity: Severity = Severity.WARNING,
        rate_limit_seconds: int = 300,  # Don't spam: 5 min cooldown per alert type
    ):
        self.name = name
        self.min_severity = min_severity
        self.rate_limit_seconds = rate_limit_seconds
        self._last_sent: Dict[str, datetime] = {}
        self._send_count: int = 0
        self._error_count: int = 0

    def should_send(self, notification: Notification) -> bool:
        """Check severity filter and rate limit."""
        if notification.severity.value < self.min_severity.value:
            return False

        # Rate limit by (source, title) combo
        key = f"{notification.source}:{notification.title}"
        last = self._last_sent.get(key)
        if last and (datetime.now() - last).total_seconds() < self.rate_limit_seconds:
            return False

        return True

    def send(self, notification: Notification) -> bool:
        """Send notification if it passes filters. Returns True on success."""
        if not self.should_send(notification):
            return False

        try:
            success = self._deliver(notification)
            if success:
                key = f"{notification.source}:{notification.title}"
                self._last_sent[key] = datetime.now()
                self._send_count += 1
            return success
        except Exception as e:
            self._error_count += 1
            logger.error(f"Channel '{self.name}' delivery failed: {e}")
            return False

    @abstractmethod
    def _deliver(self, notification: Notification) -> bool:
        """Actually deliver the notification. Implement per channel."""
        ...

    def get_stats(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "sent": self._send_count,
            "errors": self._error_count,
            "min_severity": self.min_severity.name,
        }


class WebhookChannel(NotificationChannel):
    """
    Generic HTTP POST webhook channel.

    Works with Slack, Discord, Microsoft Teams, or any service
    that accepts JSON POST webhooks.
    """

    def __init__(
        self,
        url: str,
        name: str = "webhook",
        min_severity: Severity = Severity.WARNING,
        rate_limit_seconds: int = 300,
        headers: Optional[Dict[str, str]] = None,
        format_fn: Optional[Callable[[Notification], Dict]] = None,
        timeout_seconds: int = 10,
    ):
        super().__init__(name, min_severity, rate_limit_seconds)
        self.url = url
        self.headers = headers or {"Content-Type": "application/json"}
        self.format_fn = format_fn
        self.timeout_seconds = timeout_seconds

    def _format_default(self, notification: Notification) -> Dict:
        """Default JSON payload."""
        return {
            "text": (
                f"[{notification.severity.name}] {notification.title}\n"
                f"{notification.message}\n"
                f"Source: {notification.source} | {notification.timestamp.strftime('%Y-%m-%d %H:%M:%S')}"
            ),
        }

    def _deliver(self, notification: Notification) -> bool:
        payload = (
            self.format_fn(notification) if self.format_fn
            else self._format_default(notification)
        )

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.url, data=data, headers=self.headers, method="POST"
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                success = 200 <= resp.status < 300
                if success:
                    logger.info(f"Webhook '{self.name}' delivered: {notification.title}")
                return success
        except urllib.error.URLError as e:
            logger.error(f"Webhook '{self.name}' failed: {e}")
            return False


class SlackWebhookChannel(WebhookChannel):
    """Slack-formatted webhook channel with rich message blocks."""

    def __init__(
        self,
        url: str,
        channel: str = "",
        min_severity: Severity = Severity.WARNING,
        rate_limit_seconds: int = 300,
    ):
        super().__init__(
            url=url,
            name="slack",
            min_severity=min_severity,
            rate_limit_seconds=rate_limit_seconds,
        )
        self.channel = channel

    def _format_default(self, notification: Notification) -> Dict:
        severity_emoji = {
            Severity.INFO: ":information_source:",
            Severity.WARNING: ":warning:",
            Severity.CRITICAL: ":rotating_light:",
        }

        emoji = severity_emoji.get(notification.severity, ":bell:")

        payload: Dict[str, Any] = {
            "blocks": [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": f"{emoji} {notification.title}",
                    },
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": notification.message,
                    },
                },
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": (
                                f"*Severity:* {notification.severity.name} | "
                                f"*Source:* {notification.source} | "
                                f"*Time:* {notification.timestamp.strftime('%H:%M:%S')}"
                            ),
                        }
                    ],
                },
            ],
        }

        if self.channel:
            payload["channel"] = self.channel

        # Add metadata fields if present
        if notification.metadata:
            fields = []
            for k, v in list(notification.metadata.items())[:10]:
                fields.append({
                    "type": "mrkdwn",
                    "text": f"*{k}:* {v}",
                })
            if fields:
                payload["blocks"].insert(2, {
                    "type": "section",
                    "fields": fields,
                })

        return payload


class EmailChannel(NotificationChannel):
    """SMTP email notification channel."""

    def __init__(
        self,
        smtp_host: str,
        smtp_port: int = 587,
        username: str = "",
        password: str = "",
        from_addr: str = "",
        to_addrs: Optional[List[str]] = None,
        use_tls: bool = True,
        name: str = "email",
        min_severity: Severity = Severity.CRITICAL,
        rate_limit_seconds: int = 900,  # 15 min cooldown for emails
    ):
        super().__init__(name, min_severity, rate_limit_seconds)
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.username = username
        self.password = password
        self.from_addr = from_addr or username
        self.to_addrs = to_addrs or []
        self.use_tls = use_tls

    def _deliver(self, notification: Notification) -> bool:
        if not self.to_addrs:
            logger.warning("Email channel has no recipients configured")
            return False

        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"[{notification.severity.name}] {notification.title}"
        msg["From"] = self.from_addr
        msg["To"] = ", ".join(self.to_addrs)

        # Plain text body
        text_body = (
            f"Severity: {notification.severity.name}\n"
            f"Source: {notification.source}\n"
            f"Time: {notification.timestamp.isoformat()}\n\n"
            f"{notification.message}\n"
        )

        if notification.metadata:
            text_body += "\nDetails:\n"
            for k, v in notification.metadata.items():
                text_body += f"  {k}: {v}\n"

        msg.attach(MIMEText(text_body, "plain"))

        # HTML body
        meta_rows = "".join(
            f"<tr><td><b>{k}</b></td><td>{v}</td></tr>"
            for k, v in notification.metadata.items()
        ) if notification.metadata else ""

        severity_color = {
            Severity.INFO: "#2196F3",
            Severity.WARNING: "#FF9800",
            Severity.CRITICAL: "#F44336",
        }.get(notification.severity, "#607D8B")

        html_body = f"""
        <div style="font-family: sans-serif; max-width: 600px;">
            <div style="background: {severity_color}; color: white; padding: 12px 16px; border-radius: 4px 4px 0 0;">
                <h2 style="margin: 0;">{notification.title}</h2>
            </div>
            <div style="padding: 16px; border: 1px solid #ddd; border-top: none;">
                <p>{notification.message}</p>
                <p style="color: #666; font-size: 12px;">
                    Source: {notification.source} | {notification.timestamp.strftime('%Y-%m-%d %H:%M:%S')}
                </p>
                {"<table style='width:100%; font-size:13px;'>" + meta_rows + "</table>" if meta_rows else ""}
            </div>
        </div>
        """
        msg.attach(MIMEText(html_body, "html"))

        try:
            with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=15) as server:
                if self.use_tls:
                    server.starttls()
                if self.username:
                    server.login(self.username, self.password)
                server.sendmail(self.from_addr, self.to_addrs, msg.as_string())
            logger.info(f"Email sent to {len(self.to_addrs)} recipients: {notification.title}")
            return True
        except Exception as e:
            logger.error(f"Email delivery failed: {e}")
            return False


class LogChannel(NotificationChannel):
    """
    Structured JSON log file channel. Always-on fallback.

    Writes to a JSON-lines file for persistence even if other channels fail.
    """

    def __init__(
        self,
        log_path: str = "alerts.jsonl",
        name: str = "log_file",
        min_severity: Severity = Severity.INFO,
        rate_limit_seconds: int = 0,  # No rate limit for log files
    ):
        super().__init__(name, min_severity, rate_limit_seconds)
        self.log_path = log_path

    def _deliver(self, notification: Notification) -> bool:
        record = notification.to_dict()
        try:
            with open(self.log_path, "a") as f:
                f.write(json.dumps(record, default=str) + "\n")
            return True
        except Exception as e:
            logger.error(f"Log file write failed: {e}")
            return False


class NotificationDispatcher:
    """
    Central dispatcher that routes alerts to all configured channels.

    Supports:
    - Multiple channels with independent severity filters
    - Rate limiting per channel to prevent alert fatigue
    - Delivery tracking and stats
    - Alert history buffer for deduplication
    """

    def __init__(self, history_size: int = 1000):
        self._channels: List[NotificationChannel] = []
        self._history: deque = deque(maxlen=history_size)
        self._total_dispatched: int = 0

    def add_channel(self, channel: NotificationChannel) -> None:
        """Register a notification channel."""
        self._channels.append(channel)
        logger.info(f"Registered notification channel: {channel.name}")

    def remove_channel(self, name: str) -> bool:
        """Remove a channel by name."""
        before = len(self._channels)
        self._channels = [c for c in self._channels if c.name != name]
        return len(self._channels) < before

    def dispatch(self, notification: Notification) -> Dict[str, bool]:
        """
        Send a notification to all registered channels.

        Returns:
            Dict of {channel_name: success_bool}
        """
        results = {}

        for channel in self._channels:
            results[channel.name] = channel.send(notification)

        self._history.append(notification)
        self._total_dispatched += 1

        delivered_to = [name for name, ok in results.items() if ok]
        if delivered_to:
            logger.info(
                f"Notification dispatched to {delivered_to}: {notification.title}"
            )

        return results

    def dispatch_from_alert(
        self,
        title: str,
        message: str,
        severity: Severity,
        source: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, bool]:
        """Convenience: create and dispatch a notification in one call."""
        notification = Notification(
            title=title,
            message=message,
            severity=severity,
            source=source,
            metadata=metadata or {},
        )
        return self.dispatch(notification)

    def get_stats(self) -> Dict[str, Any]:
        """Get dispatch statistics."""
        return {
            "total_dispatched": self._total_dispatched,
            "channels": [c.get_stats() for c in self._channels],
            "recent_count": len(self._history),
        }

    def get_recent(self, n: int = 10) -> List[Dict]:
        """Get last N dispatched notifications."""
        recent = list(self._history)[-n:]
        return [n.to_dict() for n in recent]
