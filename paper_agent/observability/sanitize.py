from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

REDACTED = "[REDACTED]"

_CREDENTIAL_KEY_SUFFIXES = (
    "api_key",
    "apikey",
    "authorization",
    "credential",
    "credentials",
    "password",
    "passwd",
    "secret",
    "token",
)
_RAW_PAYLOAD_KEYS = frozenset(
    {
        "provider_request",
        "provider_response",
        "raw_request",
        "raw_request_body",
        "raw_response",
        "raw_response_body",
        "request_body",
        "response_body",
    }
)


def sanitize_event_data(value: Any, *, secrets: tuple[str, ...]) -> Any:
    """Return a JSON-compatible copy with secrets and raw payloads redacted."""
    known_secrets = tuple(
        sorted({secret for secret in secrets if secret}, key=lambda item: (-len(item), item))
    )
    return _sanitize(value, secrets=known_secrets)


def _sanitize(value: Any, *, secrets: tuple[str, ...]) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        sanitized = value
        for secret in secrets:
            sanitized = sanitized.replace(secret, REDACTED)
        return sanitized
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            safe_key = key if isinstance(key, str) else _unsupported_type(key)
            if _is_sensitive_key(safe_key):
                result[safe_key] = REDACTED
            else:
                result[safe_key] = _sanitize(item, secrets=secrets)
        return result
    if isinstance(value, (list, tuple)):
        return [_sanitize(item, secrets=secrets) for item in value]
    return _unsupported_type(value)


def _is_sensitive_key(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "_", key.casefold()).strip("_")
    return normalized in _RAW_PAYLOAD_KEYS or any(
        normalized == suffix or normalized.endswith(f"_{suffix}")
        for suffix in _CREDENTIAL_KEY_SUFFIXES
    )


def _unsupported_type(value: Any) -> str:
    value_type = type(value)
    return f"[UNSUPPORTED_TYPE:{value_type.__module__}.{value_type.__qualname__}]"
