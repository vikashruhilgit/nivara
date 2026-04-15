"""Email (SMTP) notification channel.

Uses stdlib :mod:`smtplib` wrapped in :func:`asyncio.to_thread` to keep
the async boundary clean without adding ``aiosmtplib`` as a new runtime
dependency.

User-scoped SMTP credentials are not yet persisted on the ``users``
table — an encrypt-at-rest migration will land in a follow-up. Until
then, callers must build an :class:`SmtpConfig` explicitly (e.g. from
an app-wide default) and :meth:`EmailChannel.from_user` will return
``None``.
"""

from __future__ import annotations

import asyncio
import logging
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from uuid import UUID

from backend.app.models.notifications import Notification
from backend.app.models.users import User
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SmtpConfig:
    """SMTP transport configuration."""

    host: str
    port: int
    username: str
    password: str
    from_email: str
    use_tls: bool = True


class EmailChannel:
    """Sends notifications as plain-text emails over SMTP."""

    def __init__(
        self,
        session: AsyncSession,
        smtp_config: SmtpConfig | None,
    ) -> None:
        self._session = session
        self._smtp_config = smtp_config

    @classmethod
    async def from_user(cls, session: AsyncSession, user_id: UUID) -> EmailChannel | None:
        """Build an :class:`EmailChannel` from per-user SMTP credentials.

        Currently a stub: the :class:`~backend.app.models.users.User`
        model does not yet carry SMTP fields — that migration will
        arrive with encrypt-at-rest. Until then this returns ``None``
        so callers can gracefully skip email delivery.
        """
        user = await session.get(User, user_id)
        if user is None:
            return None
        # Placeholder: a future migration will add an encrypted
        # ``smtp_config_json`` column (or equivalent) on the user row.
        smtp_json = getattr(user, "smtp_config_json", None)
        if not smtp_json:
            return None
        # Parsing/decryption will be implemented alongside the migration.
        return None

    async def send(self, notification: Notification) -> bool:
        cfg = self._smtp_config
        if cfg is None:
            return False

        user = await self._session.get(User, notification.user_id)
        if user is None or not user.email:
            return False

        msg = EmailMessage()
        msg["Subject"] = notification.title
        msg["From"] = cfg.from_email
        msg["To"] = user.email
        msg.set_content(notification.body)

        try:
            await asyncio.to_thread(self._send_sync, cfg, msg)
        except (smtplib.SMTPException, OSError) as exc:
            logger.warning(
                "EmailChannel: SMTP error %s for user=%s",
                exc.__class__.__name__,
                notification.user_id,
            )
            return False

        return True

    @staticmethod
    def _send_sync(cfg: SmtpConfig, msg: EmailMessage) -> None:
        with smtplib.SMTP(cfg.host, cfg.port, timeout=30) as client:
            client.ehlo()
            if cfg.use_tls:
                client.starttls()
                client.ehlo()
            if cfg.username:
                client.login(cfg.username, cfg.password)
            client.send_message(msg)
