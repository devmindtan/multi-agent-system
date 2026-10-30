"""Parallel DAG orchestration for local-only coding agents."""

from __future__ import annotations

from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.types import Send

from agents.context_loader import context_loader_node
from agents.executor import ExecutorAgent
from agents.planner import PlannerAgent
from agents.reviewer import ReviewerAgent
from core.agent_profiles import load_agent_profiles
from core.config import PACKAGE_ROOT
from core.dag import ready_tasks, validate_plan
from core.events import EventSink, NullEventSink, emit
from core.llm_gateway import LLMGateway
from core.state import AgentGraphState, WorkerState
from core.workspace import (
    create_run_workspace, create_task_worktree, finalize_workspace, integrate_task,
)


def build_graph(
    settings: dict[str, Any], *, checkpointer: Any | None = None,
    event_sink: EventSink | None = None,
) -> Any:
    sink = event_sink or NullEventSink()
    profiles = load_agent_profiles()
    gateway = LLMGateway(settings)
    planner = PlannerAgent(gateway, profiles["supervisor"], sink)
    worker = ExecutorAgent(gateway, profiles, sink)
    reviewer = ReviewerAgent(gateway, profiles["reviewer"], sink)
    workflow = StateGraph(AgentGraphState)

    def load_context(state: AgentGraphState) -> dict[str, Any]:
        emit(sink, state["run_id"], "run.started", "runtime",
             project_root=state["project_root"])
        emit(sink, state["run_id"], "node.started", "context_loader")
        result = context_loader_node(state)
        emit(sink, state["run_id"], "node.completed", "context_loader")
        return result

    def prepare_wave(state: AgentGraphState) -> dict[str, Any]:
        validate_plan(state["plan"])
        failed_ids = {task.id for task in state["plan"] if task.status in {"failed", "blocked"}}
        for task in state["plan"]:
            if task.status == "pending" and failed_ids.intersection(task.dependencies):
                task.status = "blocked"
                task.failure = "A dependency failed"
        limit = int(settings.get("scheduler", {}).get("max_parallel_tasks", 4))
        selected = ready_tasks(state["plan"], limit)
        task_workspaces: dict[str, str] = {}
        for task in selected:
            task.status = "running"
            task_workspaces[task.id] = create_task_worktree(
                state["workspace"], task.id, task.attempts + 1
            )
        emit(sink, state["run_id"], "scheduler.wave", "scheduler",
             tasks=[task.id for task in selected])
        return {
            "plan": state["plan"], "workspace": state["workspace"],
            "task_workspaces": task_workspaces,
            "scheduled_task_ids": [task.id for task in selected],
        }

    def dispatch_wave(state: AgentGraphState) -> Any:
        selected = set(state["scheduled_task_ids"])
        if not selected:
            return "reviewer"
        return [
            Send(
                "execute_task",
                WorkerState(
                    run_id=state["run_id"], project_root=state["task_workspaces"][task.id],
                    project_context=state["project_context"], task=task,
                    settings=state.get("settings", {}), worker_results={},
                ),
            )
            for task in state["plan"] if task.id in selected
        ]

    def collect_results(state: AgentGraphState) -> dict[str, Any]:
        artifacts = list(state["artifacts"])
        scheduled = set(state["scheduled_task_ids"])
        for task in state["plan"]:
            if task.id not in scheduled:
                continue
            result = state["worker_results"][task.id]
            task.attempts = result.attempt
            artifacts.append(result.artifact)
            if result.success:
                try:
                    integrate_task(
                        state["workspace"], task.id, state["task_workspaces"][task.id],
                        task.write_scope or task.target_files,
                    )
                    task.status = "completed"
                    task.failure = None
                except Exception as exc:
                    task.status = "failed"
                    task.failure = str(exc)
                    result.artifact.error_log = str(exc)
            elif result.attempt < task.max_attempts:
                task.status = "pending"
                task.failure = result.artifact.error_log
            else:
                task.status = "failed"
                task.failure = result.artifact.error_log
        return {
            "plan": state["plan"], "workspace": state["workspace"],
            "artifacts": artifacts, "scheduled_task_ids": [], "task_workspaces": {},
        }

    def finish(state: AgentGraphState) -> dict[str, Any]:
        artifact_dir = PACKAGE_ROOT / settings["system"].get("artifact_directory", ".runtime/artifacts")
        patch = finalize_workspace(
            state["workspace"], artifact_dir, state["run_id"],
            bool(state["is_completed"] and settings.get("scheduler", {}).get("apply_changes", True)),
        )
        event_type = "run.completed" if state["is_completed"] else "run.failed"
        emit(sink, state["run_id"], event_type, "runtime",
             summary=state["final_summary"], patch=patch or "")
        return {}

    def route_review(state: AgentGraphState) -> str:
        if state.get("review_approved", False):
            return "finish"
        if any(task.status in {"failed", "blocked"} for task in state["plan"]):
            return "finish"
        if state.get("review_retry_count", 0) > state["max_retries"]:
            return "finish"
        return "prepare_wave"

    def prepare_workspace(state: AgentGraphState) -> dict[str, Any]:
        runtime_root = PACKAGE_ROOT / ".runtime"
        workspace = create_run_workspace(state["project_root"], runtime_root, state["run_id"])
        emit(sink, state["run_id"], "workspace.created", "runtime", mode=workspace["mode"])
        return {"workspace": workspace}

    workflow.add_node("load_context", load_context)
    workflow.add_node("plan_task", planner)
    workflow.add_node("prepare_workspace", prepare_workspace)
    workflow.add_node("prepare_wave", prepare_wave)
    workflow.add_node("execute_task", worker)
    workflow.add_node("collect_results", collect_results)
    workflow.add_node("reviewer", reviewer)
    workflow.add_node("finish", finish)

    workflow.set_entry_point("load_context")
    workflow.add_edge("load_context", "plan_task")
    workflow.add_edge("plan_task", "prepare_workspace")
    workflow.add_edge("prepare_workspace", "prepare_wave")
    workflow.add_conditional_edges("prepare_wave", dispatch_wave, {"reviewer": "reviewer"})
    workflow.add_edge("execute_task", "collect_results")
    workflow.add_edge("collect_results", "prepare_wave")
    workflow.add_conditional_edges(
        "reviewer", route_review,
        {"prepare_wave": "prepare_wave", "finish": "finish"},
    )
    workflow.add_edge("finish", END)
    return workflow.compile(checkpointer=checkpointer or MemorySaver())

