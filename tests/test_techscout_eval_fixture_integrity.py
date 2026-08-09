import hashlib
import json
from pathlib import Path


FIXTURES = Path("tests/fixtures/techscout/eval")
EXPECTED_SHA256 = {
    "smoke-bounded-recovery.json": "20569223990fd1f2765edee3bab94703afd4d4cd7c7c1582eeb3f2edd4b5c730",
    "smoke-happy-path.json": "6df380d1a99980f46061727cc39d619d1ea4afde7e7ab9dbb7f79fe498a8951f",
    "smoke-no-safe-winner.json": "a449e3b1c4f6c5c9117e86d79c1c499c1d1eb6b1528f348b508d1d996aaf7e2a",
    "smoke-suite.json": "6cdfdffbdd1f94a7d32835b93cbcc2c89bd8ad82473f3a99e0f620253e5bd3f3",
}


def test_frozen_techscout_eval_fixtures_have_expected_hashes_and_no_observations():
    actual = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(FIXTURES.glob("*.json"))
    }
    assert actual == EXPECTED_SHA256
    for path in FIXTURES.glob("smoke-*.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema_version") == "techscout-eval-case-v1":
            assert payload["observed_metrics"] == {}
