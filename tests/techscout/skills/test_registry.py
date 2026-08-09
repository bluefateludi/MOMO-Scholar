import pytest
from pydantic import ValidationError

from paper_agent.techscout.runtime_skills import fixed_skill_registry
from paper_agent.techscout.state import ResearchStage


def test_fixed_registry_has_exactly_four_versioned_skills() -> None:
    registry = fixed_skill_registry()

    assert {skill.name for skill in registry.all()} == {
        "official-doc-research",
        "github-project-analysis",
        "python-package-smoke-test",
        "failure-diagnosis",
    }
    assert all(skill.version == "1" for skill in registry.all())
    assert all(skill.step_budget > 0 and skill.token_budget > 0 for skill in registry.all())
    validated = registry.validate_input(
        "skill:official-doc-research@1",
        {
            "candidate_id": "candidate:qdrant",
            "query": "Qdrant filtering",
            "constraints": ("metadata filtering",),
        },
    )
    assert validated.candidate_id == "candidate:qdrant"
    with pytest.raises(ValidationError):
        registry.validate_input(
            "skill:official-doc-research@1",
            {"candidate_id": "candidate:qdrant", "query": "missing constraints"},
        )


def test_router_rejects_capability_at_wrong_stage() -> None:
    registry = fixed_skill_registry()

    selection = registry.route(
        "official-doc-research",
        ResearchStage.RESEARCH_CANDIDATES,
        selection_id="selection:test:research",
        reason="official evidence required",
    )

    assert selection.skill_id == "skill:official-doc-research@1"
    with pytest.raises(ValueError, match="not valid for stage"):
        registry.route(
            "official-doc-research",
            ResearchStage.EXECUTE_POC,
            selection_id="selection:test:wrong",
            reason="wrong stage",
        )
