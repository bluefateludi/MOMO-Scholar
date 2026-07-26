import hashlib
import json
import shutil

import pytest

from paper_agent.observability.evaluation_trace import (
    EvaluationCaseTrace,
    SealedExecutionReference,
)
from paper_agent.observability.models import (
    RunCounts,
    SafeRunSettings,
    UsageTotals,
)
from paper_agent.observability.recorder import RunRecorder
from paper_agent.observability.otlp import OtlpTraceExporter
from paper_agent.observability.trace_store import (
    TraceFileWriter,
    TraceSealedError,
    inspect_trace_file,
)
from paper_agent.observability.trace_validation import (
    rebuild_trace_index,
    validate_pipeline_trace,
    validate_trace_pair,
)
from paper_agent.observability.tracing_models import (
    PipelineCorrelationInput,
    ScoringCorrelation,
    W3CSpanContext,
)


SAFE_SETTINGS = SafeRunSettings(
    retrieval_mode='auto',
    embedding_model='text-embedding-v4',
    generation_provider='dashscope',
    generation_endpoint_host='dashscope.aliyuncs.com',
    generation_model='qwen3.7-plus',
    generation_timeout_seconds=60,
    pdf_download_timeout_seconds=30,
    pdf_max_bytes=25_000_000,
    pdf_max_pages=200,
    analysis_evidence_per_paper=6,
    chunk_max_words=180,
    chunk_overlap_words=30,
)
COUNTS = RunCounts(
    selected_papers=0,
    pdf_documents=0,
    abstract_documents=0,
    explicit_abstract_documents=0,
    pdf_fallback_documents=0,
    excluded_papers=0,
    successful_analyses=0,
    evidence_items=0,
)
USAGE = UsageTotals(operations=0, http_attempts=0)
SUCCESS_EVENTS = (
    'paper_agent.pipeline.run.started',
    'paper_agent.pipeline.retrieval',
    'paper_agent.pipeline.fulltext',
    'paper_agent.pipeline.rerank',
    'paper_agent.pipeline.analysis',
    'paper_agent.pipeline.citation_validation',
    'paper_agent.pipeline.synthesis',
    'paper_agent.pipeline.output',
    'paper_agent.pipeline.run.finished',
)


def _pipeline(tmp_path, *, correlation=None, execution_id=None):
    recorder = RunRecorder.start(
        output_base=tmp_path,
        question='trace validation',
        requested_limit=1,
        no_pdf=True,
        safe_settings=SAFE_SETTINGS,
        component_versions={},
        correlation=correlation,
        execution_id=execution_id,
    )
    for event_name in SUCCESS_EVENTS:
        recorder.trace_event(event_name, {})
    recorder.complete(
        status='completed',
        counts=COUNTS,
        retrieval_outcomes=(),
        stage_elapsed_seconds={},
        usage=USAGE,
    )
    return recorder


def test_fresh_child_validation_matches_cross_file_context(tmp_path) -> None:
    evaluation = EvaluationCaseTrace.start(
        path=tmp_path / 'score' / 'evaluation-traces.jsonl',
        correlation=ScoringCorrelation(
            scoring_attempt_id='score-1',
            execution_id='exec-1',
            case_id='case-1',
        ),
    )
    pipeline = _pipeline(
        tmp_path / 'runs',
        correlation=evaluation.fresh_pipeline_parent(),
    )
    evaluation.finish('ok')

    result = validate_trace_pair(
        evaluation_path=evaluation.path,
        run_dir=pipeline.run_dir,
    )
    assert result.correlation_mode == 'fresh_child'
    assert result.valid


def test_declared_reuse_link_validates_historical_execution(tmp_path) -> None:
    pipeline = _pipeline(
        tmp_path / 'runs',
        correlation=PipelineCorrelationInput(
            execution_id='exec-old',
            case_id='case-1',
        ),
    )
    manifest = json.loads(
        (pipeline.run_dir / 'run_manifest.json').read_text(encoding='utf-8')
    )
    evaluation = EvaluationCaseTrace.start_reuse(
        path=tmp_path / 'score' / 'evaluation-traces.jsonl',
        scoring_attempt_id='score-2',
        case_id='case-1',
        reused=SealedExecutionReference(
            execution_id='exec-old',
            trace_id=manifest['trace_root_trace_id'],
            span_id=manifest['trace_root_span_id'],
            trace_sha256=manifest['trace_sha256'],
        ),
    )
    evaluation.finish('ok')

    result = validate_trace_pair(
        evaluation_path=evaluation.path,
        run_dir=pipeline.run_dir,
    )
    assert result.correlation_mode == 'declared_reuse_link'
    assert result.valid


def test_missing_terminal_manifest_is_unknown(tmp_path) -> None:
    pipeline = _pipeline(tmp_path / 'runs')
    (pipeline.run_dir / 'run_manifest.json').unlink()

    result = validate_pipeline_trace(pipeline.run_dir)
    assert result.pipeline_outcome == 'unknown'
    assert 'terminal_manifest_missing' in result.finding_codes


def test_trace_index_ignores_untrusted_labels(tmp_path) -> None:
    pipeline = _pipeline(tmp_path / 'runs')
    index_path = tmp_path / 'trace-index.json'
    rebuilt = rebuild_trace_index(
        [
            {
                'run_dir': pipeline.run_dir,
                'untrusted_label': 'runtime-secret-value',
            }
        ],
        path=index_path,
    )
    assert rebuilt == json.loads(index_path.read_text(encoding='utf-8'))
    assert rebuilt['projection_version'] == '1.0'
    assert 'runtime-secret-value' not in index_path.read_text(encoding='utf-8')


def test_post_seal_append_is_invalid(tmp_path) -> None:
    pipeline = _pipeline(tmp_path / 'runs')
    with (pipeline.run_dir / 'traces.jsonl').open(
        'a', encoding='utf-8'
    ) as trace_file:
        trace_file.write('{}\n')

    result = validate_pipeline_trace(pipeline.run_dir)
    assert not result.valid
    assert 'trace_integrity_invalid' in result.finding_codes


def test_manifest_and_root_terminal_status_mismatch_is_reported(
    tmp_path,
) -> None:
    pipeline = _pipeline(tmp_path / 'runs')
    manifest_path = pipeline.run_dir / 'run_manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    manifest['status'] = 'failed'
    manifest['errors'] = [
        {
            'stage': 'test',
            'code': 'forced_failure',
            'paper_id': None,
            'message': None,
        }
    ]
    manifest_path.write_text(json.dumps(manifest), encoding='utf-8')

    result = validate_pipeline_trace(pipeline.run_dir)
    assert 'terminal_status_mismatch' in result.finding_codes


def test_early_search_failure_requires_only_applicable_events(tmp_path) -> None:
    recorder = RunRecorder.start(
        output_base=tmp_path,
        question='early failure',
        requested_limit=1,
        no_pdf=True,
        safe_settings=SAFE_SETTINGS,
        component_versions={},
    )
    recorder.trace_event('paper_agent.pipeline.run.started', {})
    recorder.trace_event(
        'paper_agent.pipeline.retrieval',
        {'failure_stage': 'search'},
        status='error',
        code='search_failed',
    )
    recorder.trace_event(
        'paper_agent.pipeline.run.finished',
        {'failure_stage': 'search'},
        status='error',
        code='search_failed',
    )
    recorder.fail(
        stage='search',
        code='search_failed',
        counts=COUNTS,
        retrieval_outcomes=(),
        stage_elapsed_seconds={'search': 0.1},
        usage=USAGE,
    )

    result = validate_pipeline_trace(recorder.run_dir)
    assert result.valid
    assert result.required_event_coverage == 1.0


def test_synthetic_external_parent_reuse_seal_and_recovery_acceptance(
    tmp_path,
) -> None:
    external_parent = W3CSpanContext(
        trace_id='1' * 32,
        span_id='2' * 16,
    )
    fresh = EvaluationCaseTrace.start(
        path=tmp_path / 'score-1' / 'evaluation-traces.jsonl',
        correlation=ScoringCorrelation(
            scoring_attempt_id='score-1',
            execution_id='exec-1',
            case_id='case-1',
        ),
        parent=external_parent,
    )
    pipeline = _pipeline(
        tmp_path / 'runs',
        correlation=fresh.fresh_pipeline_parent(),
    )
    fresh.finish('ok')

    manifest_path = pipeline.run_dir / 'run_manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    reuse = EvaluationCaseTrace.start_reuse(
        path=tmp_path / 'score-2' / 'evaluation-traces.jsonl',
        scoring_attempt_id='score-2',
        case_id='case-1',
        reused=SealedExecutionReference(
            execution_id='exec-1',
            trace_id=manifest['trace_root_trace_id'],
            span_id=manifest['trace_root_span_id'],
            trace_sha256=manifest['trace_sha256'],
        ),
    )
    reuse.finish('ok')

    for path in (
        fresh.path,
        pipeline.run_dir / 'traces.jsonl',
        reuse.path,
    ):
        content = path.read_bytes()
        inspection = inspect_trace_file(path)
        assert inspection.seal is not None
        assert inspection.seal.pre_seal_sha256 == hashlib.sha256(
            b''.join(content.splitlines(keepends=True)[:-1])
        ).hexdigest()
        assert inspection.sha256 == hashlib.sha256(content).hexdigest()

    assert validate_trace_pair(
        evaluation_path=fresh.path,
        run_dir=pipeline.run_dir,
    ).correlation_mode == 'fresh_child'
    assert validate_trace_pair(
        evaluation_path=reuse.path,
        run_dir=pipeline.run_dir,
    ).correlation_mode == 'declared_reuse_link'

    index = rebuild_trace_index(
        [
            {'run_dir': pipeline.run_dir, 'evaluation_path': fresh.path},
            {'run_dir': pipeline.run_dir, 'evaluation_path': reuse.path},
        ],
        path=tmp_path / 'trace-index.json',
    )
    assert len(index['entries']) == 2

    snapshots = {
        'pipeline': (pipeline.run_dir / 'traces.jsonl').read_bytes(),
        'manifest': manifest_path.read_bytes(),
        'fresh': fresh.path.read_bytes(),
    }
    exported = []
    exporter = OtlpTraceExporter(
        endpoint='https://collector.example.test/v1/traces',
        headers={},
        timeout_seconds=1,
        failure_threshold=1,
        replay=lambda inspection, **_: exported.append(inspection.sha256),
    )
    assert exporter.export_file(fresh.path)
    assert exporter.export_file(pipeline.run_dir / 'traces.jsonl')
    assert len(exported) == 2
    assert fresh.path.read_bytes() == snapshots['fresh']
    assert manifest_path.read_bytes() == snapshots['manifest']
    assert (
        pipeline.run_dir / 'traces.jsonl'
    ).read_bytes() == snapshots['pipeline']

    sealed_writer = TraceFileWriter.create(
        fresh.path,
        artifact_kind='evaluation_scoring_attempt',
        owner_id='score-1',
    )
    with pytest.raises(TraceSealedError):
        sealed_writer.append(inspect_trace_file(fresh.path).records[0])

    pre_seal_tamper = tmp_path / 'tampered-pre-seal'
    shutil.copytree(pipeline.run_dir, pre_seal_tamper)
    trace_path = pre_seal_tamper / 'traces.jsonl'
    lines = trace_path.read_bytes().splitlines(keepends=True)
    first = json.loads(lines[0])
    first['attributes']['tampered'] = True
    lines[0] = json.dumps(first, separators=(',', ':')).encode() + b'\n'
    trace_path.write_bytes(b''.join(lines))
    assert 'trace_integrity_invalid' in validate_pipeline_trace(
        pre_seal_tamper
    ).finding_codes

    full_hash_tamper = tmp_path / 'tampered-full-hash'
    shutil.copytree(pipeline.run_dir, full_hash_tamper)
    tampered_manifest_path = full_hash_tamper / 'run_manifest.json'
    tampered_manifest = json.loads(tampered_manifest_path.read_text())
    tampered_manifest['trace_sha256'] = '0' * 64
    tampered_manifest_path.write_text(json.dumps(tampered_manifest))
    assert 'full_file_hash_mismatch' in validate_pipeline_trace(
        full_hash_tamper
    ).finding_codes

    missing_manifest = tmp_path / 'missing-manifest'
    shutil.copytree(pipeline.run_dir, missing_manifest)
    (missing_manifest / 'run_manifest.json').unlink()
    assert validate_pipeline_trace(missing_manifest).pipeline_outcome == 'unknown'
