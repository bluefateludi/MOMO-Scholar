"""Deterministic offline evaluation."""

from paper_agent.eval.dataset import (
    DatasetValidationError,
    audit_evaluation_dataset,
    load_evaluation_dataset,
)
from paper_agent.eval.metrics import mrr_at_k, ndcg_at_k, precision_at_k, recall_at_k
from paper_agent.eval.retrieval_runner import evaluate_retrieval_fixture

__all__ = [
    "DatasetValidationError",
    "audit_evaluation_dataset",
    "evaluate_retrieval_fixture",
    "load_evaluation_dataset",
    "mrr_at_k",
    "ndcg_at_k",
    "precision_at_k",
    "recall_at_k",
]
