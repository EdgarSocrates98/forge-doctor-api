"""Secret redaction (§57, §125).

Redaction is always on: every model field that carries free text is redacted
at construction, and every serialized payload is redacted again on output.
There is no switch to disable it.

Covered shapes:

- mapping keys naming a secret (`Authorization`, `Cookie`, `Set-Cookie`,
  `X-API-Key`, `client_secret`, `access_token`, `refresh_token`, passwords,
  any `*token` / `*secret` / `*password` / `*api_key` key), at any depth;
- header-like text (`Authorization: Bearer ...`), masked to end of line;
- `key=value` / `key: value` / `"key": "value"` pairs, incl. URL query params;
- URL userinfo passwords (`scheme://user:secret@host`);
- bare bearer/basic credentials and JWTs.

All functions are pure and idempotent: `redact(redact(x)) == redact(x)`.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

MASK = "[REDACTED]"

_SENSITIVE_SUFFIXES = ("token", "secret", "password", "passwd", "apikey", "authorization", "cookie")
_SENSITIVE_EXACT = frozenset({"pwd"})

_KEY = (
    r"(?<![A-Za-z0-9])"
    r"(?P<key>[A-Za-z0-9_.-]*?"
    r"(?:token|secret|password|passwd|api[-_.]?key|authorization|cookie)|pwd)"
    r"(?![A-Za-z0-9])"
)
_HEADER = re.compile(
    _KEY + r"(?P<sep>[ \t]*:[ \t]*)(?![ \t]*[\"'])(?P<val>[^\r\n]+)", re.IGNORECASE
)
_PAIR = re.compile(
    _KEY + r"(?P<sep>[\"']?\s*[=:]\s*)" + r"(?P<val>\"(?:[^\"\\]|\\.)*\"|'[^']*'|[^\s&\"',;}<>]+)",
    re.IGNORECASE,
)
_USERINFO = re.compile(r"(?P<pre>\b[A-Za-z][A-Za-z0-9+.-]*://[^\s:/@]+:)(?P<pw>[^\s@/]+)(?=@)")
_AUTH_SCHEME = re.compile(r"\b(?P<scheme>Bearer|Basic)\s+(?P<tok>[A-Za-z0-9._~+/=-]+)")
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]*")
# Bare provider-shaped credentials without a key/scheme marker — Stripe,
# AWS access keys, GitHub PATs, Slack tokens.
_PROVIDER_TOKEN = re.compile(
    r"\b(?:sk-(?:live|test)-[A-Za-z0-9]{8,}|sk_(?:live|test)_[A-Za-z0-9]{8,}"
    r"|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{20,}|gho_[A-Za-z0-9]{20,}"
    r"|xox[baprs]-[A-Za-z0-9-]{10,})\b")


def is_sensitive_key(key: object) -> bool:
    """True when a mapping key or parameter name designates a secret."""
    normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
    return normalized in _SENSITIVE_EXACT or normalized.endswith(_SENSITIVE_SUFFIXES)


def _mask_header(match: re.Match[str]) -> str:
    if not is_sensitive_key(match["key"]):
        return match[0]
    return f"{match['key']}{match['sep']}{MASK}"


def _mask_pair(match: re.Match[str]) -> str:
    if not is_sensitive_key(match["key"]):
        return match[0]
    value = match["val"]
    quote = value[0] if value[0] in "\"'" else ""
    return f"{match['key']}{match['sep']}{quote}{MASK}{quote}"


def _mask_scheme(match: re.Match[str]) -> str:
    token = match["tok"]
    credential_like = len(token) >= 16 or (
        len(token) >= 8 and any(char.isdigit() or char == "=" for char in token)
    )
    return f"{match['scheme']} {MASK}" if credential_like else match[0]


def redact_text(text: str) -> str:
    """Mask secrets embedded in free text, headers, and URLs."""
    text = _USERINFO.sub(lambda m: f"{m['pre']}{MASK}", text)
    text = _PROVIDER_TOKEN.sub(MASK, text)
    text = _AUTH_SCHEME.sub(_mask_scheme, text)
    text = _JWT.sub(MASK, text)
    text = _HEADER.sub(_mask_header, text)
    return _PAIR.sub(_mask_pair, text)


def redact(value: Any) -> Any:
    """Recursively redact mappings, sequences and strings; other values pass through."""
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, Mapping):
        return {
            key: MASK if is_sensitive_key(key) and item not in (None, "") else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact(item) for item in value)
    return value
