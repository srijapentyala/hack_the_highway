#!/usr/bin/env python3
"""Control-tower UI over a finished run.

    python3 solution/control_tower.py --run runs/run1 --port 8090
"""
from __future__ import annotations

import argparse
import json
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "solution"))
STATIC = Path(__file__).resolve().parent / "static"


class Handler(SimpleHTTPRequestHandler):
    run_dir = ROOT / "runs" / "run1"
    atlas_uri = ""
    atlas_db = ""

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/report":
            payload = self._report_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if path == "/":
            self.path = "/index.html"
        return super().do_GET()

    def log_message(self, fmt, *args):
        return

    def _report_bytes(self) -> bytes:
        if self.atlas_uri:
            from tower.atlas import fetch_report

            report = fetch_report(self.atlas_uri, self.atlas_db)
            return json.dumps(report).encode()
        return (self.run_dir / "report.json").read_bytes()


def main():
    from tower.atlas import db_name, uri

    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default=str(ROOT / "runs" / "run1"))
    ap.add_argument("--port", type=int, default=8090)
    ap.add_argument("--atlas", action="store_true", help="Read /api/report from MongoDB Atlas")
    args = ap.parse_args()
    Handler.run_dir = Path(args.run)
    Handler.atlas_uri = uri() if args.atlas else ""
    Handler.atlas_db = db_name()
    source = f"Atlas {Handler.atlas_db}" if Handler.atlas_uri else Handler.run_dir / "report.json"
    server = ThreadingHTTPServer(("127.0.0.1", args.port), partial(Handler, directory=str(STATIC)))
    print(f"http://127.0.0.1:{args.port}   ({source})", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
