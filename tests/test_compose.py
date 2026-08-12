import json
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _compose_config() -> dict[str, object]:
    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("Docker Compose is unavailable")
    result = subprocess.run(
        [docker, "compose", "-f", str(ROOT / "compose.yaml"), "config", "--format", "json"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_compose_web_service_is_loopback_only_and_has_no_docker_socket() -> None:
    config = _compose_config()
    service = config["services"]["web"]

    assert service["ports"] == [{
        "mode": "ingress",
        "target": 8000,
        "published": "8000",
        "host_ip": "127.0.0.1",
        "protocol": "tcp",
    }]
    assert service["read_only"] is True
    assert service["cap_drop"] == ["ALL"]
    assert "no-new-privileges:true" in service["security_opt"]
    assert service.get("privileged", False) is False
    assert all(
        mount.get("source") != "/var/run/docker.sock"
        and mount.get("target") != "/var/run/docker.sock"
        for mount in service.get("volumes", [])
    )
