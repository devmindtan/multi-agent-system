"""Print the persisted event timeline for a run."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from core.config import PACKAGE_ROOT, load_settings
from core.events import SQLiteEventSink


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_id")
    parser.add_argument("--database")
    args = parser.parse_args()
    settings = load_settings()
    path = Path(args.database) if args.database else PACKAGE_ROOT / settings["system"]["database_path"]
    for event in SQLiteEventSink(path).read(args.run_id):
        print(json.dumps(event, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
