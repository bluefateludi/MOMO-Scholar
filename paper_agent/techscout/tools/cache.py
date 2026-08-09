from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Generic, TypeVar

from pydantic import BaseModel


T = TypeVar("T", bound=BaseModel)


def canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True, slots=True)
class CacheRead(Generic[T]):
    value: T
    stale: bool
    stored_at: datetime
    content_sha256: str


class ContentAddressedCache:
    """Small content-addressed JSON cache with separately hashed lookup keys."""

    def __init__(self, root: Path, *, ttl: timedelta = timedelta(hours=24)) -> None:
        if ttl.total_seconds() <= 0:
            raise ValueError("cache ttl must be positive")
        self._root = root
        self._ttl = ttl

    @staticmethod
    def key(namespace: str, request: BaseModel) -> str:
        return f"{namespace}:{canonical_sha256(request.model_dump(mode='json'))}"

    def put(
        self, key: str, value: BaseModel, *, now: datetime | None = None
    ) -> str:
        stored_at = now or datetime.now(timezone.utc)
        if stored_at.tzinfo is None or stored_at.utcoffset() is None:
            raise ValueError("cache timestamp must include a timezone")
        payload = value.model_dump(mode="json")
        content_hash = canonical_sha256(payload)
        blob = {"payload": payload}
        blob_path = self._root / "blobs" / f"{content_hash}.json"
        if not blob_path.is_file():
            self._write_json(blob_path, blob)
        self._write_json(
            self._root / "keys" / f"{hashlib.sha256(key.encode()).hexdigest()}.json",
            {
                "key": key,
                "content_sha256": content_hash,
                "stored_at": stored_at.isoformat(),
            },
        )
        return content_hash

    def get(
        self,
        key: str,
        model: type[T],
        *,
        now: datetime | None = None,
        allow_stale: bool = False,
    ) -> CacheRead[T] | None:
        current = now or datetime.now(timezone.utc)
        index_path = (
            self._root
            / "keys"
            / f"{hashlib.sha256(key.encode()).hexdigest()}.json"
        )
        if not index_path.is_file():
            return None
        index = self._read_json(index_path)
        if index.get("key") != key:
            raise ValueError("cache key hash collision")
        content_hash = index.get("content_sha256")
        if not isinstance(content_hash, str):
            raise ValueError("malformed cache index")
        blob_path = self._root / "blobs" / f"{content_hash}.json"
        blob = self._read_json(blob_path)
        payload = blob.get("payload")
        if canonical_sha256(payload) != content_hash:
            raise ValueError("cache blob hash mismatch")
        stored_at = datetime.fromisoformat(str(index.get("stored_at")))
        if stored_at.tzinfo is None or stored_at.utcoffset() is None:
            raise ValueError("cache timestamp must include a timezone")
        stale = current - stored_at > self._ttl
        if stale and not allow_stale:
            return None
        return CacheRead(
            value=model.model_validate_json(
                json.dumps(payload, separators=(",", ":"))
            ),
            stale=stale,
            stored_at=stored_at,
            content_sha256=content_hash,
        )

    @staticmethod
    def _read_json(path: Path) -> dict[str, object]:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("cache record must be an object")
        return value

    @staticmethod
    def _write_json(path: Path, value: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(value, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        temporary.replace(path)
