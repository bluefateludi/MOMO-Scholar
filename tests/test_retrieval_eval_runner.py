import json
from pathlib import Path

import pytest

from paper_agent.eval.retrieval_runner import evaluate_retrieval_fixture


FIXTURE_PATH = Path("tests/fixtures/retrieval_eval_cases.json")
METRIC_NAMES = {"recall_at_k", "precision_at_k", "mrr_at_k", "ndcg_at_k"}


def _write_fixture(tmp_path: Path, cases: object) -> Path:
    path = tmp_path / "retrieval.json"
    path.write_text(json.dumps(cases), encoding="utf-8")
    return path


def _base_case() -> dict[str, object]:
    return {
        "case_id": "base",
        "query": "alpha",
        "chunks": [
            {
                "chunk_id": "c1",
                "paper_id": "p1",
                "section": None,
                "page": 1,
                "text": "alpha text",
                "token_count": 2,
            }
        ],
        "relevance_by_chunk_id": {"c1": 1},
        "vector_ranked_chunk_ids": ["c1"],
    }


def test_runner_defaults_to_eight_without_loading_environment(monkeypatch) -> None:
    monkeypatch.setenv("RETRIEVAL_TOP_K", "99")
    result = evaluate_retrieval_fixture(FIXTURE_PATH)
    assert result["k"] == 8


def test_runner_freezes_case_and_mode_output_shape() -> None:
    result = evaluate_retrieval_fixture(FIXTURE_PATH, k=2)
    assert set(result) == {"k", "cases", "summary"}
    assert set(result["cases"][0]) == {"case_id", "modes"}
    assert set(result["cases"][0]["modes"]) == {"lexical", "vector", "hybrid"}
    for mode in result["cases"][0]["modes"].values():
        assert set(mode) == {"ranked_chunk_ids", "metrics"}
        assert set(mode["metrics"]) == METRIC_NAMES


def test_complementary_case_keeps_each_unique_hit_once() -> None:
    result = evaluate_retrieval_fixture(FIXTURE_PATH, k=2)
    case = next(
        item for item in result["cases"] if item["case_id"] == "complementary-results"
    )
    assert case["modes"]["lexical"]["ranked_chunk_ids"] == ["c-lex"]
    assert case["modes"]["vector"]["ranked_chunk_ids"] == ["c-vec"]
    assert set(case["modes"]["hybrid"]["ranked_chunk_ids"]) == {"c-lex", "c-vec"}
    assert len(case["modes"]["hybrid"]["ranked_chunk_ids"]) == 2


def test_duplicate_case_fuses_shared_hit_once() -> None:
    result = evaluate_retrieval_fixture(FIXTURE_PATH, k=2)
    case = next(item for item in result["cases"] if item["case_id"] == "duplicate-hit")
    assert case["modes"]["hybrid"]["ranked_chunk_ids"] == ["c-shared"]


def test_summary_is_macro_average() -> None:
    result = evaluate_retrieval_fixture(FIXTURE_PATH, k=2)
    for mode in ("lexical", "vector", "hybrid"):
        for metric in METRIC_NAMES:
            expected = sum(
                case["modes"][mode]["metrics"][metric] for case in result["cases"]
            ) / len(result["cases"])
            assert result["summary"][mode][metric] == pytest.approx(expected)


def test_empty_fixture_returns_zero_summaries(tmp_path) -> None:
    result = evaluate_retrieval_fixture(_write_fixture(tmp_path, []), k=2)
    assert result == {
        "k": 2,
        "cases": [],
        "summary": {
            mode: {metric: 0.0 for metric in METRIC_NAMES}
            for mode in ("lexical", "vector", "hybrid")
        },
    }


@pytest.mark.parametrize("k", [0, -1, True, 1.5, "2"])
def test_runner_requires_positive_plain_integer_k(tmp_path, k) -> None:
    with pytest.raises(ValueError, match="k must be a positive integer"):
        evaluate_retrieval_fixture(_write_fixture(tmp_path, []), k=k)


@pytest.mark.parametrize(
    "field",
    ["case_id", "query", "chunks", "relevance_by_chunk_id", "vector_ranked_chunk_ids"],
)
def test_runner_requires_every_case_field(tmp_path, field) -> None:
    case = _base_case()
    del case[field]
    with pytest.raises(ValueError, match=field):
        evaluate_retrieval_fixture(_write_fixture(tmp_path, [case]))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("case_id", " "),
        ("query", " "),
        ("chunks", "not-a-list"),
        ("relevance_by_chunk_id", []),
        ("vector_ranked_chunk_ids", {}),
        ("vector_ranked_chunk_ids", ["unknown"]),
        ("vector_ranked_chunk_ids", ["c1", "c1"]),
        ("relevance_by_chunk_id", {"unknown": 1}),
        ("relevance_by_chunk_id", {"c1": True}),
        ("relevance_by_chunk_id", {"c1": -1}),
        ("relevance_by_chunk_id", {"c1": 1.5}),
    ],
)
def test_runner_rejects_malformed_case_fields(tmp_path, field, value) -> None:
    case = _base_case()
    case[field] = value
    with pytest.raises(ValueError, match=field):
        evaluate_retrieval_fixture(_write_fixture(tmp_path, [case]))


def test_runner_requires_list_top_level(tmp_path) -> None:
    with pytest.raises(ValueError, match="top level"):
        evaluate_retrieval_fixture(_write_fixture(tmp_path, {}))


def test_runner_rejects_duplicate_case_ids(tmp_path) -> None:
    with pytest.raises(ValueError, match="duplicate case_id.*base"):
        evaluate_retrieval_fixture(_write_fixture(tmp_path, [_base_case(), _base_case()]))


def test_runner_rejects_duplicate_chunk_ids(tmp_path) -> None:
    case = _base_case()
    case["chunks"].append(dict(case["chunks"][0]))
    with pytest.raises(ValueError, match="base.*chunks.*duplicate.*c1"):
        evaluate_retrieval_fixture(_write_fixture(tmp_path, [case]))


def test_runner_wraps_malformed_chunk_validation(tmp_path) -> None:
    case = _base_case()
    case["chunks"][0]["token_count"] = "two"
    with pytest.raises(ValueError, match=r"base.*chunks\[0\].*token_count"):
        evaluate_retrieval_fixture(_write_fixture(tmp_path, [case]))
