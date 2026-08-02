from __future__ import annotations

import json
import socket
from pathlib import Path

import httpx
from typer.testing import CliRunner

from paper_agent.eval.citation_baseline.contracts import (
    AtomicAssertion,
    CalibrationRecord,
    CitationOccurrence,
)
from paper_agent.eval.citation_baseline.review import (
    CitedPassage,
    ReviewItem,
    assign_reviews,
    freeze_rubric,
)


runner = CliRunner()
_SHA_A = "a" * 64
_SHA_B = "b" * 64
_SHA_C = "c" * 64


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ) + "\n"


def _write_json(path: Path, value: object) -> None:
    path.write_text(_canonical_json(value), encoding="utf-8", newline="\n")


def _write_jsonl(path: Path, values: tuple[object, ...]) -> None:
    path.write_text(
        "".join(
            _canonical_json(
                value.model_dump(mode="json")
                if hasattr(value, "model_dump")
                else value
            )
            for value in values
        ),
        encoding="utf-8",
        newline="\n",
    )


def _assertion(case_id: str, assertion_id: str) -> AtomicAssertion:
    return AtomicAssertion(
        schema_version="1.0",
        assertion_id=assertion_id,
        case_id=case_id,
        run_id=f"run-{case_id}",
        text=f"Assertion for {case_id}.",
        source_section="summary",
        start_char=0,
        end_char=20,
    )


def _occurrence(assertion: AtomicAssertion) -> CitationOccurrence:
    return CitationOccurrence(
        schema_version="1.0",
        occurrence_id=f"{assertion.assertion_id}:citation:1",
        assertion_id=assertion.assertion_id,
        evidence_id=f"{assertion.run_id}:evidence:1",
        source_section="summary",
        start_char=21,
        end_char=31,
        structurally_valid=True,
    )


def _source(root: Path, *, calibration_complete: bool = True) -> tuple[Path, tuple]:
    source = root / "source"
    source.mkdir(parents=True)
    rubric = freeze_rubric("citation-support-v1", "calibration-v1")
    calibration_assertion = _assertion("case-calibration", "assertion-calibration")
    reported_assertion = _assertion("case-reported", "assertion-reported")
    calibration_occurrence = _occurrence(calibration_assertion)
    reported_occurrence = _occurrence(reported_assertion)
    items = (
        ReviewItem(
            schema_version="1.0",
            case_id=calibration_assertion.case_id,
            run_id=calibration_assertion.run_id,
            blinded_case_id="blind-001",
            assertion_id=calibration_assertion.assertion_id,
            assertion_text=calibration_assertion.text,
            citation_occurrence_ids=(calibration_occurrence.occurrence_id,),
            cited_passages=(
                CitedPassage(
                    evidence_id=calibration_occurrence.evidence_id,
                    text="Calibration evidence.",
                    paper_id="paper-1",
                    locator="p. 1",
                ),
            ),
            output_sha256=_SHA_A,
            evidence_sha256=_SHA_B,
            config_sha256=_SHA_C,
            is_calibration=True,
        ),
        ReviewItem(
            schema_version="1.0",
            case_id=reported_assertion.case_id,
            run_id=reported_assertion.run_id,
            blinded_case_id="blind-002",
            assertion_id=reported_assertion.assertion_id,
            assertion_text=reported_assertion.text,
            citation_occurrence_ids=(reported_occurrence.occurrence_id,),
            cited_passages=(
                CitedPassage(
                    evidence_id=reported_occurrence.evidence_id,
                    text="Reported evidence.",
                    paper_id="paper-2",
                    locator="p. 2",
                ),
            ),
            output_sha256=_SHA_A,
            evidence_sha256=_SHA_B,
            config_sha256=_SHA_C,
            is_calibration=False,
        ),
    )
    assignments = assign_reviews(
        items,
        {
            "assertion-calibration": ("reviewer-alpha", "reviewer-beta"),
            "assertion-reported": ("reviewer-alpha",),
        },
        rubric,
    )
    _write_json(source / "dataset-manifest.json", {
        "data_kind": "synthetic",
        "dataset_fingerprint_sha256": _SHA_A,
    })
    _write_json(source / "corpus-manifest.json", {"corpus_sha256": _SHA_B})
    _write_jsonl(source / "gold-judgments.jsonl", ())
    _write_json(
        source / "resolved-config.json",
        {
            "schema_version": "1.0",
            "cases": [
                {
                    "case_id": "case-reported",
                    "duration_ms": 4.0,
                    "unscorable_assertion_ids": [],
                    "failure_reason_code": None,
                }
            ],
            "generation_model_version": "generation@test",
            "limitations": ["Synthetic test fixture only."],
        },
    )
    _write_json(
        source / "environment.json",
        {
            "git_sha": "d" * 40,
            "git_dirty": False,
            "models": {"generation": "generation@test"},
        },
    )
    _write_jsonl(
        source / "assertions.jsonl",
        (calibration_assertion, reported_assertion),
    )
    _write_jsonl(
        source / "citation-occurrences.jsonl",
        (calibration_occurrence, reported_occurrence),
    )
    _write_jsonl(source / "evidence-matches.jsonl", ())
    _write_json(
        source / "review-rubric.json",
        {
            "schema_version": "1.0",
            "rubric_version": rubric.rubric_version,
            "calibration_set_version": rubric.calibration_set_version,
            "rubric_sha256": rubric.rubric_sha256,
            "definitions": dict(rubric.definitions),
            "reason_codes": dict(rubric.reason_codes),
            "assignments": [
                assignment.model_dump(mode="json") for assignment in assignments
            ],
        },
    )
    calibration = tuple(
        CalibrationRecord(
            schema_version="1.0",
            calibration_id=f"calibration-{assignment.reviewer_pseudonym}",
            calibration_set_version="calibration-v1",
            rubric_version="citation-support-v1",
            assertion_id="assertion-calibration",
            reviewer_pseudonym=assignment.reviewer_pseudonym,
            expected_verdict="supported",
            observed_verdict=(
                "supported" if assignment.reviewer_pseudonym == "reviewer-alpha"
                else "unsupported"
            ),
            adjudicated_verdict=("supported" if calibration_complete else None),
        )
        for assignment in assignments
        if assignment.item.is_calibration
    )
    _write_jsonl(source / "calibration.jsonl", calibration)
    _write_jsonl(source / "adjudications.jsonl", ())
    _write_jsonl(source / "failures.jsonl", ())
    _write_jsonl(source / "logs.jsonl", ())
    _write_jsonl(source / "traces.jsonl", ())
    return source, assignments


def _review_response(assignment: object) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "assignment_id": assignment.assignment_id,
        "assignment_sha256": assignment.assignment_sha256,
        "reviewer_pseudonym": assignment.reviewer_pseudonym,
        "rubric_version": assignment.rubric_version,
        "calibration_set_version": assignment.calibration_set_version,
        "output_sha256": assignment.item.output_sha256,
        "evidence_sha256": assignment.item.evidence_sha256,
        "config_sha256": assignment.item.config_sha256,
        "semantic_verdict": "supported",
        "reason_code": "human_entailment",
        "support_match_ids": [],
        "notes": None,
        "reviewed_at": "2026-07-26T09:00:00Z",
    }


def _forbid_network(monkeypatch) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("offline command attempted network access")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(httpx.Client, "request", forbidden)


def test_prepare_export_import_are_offline_and_registered(tmp_path, monkeypatch) -> None:
    from paper_agent.cli import app as root_app

    _forbid_network(monkeypatch)
    source, assignments = _source(tmp_path)
    prepared = tmp_path / "prepared"
    result = runner.invoke(
        root_app,
        ["citation-baseline", "prepare", "--source", str(source), "--output", str(prepared)],
    )
    assert result.exit_code == 0, result.output

    export = tmp_path / "review.jsonl"
    result = runner.invoke(
        root_app,
        ["citation-baseline", "export-review", "--prepared", str(prepared), "--output", str(export)],
    )
    assert result.exit_code == 0, result.output
    assert all(
        "case_id" not in json.loads(line)
        for line in export.read_text(encoding="utf-8").splitlines()
    )

    responses = tmp_path / "responses.jsonl"
    _write_jsonl(responses, tuple(_review_response(item) for item in assignments))
    judgments = tmp_path / "judgments.jsonl"
    result = runner.invoke(
        root_app,
        [
            "citation-baseline",
            "import-review",
            "--prepared",
            str(prepared),
            "--review",
            str(responses),
            "--output",
            str(judgments),
        ],
    )
    assert result.exit_code == 0, result.output
    assert len(judgments.read_text(encoding="utf-8").splitlines()) == 3


def test_import_rejects_hash_or_rubric_mismatch_with_review_exit_code(
    tmp_path,
) -> None:
    from paper_agent.eval.citation_baseline.cli import app

    source, assignments = _source(tmp_path)
    prepared = tmp_path / "prepared"
    assert runner.invoke(
        app, ["prepare", "--source", str(source), "--output", str(prepared)]
    ).exit_code == 0
    response = _review_response(assignments[0])
    response["rubric_version"] = "changed-rubric"
    review = tmp_path / "bad-review.jsonl"
    _write_jsonl(review, (response,))

    result = runner.invoke(
        app,
        ["import-review", "--prepared", str(prepared), "--review", str(review), "--output", str(tmp_path / "out.jsonl")],
    )

    assert result.exit_code == 1
    assert "rubric" in result.output.lower()
    assert "changed-rubric" not in result.output


def test_prepare_uses_input_exit_code_and_redacts_invalid_content(tmp_path) -> None:
    from paper_agent.eval.citation_baseline.cli import app

    source, _ = _source(tmp_path)
    secret = "sk-do-not-print-this-input"
    (source / "logs.jsonl").write_text(
        _canonical_json({"message": secret}),
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        ["prepare", "--source", str(source), "--output", str(tmp_path / "prepared")],
    )

    assert result.exit_code == 2
    assert secret not in result.output


def test_score_blocks_incomplete_calibration_and_missing_judgments(tmp_path) -> None:
    from paper_agent.eval.citation_baseline.cli import app

    source, assignments = _source(tmp_path, calibration_complete=False)
    prepared = tmp_path / "prepared"
    assert runner.invoke(
        app, ["prepare", "--source", str(source), "--output", str(prepared)]
    ).exit_code == 0
    incomplete = runner.invoke(
        app,
        ["score", "--prepared", str(prepared), "--judgments", str(prepared / "judgments.jsonl"), "--output", str(tmp_path / "package")],
    )
    assert incomplete.exit_code == 1
    assert "calibration" in incomplete.output.lower()

    complete_source, complete_assignments = _source(tmp_path / "complete")
    complete_prepared = tmp_path / "complete-prepared"
    assert runner.invoke(
        app, ["prepare", "--source", str(complete_source), "--output", str(complete_prepared)]
    ).exit_code == 0
    one_response = tmp_path / "one-response.jsonl"
    _write_jsonl(one_response, (_review_response(complete_assignments[-1]),))
    one_judgment = tmp_path / "one-judgment.jsonl"
    assert runner.invoke(
        app,
        ["import-review", "--prepared", str(complete_prepared), "--review", str(one_response), "--output", str(one_judgment)],
    ).exit_code == 0
    missing = runner.invoke(
        app,
        ["score", "--prepared", str(complete_prepared), "--judgments", str(one_judgment), "--output", str(tmp_path / "missing-package")],
    )
    assert missing.exit_code == 1
    assert "judgment" in missing.output.lower()


def test_score_recompute_and_verify_use_only_sealed_authorities(
    tmp_path,
    monkeypatch,
) -> None:
    from paper_agent.eval.citation_baseline.cli import app

    _forbid_network(monkeypatch)
    source, assignments = _source(tmp_path)
    prepared = tmp_path / "prepared"
    assert runner.invoke(
        app, ["prepare", "--source", str(source), "--output", str(prepared)]
    ).exit_code == 0
    review = tmp_path / "responses.jsonl"
    _write_jsonl(review, tuple(_review_response(item) for item in assignments))
    judgments = tmp_path / "judgments.jsonl"
    assert runner.invoke(
        app,
        ["import-review", "--prepared", str(prepared), "--review", str(review), "--output", str(judgments)],
    ).exit_code == 0

    package = tmp_path / "package"
    scored = runner.invoke(
        app,
        ["score", "--prepared", str(prepared), "--judgments", str(judgments), "--output", str(package)],
    )
    assert scored.exit_code == 0, scored.output
    assert (package / "artifact-manifest.json").is_file()

    verification = tmp_path / "verification"
    recomputed = runner.invoke(
        app,
        ["recompute", "--package", str(package), "--output", str(verification)],
    )
    assert recomputed.exit_code == 0, recomputed.output
    for name in (
        "case-metrics.jsonl",
        "aggregate.json",
        "confidence-intervals.json",
        "report.md",
        "resume-evidence.md",
    ):
        assert (verification / name).read_bytes() == (package / name).read_bytes()
    assert runner.invoke(app, ["verify", str(package)]).exit_code == 0

    (prepared / "assertions.jsonl").write_text("unsealed side channel\n", encoding="utf-8")
    second = tmp_path / "verification-two"
    assert runner.invoke(
        app,
        ["recompute", "--package", str(package), "--output", str(second)],
    ).exit_code == 0
    assert (second / "aggregate.json").read_bytes() == (package / "aggregate.json").read_bytes()


def test_corrupt_package_uses_integrity_exit_and_redacts_content(tmp_path) -> None:
    from paper_agent.eval.citation_baseline.cli import app

    source, assignments = _source(tmp_path)
    prepared = tmp_path / "prepared"
    assert runner.invoke(
        app, ["prepare", "--source", str(source), "--output", str(prepared)]
    ).exit_code == 0
    review = tmp_path / "responses.jsonl"
    _write_jsonl(review, tuple(_review_response(item) for item in assignments))
    judgments = tmp_path / "judgments.jsonl"
    assert runner.invoke(
        app,
        ["import-review", "--prepared", str(prepared), "--review", str(review), "--output", str(judgments)],
    ).exit_code == 0
    package = tmp_path / "package"
    assert runner.invoke(
        app,
        ["score", "--prepared", str(prepared), "--judgments", str(judgments), "--output", str(package)],
    ).exit_code == 0
    secret = "sk-do-not-print-this-value"
    with (package / "logs.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(secret)

    result = runner.invoke(app, ["verify", str(package)])

    assert result.exit_code == 3
    assert "corrupt" in result.output.lower() or "integrity" in result.output.lower()
    assert secret not in result.output
