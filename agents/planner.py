"""Task decomposition agent."""

from __future__ import annotations

from typing import Any

from agents.base import BaseAgent
from core.state import AgentGraphState, SubTask


PLANNER_PROMPT = """You are the Technical Lead Planner.
Analyze the user request, repository structure, and project guidelines.
Break the task into a sequential list of minimal, atomic, verifiable subtasks.
Do not write implementation code. Use project-relative file paths. Verification
commands must use an executable normally available in the project and must not
contain shell operators.

Return only a JSON object with this schema:
{"tasks":[{"id":1,"description":"...","target_files":["path"],
"verification_command":"pytest path/to/test.py"}]}
"""


class PlannerAgent(BaseAgent):
    def __call__(self, state: AgentGraphState) -> dict[str, Any]:
        response = self.gateway.completion(
            "planner",
            [
                {"role": "system", "content": PLANNER_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"USER REQUEST:\n{state['user_prompt']}\n\n"
                        f"PROJECT CONTEXT:\n{state['project_context']}"
                    ),
                },
            ],
            json_mode=True,
        )
        payload = self.parse_json(self.content(self.gateway.message(response)))
        raw_tasks = payload.get("tasks")
        if not isinstance(raw_tasks, list) or not raw_tasks:
            raise ValueError("Planner returned an empty or invalid tasks list")
        tasks = [SubTask.model_validate(item) for item in raw_tasks]
        if len({task.id for task in tasks}) != len(tasks):
            raise ValueError("Planner task ids must be unique")
        return {"plan": tasks, "current_task_index": 0, "retry_count": 0}

