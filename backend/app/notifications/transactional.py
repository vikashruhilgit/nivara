"""App-wide transactional email senders.

Unlike :mod:`backend.app.notifications.email` (which sends user-facing
:class:`~backend.app.models.notifications.Notification` rows), this module
sends standalone transactional messages that are not tied to a notification
row — e.g. the forgot/reset-password code email.

Configuration is sourced from app-wide :func:`get_settings` (never per-user
SMTP, which is still a stub). The blocking :mod:`smtplib` call is wrapped in
:func:`asyncio.to_thread` to keep the async boundary clean, matching the
pattern in :mod:`backend.app.notifications.email`.

Delivery is best-effort and **never raises** on missing/incomplete SMTP
configuration: the calling endpoint must not fail just because email
transport is not configured. In ``development`` only, the reset code/link is
logged so a local dev can complete the flow; in other environments the code
is never logged (secrets hygiene per CLAUDE.md).
"""

from __future__ import annotations

import asyncio
import logging
import smtplib
from email.message import EmailMessage

from backend.app.config import get_settings
from backend.app.notifications.email import SmtpConfig

logger = logging.getLogger(__name__)


def _build_smtp_config() -> SmtpConfig | None:
    """Build an :class:`SmtpConfig` from app-wide settings.

    Returns ``None`` when required transport fields are missing, signalling
    the caller to fall back to the dev-logging / no-op path.
    """
    settings = get_settings()
    if not settings.smtp_host or not settings.smtp_from_email:
        return None
    return SmtpConfig(
        host=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_username or "",
        password=settings.smtp_password or "",
        from_email=settings.smtp_from_email,
        use_tls=settings.smtp_use_tls,
    )


def _build_reset_message(
    cfg: SmtpConfig, to_email: str, code: str, reset_link: str
) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = "Your InvestIQ password reset code"
    msg["From"] = cfg.from_email
    msg["To"] = to_email
    msg.set_content(
        "You (or someone using your email) requested a password reset for "
        "your InvestIQ account.\n\n"
        f"Your password reset code is: {code}\n\n"
        f"You can also reset your password here: {reset_link}\n\n"
        "This code expires shortly. If you did not request a reset, you can "
        "safely ignore this email."
    )
    return msg


def _send_sync(cfg: SmtpConfig, msg: EmailMessage) -> None:
    with smtplib.SMTP(cfg.host, cfg.port, timeout=30) as client:
        client.ehlo()
        if cfg.use_tls:
            client.starttls()
            client.ehlo()
        if cfg.username:
            client.login(cfg.username, cfg.password)
        client.send_message(msg)


async def send_password_reset_email(to_email: str, code: str) -> None:
    """Send a password-reset code (and link) to ``to_email``.

    Never raises: on missing SMTP config the function degrades gracefully so
    the calling endpoint cannot fail. In ``development`` the code/link is
    logged for local testing; in other environments the code is never logged.
    """
    settings = get_settings()
    reset_link = f"{settings.app_public_base_url.rstrip('/')}/reset-password?code={code}"

    cfg = _build_smtp_config()
    if cfg is None:
        if settings.environment == "development":
            logger.warning(
                "Transactional email: SMTP not configured; password reset for "
                "%s NOT emailed. DEV-ONLY reset code=%s link=%s",
                to_email,
                code,
                reset_link,
            )
        else:
            logger.warning(
                "Transactional email: SMTP not configured; password reset email "
                "for %s was not sent.",
                to_email,
            )
        return

    msg = _build_reset_message(cfg, to_email, code, reset_link)

    try:
        await asyncio.to_thread(_send_sync, cfg, msg)
    except (smtplib.SMTPException, OSError) as exc:
        logger.warning(
            "Transactional email: SMTP error %s sending password reset to %s",
            exc.__class__.__name__,
            to_email,
        )
        return
