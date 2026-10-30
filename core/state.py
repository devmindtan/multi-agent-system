"""Shared, serializable graph state models."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field
from typing_extensions import NotRequired, TypedDict


class SubTask(BaseModel):
    id: int
    description: str
    target_files: list[str] = Field(default_factory=list)
    verification_command: str | None = None
    status: Literal["pending", "in_progress", "completed", "failed"] = "pending"


class ExecutionArtifact(BaseModel):
    task_id: int
    files_created: list[str] = Field(default_factory=list)
    files_modified: list[str] = Field(default_factory=list)
    command_outputs: list[dict[str, Any]] = Field(default_factory=list)
    error_log: str | None = None


class AgentGraphState(TypedDict):
    project_root: str
    user_prompt: str
    project_context: str
    plan: list[SubTask]
    current_task_index: int
    retry_count: int
    max_retries: int
    artifacts: list[ExecutionArtifact]
    is_completed: bool
    final_summary: str
    verification_passed: NotRequired[bool]
    review_approved: NotRequired[bool]
    review_feedback: NotRequired[str]
    review_retry_count: NotRequired[int]
    settings: NotRequired[dict[str, Any]]

