import json
import hashlib

import httpx
import pymupdf
import pytest

from paper_agent.config import ObservabilityConfigurationError, Settings
from paper_agent.evidence import EvidencePackBuilder
from paper_agent.fulltext import FullTextDownloader, PdfParser
from paper_agent.generation import StructuredGeneration
from paper_agent.observability import RunManifest
from paper_agent.pipeline import PipelineDependencies, PipelineResult, run_pipeline
from paper_agent.schemas import Evidence, Paper
from paper_agent.synthesis.models import GroundedClaim, GroundedFinding, PaperAnalysis, SurveyDraft
from paper_agent.synthesis.paper_reader import PaperAnalyzer
from paper_agent.synthesis.survey import SurveySynthesizer


EXPECTED = {"papers.json", "documents.json", "evidence.json", "analyses.json", "report.json", "report.md", "run_manifest.json", "logs.jsonl", "traces.jsonl"}


def _papers():
    return [Paper(paper_id=f"arxiv:2401.0000{i}", title=f"Paper {i}", authors=["A"], year=2024, abstract=f"Abstract evidence for paper {i}. " * 20, url=f"https://arxiv.org/abs/2401.0000{i}", pdf_url=f"https://arxiv.org/pdf/2401.0000{i}", source="arxiv") for i in (1, 2)]


def _pdf():
    document = pymupdf.open()
    for heading, body in (("Introduction", "retrieval agents ground literature reviews "), ("Methods", "hybrid lexical vector fusion selects evidence ")):
        page = document.new_page()
        page.insert_text((72, 72), heading + "\n" + body * 25)
    data = document.tobytes()
    document.close()
    return data


class Embeddings:
    def embed(self, *, texts, **kwargs):
        return [[float("hybrid" in text.lower()), 1.0] for text in texts]


class Provider:
    def __init__(self): self.calls = []
    def generate_structured(self, operation, messages, response_schema, timeout):
        self.calls.append((operation, response_schema, timeout))
        payload = json.loads(messages[-1].content)
        ids = [item["evidence_id"] for item in payload["evidence"]]
        if response_schema is PaperAnalysis:
            result = PaperAnalysis(paper_id=payload["paper"]["paper_id"], contributions=[GroundedFinding(text="Grounded contribution", evidence_ids=[ids[0]])])
        else:
            claim = GroundedClaim(text="Grounded cross-paper result", evidence_ids=ids)
            result = SurveyDraft(tldr_claims=[claim], method_taxonomy=[claim], comparisons=[claim], key_findings=[claim], limitations=[], open_questions=[])
        return StructuredGeneration(result=result, model="qwen3.7-plus", prompt_tokens=10, completion_tokens=4, total_tokens=14, attempts=1, elapsed_seconds=0.01)


def _dependencies(settings, provider, pdf_client, parser=None):
    return PipelineDependencies(search=lambda query, limit: _papers(), downloader=FullTextDownloader(client=pdf_client, timeout_seconds=5, max_bytes=1_000_000), parser=parser or PdfParser(max_pages=10), evidence_packs=EvidencePackBuilder(settings=settings, embedding_transport=Embeddings()), analyzer=PaperAnalyzer(provider), synthesizer=SurveySynthesizer(provider))


def test_pdf_to_formal_report_uses_real_vertical_components(tmp_path):
    pdf = _pdf()
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, headers={"content-type": "application/pdf"}, content=pdf)))
    settings = Settings(dashscope_api_key="offline", retrieval_mode="hybrid", retrieval_top_k=2, analysis_evidence_per_paper=2)
    provider = Provider()
    result = run_pipeline("hybrid literature agents", output_base=tmp_path, limit=3, settings=settings, dependencies=_dependencies(settings, provider, client))
    assert isinstance(result, PipelineResult)
    assert result.status == "completed"
    assert {path.name for path in result.run_dir.iterdir()} == EXPECTED
    manifest = RunManifest.model_validate_json((result.run_dir / "run_manifest.json").read_text())
    trace_bytes = (result.run_dir / 'traces.jsonl').read_bytes()
    trace_records = [
        json.loads(line) for line in trace_bytes.splitlines()
    ]
    assert [
        record['name']
        for record in trace_records
        if record['record_type'] == 'span_start'
    ] == ['paper_agent.pipeline.run']
    assert {
        record['name']
        for record in trace_records
        if record['record_type'] == 'span_event'
    } == {
        'paper_agent.pipeline.run.started',
        'paper_agent.pipeline.retrieval',
        'paper_agent.pipeline.fulltext',
        'paper_agent.pipeline.rerank',
        'paper_agent.pipeline.analysis',
        'paper_agent.pipeline.citation_validation',
        'paper_agent.pipeline.synthesis',
        'paper_agent.pipeline.output',
        'paper_agent.pipeline.run.finished',
    }
    assert trace_records[-1]['record_type'] == 'trace_seal'
    assert manifest.trace_sha256 == hashlib.sha256(trace_bytes).hexdigest()
    evidence = [Evidence.model_validate(item) for item in json.loads((result.run_dir / "evidence.json").read_text())]
    assert len(manifest.retrieval_outcomes) == 2
    assert manifest.usage.model_dump() == {"operations": 3, "http_attempts": 3, "prompt_tokens": 30, "completion_tokens": 12, "total_tokens": 42}
    assert all(item.page and item.section and item.quote for item in evidence)
    assert all(item.evidence_id.startswith(f"{result.run_dir.name}:paper:{item.paper_id}:") for item in evidence)


def test_no_pdf_bypasses_transport_and_parser_but_generates_formal_report(tmp_path):
    class ForbiddenParser:
        def parse(self, **kwargs): raise AssertionError("parser must not be called")
    client = httpx.Client(transport=httpx.MockTransport(lambda request: (_ for _ in ()).throw(AssertionError("PDF transport must not be called"))))
    settings = Settings(dashscope_api_key="offline", retrieval_mode="hybrid")
    provider = Provider()
    result = run_pipeline("abstract agents", output_base=tmp_path, no_pdf=True, settings=settings, dependencies=_dependencies(settings, provider, client, ForbiddenParser()))
    manifest = RunManifest.model_validate_json((result.run_dir / "run_manifest.json").read_text())
    documents = json.loads((result.run_dir / "documents.json").read_text())
    assert all(item["content_source"] == "abstract" and item["fallback_code"] is None for item in documents)
    assert manifest.counts.pdf_fallback_documents == 0
    assert manifest.counts.explicit_abstract_documents == 2
    assert all(call[0] in {"paper_analysis", "survey_synthesis"} for call in provider.calls)
    assert "# Formal Survey:" in (result.run_dir / "report.md").read_text()


def test_otlp_preflight_fails_before_run_directory_creation(
    tmp_path, monkeypatch
):
    settings = Settings(
        dashscope_api_key='offline',
        otlp_enabled=True,
        otlp_endpoint='https://collector.example.test/v1/traces',
    )

    def fail_preflight() -> None:
        raise ObservabilityConfigurationError('observability extra required')

    monkeypatch.setattr('paper_agent.pipeline.preflight_otlp', fail_preflight)

    with pytest.raises(ObservabilityConfigurationError):
        run_pipeline('trace preflight', output_base=tmp_path, settings=settings)

    assert list(tmp_path.iterdir()) == []
