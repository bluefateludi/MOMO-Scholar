from __future__ import annotations

import argparse
import ipaddress
import logging
from pathlib import Path

import uvicorn

from paper_agent.web.app import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local-only MOMO Scholar Web API/UI")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--state-root", type=Path, default=Path("outputs/.web"))
    parser.add_argument("--output-root", type=Path, default=Path("outputs"))
    parser.add_argument("--dev-origin", action="append", default=[], help="Exact development browser origin; may be repeated")
    parser.add_argument("--allow-network", action="store_true")
    args = parser.parse_args()
    try:
        loopback = ipaddress.ip_address(args.host).is_loopback
    except ValueError:
        loopback = args.host == "localhost"
    if not loopback and not args.allow_network:
        parser.error("non-loopback binding requires --allow-network; the Web MVP has no authentication")
    if not loopback:
        logging.warning("MOMO Scholar Web is binding beyond loopback without authentication")
    app = create_app(
        state_root=args.state_root,
        output_root=args.output_root,
        allowed_origins=tuple(args.dev_origin),
    )
    uvicorn.run(app, host=args.host, port=args.port, workers=1)


if __name__ == "__main__":
    main()
