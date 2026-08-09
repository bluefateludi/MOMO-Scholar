from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any


class SealedJsonlError(ValueError):
    pass


def _canonical_line(value: Mapping[str, Any]) -> bytes:
    try:
        return (
            json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
            + b"\n"
        )
    except (TypeError, ValueError) as error:
        raise SealedJsonlError("record must be canonical JSON") from error


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


class SealedJsonlWriter:
    """Append canonical records, then hash-bind the stream to a manifest."""

    def __init__(self, path: Path, *, owner_id: str, artifact_kind: str) -> None:
        if not owner_id.strip() or not artifact_kind.strip():
            raise SealedJsonlError("owner and artifact kind must be nonblank")
        self.path = path
        self.owner_id = owner_id
        self.artifact_kind = artifact_kind
        self.manifest_path = path.with_name(f"{path.stem}-manifest.json")
        if path.exists() or self.manifest_path.exists():
            raise SealedJsonlError("sealed JSONL output already exists")
        path.parent.mkdir(parents=True, exist_ok=True)
        self._record_count = 0
        self._handle = path.open("x+b")
        self._sealed = False

    def append(self, record: Mapping[str, Any]) -> None:
        if self._sealed:
            raise SealedJsonlError("sealed JSONL output is immutable")
        self._handle.write(_canonical_line(record))
        self._handle.flush()
        self._record_count += 1

    def seal(
        self,
        *,
        timestamp: datetime,
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if self._sealed:
            raise SealedJsonlError("sealed JSONL output is immutable")
        self._handle.flush()
        self._handle.seek(0)
        pre_seal = self._handle.read()
        seal = {
            "schema_version": "1.0",
            "record_type": "trace_seal",
            "timestamp": timestamp.isoformat().replace("+00:00", "Z"),
            "artifact_kind": self.artifact_kind,
            "owner_id": self.owner_id,
            "record_count": self._record_count,
            "pre_seal_sha256": _sha256(pre_seal),
        }
        content = pre_seal + _canonical_line(seal)
        self._handle.seek(0, 2)
        self._handle.write(_canonical_line(seal))
        self._handle.flush()
        self._handle.close()
        manifest: dict[str, Any] = {
            "schema_version": "1.0",
            "sealed": True,
            "artifact_kind": self.artifact_kind,
            "owner_id": self.owner_id,
            "record_count": self._record_count,
            "path": self.path.name,
            "byte_length": len(content),
            "sha256": _sha256(content),
        }
        if metadata:
            for key, value in metadata.items():
                if key in manifest or not key.strip():
                    raise SealedJsonlError("manifest metadata key is invalid")
                manifest[key] = value
        self.manifest_path.write_bytes(_canonical_line(manifest))
        self._sealed = True
        return manifest


def verify_sealed_jsonl(path: Path) -> dict[str, Any]:
    manifest_path = path.with_name(f"{path.stem}-manifest.json")
    try:
        content = path.read_bytes()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        lines = content.splitlines(keepends=True)
        seal = json.loads(lines[-1])
    except (OSError, UnicodeError, json.JSONDecodeError, IndexError) as error:
        raise SealedJsonlError("sealed JSONL output is missing or invalid") from error
    if (
        manifest.get("sealed") is not True
        or manifest.get("byte_length") != len(content)
        or manifest.get("sha256") != _sha256(content)
        or seal.get("record_type") != "trace_seal"
        or seal.get("record_count") != len(lines) - 1
        or seal.get("pre_seal_sha256") != _sha256(b"".join(lines[:-1]))
        or manifest.get("record_count") != seal.get("record_count")
        or manifest.get("owner_id") != seal.get("owner_id")
        or manifest.get("artifact_kind") != seal.get("artifact_kind")
    ):
        raise SealedJsonlError("sealed JSONL integrity check failed")
    return manifest


__all__ = ["SealedJsonlError", "SealedJsonlWriter", "verify_sealed_jsonl"]
