from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.events import AgentEvent, SQLiteEventSink
from core.jobs import JobStore


class PersistenceTests(unittest.TestCase):
    def test_event_timeline_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            sink = SQLiteEventSink(Path(directory) / "state.db")
            sink.emit(AgentEvent.create("run-1", "task.started", "worker", task_id="a"))
            events = sink.read("run-1")
            self.assertEqual(events[0]["type"], "task.started")
            self.assertEqual(events[0]["data"]["task_id"], "a")

    def test_scheduled_run_claim_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory) / "state.db")
            store.add("nightly", "/project", "run tests", "0 2 * * *")
            self.assertTrue(store.claim("nightly", "2026-10-30T02:00Z", "run-1"))
            self.assertFalse(store.claim("nightly", "2026-10-30T02:00Z", "run-2"))


if __name__ == "__main__":
    unittest.main()
