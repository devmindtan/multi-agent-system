"""Deterministic verification and final LLM quality review."""

from __future__ import annotations

from typing import Any

from agents.base import BaseAgent
from core.agent_profiles import AgentProfile
from core.events import EventSink, emit
from core.state import AgentGraphState


class ReviewerAgent(BaseAgent):
    def __init__(self, gateway, profile: AgentProfile, sink: EventSink):
        super().__init__(gateway)
        self.profile = profile
        self.sink = sink

    def __call__(self, state: AgentGraphState) -> dict[str, Any]:
        emit(self.sink, state["run_id"], "agent.started", "reviewer")
        failed = [task for task in state["plan"] if task.status in {"failed", "blocked"}]
        if failed:
            reason = "; ".join(f"{task.id}: {task.failure or task.status}" for task in failed)
            emit(self.sink, state["run_id"], "review.completed", "reviewer",
                 approved=False, reason=reason)
            return {
                "review_approved": False,
                "is_completed": False,
                "final_summary": f"Execution failed: {reason}",
            }

        evidence = "\n".join(
            f"Task {artifact.task_id}: created={artifact.files_created}, "
            f"modified={artifact.files_modified}, error={artifact.error_log}"
            for artifact in state["artifacts"]
        )
        response = self.gateway.completion(
            self.profile.model_role,
            [
                {"role": "system", "content": self.profile.instructions()},
                {
                    "role": "user",
                    "content": (
                        f"REQUEST:\n{state['user_prompt']}\n\nPLAN:\n"
                        f"{[task.model_dump() for task in state['plan']]}\n\n"
                        f"EXECUTION EVIDENCE:\n{evidence}"
                    ),
                },
            ],
            json_mode=True,
        )
        payload = self.parse_json(self.content(self.gateway.message(response)))
        approved = str(payload.get("status", "")).upper() == "APPROVE"
        reason = str(payload.get("reason", "No review reason supplied"))
        review_retry_count = state.get("review_retry_count", 0) + (0 if approved else 1)
        if not approved and state["plan"]:
            repair_task = state["plan"][-1]
            if repair_task.attempts < repair_task.max_attempts:
                repair_task.status = "pending"
                repair_task.failure = f"Reviewer feedback: {reason}"
            else:
                repair_task.status = "failed"
                repair_task.failure = f"Reviewer rejected after retry budget: {reason}"
        emit(self.sink, state["run_id"], "review.completed", "reviewer",
             approved=approved, reason=reason)
        return {
            "plan": state["plan"],
            "review_approved": approved,
            "review_feedback": "" if approved else reason,
            "review_retry_count": review_retry_count,
            "is_completed": approved,
            "final_summary": (
                f"All {len(state['plan'])} subtasks completed and review approved: {reason}"
                if approved
                else f"Review rejected: {reason}"
            ),
        }

