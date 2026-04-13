"""Tests for ``backend.app.services.encryption`` (AES-256-GCM + dual-key)."""

from __future__ import annotations

import base64
import os
from collections.abc import Iterator
from uuid import uuid4

import pytest
from backend.app.config import Settings, get_settings
from backend.app.services import encryption as enc_module
from backend.app.services.encryption import (
    EncryptionError,
    decrypt_token,
    encrypt_token,
    reset_master_key_cache,
)


def _b64key() -> str:
    return base64.urlsafe_b64encode(os.urandom(32)).decode()


@pytest.fixture
def _with_master_key() -> Iterator[str]:
    key = _b64key()
    settings = Settings(master_encryption_key=key)
    enc_module.get_settings = lambda: settings  # type: ignore[assignment]
    reset_master_key_cache()
    try:
        yield key
    finally:
        enc_module.get_settings = get_settings  # type: ignore[assignment]
        reset_master_key_cache()


@pytest.fixture
def _dual_keys() -> Iterator[tuple[str, str]]:
    """Return (new, old) with new first in the env — decrypt must still work with old."""
    old = _b64key()
    new = _b64key()
    yield new, old


def test_roundtrip(_with_master_key: str) -> None:
    user_id = uuid4()
    ct = encrypt_token("super-secret-broker-token", user_id=user_id)
    assert ct != b"super-secret-broker-token"
    assert decrypt_token(ct, user_id=user_id) == "super-secret-broker-token"


def test_blob_is_self_describing(_with_master_key: str) -> None:
    ct = encrypt_token("tok", user_id=uuid4())
    # version=1, kid=0, 12-byte nonce, then ciphertext+tag (>=16 bytes)
    assert ct[0] == 1
    assert ct[1] == 0
    assert len(ct) >= 2 + 12 + 16


def test_different_users_get_different_ciphertexts(_with_master_key: str) -> None:
    a = encrypt_token("same-plaintext", user_id=uuid4())
    b = encrypt_token("same-plaintext", user_id=uuid4())
    assert a != b


def test_cannot_decrypt_with_wrong_user_id(_with_master_key: str) -> None:
    ct = encrypt_token("tok", user_id=uuid4())
    with pytest.raises(EncryptionError):
        decrypt_token(ct, user_id=uuid4())


def test_dual_key_rotation_old_key_decrypts(_dual_keys: tuple[str, str]) -> None:
    new, old = _dual_keys
    user_id = uuid4()

    # Step 1: old key is current; encrypt a token.
    settings_old = Settings(master_encryption_key=old)
    enc_module.get_settings = lambda: settings_old  # type: ignore[assignment]
    reset_master_key_cache()
    ct = encrypt_token("rotate-me", user_id=user_id)

    # Step 2: rotate → env now lists "new,old"; decrypt must still succeed.
    settings_dual = Settings(master_encryption_key=f"{new},{old}")
    enc_module.get_settings = lambda: settings_dual  # type: ignore[assignment]
    reset_master_key_cache()
    try:
        assert decrypt_token(ct, user_id=user_id) == "rotate-me"
        # And new encryptions use the new key (but still decrypt under dual cfg).
        ct2 = encrypt_token("freshly-rotated", user_id=user_id)
        assert decrypt_token(ct2, user_id=user_id) == "freshly-rotated"
    finally:
        enc_module.get_settings = get_settings  # type: ignore[assignment]
        reset_master_key_cache()


def test_missing_master_key_errors() -> None:
    settings = Settings(master_encryption_key=None)
    enc_module.get_settings = lambda: settings  # type: ignore[assignment]
    reset_master_key_cache()
    try:
        with pytest.raises(EncryptionError):
            encrypt_token("x", user_id=uuid4())
    finally:
        enc_module.get_settings = get_settings  # type: ignore[assignment]
        reset_master_key_cache()


def test_malformed_master_key_rejected() -> None:
    settings = Settings(master_encryption_key="not-base64-!!")
    enc_module.get_settings = lambda: settings  # type: ignore[assignment]
    reset_master_key_cache()
    try:
        with pytest.raises(EncryptionError):
            encrypt_token("x", user_id=uuid4())
    finally:
        enc_module.get_settings = get_settings  # type: ignore[assignment]
        reset_master_key_cache()


def test_wrong_length_master_key_rejected() -> None:
    short = base64.urlsafe_b64encode(b"only-16-bytes-ok").decode()
    settings = Settings(master_encryption_key=short)
    enc_module.get_settings = lambda: settings  # type: ignore[assignment]
    reset_master_key_cache()
    try:
        with pytest.raises(EncryptionError):
            encrypt_token("x", user_id=uuid4())
    finally:
        enc_module.get_settings = get_settings  # type: ignore[assignment]
        reset_master_key_cache()
