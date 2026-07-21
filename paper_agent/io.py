from __future__ import annotations

import json
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any


def slugify(value: str, max_length: int = 60) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return slug[:max_length].strip("-") or "paper-agent-run"


def create_run_dir(base_dir: Path, question: str) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    run_dir = base_dir / f"{timestamp}-{slugify(question)}"
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


def write_json(path: Path, data: Any) -> None:
    serialized = json.dumps(data, ensure_ascii=False, indent=2)
    _write_atomically(path, serialized)


def append_json_line(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open(mode="a", encoding="utf-8") as file:
        line = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        file.write(line + "\n")


def write_text(path: Path, text: str) -> None:
    _write_atomically(path, text)


def _write_atomically(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            delete=False,
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(text)
            temporary_file.flush()
        temporary_path.replace(path)
    except BaseException:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise
