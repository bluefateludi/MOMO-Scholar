from pathlib import Path

from scripts.generate_web_contracts import (
    FIXTURE_TYPESCRIPT_PATH,
    OPENAPI_PATH,
    fixture_typescript_text,
    generated_typescript_matches,
    openapi_text,
)
from scripts.generate_web_demo import bundle
from paper_agent.web.demo import DEMO_ARTIFACT_RUN_ID, DEMO_ROOT


def test_openapi_snapshot_matches_running_app():
    assert OPENAPI_PATH.read_text(encoding="utf-8") == openapi_text()


def test_typescript_snapshot_check_normalizes_platform_line_endings(tmp_path):
    expected = tmp_path / "expected.ts"
    generated = tmp_path / "generated.ts"
    expected.write_bytes(b"export interface Run {\r\n  id: string;\r\n}\r\n")
    generated.write_bytes(b"export interface Run {\n  id: string;\n}\n")

    assert generated_typescript_matches(expected, generated)

    generated.write_text("export interface Run { id: number; }\n", encoding="utf-8")
    assert not generated_typescript_matches(expected, generated)


def test_frontend_techscout_fixture_is_generated_from_python_projection():
    assert FIXTURE_TYPESCRIPT_PATH.read_text(encoding="utf-8") == fixture_typescript_text()


def test_bundled_demo_matches_deterministic_generator():
    run_dir = DEMO_ROOT / DEMO_ARTIFACT_RUN_ID
    assert {path.name for path in run_dir.iterdir()} == set(bundle())
    for name, expected in bundle().items():
        assert (run_dir / name).read_text(encoding="utf-8") == expected
