from __future__ import annotations

import unittest

from core.dag import ready_tasks, scopes_overlap, validate_plan
from core.state import TaskSpec


class DagTests(unittest.TestCase):
    def test_independent_tasks_are_ready_together(self) -> None:
        tasks = [
            TaskSpec(id="a", description="A", write_scope=["src/a.py"]),
            TaskSpec(id="b", description="B", write_scope=["src/b.py"]),
            TaskSpec(id="c", description="C", dependencies=["a", "b"]),
        ]
        validate_plan(tasks)
        self.assertEqual([task.id for task in ready_tasks(tasks, 4)], ["a", "b"])

    def test_overlapping_writers_are_not_scheduled_together(self) -> None:
        tasks = [
            TaskSpec(id="a", description="A", write_scope=["src/**"]),
            TaskSpec(id="b", description="B", write_scope=["src/b.py"]),
        ]
        self.assertTrue(scopes_overlap(tasks[0], tasks[1]))
        self.assertEqual(len(ready_tasks(tasks, 4)), 1)

    def test_cycle_is_rejected(self) -> None:
        tasks = [
            TaskSpec(id="a", description="A", dependencies=["b"]),
            TaskSpec(id="b", description="B", dependencies=["a"]),
        ]
        with self.assertRaisesRegex(ValueError, "cycle"):
            validate_plan(tasks)
