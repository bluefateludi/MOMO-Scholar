import json

import pytest

from paper_agent.generation import (
    GenerationFailureMetadata,
    GenerationRequestError,
    StructuredGeneration,
)
from paper_agent.schemas import Evidence
from paper_agent.synthesis.models import (
    CheckedFinding,
    CheckedPaperAnalysis,
    GroundedClaim,
    SurveyDraft,
)
from paper_agent.synthesis.survey import SurveySynthesizer
from tests.generation.fakes import FakeGenerationProvider


def _evidence(evidence_id: str, paper_id: str) -> Evidence:
    return Evidence(
        evidence_id=evidence_id,
        paper_id=paper_id,
        chunk_id=f"{paper_id}:chunk:001",
        section="Methods",
        page=2,
        claim_type="method",
        quote=f"Evidence for {paper_id}",
        relevance_score=0.9,
    )


def _finding(
    evidence_id: str, *, status: str = "supported", text: str = "finding"
) -> CheckedFinding:
    return CheckedFinding(
        text=text,
        evidence_ids=[evidence_id],
        support_status=status,
    )


def _draft(evidence_id: str = "run:paper:p1:ev_001") -> SurveyDraft:
    claim = GroundedClaim(text="grounded claim", evidence_ids=[evidence_id])
    return SurveyDraft(
        tldr_claims=[claim],
        method_taxonomy=[claim],
        comparisons=[claim],
        key_findings=[claim],
        limitations=[claim],
        open_questions=[claim],
    )


def _generation(draft: SurveyDraft | None = None) -> StructuredGeneration[SurveyDraft]:
    return StructuredGeneration(
        result=draft or _draft(),
        model="fake-model",
        prompt_tokens=11,
        completion_tokens=7,
        total_tokens=18,
        attempts=2,
        elapsed_seconds=0.25,
    )


def test_synthesize_sends_only_supported_findings_and_resolvable_evidence() -> None:
    expected = _generation()
    provider = FakeGenerationProvider([expected])
    supported_id = "run:paper:p1:ev_001"
    weak_id = "run:paper:p1:ev_002"
    analyses = [
        CheckedPaperAnalysis(
            paper_id="p1",
            contributions=[_finding(supported_id, text="supported contribution")],
            methods=[_finding(weak_id, status="weakly_supported", text="weak method")],
        ),
        CheckedPaperAnalysis(
            paper_id="p2",
            limitations=[
                _finding(weak_id, status="weakly_supported", text="weak-only analysis")
            ],
        ),
    ]

    actual = SurveySynthesizer(provider).synthesize(
        question="How do the methods compare?",
        analyses=analyses,
        evidence=[_evidence(supported_id, "p1"), _evidence(weak_id, "p1")],
        timeout=12.5,
    )

    assert actual is expected
    assert len(provider.calls) == 1
    call = provider.calls[0]
    assert call.operation == "survey_synthesis"
    assert call.response_schema is SurveyDraft
    assert call.timeout == 12.5
    assert [message.role for message in call.messages] == ["system", "user"]
    assert "outside claims" in call.messages[0].content.lower()
    payload = json.loads(call.messages[1].content)
    assert payload["question"] == "How do the methods compare?"
    assert payload["analyses"] == [
        {
            "paper_id": "p1",
            "contributions": [
                {"text": "supported contribution", "evidence_ids": [supported_id]}
            ],
            "methods": [],
            "experiments": [],
            "results": [],
            "limitations": [],
        }
    ]
    assert payload["evidence"] == [_evidence(supported_id, "p1").model_dump()]
    assert "weak method" not in call.messages[1].content
    assert "weak-only analysis" not in call.messages[1].content
    assert weak_id not in call.messages[1].content


def test_synthesize_allows_one_paper() -> None:
    provider = FakeGenerationProvider([_generation()])
    evidence_id = "run:paper:p1:ev_001"

    SurveySynthesizer(provider).synthesize(
        question="What works?",
        analyses=[
            CheckedPaperAnalysis(
                paper_id="p1", results=[_finding(evidence_id)]
            )
        ],
        evidence=[_evidence(evidence_id, "p1")],
        timeout=3.0,
    )

    assert len(provider.calls) == 1


@pytest.mark.parametrize(
    "analyses,evidence,match",
    [
        ([], [], "successful analysis"),
        ([CheckedPaperAnalysis(paper_id="p1")], [], "supported finding"),
        (
            [
                CheckedPaperAnalysis(
                    paper_id="p1",
                    contributions=[_finding("run:paper:p2:ev_001")],
                )
            ],
            [_evidence("run:paper:p2:ev_001", "p2")],
            "foreign evidence",
        ),
    ],
)
def test_synthesize_rejects_invalid_inputs_before_provider(
    analyses: list[CheckedPaperAnalysis], evidence: list[Evidence], match: str
) -> None:
    provider = FakeGenerationProvider([])

    with pytest.raises(ValueError, match=match):
        SurveySynthesizer(provider).synthesize(
            question="question",
            analyses=analyses,
            evidence=evidence,
            timeout=2.0,
        )

    assert provider.calls == []


def test_synthesize_propagates_provider_errors() -> None:
    error = GenerationRequestError(
        metadata=GenerationFailureMetadata(attempts=1, elapsed_seconds=0.1)
    )
    provider = FakeGenerationProvider([error])
    evidence_id = "run:paper:p1:ev_001"

    with pytest.raises(GenerationRequestError) as caught:
        SurveySynthesizer(provider).synthesize(
            question="question",
            analyses=[
                CheckedPaperAnalysis(
                    paper_id="p1", results=[_finding(evidence_id)]
                )
            ],
            evidence=[_evidence(evidence_id, "p1")],
            timeout=2.0,
        )

    assert caught.value is error


def test_synthesize_preserves_invalid_generated_ids_for_checker() -> None:
    draft = _draft("unknown:ev_999")
    provider = FakeGenerationProvider([_generation(draft)])
    evidence_id = "run:paper:p1:ev_001"

    result = SurveySynthesizer(provider).synthesize(
        question="question",
        analyses=[
            CheckedPaperAnalysis(paper_id="p1", results=[_finding(evidence_id)])
        ],
        evidence=[_evidence(evidence_id, "p1")],
        timeout=2.0,
    )

    assert result.result is draft
    assert result.result.tldr_claims[0].evidence_ids == ["unknown:ev_999"]
