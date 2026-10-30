"""SQLite-backed idempotent definitions for recurring local runs."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path


class JobStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS jobs(
              job_id TEXT PRIMARY KEY, project_root TEXT NOT NULL,
              task TEXT NOT NULL, schedule TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1);
            CREATE TABLE IF NOT EXISTS job_runs(
              job_id TEXT NOT NULL, scheduled_for TEXT NOT NULL,
              run_id TEXT NOT NULL, status TEXT NOT NULL,
              PRIMARY KEY(job_id, scheduled_for));
            """)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=30)

    def add(self, job_id: str, project_root: str, task: str, schedule: str) -> None:
        with self._connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO jobs(job_id,project_root,task,schedule,enabled) VALUES(?,?,?,?,1)",
                (job_id, project_root, task, schedule),
            )

    def list(self) -> list[dict[str, str]]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT job_id,project_root,task,schedule,enabled FROM jobs ORDER BY job_id"
            ).fetchall()
        return [dict(zip(("job_id", "project_root", "task", "schedule", "enabled"), row)) for row in rows]

    def get(self, job_id: str) -> dict[str, str] | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT job_id,project_root,task,schedule,enabled FROM jobs WHERE job_id=?",
                (job_id,),
            ).fetchone()
        return dict(zip(("job_id", "project_root", "task", "schedule", "enabled"), row)) if row else None


    def claim(self, job_id: str, scheduled_for: str, run_id: str) -> bool:
        try:
            with self._connect() as db:
                db.execute(
                    "INSERT INTO job_runs(job_id,scheduled_for,run_id,status) VALUES(?,?,?,'running')",
                    (job_id, scheduled_for, run_id),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def complete(self, run_id: str, status: str) -> None:
        with self._connect() as db:
            db.execute("UPDATE job_runs SET status=? WHERE run_id=?", (status, run_id))
