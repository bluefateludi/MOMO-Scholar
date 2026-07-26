import json

import pytest

from paper_agent.eval.evidence_package import (
    EvidencePackageBuilder,
    EvidencePackageError,
    verify_evidence_package,
)


REQUIRED = {
    "dataset-manifest.json": {"dataset_id": "momo-eval-v1"},
    "corpus-manifest.json": {"corpus_sha256": "a" * 64},
    "gold-judgments.jsonl": '{"case_id":"case-1"}\n',
    "resolved-config.json": {"primary_k": 8},
    "environment.json": {
        "git_sha": "b" * 40,
        "git_dirty": False,
        "models": {"embedding": "text-embedding-v4@2026-07-01"},
    },
    "raw-rankings.jsonl": '{"case_id":"case-1"}\n',
    "case-metrics.jsonl": '{"case_id":"case-1"}\n',
    "aggregate.json": {"case_count": 1},
    "confidence-intervals.json": {"confidence_level": 0.95},
    "failures.jsonl": "",
    "logs.jsonl": "",
    "traces.jsonl": "",
    "report.md": "# Report\n",
    "resume-evidence.md": "# Resume Evidence\n",
}


def _complete(builder: EvidencePackageBuilder) -> None:
    for path, content in REQUIRED.items():
        if isinstance(content, dict):
            builder.write_json(path, content)
        else:
            builder.write_text(path, content)


def test_seal_records_hash_and_length_for_every_required_artifact(tmp_path) -> None:
    builder = EvidencePackageBuilder(tmp_path / "experiment")
    _complete(builder)

    manifest = builder.seal(package_kind="retrieval_benchmark")

    assert manifest["sealed"] is True
    assert manifest["package_kind"] == "retrieval_benchmark"
    assert {item["path"] for item in manifest["artifacts"]} == set(REQUIRED)
    assert all(len(item["sha256"]) == 64 for item in manifest["artifacts"])
    assert all(item["byte_length"] >= 0 for item in manifest["artifacts"])
    assert verify_evidence_package(builder.root)["sealed"] is True


def test_seal_rejects_missing_artifact_dirty_git_and_missing_model_version(tmp_path) -> None:
    missing = EvidencePackageBuilder(tmp_path / "missing")
    with pytest.raises(EvidencePackageError, match="missing required artifacts"):
        missing.seal(package_kind="retrieval_benchmark")

    dirty = EvidencePackageBuilder(tmp_path / "dirty")
    _complete(dirty)
    dirty.write_json(
        "environment.json",
        {"git_sha": "b" * 40, "git_dirty": True, "models": {"embedding": "v1"}},
    )
    with pytest.raises(EvidencePackageError, match="clean Git worktree"):
        dirty.seal(package_kind="retrieval_benchmark")

    no_model = EvidencePackageBuilder(tmp_path / "no-model")
    _complete(no_model)
    no_model.write_json(
        "environment.json",
        {"git_sha": "b" * 40, "git_dirty": False, "models": {}},
    )
    with pytest.raises(EvidencePackageError, match="model version"):
        no_model.seal(package_kind="retrieval_benchmark")


@pytest.mark.parametrize("path", ["../outside.json", "/absolute.json", "nested/file.json"])
def test_builder_rejects_noncanonical_artifact_paths(tmp_path, path: str) -> None:
    builder = EvidencePackageBuilder(tmp_path / "experiment")

    with pytest.raises(EvidencePackageError, match="artifact path"):
        builder.write_json(path, {})


def test_sealed_builder_refuses_mutation_and_verifier_detects_external_append(tmp_path) -> None:
    builder = EvidencePackageBuilder(tmp_path / "experiment")
    _complete(builder)
    builder.seal(package_kind="retrieval_benchmark")

    with pytest.raises(EvidencePackageError, match="sealed"):
        builder.write_text("logs.jsonl", "late\n")

    with (builder.root / "logs.jsonl").open("a", encoding="utf-8") as handle:
        handle.write("external mutation\n")
    with pytest.raises(EvidencePackageError, match="(length|hash) mismatch"):
        verify_evidence_package(builder.root)


def test_verifier_rejects_manifest_path_tampering(tmp_path) -> None:
    builder = EvidencePackageBuilder(tmp_path / "experiment")
    _complete(builder)
    builder.seal(package_kind="retrieval_benchmark")
    manifest_path = builder.root / "artifact-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifacts"][0]["path"] = "../outside.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(EvidencePackageError, match="artifact path"):
        verify_evidence_package(builder.root)
