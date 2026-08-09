from __future__ import annotations

import json
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = REPOSITORY_ROOT / "tests" / "fixtures" / "techscout"
EXPECTED_FIXTURES = {
    "bounded-failure-recovery.json",
    "happy-path.json",
    "no-safe-winner-research-only.json",
}
EXPECTED_SCENARIOS = {
    "happy_path",
    "no_safe_winner_research_only",
    "bounded_failure_recovery",
}


def _load_fixtures() -> list[dict[str, object]]:
    paths = sorted(path for path in FIXTURE_ROOT.iterdir() if path.is_file())
    assert {path.name for path in paths} == EXPECTED_FIXTURES
    return [json.loads(path.read_text(encoding="utf-8")) for path in paths]


def test_exactly_three_frozen_vertical_tasks_cover_the_required_scenarios() -> None:
    fixtures = _load_fixtures()

    assert len(fixtures) == 3
    assert {fixture["scenario"] for fixture in fixtures} == EXPECTED_SCENARIOS
    assert len({fixture["task_id"] for fixture in fixtures}) == 3
    assert all(fixture["schema_version"] == "techscout-smoke-task-v1" for fixture in fixtures)
    assert all(fixture["fixture_kind"] == "synthetic_frozen_acceptance" for fixture in fixtures)
    assert all(fixture["network_policy"] == "offline" for fixture in fixtures)
    assert all(2 <= len(fixture["request"]["candidates"]) <= 3 for fixture in fixtures)
    assert all(fixture["observed_metrics"] == {} for fixture in fixtures)


def test_support_scope_and_research_only_boundary_are_frozen() -> None:
    fixtures = _load_fixtures()
    candidates = {
        candidate["candidate_id"]: candidate
        for fixture in fixtures
        for candidate in fixture["request"]["candidates"]
    }

    assert {
        candidate["component_family"] for candidate in candidates.values()
    } == {"python_vector_store_for_local_rag"}
    assert candidates["chroma"]["support_level"] == "v1_supported"
    assert candidates["qdrant-local"]["support_level"] == "v1_supported"
    assert candidates["chroma"]["poc_policy"] == "allowlisted_recipe"
    assert candidates["qdrant-local"]["poc_policy"] == "allowlisted_recipe"
    assert candidates["pgvector"]["support_level"] == "research_only"
    assert candidates["pgvector"]["poc_policy"] == "requires_postgresql_fixture"
    assert candidates["pgvector"]["postgresql_fixture_available"] is False


def test_expected_outcomes_are_honest_and_recovery_is_local_and_bounded() -> None:
    fixtures = {fixture["scenario"]: fixture for fixture in _load_fixtures()}

    happy = fixtures["happy_path"]["expected"]
    assert happy["terminal_status"] == "completed"
    assert happy["decision"] == "recommended"

    no_winner = fixtures["no_safe_winner_research_only"]["expected"]
    assert no_winner["terminal_status"] == "completed_with_limitations"
    assert no_winner["decision"] == "no_safe_winner"
    assert no_winner["poc_executions"] == []

    recovery = fixtures["bounded_failure_recovery"]["expected"]
    assert recovery["terminal_status"] == "completed"
    assert recovery["recovery"]["maximum_attempts"] == 1
    assert recovery["recovery"]["replayed_stages"] == ["poc"]
    assert recovery["recovery"]["preserve_first_failure"] is True


def test_numbers_are_planning_targets_not_measured_or_resume_claims() -> None:
    for fixture in _load_fixtures():
        targets = fixture["planning_targets"]
        assert targets["classification"] == "planning_target"
        assert targets["measured_result"] is None
        assert targets["resume_claim"] is False
        assert targets["fast_terminal_seconds"] == 120
        assert fixture["observed_metrics"] == {}
