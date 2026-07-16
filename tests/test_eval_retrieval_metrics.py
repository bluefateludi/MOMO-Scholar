"""Tests for deterministic Top-K retrieval ranking metrics."""

import math
from collections.abc import Callable
from typing import Any

import pytest

from paper_agent.eval import mrr_at_k, ndcg_at_k, precision_at_k, recall_at_k


RankingMetric = Callable[[list[str], dict[str, int], int], float]
METRICS = [recall_at_k, precision_at_k, mrr_at_k, ndcg_at_k]


def test_binary_ranking_metrics_use_only_top_k() -> None:
    ranked = ["c0", "c2", "c1"]
    grades = {"c1": 2, "c2": 1}

    assert recall_at_k(ranked, grades, 2) == 0.5
    assert precision_at_k(ranked, grades, 2) == 0.5
    assert mrr_at_k(ranked, grades, 2) == 0.5


def test_precision_uses_actual_returned_length() -> None:
    assert precision_at_k(["c1"], {"c1": 1}, 5) == 1.0


def test_ndcg_uses_graded_gain_and_log_discount() -> None:
    result = ndcg_at_k(["c2", "c1"], {"c1": 2, "c2": 1}, 2)
    actual = 1.0 + 3.0 / math.log2(3)
    ideal = 3.0 + 1.0 / math.log2(3)

    assert result == pytest.approx(actual / ideal)


@pytest.mark.parametrize("k", [0, -1, True, 1.5, "2"])
@pytest.mark.parametrize("metric", METRICS)
def test_ranking_metrics_require_positive_plain_integer_k(
    metric: RankingMetric,
    k: Any,
) -> None:
    with pytest.raises(ValueError, match="k must be a positive integer"):
        metric([], {}, k)


@pytest.mark.parametrize("metric", METRICS)
@pytest.mark.parametrize(
    ("ranked_ids", "relevance_by_id", "message"),
    [
        (["c1", "c1"], {"c1": 1}, "ranked IDs must be unique"),
        (["c1", 2], {"c1": 1}, "ranked IDs must be strings"),
        (["c1"], {2: 1}, "relevance IDs must be strings"),
        (["c1"], {"c1": True}, "grades must be non-negative integers"),
        (["c1"], {"c1": -1}, "grades must be non-negative integers"),
        (["c1"], {"c1": 1.5}, "grades must be non-negative integers"),
    ],
)
def test_ranking_metrics_reject_invalid_rankings_and_grades(
    metric: RankingMetric,
    ranked_ids: list[Any],
    relevance_by_id: dict[Any, Any],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        metric(ranked_ids, relevance_by_id, 2)


@pytest.mark.parametrize("metric", METRICS)
def test_ranking_metrics_return_zero_for_empty_ranking(
    metric: RankingMetric,
) -> None:
    assert metric([], {"c1": 1}, 3) == 0.0


@pytest.mark.parametrize("metric", METRICS)
def test_ranking_metrics_return_zero_when_no_items_are_relevant(
    metric: RankingMetric,
) -> None:
    assert metric(["c1", "c2"], {"c1": 0, "c2": 0}, 2) == 0.0


@pytest.mark.parametrize("metric", METRICS)
def test_ranking_metrics_return_zero_for_empty_relevance_mapping(
    metric: RankingMetric,
) -> None:
    assert metric(["c1", "c2"], {}, 2) == 0.0


def test_all_ranking_metrics_truncate_results_at_k() -> None:
    ranked = ["c0", "c1"]
    grades = {"c1": 1}

    assert recall_at_k(ranked, grades, 1) == 0.0
    assert precision_at_k(ranked, grades, 1) == 0.0
    assert mrr_at_k(ranked, grades, 1) == 0.0
    assert ndcg_at_k(ranked, grades, 1) == 0.0
