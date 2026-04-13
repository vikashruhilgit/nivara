"""AES-256-GCM encryption service for broker tokens.

Design
------
- **Per-user subkey:** the master key from :class:`Settings` is HKDF-expanded
  (SHA-256) with a deterministic, user-scoped salt — so compromise of one
  user's ciphertext cannot be replayed against another user.
- **AES-GCM:** 96-bit random nonce per encryption; ciphertext blob is
  ``version(1) || kid(1) || nonce(12) || ciphertext||tag``.
- **Dual-key rotation:** :attr:`Settings.master_encryption_key` is a
  comma-separated list ``"new,old"``. Encryption always uses ``new`` (kid=0);
  decryption tries keys in declared order.

Master key format: URL-safe base64 of 32 bytes (256 bit). Generate with
``python -c "import os, base64; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"``.
"""

from __future__ import annotations

import base64
import os
from functools import lru_cache
from uuid import UUID

from backend.app.config import get_settings
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

_VERSION = 1
_NONCE_LEN = 12
_KEY_LEN = 32
_HKDF_INFO = b"investiq/broker-token/v1"
_HKDF_SALT_PREFIX = b"investiq/hkdf-salt/v1/"


class EncryptionError(Exception):
    """Raised on master-key misconfiguration or decrypt failure."""


def _decode_master_key(raw: str) -> bytes:
    """Decode a single base64 master key and verify it is 32 bytes."""
    try:
        key = base64.urlsafe_b64decode(raw.encode())
    except (ValueError, TypeError) as exc:  # malformed base64
        raise EncryptionError("MASTER_ENCRYPTION_KEY is not valid base64") from exc
    if len(key) != _KEY_LEN:
        raise EncryptionError(
            f"MASTER_ENCRYPTION_KEY must decode to {_KEY_LEN} bytes, got {len(key)}"
        )
    return key


@lru_cache(maxsize=1)
def _master_keys() -> list[bytes]:
    """Return the ordered list of master keys (new first, old fallbacks after).

    Cached so HKDF derivations stay cheap across hot request paths.
    """
    settings = get_settings()
    raw = (settings.master_encryption_key or "").strip()
    if not raw:
        raise EncryptionError("MASTER_ENCRYPTION_KEY is not configured")
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if not parts:
        raise EncryptionError("MASTER_ENCRYPTION_KEY is empty after parsing")
    return [_decode_master_key(p) for p in parts]


def reset_master_key_cache() -> None:
    """Drop the cached master-key list (tests / key-rotation signal handlers)."""
    _master_keys.cache_clear()


def _derive_user_key(master: bytes, user_id: UUID) -> bytes:
    """HKDF-SHA256 expand ``master`` into a per-user AES key.

    Salt is deterministic (``b"investiq/hkdf-salt/v1/" + user_id.bytes``) so
    the same user gets the same key on every process restart — essential for
    decrypting previously-stored tokens.
    """
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=_KEY_LEN,
        salt=_HKDF_SALT_PREFIX + user_id.bytes,
        info=_HKDF_INFO,
    )
    return hkdf.derive(master)


def encrypt_token(plaintext: str, *, user_id: UUID) -> bytes:
    """Encrypt a broker token under the *primary* master key.

    Returns a self-describing blob: ``version||kid||nonce||ciphertext+tag``.
    """
    if not plaintext:
        raise EncryptionError("plaintext must be non-empty")
    master = _master_keys()[0]
    key = _derive_user_key(master, user_id)
    nonce = os.urandom(_NONCE_LEN)
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
    # kid=0 → primary key. Decryption still tries all keys in order for safety.
    return bytes([_VERSION, 0]) + nonce + ciphertext


def decrypt_token(blob: bytes, *, user_id: UUID) -> str:
    """Decrypt a token blob, trying each master key (new → old) in turn."""
    if len(blob) < 2 + _NONCE_LEN + 16:
        raise EncryptionError("ciphertext blob is too short")
    version = blob[0]
    if version != _VERSION:
        raise EncryptionError(f"unsupported blob version {version}")
    nonce = blob[2 : 2 + _NONCE_LEN]
    ciphertext = blob[2 + _NONCE_LEN :]

    last_exc: Exception | None = None
    for master in _master_keys():
        key = _derive_user_key(master, user_id)
        try:
            pt = AESGCM(key).decrypt(nonce, ciphertext, None)
            return pt.decode("utf-8")
        except Exception as exc:  # noqa: BLE001 - try next key
            last_exc = exc
            continue

    raise EncryptionError("decryption failed under all configured master keys") from last_exc
