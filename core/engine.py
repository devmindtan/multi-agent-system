"""LangGraph workflow construction and routing."""

from __future__ import annotations

from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from agents.context_loader import context_loader_node
from agents.executor import ExecutorAgent
from agents.planner import PlannerAgent
from agents.reviewer import ReviewerAgent, verifier_node
from core.llm_gateway import LLMGateway
from core.state import AgentGraphState


def build_graph(settings: dict[str, Any], *, checkpointer: Any | None = None) -> Any:
    gateway = LLMGateway(settings)
    workflow = StateGraph(AgentGraphState)
    workflow.add_node("load_context", context_loader_node)
    workflow.add_node("plan_task", PlannerAgent(gateway))
    workflow.add_node("execute_subtask", ExecutorAgent(gateway))
    workflow.add_node("verify_execution", verifier_node)
    workflow.add_node("reviewer", ReviewerAgent(gateway))

    workflow.set_entry_point("load_context")
    workflow.add_edge("load_context", "plan_task")
    workflow.add_edge("plan_task", "execute_subtask")
    workflow.add_edge("execute_subtask", "verify_execution")

    def route_verification(state: AgentGraphState) -> str:
        if not state.get("verification_passed", False):
            return "execute_subtask" if state["retry_count"] <= state["max_retries"] else "reviewer"
        all_completed = all(task.status == "completed" for task in state["plan"])
        return "reviewer" if all_completed else "execute_subtask"

    def route_review(state: AgentGraphState) -> str:
        if state.get("review_approved", False):
            return END
        exhausted_task = any(task.status == "failed" for task in state["plan"])
        if exhausted_task or state.get("review_retry_count", 0) > state["max_retries"]:
            return END
        return "execute_subtask"

    workflow.add_conditional_edges(
        "verify_execution",
        route_verification,
        {"execute_subtask": "execute_subtask", "reviewer": "reviewer"},
    )
    workflow.add_conditional_edges(
        "reviewer",
        route_review,
        {"execute_subtask": "execute_subtask", END: END},
    )
    return workflow.compile(checkpointer=checkpointer or MemorySaver())

