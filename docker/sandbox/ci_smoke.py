"""Offline probe for the resource-bounded CI sandbox image."""

from __future__ import annotations

import errno
import json
import os
from pathlib import Path


def _read_cgroup_limit(name: str) -> str:
    path = Path("/sys/fs/cgroup") / name
    if not path.is_file():
        raise RuntimeError(f"cgroup v2 limit is unavailable: {name}")
    return path.read_text(encoding="utf-8").strip()


def main() -> None:
    interfaces = {path.name for path in Path("/sys/class/net").iterdir()}
    if interfaces != {"lo"}:
        raise RuntimeError(f"unexpected network interfaces: {sorted(interfaces)}")

    sensitive_fragments = (
        "API_KEY",
        "CREDENTIAL",
        "PASSWORD",
        "PRIVATE_KEY",
        "SECRET",
        "TOKEN",
    )
    sensitive_names = sorted(
        name for name in os.environ if any(part in name.upper() for part in sensitive_fragments)
    )
    if sensitive_names:
        raise RuntimeError(f"sensitive environment names were forwarded: {sensitive_names}")

    limits = {
        "cpu": _read_cgroup_limit("cpu.max"),
        "memory": _read_cgroup_limit("memory.max"),
        "pids": _read_cgroup_limit("pids.max"),
    }
    if limits["cpu"].split()[0] == "max":
        raise RuntimeError("CPU limit is not set")
    if limits["memory"] == "max":
        raise RuntimeError("memory limit is not set")
    if limits["pids"] == "max":
        raise RuntimeError("PID limit is not set")

    probe = Path("/techscout-read-only-probe")
    try:
        probe.write_text("unexpected write", encoding="utf-8")
    except OSError as exc:
        if exc.errno != errno.EROFS:
            raise RuntimeError("root write failed without a read-only filesystem") from exc
    else:
        probe.unlink(missing_ok=True)
        raise RuntimeError("container root filesystem is writable")

    print(json.dumps({"network": "none", "read_only": True, "limits": limits}, sort_keys=True))


if __name__ == "__main__":
    main()
