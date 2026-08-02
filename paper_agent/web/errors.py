from __future__ import annotations

from dataclasses import dataclass


_MESSAGES = {
    "run_not_found": "The requested run was not found.",
    "paper_not_found": "The requested paper was not found.",
    "evidence_not_found": "The requested evidence was not found.",
    "artifact_not_found": "The requested artifact was not found.",
    "artifact_not_ready": "The requested artifact is not available yet.",
    "report_unavailable": "This run does not have an available report.",
    "artifact_corrupt": "A persisted run artifact could not be read safely.",
    "validation_error": "The request did not satisfy the API contract.",
    "queue_full": "The run queue is full.",
    "execution_unavailable": "Run execution is unavailable.",
    "run_busy": "The requested run is busy.",
    "origin_not_allowed": "The request origin is not allowed.",
    "internal_error": "The request could not be completed.",
}


@dataclass(slots=True)
class WebError(Exception):
    status_code: int
    code: str
    details: dict[str, object] | None = None

    @property
    def message(self) -> str:
        return _MESSAGES[self.code]
