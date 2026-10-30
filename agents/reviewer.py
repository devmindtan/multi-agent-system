"""Deterministic verification and final LLM quality review."""

from __future__ import annotations

from typing import Any

from agents.base import BaseAgent
from core.state import AgentGraphState
from tools.bash_tools import run_command


def verifier_node(state: AgentGraphState) -> dict[str, Any]:
    index = state["current_task_index"]
    task = state["plan"][index]
    artifacts = state["artifacts"]
    artifact = artifacts[-1]
    result: dict[str, Any] | None = None
    error = artifact.error_log
    if not error and task.verification_command:
        result = run_command(state["project_root"], task.verification_command)
        artifact.command_outputs.append(
            {"command": task.verification_command, "phase": "verifier", **result}
        )
        if result["exit_code"] != 0:
            error = result["stderr"] or result["stdout"] or "Verification failed"

    if error:
        artifact.error_log = error
        task.status = "failed"
        retry_count = state["retry_count"] + 1
        return {
            "plan": state["plan"],
            "artifacts": artifacts,
            "retry_count": retry_count,
            "verification_passed": False,
            "review_feedback": error,
        }

    task.status = "completed"
    next_index = index + 1 if index + 1 < len(state["plan"]) else index
    return {
        "plan": state["plan"],
        "artifacts": artifacts,
        "current_task_index": next_index,
        "retry_count": 0,
        "verification_passed": True,
        "review_feedback": "",
    }


REVIEWER_PROMPT = """You are the final software quality reviewer. Check whether the
completed task plan and execution evidence satisfy the original request and project
rules. Reject only for a concrete correctness, scope, security, or verification gap.
Return only JSON: {"status":"APPROVE"|"REJECT","reason":"concise reason"}.
"""


class ReviewerAgent(BaseAgent):
    def __call__(self, state: AgentGraphState) -> dict[str, Any]:
        failed = [task for task in state["plan"] if task.status == "failed"]
        if failed:
            reason = state.get("review_feedback") or "A subtask exhausted its retry budget"
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
            "reviewer",
            [
                {"role": "system", "content": REVIEWER_PROMPT},
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
        return {
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

