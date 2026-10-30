from __future__ import annotations

import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from core.config import load_settings
from main import initial_state


def _response(content: str) -> SimpleNamespace:
    message = {"role": "assistant", "content": content}
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class FakeGateway:
    def __init__(self, settings):
        self.settings = settings

    @staticmethod
    def message(response):
        return response.choices[0].message

    def completion(self, role, messages, **kwargs):
        if role == "planner":
            if "parallel" in messages[-1]["content"].lower():
                return _response(
                    '{"tasks":['
                    '{"id":"a","description":"first","write_scope":["a.txt"],'
                    '"verification_commands":["python3 --version"]},'
                    '{"id":"b","description":"second","write_scope":["b.txt"],'
                    '"verification_commands":["python3 --version"]}]}'
                )
            return _response(
                '{"tasks":[{"id":1,"description":"smoke test",'
                '"target_files":[],"verification_command":"python3 --version"}]}'
            )
        if role == "reviewer":
            return _response('{"status":"APPROVE","reason":"checks passed"}')
        return _response("Subtask completed")


class EngineSmokeTests(unittest.TestCase):
    def test_complete_graph_route(self) -> None:
        from core import engine

        settings = load_settings()
        with tempfile.TemporaryDirectory() as project_root:
            state = initial_state(project_root, "Run a smoke test", settings)
            with patch.object(engine, "LLMGateway", FakeGateway):
                graph = engine.build_graph(settings)
                result = graph.invoke(
                    state,
                    config={"configurable": {"thread_id": "test"}},
                )

        self.assertTrue(result["is_completed"])
        self.assertTrue(result["review_approved"])
        self.assertEqual(result["plan"][0].status, "completed")
        self.assertEqual(result["artifacts"][-1].command_outputs[-1]["exit_code"], 0)

    def test_parallel_fan_out_and_collection(self) -> None:
        from core import engine

        settings = load_settings()
        with tempfile.TemporaryDirectory() as project_root:
            state = initial_state(project_root, "Run parallel tasks", settings)
            with patch.object(engine, "LLMGateway", FakeGateway):
                result = engine.build_graph(settings).invoke(
                    state, config={"configurable": {"thread_id": "parallel"}},
                )

        self.assertTrue(result["is_completed"])
        self.assertEqual({task.status for task in result["plan"]}, {"completed"})
        self.assertEqual({item.task_id for item in result["artifacts"]}, {"a", "b"})


if __name__ == "__main__":
    unittest.main()
