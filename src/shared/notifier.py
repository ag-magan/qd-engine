import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from src.shared.config import NOTIFY_ADDRESS, NOTIFY_PASSWORD

logger = logging.getLogger(__name__)


def send_email(subject: str, html_body: str, to_address: str = None) -> bool:
    """Send an HTML email via SMTP."""
    if not NOTIFY_ADDRESS or not NOTIFY_PASSWORD:
        logger.warning("Notification credentials not configured, skipping email")
        return False

    to_addr = to_address or NOTIFY_ADDRESS

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = NOTIFY_ADDRESS
        msg["To"] = to_addr

        html_part = MIMEText(html_body, "html")
        msg.attach(html_part)

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(NOTIFY_ADDRESS, NOTIFY_PASSWORD)
            server.sendmail(NOTIFY_ADDRESS, to_addr, msg.as_string())

        logger.info(f"Email sent: {subject}")
        return True

    except Exception as e:
        logger.error(f"Failed to send email '{subject}': {e}")
        return False
