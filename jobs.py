"""Manage idempotent recurring jobs; invoke `run` from cron/systemd timers."""

from __future__ import annotations

import argparse
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from core.config import PACKAGE_ROOT, load_settings
from core.jobs import JobStore
from main import main as run_main


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Manage local multi-agent jobs")
    root.add_argument("--database", help="Runtime SQLite path")
    commands = root.add_subparsers(dest="command", required=True)
    add = commands.add_parser("add")
    add.add_argument("--id", required=True)
    add.add_argument("--project-dir", required=True)
    add.add_argument("--task", required=True)
    add.add_argument("--schedule", required=True, help="Cron/systemd schedule for documentation")
    commands.add_parser("list")
    run = commands.add_parser("run")
    run.add_argument("--id", required=True)
    run.add_argument("--scheduled-for", help="Idempotency timestamp; defaults to current UTC minute")
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    settings = load_settings()
    database = Path(args.database) if args.database else PACKAGE_ROOT / settings["system"]["database_path"]
    store = JobStore(database)
    if args.command == "add":
        store.add(args.id, str(Path(args.project_dir).expanduser().resolve()), args.task, args.schedule)
        print(f"Saved job {args.id}")
        return 0
    if args.command == "list":
        print(json.dumps(store.list(), ensure_ascii=False, indent=2))
        return 0
    job = store.get(args.id)
    if not job or not job["enabled"]:
        print(f"Job not found or disabled: {args.id}")
        return 2
    scheduled_for = args.scheduled_for or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    run_id = str(uuid.uuid4())
    if not store.claim(args.id, scheduled_for, run_id):
        print(f"Job {args.id} was already claimed for {scheduled_for}")
        return 0
    code = run_main([
        "--project-dir", str(job["project_root"]), "--task", str(job["task"]),
        "--run-id", run_id, "--event-db", str(database),
    ])
    store.complete(run_id, "completed" if code == 0 else "failed")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
