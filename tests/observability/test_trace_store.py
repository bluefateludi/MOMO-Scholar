import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

import paper_agent.observability.trace_store as trace_store_module
from paper_agent.observability.trace_store import (
    TraceFileWriter,
    TraceIntegrityError,
    TracePersistenceError,
    TraceSealedError,
    inspect_trace_file,
)
from paper_agent.observability.tracing_models import (
    SpanEndRecord,
    SpanEventRecord,
    SpanStartRecord,
    TraceSealRecord,
)


NOW = datetime(2026, 7, 23, 12, tzinfo=timezone.utc)


def _store(tmp_path) -> TraceFileWriter:
    return TraceFileWriter.create(
        tmp_path / 'traces.jsonl',
        artifact_kind='pipeline_execution',
        owner_id='exec-1',
    )


def _start() -> SpanStartRecord:
    return SpanStartRecord(
        timestamp=NOW,
        trace_id='1' * 32,
        span_id='2' * 16,
        parent_span_id=None,
        name='paper_agent.pipeline.run',
        run_id='run-1',
        execution_id='exec-1',
        correlation_mode='standalone',
        attributes={},
        links=[],
    )


def _event() -> SpanEventRecord:
    return SpanEventRecord(
        timestamp=NOW,
        trace_id='1' * 32,
        span_id='2' * 16,
        span_name='paper_agent.pipeline.run',
        name='paper_agent.pipeline.retrieval',
        status='ok',
        attributes={},
    )


def _end() -> SpanEndRecord:
    return SpanEndRecord(
        timestamp=NOW,
        trace_id='1' * 32,
        span_id='2' * 16,
        name='paper_agent.pipeline.run',
        status='ok',
        duration_ms=1.0,
        attributes={},
    )


def _raise_oserror() -> None:
    raise OSError('sensitive filesystem detail')


def test_seal_is_final_record_and_returns_full_file_hash(tmp_path) -> None:
    store = TraceFileWriter.create(
        tmp_path / 'traces.jsonl',
        artifact_kind='pipeline_execution',
        owner_id='exec-1',
    )
    store.append(_start())
    store.append(_end())

    digest = store.seal(timestamp=NOW)

    lines = (tmp_path / 'traces.jsonl').read_bytes().splitlines()
    seal = json.loads(lines[-1])
    assert seal['record_type'] == 'trace_seal'
    assert seal['record_count'] == 2
    assert digest == hashlib.sha256(
        (tmp_path / 'traces.jsonl').read_bytes()
    ).hexdigest()
    with pytest.raises(TraceSealedError):
        store.append(_event())


def test_seal_hashes_exact_pre_seal_bytes(tmp_path) -> None:
    store = _store(tmp_path)
    store.append(_start())
    before = (tmp_path / 'traces.jsonl').read_bytes()

    store.seal(timestamp=NOW)

    seal = json.loads(
        (tmp_path / 'traces.jsonl').read_text(encoding='utf-8').splitlines()[-1]
    )
    assert seal['record_count'] == 1
    assert seal['pre_seal_sha256'] == hashlib.sha256(before).hexdigest()


def test_append_or_flush_failure_is_integrity_error(tmp_path, monkeypatch) -> None:
    store = _store(tmp_path)
    monkeypatch.setattr(store, '_flush', _raise_oserror)

    with pytest.raises(TracePersistenceError) as error:
        store.seal(timestamp=NOW)

    assert 'sensitive filesystem detail' not in str(error.value)


def test_inspection_rejects_record_appended_after_seal(tmp_path) -> None:
    store = _store(tmp_path)
    store.append(_start())
    store.seal(timestamp=NOW)
    trace_path = tmp_path / 'traces.jsonl'
    with trace_path.open('ab') as file:
        file.write(_event().model_dump_json().encode('utf-8') + b'\n')

    with pytest.raises(TraceIntegrityError, match='final record'):
        inspect_trace_file(trace_path)


def test_reopening_sealed_trace_returns_read_only_writer(tmp_path) -> None:
    store = _store(tmp_path)
    store.append(_start())
    store.seal(timestamp=NOW)

    reopened = TraceFileWriter.create(
        tmp_path / 'traces.jsonl',
        artifact_kind='pipeline_execution',
        owner_id='exec-1',
    )

    assert reopened.sealed
    with pytest.raises(TraceSealedError):
        reopened.append(_event())


def test_append_rejects_caller_created_seal_record(tmp_path) -> None:
    store = _store(tmp_path)
    seal = TraceSealRecord(
        timestamp=NOW,
        artifact_kind='pipeline_execution',
        owner_id='exec-1',
        record_count=0,
        pre_seal_sha256=hashlib.sha256(b'').hexdigest(),
    )

    with pytest.raises(TypeError, match='lifecycle record'):
        store.append(seal)  # type: ignore[arg-type]


def test_persistence_failure_makes_writer_unusable(tmp_path, monkeypatch) -> None:
    store = _store(tmp_path)
    real_flush = store._flush
    monkeypatch.setattr(store, '_flush', _raise_oserror)
    with pytest.raises(TracePersistenceError):
        store.append(_start())
    monkeypatch.setattr(store, '_flush', real_flush)

    with pytest.raises(TracePersistenceError, match='unusable'):
        store.append(_event())


def test_second_seal_is_rejected(tmp_path) -> None:
    store = _store(tmp_path)
    store.seal(timestamp=NOW)

    with pytest.raises(TraceSealedError):
        store.seal(timestamp=NOW)


def test_append_does_not_mutate_input_model(tmp_path) -> None:
    store = _store(tmp_path)
    record = _start()
    before = record.model_dump(mode='python')

    store.append(record)

    assert record.model_dump(mode='python') == before


def test_append_writes_one_compact_utf8_json_object_per_line(tmp_path) -> None:
    store = _store(tmp_path)
    record = _event().model_copy(
        update={'attributes': {'message': '中文\nsecond line'}}
    )

    store.append(record)

    content = (tmp_path / 'traces.jsonl').read_bytes()
    text = content.decode('utf-8')
    assert content.count(b'\n') == 1
    assert '中文' in text
    assert ': ' not in text
    assert json.loads(text) == record.model_dump(mode='json')


def test_create_does_not_truncate_existing_unsealed_trace(tmp_path) -> None:
    trace_path = tmp_path / 'traces.jsonl'
    existing = _start().model_dump_json().encode('utf-8') + b'\n'
    trace_path.write_bytes(existing)

    with pytest.raises(TracePersistenceError, match='not sealed'):
        _store(tmp_path)

    assert trace_path.read_bytes() == existing


def test_reopen_requires_matching_artifact_ownership(tmp_path) -> None:
    store = _store(tmp_path)
    store.seal(timestamp=NOW)
    trace_path = tmp_path / 'traces.jsonl'
    before = trace_path.read_bytes()

    with pytest.raises(TraceIntegrityError, match='ownership'):
        TraceFileWriter.create(
            trace_path,
            artifact_kind='pipeline_execution',
            owner_id='exec-other',
        )

    assert trace_path.read_bytes() == before


def test_full_file_hash_failure_is_safe_persistence_error(
    tmp_path, monkeypatch
) -> None:
    store = _store(tmp_path)
    real_sha256_file = trace_store_module._sha256_file
    calls = 0

    def fail_second_hash(path):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError('sensitive hash read detail')
        return real_sha256_file(path)

    monkeypatch.setattr(trace_store_module, '_sha256_file', fail_second_hash)

    with pytest.raises(TracePersistenceError) as error:
        store.seal(timestamp=NOW)

    assert store.sealed
    assert 'sensitive hash read detail' not in str(error.value)


def test_append_rejects_record_from_different_artifact_owner(tmp_path) -> None:
    store = _store(tmp_path)
    other_execution = _start().model_copy(update={'execution_id': 'exec-other'})

    with pytest.raises(TraceIntegrityError, match='ownership'):
        store.append(other_execution)

    assert (tmp_path / 'traces.jsonl').read_bytes() == b''


def test_create_wraps_directory_creation_failure_safely(
    tmp_path, monkeypatch
) -> None:
    trace_dir = tmp_path / 'trace-output'
    real_mkdir = Path.mkdir

    def fail_trace_directory(path, *args, **kwargs):
        if path == trace_dir:
            raise OSError('sensitive-directory-sentinel')
        return real_mkdir(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'mkdir', fail_trace_directory)

    with pytest.raises(TracePersistenceError) as error:
        TraceFileWriter.create(
            trace_dir / 'traces.jsonl',
            artifact_kind='pipeline_execution',
            owner_id='exec-1',
        )

    assert 'sensitive-directory-sentinel' not in str(error.value)
