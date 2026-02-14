import logging
import time
from typing import Optional

from src.shared.database import Database
from src.shared.notifier import send_email

logger = logging.getLogger(__name__)


class HealthTracker:
    """Track errors, warnings, and health status during a workflow run.

    Usage:
        tracker = HealthTracker("process-a", "quiver_strat")
        try:
            # ... do work ...
            tracker.add_warning("Data endpoint returned empty data")
        except Exception as e:
            tracker.add_error("DataProvider", str(e))
        finally:
            tracker.finalize()
    """

    def __init__(self, workflow: str, account_id: str = None):
        self.workflow = workflow
        self.account_id = account_id
        self.errors: list[dict] = []
        self.warnings: list[dict] = []
        self.start_time = time.time()
        self.db = Database()

    def add_error(self, service: str, message: str, impact: str = "") -> None:
        """Record an error that occurred during the run."""
        error = {"service": service, "message": message, "impact": impact}
        self.errors.append(error)
        logger.error(f"[{self.workflow}] {service}: {message}")

    def add_warning(self, message: str, service: str = "") -> None:
        """Record a warning (partial failure or degraded operation)."""
        warning = {"service": service, "message": message}
        self.warnings.append(warning)
        logger.warning(f"[{self.workflow}] {message}")

    @property
    def severity(self) -> str:
        """Determine severity level based on errors."""
        if not self.errors:
            return "success"
        # Critical if any error mentions trading halted or all services down
        critical_keywords = ["halt", "circuit breaker", "all failed", "cannot trade"]
        for err in self.errors:
            if any(kw in err["message"].lower() for kw in critical_keywords):
                return "critical"
        if len(self.errors) >= 3:
            return "critical"
        return "warning"

    def finalize(self) -> None:
        """Log health check to DB and send alert email if errors occurred."""
        duration = time.time() - self.start_time
        status = self.severity

        # Log to health_checks table
        self.db.log_health_check({
            "workflow": self.workflow,
            "account_id": self.account_id,
            "status": status,
            "errors": self.errors if self.errors else None,
            "warnings": self.warnings if self.warnings else None,
            "run_duration_seconds": round(duration, 2),
        })

        # Send alert email if there were errors
        if self.errors:
            self._send_alert_email(duration)

        if status == "success":
            logger.info(
                f"[{self.workflow}] Completed successfully in {duration:.1f}s"
            )

    def _send_alert_email(self, duration: float) -> None:
        """Send an alert email with error details."""
        sev = self.severity.upper()
        error_services = ", ".join(set(e["service"] for e in self.errors if e["service"]))
        brief = error_services or "Runtime errors"
        subject = f"[ALERT] QD Engine - {sev}: {brief} ({self.workflow})"

        errors_html = ""
        for err in self.errors:
            errors_html += f"""
            <tr>
                <td style="padding:8px;border:1px solid #444;color:#ff6b6b;">{err['service']}</td>
                <td style="padding:8px;border:1px solid #444;color:#eee;">{err['message']}</td>
                <td style="padding:8px;border:1px solid #444;color:#ffd93d;">{err['impact']}</td>
            </tr>"""

        warnings_html = ""
        if self.warnings:
            warnings_html = "<h3 style='color:#ffd93d;'>Warnings</h3><ul>"
            for w in self.warnings:
                warnings_html += f"<li style='color:#eee;'>{w['message']}</li>"
            warnings_html += "</ul>"

        sev_color = {
            "CRITICAL": "#ff4444",
            "WARNING": "#ffd93d",
            "INFO": "#4ecdc4",
        }.get(sev, "#ffd93d")

        html = f"""
        <html>
        <body style="background:#1a1a2e;color:#eee;font-family:monospace;padding:20px;">
            <h2 style="color:{sev_color};">Alert: {sev}</h2>
            <p><strong>Workflow:</strong> {self.workflow}</p>
            <p><strong>Account:</strong> {self.account_id or 'N/A'}</p>
            <p><strong>Duration:</strong> {duration:.1f}s</p>

            <h3 style="color:#ff6b6b;">Errors</h3>
            <table style="border-collapse:collapse;width:100%;">
                <tr style="background:#2a2a4a;">
                    <th style="padding:8px;border:1px solid #444;text-align:left;">Service</th>
                    <th style="padding:8px;border:1px solid #444;text-align:left;">Error</th>
                    <th style="padding:8px;border:1px solid #444;text-align:left;">Impact</th>
                </tr>
                {errors_html}
            </table>

            {warnings_html}
        </body>
        </html>
        """

        send_email(subject, html)
