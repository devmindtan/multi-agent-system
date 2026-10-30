from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agents.executor import ExecutorAgent
from core.agent_profiles import load_agent_profiles
from core.events import NullEventSink
from core.state import TaskSpec


def tool_call(call_id: str, name: str, **arguments: str) -> dict:
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [{
            "id": call_id,
            "type": "function",
            "function": {"name": name, "arguments": json.dumps(arguments)},
        }],
    }


class ScriptedGateway:
    def __init__(self, responses: list[dict]):
        self.responses = iter(responses)
        self.calls = 0

    def completion(self, role, messages, **kwargs):
        self.calls += 1
        return next(self.responses)

    @staticmethod
    def message(response):
        return response


class ExecutorTests(unittest.TestCase):
    def test_repeated_failed_edit_stops_early(self) -> None:
        gateway = ScriptedGateway([
            tool_call("1", "patch_file", relative_path="sample.py", old_text="missing", new_text="new"),
            tool_call("2", "read_file", relative_path="sample.py"),
            tool_call("3", "patch_file", relative_path="sample.py", old_text="missing", new_text="new"),
        ])
        agent = ExecutorAgent(gateway, load_agent_profiles(), NullEventSink())
        with tempfile.TemporaryDirectory() as project_root:
            Path(project_root, "sample.py").write_text("current\n", encoding="utf-8")
            task = TaskSpec(
                id="test-edit-loop", description="change sample", kind="test",
                target_files=["sample.py"], write_scope=["sample.py"], max_attempts=2,
            )
            result = agent({
                "run_id": "test-run", "project_root": project_root,
                "project_context": "test", "task": task,
                "settings": {"system": {"max_executor_steps": 10}},
                "worker_results": {},
            })["worker_results"][task.id]

        self.assertFalse(result.success)
        self.assertIn("failed patch_file calls", result.artifact.error_log or "")
        self.assertEqual(gateway.calls, 3)

    def test_repeated_out_of_scope_edit_preserves_valid_work(self) -> None:
        gateway = ScriptedGateway([
            tool_call("1", "write_file", relative_path="allowed.py", content="changed\n"),
            tool_call("2", "write_file", relative_path="other.py", content="no\n"),
            tool_call("3", "write_file", relative_path="other.py", content="no\n"),
        ])
        agent = ExecutorAgent(gateway, load_agent_profiles(), NullEventSink())
        with tempfile.TemporaryDirectory() as project_root:
            Path(project_root, "allowed.py").write_text("current\n", encoding="utf-8")
            task = TaskSpec(
                id="test-scope-loop", description="change allowed file", kind="implement",
                target_files=["allowed.py"], write_scope=["allowed.py"], max_attempts=2,
            )
            result = agent({
                "run_id": "test-run", "project_root": project_root,
                "project_context": "test", "task": task,
                "settings": {"system": {"max_executor_steps": 10}},
                "worker_results": {},
            })["worker_results"][task.id]
            content = Path(project_root, "allowed.py").read_text(encoding="utf-8")

        self.assertTrue(result.success)
        self.assertEqual(content, "changed\n")
        self.assertIn("out-of-scope", result.artifact.summary)
        self.assertEqual(gateway.calls, 3)


if __name__ == "__main__":
    unittest.main()
