"""Prompt sanitization + PII redaction for AI analysis inputs.

Defence-in-depth: the model in live mode will still have system-prompt
hardening, but we refuse to forward obviously adversarial user-controlled
text. These filters are deliberately conservative — they only strip the
narrow set of markers we have a specific threat model for.
"""

from __future__ import annotations

import re

# Prompt-injection markers: system tags, special tokens, fake role prefixes,
# and "ignore previous instructions" variants. All patterns are conservative;
# false negatives are preferred over mangling legitimate financial text.
_INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"</?\s*system\s*>", re.IGNORECASE),
    re.compile(r"<\|[^|]*\|>"),
    re.compile(r"(?im)^\s*(assistant|human|user|system)\s*:"),
    re.compile(r"(?i)ignore\s+(?:all\s+|previous\s+|prior\s+)?instructions"),
)

# PII patterns — minimal but covers the common leak shapes.
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE = re.compile(r"(?<!\d)(\+?\d[\d\-\s().]{7,}\d)(?!\d)")


def sanitize_prompt(text: str, *, max_tokens: int = 4000) -> str:
    """Strip prompt-injection markers and truncate by approximate token count.

    The token approximation is ``1 token ≈ 4 characters`` of English. We
    prefix-truncate (keep the *start*) because the system prefix carries the
    most context; dropping tail content is safer than dropping the lede.
    """
    for pat in _INJECTION_PATTERNS:
        text = pat.sub("", text)
    max_chars = max_tokens * 4
    if len(text) > max_chars:
        text = text[:max_chars]
    return text.strip()


def redact_pii(text: str) -> str:
    """Replace emails / phone-ish numbers with ``[REDACTED_*]`` placeholders."""
    text = _EMAIL.sub("[REDACTED_EMAIL]", text)
    text = _PHONE.sub("[REDACTED_PHONE]", text)
    return text


__all__ = ["redact_pii", "sanitize_prompt"]
