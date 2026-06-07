"""Unit tests for ``backend.app.notifications.transactional``.

The forgot/reset-password service tests monkeypatch ``send_password_reset_email``
wholesale, so this module's internals are never exercised there. These tests
cover the four behavioural branches directly:

1. No SMTP config + ``development`` → no send, dev-logs the code.
2. No SMTP config + non-``development`` → no send, code never logged
   (secrets-hygiene guarantee).
3. SMTP configured → a send is attempted to the right recipient with the code
   in the body.
4. SMTP send raises ``SMTPException`` / ``OSError`` → swallowed (never raises),
   code not logged outside dev.

``transactional`` binds ``get_settings`` at module import, so we override that
bound name (not :func:`backend.app.config.get_settings`) to inject test
settings — the autouse conftest fixture does not patch this module.
"""

from __future__ import annotations

import logging
import smtplib
from collections.abc import Callable

import pytest
from backend.app.config import Settings
from backend.app.notifications import transactional

pytestmark = pytest.mark.asyncio

_TO = "user@example.com"
_CODE = "super-secret-reset-code-xyz"


def _settings(**overrides: object) -> Settings:
    """Build a ``Settings`` with safe test defaults plus overrides.

    ``Settings()`` would read the developer's real ``.env``; supplying the
    fields these tests care about keeps them hermetic.
    """
    base: dict[str, object] = {
        "environment": "production",
        "smtp_host": None,
        "smtp_from_email": None,
        "password_reset_token_expires_minutes": 30,
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


@pytest.fixture
def patch_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> Callable[..., Settings]:
    """Return a setter that overrides ``transactional.get_settings``."""

    def _apply(**overrides: object) -> Settings:
        settings = _settings(**overrides)
        monkeypatch.setattr(transactional, "get_settings", lambda: settings)
        return settings

    return _apply


# --- Branch 1: no SMTP config + development → dev-logs the code --------------


async def test_no_smtp_development_logs_code_and_does_not_send(
    patch_settings: Callable[..., Settings],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    patch_settings(environment="development", smtp_host=None, smtp_from_email=None)

    # Guard: nothing should be sent.
    def _boom(*args: object, **kwargs: object) -> None:
        raise AssertionError("asyncio.to_thread must not be called without SMTP config")

    monkeypatch.setattr(transactional.asyncio, "to_thread", _boom)
    monkeypatch.setattr(
        transactional.smtplib,
        "SMTP",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("SMTP must not be opened")),
    )

    with caplog.at_level(logging.WARNING, logger=transactional.logger.name):
        await transactional.send_password_reset_email(_TO, _CODE)

    # Dev path logs the code so a local dev can complete the flow.
    assert _CODE in caplog.text


# --- Branch 2: no SMTP config + non-dev → code never logged -----------------


async def test_no_smtp_production_does_not_log_code_or_send(
    patch_settings: Callable[..., Settings],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    patch_settings(environment="production", smtp_host=None, smtp_from_email=None)

    def _boom(*args: object, **kwargs: object) -> None:
        raise AssertionError("asyncio.to_thread must not be called without SMTP config")

    monkeypatch.setattr(transactional.asyncio, "to_thread", _boom)

    with caplog.at_level(logging.WARNING, logger=transactional.logger.name):
        await transactional.send_password_reset_email(_TO, _CODE)

    # Secrets hygiene: the reset code must never appear in non-dev logs.
    assert _CODE not in caplog.text
    # But the no-send warning (without the code) is still emitted.
    assert _TO in caplog.text


# --- Branch 3: SMTP configured → a send is attempted with the code ----------


async def test_smtp_configured_sends_with_code_in_body(
    patch_settings: Callable[..., Settings],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_settings(
        environment="production",
        smtp_host="smtp.example.com",
        smtp_from_email="noreply@investiq.test",
        smtp_username="smtp-user",
        smtp_password="smtp-pass",
        smtp_port=587,
        smtp_use_tls=True,
        password_reset_token_expires_minutes=42,
    )

    captured: dict[str, object] = {}

    class _FakeSMTP:
        def __init__(self, host: str, port: int, timeout: int | None = None) -> None:
            captured["host"] = host
            captured["port"] = port

        def __enter__(self) -> _FakeSMTP:
            return self

        def __exit__(self, *exc: object) -> None:
            return None

        def ehlo(self) -> None:
            return None

        def starttls(self) -> None:
            captured["starttls"] = True

        def login(self, username: str, password: str) -> None:
            captured["login"] = username

        def send_message(self, msg: object) -> None:
            captured["msg"] = msg

    monkeypatch.setattr(transactional.smtplib, "SMTP", _FakeSMTP)

    await transactional.send_password_reset_email(_TO, _CODE)

    # A send was attempted to the configured host, with STARTTLS + login.
    assert captured["host"] == "smtp.example.com"
    assert captured.get("starttls") is True
    assert captured.get("login") == "smtp-user"
    msg = captured["msg"]
    assert msg is not None
    assert msg["To"] == _TO
    assert msg["From"] == "noreply@investiq.test"
    body = msg.get_content()
    # The reset code is in the body for manual entry...
    assert _CODE in body
    # ...the configured expiry is surfaced...
    assert "42 minutes" in body
    # ...and the secret is NOT embedded in any URL query string.
    assert "?code=" not in body
    assert "?token=" not in body


# --- Branch 4: SMTP send raises → swallowed, never raises -------------------


@pytest.mark.parametrize(
    "exc",
    [
        smtplib.SMTPException("boom"),
        OSError("connection refused"),
        # Non-SMTP failures must also be swallowed (never-raise contract). The
        # UnicodeEncodeError mirrors a real incident: an app password copied
        # from Google's UI carried a non-breaking space, so smtplib.login()
        # raised while ASCII-encoding the credential.
        ValueError("unexpected non-SMTP error"),
        UnicodeEncodeError("ascii", "\xa0", 0, 1, "ordinal not in range(128)"),
    ],
)
async def test_smtp_send_error_is_swallowed(
    patch_settings: Callable[..., Settings],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    exc: Exception,
) -> None:
    patch_settings(
        environment="production",
        smtp_host="smtp.example.com",
        smtp_from_email="noreply@investiq.test",
    )

    async def _raise(*args: object, **kwargs: object) -> None:
        raise exc

    monkeypatch.setattr(transactional.asyncio, "to_thread", _raise)

    with caplog.at_level(logging.WARNING, logger=transactional.logger.name):
        # Never-raise guarantee: this must not propagate.
        await transactional.send_password_reset_email(_TO, _CODE)

    # The error is logged by class name only — never the reset code.
    assert _CODE not in caplog.text
    assert exc.__class__.__name__ in caplog.text
