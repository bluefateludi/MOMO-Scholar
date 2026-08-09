from __future__ import annotations

from base64 import urlsafe_b64decode, urlsafe_b64encode

from paper_agent.web.errors import WebError


def encode_event_cursor(sequence: int) -> str:
    if sequence < 0:
        raise ValueError("event sequence must be non-negative")
    return urlsafe_b64encode(f"event:{sequence}".encode("ascii")).decode("ascii")


def decode_event_cursor(cursor: str | None) -> int:
    if cursor is None:
        return 0
    try:
        decoded = urlsafe_b64decode(cursor.encode("ascii")).decode("ascii")
        prefix, value = decoded.split(":", 1)
        sequence = int(value)
        if prefix != "event" or sequence < 0:
            raise ValueError
        return sequence
    except (ValueError, UnicodeError) as exc:
        raise WebError(422, "validation_error") from exc
