#!/usr/bin/env python3
"""Run the GitLab inventory and serve the resulting reports over HTTP.

Defaults to binding 0.0.0.0:8765 because the lab runs in an isolated network.
Use Ctrl+C to stop.
"""
from __future__ import annotations

import argparse
import socket
import subprocess
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
INVENTORY = HERE / "gitlab-inventory.py"
REPORTS_DIR = HERE / "reports"


def run_inventory(config: Path | None) -> None:
    cmd = [sys.executable, str(INVENTORY), "--format", "both"]
    if config is not None:
        cmd += ["--config", str(config)]
    print(f"running inventory: {' '.join(cmd)}")
    subprocess.run(cmd, check=True)


def serve(bind: str, port: int) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    handler = partial(SimpleHTTPRequestHandler, directory=str(REPORTS_DIR))
    server = ThreadingHTTPServer((bind, port), handler)
    print(f"serving {REPORTS_DIR} on:")
    print(f"  http://{bind}:{port}/latest.html")
    print(f"  http://{bind}:{port}/latest-anonymized.html")
    print(f"  http://{bind}:{port}/latest.md")
    print(f"  http://{bind}:{port}/latest-anonymized.md")
    print(f"  http://{bind}:{port}/latest.json")
    if bind in ("0.0.0.0", "::"):
        try:
            host = socket.gethostname()
            print(f"  (also reachable as http://{host}:{port}/latest.html)")
        except OSError:
            pass
    print("Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down.")
    finally:
        server.server_close()


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Run gitlab-inventory.py and serve the reports/ directory over HTTP.")
    parser.add_argument("--port", type=int, default=8765, help="TCP port to listen on (default: 8765)")
    parser.add_argument("--bind", default="0.0.0.0",
                        help="Address to bind (default: 0.0.0.0 — intended for isolated lab networks)")
    parser.add_argument("--no-run", action="store_true",
                        help="Skip running the inventory; only serve existing reports")
    parser.add_argument("--config", type=Path, default=None,
                        help="Path to gitlab-inventory config.ini (passed through)")
    args = parser.parse_args(argv)

    if not args.no_run:
        try:
            run_inventory(args.config)
        except subprocess.CalledProcessError as e:
            return e.returncode

    serve(args.bind, args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
