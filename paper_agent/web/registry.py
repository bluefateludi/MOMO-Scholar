from __future__ import annotations

import re
import sqlite3
from base64 import urlsafe_b64decode, urlsafe_b64encode
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from pydantic import TypeAdapter

from paper_agent.modeling import StrictModel
from paper_agent.observability.sanitize import sanitize_event_data
from paper_agent.web.api_models import ApiStatus, CreateRunRequest, Phase, RunProgress
from paper_agent.web.errors import WebError


_CREDENTIAL_VALUE = re.compile(
    r"(?i)\b(api[_-]?key|authorization|credential|password|passwd|secret|token)\b"
    r"\s*[:=]\s*(?:bearer\s+)?[^\s,;]+"
)
_BEARER_VALUE = re.compile(r"(?i)\bbearer\s+[a-z0-9._~+/=-]+")
_SENSITIVE_QUERY_VALUE = re.compile(
    r"(?i)([?&](?:api[_-]?key|authorization|password|secret|token)=)[^&#\s]+"
)


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


class RegistryEvent(StrictModel):
    sequence: int
    event_type: str
    stage: str | None
    status: str
    label: str
    skill: str | None
    tool: str | None
    duration_ms: int | None
    created_at: datetime


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
            if version > 2:
                raise RuntimeError("run registry schema is newer than this server")
            db.execute("BEGIN IMMEDIATE")
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
            if version < 2:
                db.execute("""
                    CREATE TABLE IF NOT EXISTS run_events (
                      sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                      run_id TEXT NOT NULL,
                      event_type TEXT NOT NULL CHECK (event_type IN ('run','stage','skill','tool','recovery','approval')),
                      stage TEXT, status TEXT NOT NULL, label TEXT NOT NULL,
                      skill TEXT, tool TEXT, duration_ms INTEGER,
                      created_at TEXT NOT NULL,
                      FOREIGN KEY(run_id) REFERENCES runs(id) ON DELETE CASCADE
                    )
                """)
                db.execute(
                    "CREATE INDEX IF NOT EXISTS idx_run_events_run_sequence ON run_events(run_id,sequence)"
                )
            db.execute("PRAGMA user_version=2")
            db.commit()

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
            self._append_event_in_transaction(
                db, run_id, event_type="run", stage="queued", status="queued",
                label="Run accepted by the local queue.",
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
            if changed:
                self._append_event_in_transaction(
                    db, row["id"], event_type="stage", stage="initializing",
                    status="running", label="Execution started.",
                )
            db.commit()
        return self.get(row["id"]) if changed else None

    def set_artifact_id(self, run_id: str, artifact_run_id: str) -> None:
        if not artifact_run_id or Path(artifact_run_id).name != artifact_run_id or any(c in artifact_run_id for c in ("/", "\\")):
            raise ValueError("artifact_run_id must be a basename")
        self._update(run_id, artifact_run_id=artifact_run_id)

    def update_progress(self, run_id: str, phase: Phase, progress: RunProgress) -> None:
        phases = ["queued","initializing","search","acquisition","chunking","retrieval","analysis","synthesis","citation_check","publishing","terminal"]
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT phase FROM runs WHERE id=?", (run_id,)).fetchone()
            if row is None:
                db.rollback()
                raise WebError(404, "run_not_found")
            current_phase = row["phase"]
            if phases.index(phase) < phases.index(current_phase):
                db.rollback()
                return
            now = utc_now().isoformat()
            db.execute(
                "UPDATE runs SET phase=?,progress_json=?,updated_at=? WHERE id=?",
                (phase, progress.model_dump_json(), now, run_id),
            )
            if phase != current_phase:
                self._append_event_in_transaction(
                    db, run_id, event_type="stage", stage=phase, status="running",
                    label=f"Entered {phase.replace('_', ' ')} stage.",
                )
            db.commit()

    def terminal(self, run_id: str, status: ApiStatus, *, finished_at: datetime | None = None, error: RegistryError | dict[str, object] | None = None) -> None:
        if status not in ("completed", "completed_with_degradation", "failed", "interrupted"):
            raise ValueError("terminal status required")
        now = utc_now().isoformat()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM runs WHERE id=?", (run_id,)).fetchone() is None:
                db.rollback()
                raise WebError(404, "run_not_found")
            db.execute(
                """UPDATE runs SET status=?,phase='terminal',finished_at=?,error_json=?,updated_at=?
                   WHERE id=?""",
                (
                    status, (finished_at or utc_now()).isoformat(),
                    RegistryError.model_validate(error).model_dump_json() if error else None,
                    now, run_id,
                ),
            )
            self._append_event_in_transaction(
                db, run_id, event_type="run", stage="terminal", status=status,
                label="Run reached a terminal state.",
            )
            db.commit()

    def append_event(
        self,
        run_id: str,
        *,
        event_type: str,
        stage: str | None,
        status: str,
        label: str,
        skill: str | None = None,
        tool: str | None = None,
        duration_ms: int | None = None,
        secrets: tuple[str, ...] = (),
    ) -> None:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM runs WHERE id=?", (run_id,)).fetchone() is None:
                db.rollback()
                raise WebError(404, "run_not_found")
            self._append_event_in_transaction(
                db, run_id, event_type=event_type, stage=stage, status=status,
                label=label, skill=skill, tool=tool, duration_ms=duration_ms,
                secrets=secrets,
            )
            db.commit()

    def list_events(
        self, run_id: str, *, after_sequence: int, limit: int,
    ) -> tuple[list[RegistryEvent], bool]:
        self.get(run_id)
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM run_events WHERE run_id=? AND sequence>? ORDER BY sequence LIMIT ?",
                (run_id, after_sequence, limit + 1),
            ).fetchall()
        page = rows[:limit]
        return [self._parse_event(row) for row in page], len(rows) > limit

    @staticmethod
    def _append_event_in_transaction(
        db: sqlite3.Connection,
        run_id: str,
        *,
        event_type: str,
        stage: str | None,
        status: str,
        label: str,
        skill: str | None = None,
        tool: str | None = None,
        duration_ms: int | None = None,
        secrets: tuple[str, ...] = (),
    ) -> None:
        if event_type not in {"run", "stage", "skill", "tool", "recovery", "approval"}:
            raise ValueError("unsupported event type")
        if duration_ms is not None and duration_ms < 0:
            raise ValueError("duration_ms must be non-negative")

        def clean(value: str | None, maximum: int) -> str | None:
            if value is None:
                return None
            redacted = sanitize_event_data(value, secrets=secrets)
            if not isinstance(redacted, str):
                raise ValueError("trace text must be a string")
            normalized = re.sub(r"[\x00-\x1f\x7f]", " ", redacted).strip()
            normalized = _BEARER_VALUE.sub("[REDACTED]", normalized)
            normalized = _CREDENTIAL_VALUE.sub(
                lambda match: f"{match.group(1)}=[REDACTED]", normalized,
            )
            normalized = _SENSITIVE_QUERY_VALUE.sub(r"\1[REDACTED]", normalized)
            if not normalized:
                raise ValueError("trace text must not be empty")
            return normalized[:maximum]

        db.execute(
            """INSERT INTO run_events
               (run_id,event_type,stage,status,label,skill,tool,duration_ms,created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                run_id, event_type, clean(stage, 80), clean(status, 80),
                clean(label, 240), clean(skill, 120), clean(tool, 120),
                duration_ms, utc_now().isoformat(),
            ),
        )

    @staticmethod
    def _parse_event(row: sqlite3.Row) -> RegistryEvent:
        return RegistryEvent(
            sequence=row["sequence"],
            event_type=row["event_type"], stage=row["stage"], status=row["status"],
            label=row["label"], skill=row["skill"], tool=row["tool"],
            duration_ms=row["duration_ms"],
            created_at=TypeAdapter(datetime).validate_python(row["created_at"]),
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
