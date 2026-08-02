from pathlib import Path

from scripts.generate_web_contracts import OPENAPI_PATH, openapi_text
from scripts.generate_web_demo import bundle
from paper_agent.web.demo import DEMO_ARTIFACT_RUN_ID, DEMO_ROOT


def test_openapi_snapshot_matches_running_app():
    assert OPENAPI_PATH.read_text(encoding="utf-8") == openapi_text()


def test_bundled_demo_matches_deterministic_generator():
    run_dir = DEMO_ROOT / DEMO_ARTIFACT_RUN_ID
    assert {path.name for path in run_dir.iterdir()} == set(bundle())
    for name, expected in bundle().items():
        assert (run_dir / name).read_text(encoding="utf-8") == expected
