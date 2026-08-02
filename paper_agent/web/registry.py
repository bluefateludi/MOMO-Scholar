from __future__ import annotations

import sqlite3
from base64 import urlsafe_b64decode, urlsafe_b64encode
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from pydantic import TypeAdapter

from paper_agent.modeling import StrictModel
from paper_agent.web.api_models import ApiStatus, CreateRunRequest, Phase, RunProgress
from paper_agent.web.errors import WebError


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class RegistryRun(StrictModel):
    id: str
    artifact_run_id: str | None
    origin: str
    status: ApiStatus
    phase: Phase
    request: CreateRunRequest
    progress: RunProgress
    error: "RegistryError | None"
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    updated_at: datetime


class RegistryError(StrictModel):
    stage: str
    code: str
    paper_id: str | None = None


class RunRegistry:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._migrate()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=5000")
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            yield connection
        finally:
            connection.close()

    def _migrate(self) -> None:
        with self._connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version > 1:
                raise RuntimeError("run registry schema is newer than this server")
            db.execute("""
                CREATE TABLE IF NOT EXISTS runs (
                  id TEXT PRIMARY KEY,
                  artifact_run_id TEXT UNIQUE,
                  origin TEXT NOT NULL CHECK (origin IN ('live','bundled_demo')),
                  status TEXT NOT NULL CHECK (status IN ('queued','running','completed','completed_with_degradation','failed','interrupted')),
                  phase TEXT NOT NULL CHECK (phase IN ('queued','initializing','search','acquisition','chunking','retrieval','analysis','synthesis','citation_check','publishing','terminal')),
                  request_json TEXT NOT NULL, progress_json TEXT NOT NULL,
                  error_json TEXT, created_at TEXT NOT NULL, started_at TEXT,
                  finished_at TEXT, updated_at TEXT NOT NULL
                )
            """)
            db.execute("PRAGMA user_version=1")

    def admit(self, run_id: str, request: CreateRunRequest, capacity: int) -> RegistryRun:
        now = utc_now().isoformat()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            active = db.execute("SELECT COUNT(*) FROM runs WHERE status IN ('queued','running')").fetchone()[0]
            if active >= capacity:
                db.rollback()
                raise WebError(503, "queue_full")
            db.execute(
                "INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (run_id, None, "live", "queued", "queued", request.model_dump_json(),
                 RunProgress().model_dump_json(), None, now, None, None, now),
            )
            db.commit()
        return self.get(run_id)

    def get(self, run_id: str) -> RegistryRun:
        with self._connect() as db:
            row = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise WebError(404, "run_not_found")
        return self._parse(row)

    def claim_oldest(self) -> RegistryRun | None:
        now = utc_now().isoformat()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM runs WHERE status='running' LIMIT 1").fetchone():
                db.rollback()
                return None
            row = db.execute("SELECT id FROM runs WHERE status='queued' ORDER BY created_at,id LIMIT 1").fetchone()
            if row is None:
                db.rollback()
                return None
            changed = db.execute(
                "UPDATE runs SET status='running',phase='initializing',started_at=?,updated_at=? WHERE id=? AND status='queued'",
                (now, now, row["id"]),
            ).rowcount
            db.commit()
        return self.get(row["id"]) if changed else None

    def set_artifact_id(self, run_id: str, artifact_run_id: str) -> None:
        if not artifact_run_id or Path(artifact_run_id).name != artifact_run_id or any(c in artifact_run_id for c in ("/", "\\")):
            raise ValueError("artifact_run_id must be a basename")
        self._update(run_id, artifact_run_id=artifact_run_id)

    def update_progress(self, run_id: str, phase: Phase, progress: RunProgress) -> None:
        phases = ["queued","initializing","search","acquisition","chunking","retrieval","analysis","synthesis","citation_check","publishing","terminal"]
        current = self.get(run_id)
        if phases.index(phase) < phases.index(current.phase):
            return
        self._update(run_id, phase=phase, progress_json=progress.model_dump_json())

    def terminal(self, run_id: str, status: ApiStatus, *, finished_at: datetime | None = None, error: RegistryError | dict[str, object] | None = None) -> None:
        if status not in ("completed", "completed_with_degradation", "failed", "interrupted"):
            raise ValueError("terminal status required")
        self._update(
            run_id, status=status, phase="terminal",
            finished_at=(finished_at or utc_now()).isoformat(),
            error_json=(RegistryError.model_validate(error).model_dump_json() if error else None),
        )

    def active(self) -> list[RegistryRun]:
        with self._connect() as db:
            rows = db.execute("SELECT * FROM runs WHERE status IN ('queued','running') ORDER BY created_at").fetchall()
        return [self._parse(row) for row in rows]

    def list(self, limit: int, cursor: str | None = None) -> tuple[list[RegistryRun], str | None]:
        parameters: list[object] = []
        where = ""
        if cursor:
            try:
                decoded = urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
                created_at, run_id = decoded.split("\0", 1)
            except (ValueError, UnicodeError) as exc:
                raise WebError(422, "validation_error") from exc
            where = "WHERE (created_at < ? OR (created_at = ? AND id < ?))"
            parameters.extend((created_at, created_at, run_id))
        with self._connect() as db:
            rows = db.execute(
                f"SELECT * FROM runs {where} ORDER BY created_at DESC,id DESC LIMIT ?",
                (*parameters, limit + 1),
            ).fetchall()
        has_more = len(rows) > limit
        page = rows[:limit]
        next_cursor = None
        if has_more and page:
            token = f"{page[-1]['created_at']}\0{page[-1]['id']}".encode("utf-8")
            next_cursor = urlsafe_b64encode(token).decode("ascii")
        return [self._parse(row) for row in page], next_cursor

    def seed_demo(
        self,
        *,
        run_id: str,
        artifact_run_id: str,
        request: CreateRunRequest,
        started_at: datetime,
        finished_at: datetime,
        status: ApiStatus,
    ) -> None:
        if status not in ("completed", "completed_with_degradation"):
            raise ValueError("bundled demo must be successful and terminal")
        now = finished_at.isoformat()
        with self._connect() as db:
            existing = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            if existing is not None:
                row = self._parse(existing)
                if row.origin != "bundled_demo" or row.artifact_run_id != artifact_run_id:
                    raise RuntimeError("bundled demo registry row does not match packaged artifacts")
                db.execute(
                    """UPDATE runs SET status=?,phase='terminal',request_json=?,progress_json=?,
                       error_json=NULL,started_at=?,finished_at=?,updated_at=? WHERE id=?""",
                    (
                        status, request.model_dump_json(),
                        RunProgress(completed_units=request.paper_limit, total_units=request.paper_limit).model_dump_json(),
                        started_at.isoformat(), now, now, run_id,
                    ),
                )
                return
            db.execute(
                "INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    run_id, artifact_run_id, "bundled_demo", status, "terminal",
                    request.model_dump_json(),
                    RunProgress(completed_units=request.paper_limit, total_units=request.paper_limit).model_dump_json(),
                    None, started_at.isoformat(), started_at.isoformat(), now, now,
                ),
            )

    def _update(self, run_id: str, **values: object) -> None:
        values["updated_at"] = utc_now().isoformat()
        assignments = ",".join(f"{name}=?" for name in values)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(f"UPDATE runs SET {assignments} WHERE id=?", (*values.values(), run_id))
            db.commit()

    @staticmethod
    def _parse(row: sqlite3.Row) -> RegistryRun:
        return RegistryRun(
            id=row["id"], artifact_run_id=row["artifact_run_id"], origin=row["origin"],
            status=row["status"], phase=row["phase"],
            request=CreateRunRequest.model_validate_json(row["request_json"]),
            progress=RunProgress.model_validate_json(row["progress_json"]),
            error=RegistryError.model_validate_json(row["error_json"]) if row["error_json"] else None,
            created_at=TypeAdapter(datetime).validate_python(row["created_at"]),
            started_at=TypeAdapter(datetime).validate_python(row["started_at"]) if row["started_at"] else None,
            finished_at=TypeAdapter(datetime).validate_python(row["finished_at"]) if row["finished_at"] else None,
            updated_at=TypeAdapter(datetime).validate_python(row["updated_at"]),
        )
