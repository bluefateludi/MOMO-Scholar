import hashlib
import json
from pathlib import Path


FIXTURES = Path("tests/fixtures/techscout/eval")
EXPECTED_SHA256 = {
    "smoke-bounded-recovery.json": "06c0a0268bd14a7970f61e217e729f953e07f2ee3f6607d088ab24a3976cb90f",
    "smoke-happy-path.json": "75eee8b1a6d1cc4278b717fce9b1f953321c470b496ede4d50e96960e522138b",
    "smoke-no-safe-winner.json": "1cfe6f27419bcf570d30ade0474d2e0f05fa11b9a3ef8227b2862588ed3e2c1b",
    "smoke-suite.json": "6cdfdffbdd1f94a7d32835b93cbcc2c89bd8ad82473f3a99e0f620253e5bd3f3",
}


def test_frozen_eval_fixtures_have_expected_hashes_and_no_observations():
    actual = {
        path.name: hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
        for path in sorted(FIXTURES.glob("*.json"))
    }
    assert actual == EXPECTED_SHA256
    for path in FIXTURES.glob("smoke-*.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema_version") == "techscout-eval-case-v1":
            assert payload["observed_metrics"] == {}
