from __future__ import annotations

import logging
from pathlib import Path

from paper_agent.web.api_models import CreateRunRequest
from paper_agent.web.artifacts import ARTIFACT_NAMES, ArtifactReader
from paper_agent.web.registry import RunRegistry


DEMO_API_ID = "00000000-0000-4000-8000-000000000001"
DEMO_ARTIFACT_RUN_ID = "synthetic-demo-v1"
DEMO_ROOT = Path(__file__).with_name("demo_data")
DEMO_REQUEST = CreateRunRequest.model_validate(
    {
        "question": "How can hybrid retrieval support resilient scientific literature review?",
        "paper_limit": 2,
        "content_mode": "pdf_preferred",
        "retrieval": {
            "mode": "auto",
            "candidate_k": 30,
            "top_k": 8,
            "rrf_k": 60,
            "analysis_evidence_per_paper": 6,
        },
    }
)


def seed_bundled_demo(registry: RunRegistry, artifacts: ArtifactReader) -> bool:
    """Validate the immutable bundle through production readers, then seed its row."""
    try:
        manifest = artifacts.manifest("bundled_demo", DEMO_ARTIFACT_RUN_ID)
        if manifest.status not in {"completed", "completed_with_degradation"}:
            raise ValueError("bundled demo manifest is not successful")
        if (
            manifest.question != DEMO_REQUEST.question
            or manifest.requested_limit != DEMO_REQUEST.paper_limit
            or manifest.no_pdf is not False
        ):
            raise ValueError("bundled demo request does not match its manifest")
        for name in ARTIFACT_NAMES:
            artifacts.validate_download(
                "bundled_demo", DEMO_ARTIFACT_RUN_ID, name, terminal=True,
            )
        artifacts.papers("bundled_demo", DEMO_ARTIFACT_RUN_ID)
        artifacts.evidence("bundled_demo", DEMO_ARTIFACT_RUN_ID)
        artifacts.report("bundled_demo", DEMO_ARTIFACT_RUN_ID)
        registry.seed_demo(
            run_id=DEMO_API_ID,
            artifact_run_id=DEMO_ARTIFACT_RUN_ID,
            request=DEMO_REQUEST,
            started_at=manifest.started_at,
            finished_at=manifest.finished_at,
            status=manifest.status,
        )
    except Exception:
        logging.getLogger("paper_agent.web.demo").warning(
            "bundled demo is unavailable or invalid"
        )
        return False
    return True
