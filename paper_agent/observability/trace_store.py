from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import BinaryIO

from paper_agent.observability.tracing_models import (
    SpanEndRecord,
    SpanEventRecord,
    SpanStartRecord,
    TraceArtifactKind,
    TraceSealRecord,
)


TraceRecord = SpanStartRecord | SpanEventRecord | SpanEndRecord


class TracePersistenceError(RuntimeError):
    pass


class TraceIntegrityError(ValueError):
    pass


class TraceSealedError(RuntimeError):
    pass


@dataclass(frozen=True)
class TraceFileInspection:
    records: tuple[TraceRecord | TraceSealRecord, ...]
    sha256: str

    @property
    def seal(self) -> TraceSealRecord | None:
        if self.records and isinstance(self.records[-1], TraceSealRecord):
            return self.records[-1]
        return None

    @property
    def sealed(self) -> bool:
        return self.seal is not None


class TraceFileWriter:
    def __init__(
        self,
        path: Path,
        *,
        artifact_kind: TraceArtifactKind,
        owner_id: str,
        handle: BinaryIO | None,
        record_count: int = 0,
        sealed: bool = False,
    ) -> None:
        self.path = path
        self.artifact_kind = artifact_kind
        self.owner_id = owner_id
        self._handle = handle
        self._record_count = record_count
        self._sealed = sealed
        self._failed = False

    @classmethod
    def create(
        cls,
        path: Path,
        *,
        artifact_kind: TraceArtifactKind,
        owner_id: str,
    ) -> TraceFileWriter:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise TracePersistenceError('unable to create trace file') from error
        if path.exists():
            return cls._reopen_sealed(
                path,
                artifact_kind=artifact_kind,
                owner_id=owner_id,
            )
        try:
            handle = path.open('x+b')
        except FileExistsError:
            return cls._reopen_sealed(
                path,
                artifact_kind=artifact_kind,
                owner_id=owner_id,
            )
        except OSError as error:
            raise TracePersistenceError('unable to create trace file') from error
        return cls(
            path,
            artifact_kind=artifact_kind,
            owner_id=owner_id,
            handle=handle,
        )

    @classmethod
    def _reopen_sealed(
        cls,
        path: Path,
        *,
        artifact_kind: TraceArtifactKind,
        owner_id: str,
    ) -> TraceFileWriter:
        inspection = inspect_trace_file(path)
        seal = inspection.seal
        if seal is None:
            raise TracePersistenceError('existing trace file is not sealed')
        if seal.artifact_kind != artifact_kind or seal.owner_id != owner_id:
            raise TraceIntegrityError('trace artifact ownership does not match')
        return cls(
            path,
            artifact_kind=artifact_kind,
            owner_id=owner_id,
            handle=None,
            record_count=seal.record_count,
            sealed=True,
        )

    @property
    def sealed(self) -> bool:
        return self._sealed

    def append(self, record: TraceRecord) -> None:
        if self._sealed:
            raise TraceSealedError('trace file is sealed')
        if self._failed:
            raise TracePersistenceError('trace writer is unusable')
        if not isinstance(record, (SpanStartRecord, SpanEventRecord, SpanEndRecord)):
            raise TypeError('append requires a validated lifecycle record')
        _require_artifact_ownership(record, self.artifact_kind, self.owner_id)
        self._append_record(record)
        self._record_count += 1

    def seal(self, *, timestamp: datetime) -> str:
        if self._sealed:
            raise TraceSealedError('trace file is sealed')
        if self._failed:
            raise TracePersistenceError('trace writer is unusable')
        try:
            self._flush()
            pre_seal_sha256 = _sha256_file(self.path)
            seal = TraceSealRecord(
                timestamp=timestamp,
                artifact_kind=self.artifact_kind,
                owner_id=self.owner_id,
                record_count=self._record_count,
                pre_seal_sha256=pre_seal_sha256,
            )
            self._append_record(seal)
            self._handle.close()
        except OSError as error:
            self._failed = True
            raise TracePersistenceError('unable to seal trace file') from error
        self._sealed = True
        try:
            return _sha256_file(self.path)
        except OSError as error:
            raise TracePersistenceError('unable to hash sealed trace file') from error

    def _append_record(self, record: TraceRecord | TraceSealRecord) -> None:
        if self._handle is None:
            raise TraceSealedError('trace file is sealed')
        line = json.dumps(
            record.model_dump(mode='json'),
            ensure_ascii=False,
            separators=(',', ':'),
        ).encode('utf-8') + b'\n'
        try:
            self._handle.write(line)
            self._flush()
        except OSError as error:
            self._failed = True
            raise TracePersistenceError('unable to persist trace record') from error

    def _flush(self) -> None:
        self._handle.flush()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as file:
        for chunk in iter(lambda: file.read(64 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_trace_file(path: Path) -> TraceFileInspection:
    try:
        content = path.read_bytes()
    except OSError as error:
        raise TracePersistenceError('unable to read trace file') from error

    raw_lines = content.splitlines(keepends=True)
    records: list[TraceRecord | TraceSealRecord] = []
    for raw_line in raw_lines:
        try:
            value = json.loads(raw_line)
            if not isinstance(value, dict):
                raise ValueError('trace record must be a JSON object')
            model = _record_model(value.get('record_type'))
            records.append(model.model_validate(value))
        except (UnicodeError, ValueError, TypeError) as error:
            raise TraceIntegrityError('trace file contains an invalid record') from error

    seal_positions = [
        index
        for index, record in enumerate(records)
        if isinstance(record, TraceSealRecord)
    ]
    if seal_positions and seal_positions != [len(records) - 1]:
        raise TraceIntegrityError('trace seal must be the final record')
    if seal_positions:
        seal = records[-1]
        assert isinstance(seal, TraceSealRecord)
        if seal.record_count != len(records) - 1:
            raise TraceIntegrityError('trace seal record count does not match')
        pre_seal_bytes = b''.join(raw_lines[:-1])
        if seal.pre_seal_sha256 != hashlib.sha256(pre_seal_bytes).hexdigest():
            raise TraceIntegrityError('trace pre-seal hash does not match')
        for record in records[:-1]:
            assert not isinstance(record, TraceSealRecord)
            _require_artifact_ownership(
                record,
                seal.artifact_kind,
                seal.owner_id,
            )

    return TraceFileInspection(
        records=tuple(records),
        sha256=hashlib.sha256(content).hexdigest(),
    )


def _record_model(record_type: object):
    models = {
        'span_start': SpanStartRecord,
        'span_event': SpanEventRecord,
        'span_end': SpanEndRecord,
        'trace_seal': TraceSealRecord,
    }
    try:
        return models[record_type]
    except (KeyError, TypeError) as error:
        raise ValueError('unknown trace record type') from error


def _require_artifact_ownership(
    record: TraceRecord,
    artifact_kind: TraceArtifactKind,
    owner_id: str,
) -> None:
    if artifact_kind == 'pipeline_execution':
        expected_name = 'paper_agent.pipeline.run'
        owner_matches = not isinstance(record, SpanStartRecord) or (
            record.execution_id == owner_id
        )
    else:
        expected_name = 'paper_agent.evaluation.case'
        owner_matches = not isinstance(record, SpanStartRecord) or (
            record.scoring_attempt_id == owner_id
        )
    record_name = record.span_name if isinstance(record, SpanEventRecord) else record.name
    if record_name != expected_name or not owner_matches:
        raise TraceIntegrityError('trace record does not match artifact ownership')
