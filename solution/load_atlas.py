#!/usr/bin/env python3
"""Load the finished run into MongoDB Atlas. Does not call enterprise tools.

    MONGODB_URI='mongodb+srv://...' python3 solution/load_atlas.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "solution"))

from tower.atlas import db_name, publish, uri  # noqa: E402


def main() -> int:
    connection = uri()
    if not connection:
        print(
            "Set MONGODB_URI to the Atlas connection string, then run this again.\n"
            "Atlas → Database → Connect → Drivers → copy the mongodb+srv URI.\n"
            "Optional: MONGODB_DB (default hack_the_highway).",
            file=sys.stderr,
        )
        return 2
    report_path = ROOT / "runs" / "run1" / "report.json"
    report = json.loads(report_path.read_text())
    counts = publish(report, connection, db_name())
    print(
        f"Loaded {db_name()}: {counts['entities']} entities, "
        f"{counts['relations']} relations, {counts['events']} events."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
