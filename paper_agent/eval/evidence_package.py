from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path, PurePath


REQUIRED_ARTIFACTS = frozenset(
    {
        "dataset-manifest.json",
        "corpus-manifest.json",
        "gold-judgments.jsonl",
        "resolved-config.json",
        "environment.json",
        "raw-rankings.jsonl",
        "case-metrics.jsonl",
        "aggregate.json",
        "confidence-intervals.json",
        "failures.jsonl",
        "logs.jsonl",
        "traces.jsonl",
        "report.md",
        "resume-evidence.md",
    }
)
_MANIFEST = "artifact-manifest.json"


class EvidencePackageError(ValueError):
    pass


def _validate_artifact_path(path: str) -> str:
    parsed = PurePath(path)
    if (
        not path
        or parsed.is_absolute()
        or len(parsed.parts) != 1
        or path in {".", "..", _MANIFEST}
        or "/" in path
        or "\\" in path
    ):
        raise EvidencePackageError("artifact path must be a canonical top-level name")
    return path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(64 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_write(path: Path, content: bytes) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_bytes(content)
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


class EvidencePackageBuilder:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    @property
    def sealed(self) -> bool:
        return (self.root / _MANIFEST).exists()

    def write_json(self, path: str, value: object) -> None:
        content = (
            json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
            + "\n"
        )
        self.write_text(path, content)

    def write_text(self, path: str, content: str) -> None:
        if self.sealed:
            raise EvidencePackageError("evidence package is sealed")
        name = _validate_artifact_path(path)
        _atomic_write(self.root / name, content.encode("utf-8"))

    def seal(self, *, package_kind: str) -> dict[str, object]:
        if self.sealed:
            raise EvidencePackageError("evidence package is already sealed")
        present = {path.name for path in self.root.iterdir() if path.is_file()}
        missing = sorted(REQUIRED_ARTIFACTS - present)
        if missing:
            raise EvidencePackageError(
                f"missing required artifacts: {', '.join(missing)}"
            )
        if not package_kind.strip():
            raise EvidencePackageError("package kind must not be blank")
        try:
            environment = json.loads(
                (self.root / "environment.json").read_text(encoding="utf-8")
            )
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise EvidencePackageError("environment.json is invalid") from error
        if environment.get("git_dirty") is not False:
            raise EvidencePackageError("publishable package requires a clean Git worktree")
        models = environment.get("models")
        if not isinstance(models, dict) or not models or any(
            not isinstance(value, str) or not value.strip() for value in models.values()
        ):
            raise EvidencePackageError("environment must record every model version")

        artifacts = []
        for name in sorted(REQUIRED_ARTIFACTS):
            path = self.root / name
            artifacts.append(
                {
                    "path": name,
                    "byte_length": path.stat().st_size,
                    "sha256": _sha256(path),
                }
            )
        manifest: dict[str, object] = {
            "schema_version": "1.0",
            "package_kind": package_kind,
            "sealed": True,
            "sealed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "artifacts": artifacts,
        }
        content = (
            json.dumps(
                manifest,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            )
            + "\n"
        ).encode("utf-8")
        _atomic_write(self.root / _MANIFEST, content)
        return manifest


def verify_evidence_package(root: str | Path) -> dict[str, object]:
    package_root = Path(root)
    try:
        manifest = json.loads(
            (package_root / _MANIFEST).read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise EvidencePackageError("artifact manifest is missing or invalid") from error
    if not isinstance(manifest, dict) or manifest.get("sealed") is not True:
        raise EvidencePackageError("artifact manifest is not sealed")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        raise EvidencePackageError("artifact manifest entries are invalid")
    seen: set[str] = set()
    for entry in artifacts:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            raise EvidencePackageError("artifact manifest entries are invalid")
        name = _validate_artifact_path(entry["path"])
        if name in seen:
            raise EvidencePackageError("artifact manifest contains duplicate paths")
        seen.add(name)
        path = package_root / name
        if not path.is_file():
            raise EvidencePackageError(f"artifact is missing: {name}")
        if path.stat().st_size != entry.get("byte_length"):
            raise EvidencePackageError(f"artifact length mismatch: {name}")
        if _sha256(path) != entry.get("sha256"):
            raise EvidencePackageError(f"artifact hash mismatch: {name}")
    if seen != REQUIRED_ARTIFACTS:
        raise EvidencePackageError("artifact manifest does not cover required artifacts")
    return manifest


__all__ = [
    "EvidencePackageBuilder",
    "EvidencePackageError",
    "REQUIRED_ARTIFACTS",
    "verify_evidence_package",
]
