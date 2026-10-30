"""Task decomposition agent."""

from __future__ import annotations

from typing import Any

from agents.base import BaseAgent
from core.agent_profiles import AgentProfile
from core.dag import validate_plan
from core.events import EventSink, emit
from core.state import AgentGraphState, TaskSpec


class PlannerAgent(BaseAgent):
    def __init__(self, gateway, profile: AgentProfile, sink: EventSink):
        super().__init__(gateway)
        self.profile = profile
        self.sink = sink

    def __call__(self, state: AgentGraphState) -> dict[str, Any]:
        emit(self.sink, state["run_id"], "agent.started", "supervisor")
        response = self.gateway.completion(
            self.profile.model_role,
            [
                {"role": "system", "content": self.profile.instructions()},
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
        tasks: list[TaskSpec] = []
        for position, item in enumerate(raw_tasks, 1):
            if "verification_command" in item and "verification_commands" not in item:
                command = item.pop("verification_command")
                item["verification_commands"] = [command] if command else []
            item.setdefault("id", f"task-{position}")
            item.setdefault("write_scope", item.get("target_files", []))
            item.setdefault("max_attempts", state["max_retries"] + 1)
            tasks.append(TaskSpec.model_validate(item))
        validate_plan(tasks)
        emit(self.sink, state["run_id"], "plan.created", "supervisor", tasks=len(tasks))
        return {"plan": tasks}

