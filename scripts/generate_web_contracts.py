from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from paper_agent.web.app import create_app


OPENAPI_PATH = ROOT / "openapi" / "web-v1.json"
TYPESCRIPT_PATH = ROOT / "web" / "src" / "api" / "openapi.generated.ts"


def openapi_text() -> str:
    with tempfile.TemporaryDirectory(prefix="momo-web-contract-") as directory:
        root = Path(directory)
        app = create_app(
            state_root=root / "state",
            output_root=root / "outputs",
            web_dist=root / "no-ui",
        )
        return json.dumps(app.openapi(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def generate_typescript(schema_path: Path, output_path: Path) -> None:
    executable = ROOT / "web" / "node_modules" / ".bin" / (
        "openapi-typescript.cmd" if os.name == "nt" else "openapi-typescript"
    )
    if not executable.exists():
        raise SystemExit("openapi-typescript is missing; run npm ci in web/")
    subprocess.run(
        [str(executable), str(schema_path), "--output", str(output_path)],
        cwd=ROOT / "web",
        check=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected_openapi = openapi_text()
    if not args.check:
        OPENAPI_PATH.parent.mkdir(parents=True, exist_ok=True)
        OPENAPI_PATH.write_text(expected_openapi, encoding="utf-8", newline="\n")
        generate_typescript(OPENAPI_PATH, TYPESCRIPT_PATH)
        return
    if not OPENAPI_PATH.is_file() or OPENAPI_PATH.read_text(encoding="utf-8") != expected_openapi:
        raise SystemExit("openapi/web-v1.json is stale; run npm run contracts:generate")
    with tempfile.TemporaryDirectory(prefix="momo-web-types-") as directory:
        generated = Path(directory) / "openapi.generated.ts"
        generate_typescript(OPENAPI_PATH, generated)
        if not TYPESCRIPT_PATH.is_file() or TYPESCRIPT_PATH.read_bytes() != generated.read_bytes():
            raise SystemExit("web TypeScript contracts are stale; run npm run contracts:generate")


if __name__ == "__main__":
    main()
