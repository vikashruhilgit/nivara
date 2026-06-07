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
transport is not configured. In ``development`` only, the reset code is
logged so a local dev can complete the flow; in other environments the code
is never logged (secrets hygiene per CLAUDE.md).

The email presents the reset **code** for manual entry in the app's Reset
Password screen. The secret is deliberately never embedded in a URL query
string (which would leak via access logs / referer headers); deep-linking is
a designated Phase-2 follow-up.
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
    cfg: SmtpConfig, to_email: str, code: str, expires_minutes: int
) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = "Your InvestIQ password reset code"
    msg["From"] = cfg.from_email
    msg["To"] = to_email
    msg.set_content(
        "You (or someone using your email) requested a password reset for "
        "your InvestIQ account.\n\n"
        f"Your password reset code is: {code}\n\n"
        "Open the InvestIQ app, go to the Reset Password screen, and enter "
        f"this code. It expires in {expires_minutes} minutes.\n\n"
        "If you did not request a reset, you can safely ignore this email."
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
    """Send a password-reset code to ``to_email`` for manual entry in-app.

    Never raises: on missing SMTP config the function degrades gracefully so
    the calling endpoint cannot fail. In ``development`` the code is logged for
    local testing; in other environments the code is never logged. The code is
    never placed in a URL (no secret-in-query-string leakage).
    """
    settings = get_settings()
    expires_minutes = settings.password_reset_token_expires_minutes

    cfg = _build_smtp_config()
    if cfg is None:
        if settings.environment == "development":
            logger.warning(
                "Transactional email: SMTP not configured; password reset for "
                "%s NOT emailed. DEV-ONLY reset code=%s",
                to_email,
                code,
            )
        else:
            logger.warning(
                "Transactional email: SMTP not configured; password reset email "
                "for %s was not sent.",
                to_email,
            )
        return

    msg = _build_reset_message(cfg, to_email, code, expires_minutes)

    try:
        await asyncio.to_thread(_send_sync, cfg, msg)
    except (smtplib.SMTPException, OSError) as exc:
        logger.warning(
            "Transactional email: SMTP error %s sending password reset to %s",
            exc.__class__.__name__,
            to_email,
        )
        return
    except Exception as exc:  # noqa: BLE001 - best-effort sender must never propagate
        # ANY other failure must be swallowed so the calling endpoint cannot
        # fail. A common real-world case is a UnicodeEncodeError raised by
        # smtplib.login() when an SMTP credential contains a stray non-ASCII
        # character (e.g. a non-breaking space copied from a provider's UI).
        # The reset code is never logged here.
        logger.warning(
            "Transactional email: unexpected %s sending password reset to %s "
            "(verify SMTP credentials contain no stray/non-ASCII characters)",
            exc.__class__.__name__,
            to_email,
        )
        return
