"""Email utilities – send welcome and password-reset emails.

Falls back to logging when SMTP is not configured.
"""

import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import aiosmtplib

from api.config import settings

logger = logging.getLogger(__name__)


def _build_message(to_email: str, subject: str, body_text: str, body_html: str) -> MIMEMultipart:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.smtp_from_email
    msg["To"] = to_email
    msg.attach(MIMEText(body_text, "plain"))
    msg.attach(MIMEText(body_html, "html"))
    return msg


async def _send(to_email: str, subject: str, body_text: str, body_html: str) -> None:
    if not settings.smtp_host:
        logger.info(
            "SMTP not configured – would send '%s' to %s:\n%s",
            subject,
            to_email,
            body_text,
        )
        return

    msg = _build_message(to_email, subject, body_text, body_html)
    try:
        await aiosmtplib.send(
            msg,
            hostname=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_user or None,
            password=settings.smtp_password or None,
            use_tls=settings.smtp_use_tls,
        )
        logger.info("Email '%s' sent to %s", subject, to_email)
    except Exception:  # noqa: BLE001
        logger.exception("Failed to send email '%s' to %s", subject, to_email)


async def send_welcome_email(to_email: str, temp_password: str) -> None:
    """Send a welcome email with a one-time temporary password."""
    subject = "Welcome to Arcus – your temporary password"
    text = (
        f"Welcome to Arcus!\n\n"
        f"Your temporary password is: {temp_password}\n\n"
        f"Please log in and change your password immediately.\n"
        f"This password can only be used once.\n"
    )
    html = f"""
    <html><body style="font-family:sans-serif;max-width:480px;margin:auto;">
      <h2>Welcome to Arcus</h2>
      <p>Your temporary password is:</p>
      <p style="font-size:1.4em;font-weight:bold;letter-spacing:2px;
                background:#f3f4f6;padding:12px;border-radius:6px;display:inline-block;">
        {temp_password}
      </p>
      <p>Please log in and change your password immediately.<br>
         This password can only be used once.</p>
    </body></html>
    """
    await _send(to_email, subject, text, html)


async def send_password_reset_email(to_email: str, temp_password: str) -> None:
    """Send a password-reset email with a new one-time temporary password."""
    subject = "Arcus – your new temporary password"
    text = (
        f"A password reset was requested for your Arcus account.\n\n"
        f"Your new temporary password is: {temp_password}\n\n"
        f"Please log in and change your password immediately.\n"
    )
    html = f"""
    <html><body style="font-family:sans-serif;max-width:480px;margin:auto;">
      <h2>Arcus – Password Reset</h2>
      <p>Your new temporary password is:</p>
      <p style="font-size:1.4em;font-weight:bold;letter-spacing:2px;
                background:#f3f4f6;padding:12px;border-radius:6px;display:inline-block;">
        {temp_password}
      </p>
      <p>Please log in and change your password immediately.</p>
    </body></html>
    """
    await _send(to_email, subject, text, html)
