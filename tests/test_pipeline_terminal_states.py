import json

import pytest

from paper_agent.config import Settings
from paper_agent.evidence import EvidencePack
from paper_agent.fulltext import PdfDownloadError
from paper_agent.generation import (
    GenerationAuthenticationError,
    GenerationFailureMetadata,
    GenerationTimeoutError,
    StructuredGeneration,
)
from paper_agent.observability import RetrievalRecord, RunManifest
from paper_agent.pipeline import PipelineDependencies, run_pipeline
from paper_agent.schemas import Evidence, Paper
from paper_agent.synthesis.models import GroundedClaim, GroundedFinding, PaperAnalysis, SurveyDraft


PDF_FALLBACK_CODES = [
    "pdf_url_missing", "pdf_download_timeout", "pdf_not_found", "pdf_http_error",
    "pdf_redirect_rejected", "pdf_too_large", "pdf_content_invalid", "pdf_corrupt",
    "pdf_encrypted", "pdf_too_many_pages", "pdf_text_empty",
]


def _papers(count=2):
    return [Paper(paper_id=f"p{i}", title=f"Paper {i}", abstract=(f"usable abstract {i} " * 30), url=f"https://arxiv.org/abs/2401.0000{i}", source="arxiv") for i in range(1, count + 1)]


class FailingDownloader:
    def __init__(self, code): self.code = code
    def download(self, paper): raise PdfDownloadError(self.code, "safe fallback")


class ForbiddenParser:
    def parse(self, **kwargs): raise AssertionError("parser should not run")


class Packs:
    def build(self, *, paper_id, chunks, run_id, **kwargs):
        chunk = chunks[0]
        item = Evidence(evidence_id=f"{run_id}:paper:{paper_id}:ev_001", paper_id=paper_id, chunk_id=chunk.chunk_id, section=chunk.section, page=chunk.page, claim_type="finding", quote=chunk.text, relevance_score=1)
        return EvidencePack(paper_id=paper_id, evidence=[item], retrieval=RetrievalRecord(paper_id=paper_id, requested_mode="hybrid", actual_mode="hybrid", degraded=False))


def _generation(result):
    return StructuredGeneration(result=result, model="qwen3.7-plus", prompt_tokens=2, completion_tokens=1, total_tokens=3, attempts=1, elapsed_seconds=0)


class Analyzer:
    def __init__(self, error=None): self.error = error
    def analyze(self, *, paper, evidence_pack, **kwargs):
        if self.error: raise self.error
        return _generation(PaperAnalysis(paper_id=paper.paper_id, contributions=[GroundedFinding(text="supported", evidence_ids=[evidence_pack.evidence[0].evidence_id])]))


class Synthesizer:
    def synthesize(self, *, question, evidence, **kwargs):
        claim = GroundedClaim(text="supported survey", evidence_ids=[item.evidence_id for item in evidence])
        return _generation(SurveyDraft(tldr_claims=[claim], method_taxonomy=[], comparisons=[], key_findings=[claim], limitations=[], open_questions=[]))


def _deps(code="pdf_not_found", analyzer=None, papers=None):
    selected = papers or _papers()
    return PipelineDependencies(search=lambda q, l: selected, downloader=FailingDownloader(code), parser=ForbiddenParser(), evidence_packs=Packs(), analyzer=analyzer or Analyzer(), synthesizer=Synthesizer())


def _manifest(run_dir):
    return RunManifest.model_validate_json((run_dir / "run_manifest.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("code", PDF_FALLBACK_CODES)
def test_every_approved_pdf_failure_falls_back_and_degrades(tmp_path, code):
    result = run_pipeline("question", output_base=tmp_path, settings=Settings(dashscope_api_key="offline", retrieval_mode="hybrid"), dependencies=_deps(code))
    manifest = _manifest(result.run_dir)
    documents = json.loads((result.run_dir / "documents.json").read_text(encoding="utf-8"))
    assert result.status == "completed_with_degradation"
    assert manifest.counts.pdf_fallback_documents == 2
    assert {item["fallback_code"] for item in documents} == {code}
    assert {issue.code for issue in manifest.degradations} == {code}
    assert (result.run_dir / "report.md").exists()


def test_explicit_no_pdf_is_not_a_degradation(tmp_path):
    result = run_pipeline("question", output_base=tmp_path, no_pdf=True, settings=Settings(dashscope_api_key="offline", retrieval_mode="hybrid"), dependencies=_deps())
    assert result.status == "completed"


def test_pdf_failure_without_abstract_excludes_paper_when_minimum_still_met(tmp_path):
    papers = _papers(3)
    papers[2] = papers[2].model_copy(update={"abstract": ""})
    result = run_pipeline("question", output_base=tmp_path, settings=Settings(dashscope_api_key="offline", retrieval_mode="hybrid"), dependencies=_deps(papers=papers))
    manifest = _manifest(result.run_dir)
    assert result.status == "completed_with_degradation"
    assert manifest.counts.excluded_papers == 1
    assert manifest.counts.successful_analyses == 2


def test_publishable_citation_sanitization_marks_degradation(tmp_path):
    class SanitizingAnalyzer(Analyzer):
        def analyze(self, *, paper, evidence_pack, **kwargs):
            evidence_id = evidence_pack.evidence[0].evidence_id
            return _generation(PaperAnalysis(
                paper_id=paper.paper_id,
                contributions=[GroundedFinding(text="supported", evidence_ids=[evidence_id])],
                methods=[GroundedFinding(text="audit weak", evidence_ids=[evidence_id, evidence_id, "foreign:ev_999"])],
            ))
    result = run_pipeline("question", output_base=tmp_path, no_pdf=True, settings=Settings(dashscope_api_key="offline", retrieval_mode="hybrid"), dependencies=_deps(analyzer=SanitizingAnalyzer()))
    manifest = _manifest(result.run_dir)
    assert result.status == "completed_with_degradation"
    issues = [issue for issue in manifest.degradations if issue.code == "citation_references_sanitized"]
    assert len(issues) == 2
    assert all("sanitized=" in issue.message for issue in issues)


def test_terminal_generation_error_finalizes_failed_run(tmp_path):
    error = GenerationAuthenticationError(metadata=GenerationFailureMetadata(attempts=1, elapsed_seconds=.1, total_tokens=7))
    with pytest.raises(Exception) as caught:
        run_pipeline("question", output_base=tmp_path, settings=Settings(dashscope_api_key="offline", retrieval_mode="hybrid"), dependencies=_deps(analyzer=Analyzer(error)))
    manifest = _manifest(caught.value.run_dir)
    assert type(caught.value).__name__ == "PipelineRunFailed"
    assert caught.value.code == "generation_authentication_error"
    assert manifest.status == "failed" and manifest.usage.http_attempts == 1 and manifest.usage.total_tokens == 7
    assert json.loads((caught.value.run_dir / "logs.jsonl").read_text().splitlines()[-1])["status"] == "error"
    assert not (caught.value.run_dir / "report.md").exists()


def test_skippable_generation_error_still_requires_two_supported_analyses(tmp_path):
    error = GenerationTimeoutError(metadata=GenerationFailureMetadata(attempts=2, elapsed_seconds=.1))
    with pytest.raises(Exception) as caught:
        run_pipeline("question", output_base=tmp_path, settings=Settings(dashscope_api_key="offline", retrieval_mode="hybrid"), dependencies=_deps(analyzer=Analyzer(error)))
    assert caught.value.code == "insufficient_successful_analyses"


def test_unexpected_exception_is_safely_finalized_and_chained(tmp_path):
    secret = "dont-persist-this-secret"
    deps = _deps()
    deps = PipelineDependencies(search=lambda q, l: (_ for _ in ()).throw(RuntimeError(secret)), downloader=deps.downloader, parser=deps.parser, evidence_packs=deps.evidence_packs, analyzer=deps.analyzer, synthesizer=deps.synthesizer)
    with pytest.raises(Exception) as caught:
        run_pipeline("question", output_base=tmp_path, settings=Settings(dashscope_api_key=secret, retrieval_mode="hybrid"), dependencies=deps)
    assert caught.value.code == "unexpected_pipeline_error"
    assert isinstance(caught.value.__cause__, RuntimeError)
    persisted = (caught.value.run_dir / "run_manifest.json").read_text() + (caught.value.run_dir / "logs.jsonl").read_text()
    assert secret not in persisted
