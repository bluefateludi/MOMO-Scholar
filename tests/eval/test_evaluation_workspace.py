from __future__ import annotations

import json
import subprocess
from pathlib import Path

from paper_agent.eval.contracts import CorpusPaper, EvalCase
from paper_agent.eval.retrieval_benchmark.contracts import (
    RetrievalBenchmarkConfig,
)
from paper_agent.schemas import Chunk


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
EVALUATIONS_ROOT = REPOSITORY_ROOT / "evaluations"
TEMPLATES_ROOT = EVALUATIONS_ROOT / "templates"
TRACKED_EVALUATION_FILES = {
    "evaluations/DATASETS.md",
    "evaluations/README.md",
    "evaluations/templates/corpus-manifest.template.json",
    "evaluations/templates/gold-judgments.template.json",
    "evaluations/templates/license-provenance-registry.template.json",
    "evaluations/templates/resolved-config.template.json",
}


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ("git", *args),
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def _load_template(name: str) -> dict[str, object]:
    return json.loads(
        (TEMPLATES_ROOT / name).read_text(encoding="utf-8")
    )


def _contract_path(contract: type[object]) -> str:
    return f"{contract.__module__}.{contract.__name__}"


def test_evaluations_default_deny_has_an_exact_trackable_allowlist() -> None:
    ignored_paths = (
        "evaluations/datasets/momo-eval-v1/development.jsonl",
        "evaluations/experiments/smoke/raw-rankings.jsonl",
        "evaluations/downloads/scifact/corpus.jsonl",
        "evaluations/cache/vector-index.bin",
        "evaluations/.env",
        "evaluations/credentials/provider.json",
        "evaluations/templates/unreviewed-case.json",
    )
    ignored = _git("check-ignore", *ignored_paths)

    assert ignored.returncode == 0, ignored.stderr
    assert set(ignored.stdout.splitlines()) == set(ignored_paths)

    allowed = _git("check-ignore", *sorted(TRACKED_EVALUATION_FILES))
    assert allowed.returncode == 1, allowed.stdout

    trackable = _git(
        "ls-files",
        "--cached",
        "--others",
        "--exclude-standard",
        "--",
        "evaluations",
    )
    assert trackable.returncode == 0, trackable.stderr
    assert set(trackable.stdout.splitlines()) == TRACKED_EVALUATION_FILES


def test_license_registry_template_is_empty_and_complete() -> None:
    template = _load_template("license-provenance-registry.template.json")

    assert template["contains_real_data"] is False
    assert template["entries"] == []
    assert template["required_entry_fields"] == [
        "source",
        "asset",
        "version",
        "url",
        "license",
        "redistribution_decision",
        "sha256",
        "reviewer",
        "review_date",
    ]


def test_data_templates_are_empty_and_reference_existing_contracts() -> None:
    corpus = _load_template("corpus-manifest.template.json")
    gold = _load_template("gold-judgments.template.json")
    config = _load_template("resolved-config.template.json")

    assert corpus["contains_real_data"] is False
    assert corpus["document_contract"] == _contract_path(CorpusPaper)
    assert corpus["chunk_contract"] == _contract_path(Chunk)
    assert corpus["documents"] == []
    assert corpus["chunks"] == []
    assert corpus["corpus_sha256"] is None

    assert gold["contains_real_data"] is False
    assert gold["case_contract"] == _contract_path(EvalCase)
    assert gold["judgment_source"] == "EvalCase.reference"
    assert gold["judgments"] == []

    assert config["contains_real_data"] is False
    assert config["config_contract"] == _contract_path(
        RetrievalBenchmarkConfig
    )
    assert config["resolved_config"] is None
    assert config["case_limit"] == 2
    assert config["timeout_seconds"] is None
    assert config["budget"]["currency"] is None
    assert config["budget"]["maximum_amount"] is None
    assert config["provider_costs_acknowledged"] is False


def test_allowlisted_evaluation_files_do_not_contain_secret_material() -> None:
    forbidden_fragments = (
        "sk-",
        "bearer ",
        "api_key=",
        "api-key=",
        "access_token=",
        "secret_key=",
        "password=",
    )

    for relative_path in TRACKED_EVALUATION_FILES:
        content = (REPOSITORY_ROOT / relative_path).read_text(
            encoding="utf-8"
        ).lower()
        assert not any(fragment in content for fragment in forbidden_fragments)


def test_dataset_registry_documents_real_data_review_gates() -> None:
    content = (EVALUATIONS_ROOT / "DATASETS.md").read_text(encoding="utf-8")

    assert "CC-BY-4.0" in content
    assert "ODC-By-1.0" in content
    assert "QASPER" in content
    assert "review required" in content.lower()
    assert "synthetic" in content.lower()
    assert "not baseline" in content.lower()
