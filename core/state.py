"""Serializable domain and graph state for parallel local agents."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, field_validator
from typing_extensions import NotRequired, TypedDict


TaskStatus = Literal["pending", "running", "completed", "failed", "blocked"]


class TaskSpec(BaseModel):
    id: str
    description: str
    kind: Literal["research", "design", "implement", "test", "review", "integrate"] = "implement"
    dependencies: list[str] = Field(default_factory=list)
    target_files: list[str] = Field(default_factory=list)
    write_scope: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    verification_commands: list[str] = Field(default_factory=list)
    max_attempts: int = Field(default=3, ge=1, le=10)
    attempts: int = 0
    status: TaskStatus = "pending"
    failure: str | None = None

    @field_validator("id", mode="before")
    @classmethod
    def stringify_id(cls, value: Any) -> str:
        return str(value)

    @field_validator("dependencies", mode="before")
    @classmethod
    def stringify_dependencies(cls, value: Any) -> list[str]:
        return [str(item) for item in (value or [])]

    @property
    def verification_command(self) -> str | None:
        return self.verification_commands[0] if self.verification_commands else None


SubTask = TaskSpec


class ExecutionArtifact(BaseModel):
    task_id: str
    files_created: list[str] = Field(default_factory=list)
    files_modified: list[str] = Field(default_factory=list)
    command_outputs: list[dict[str, Any]] = Field(default_factory=list)
    error_log: str | None = None
    summary: str = ""


class TaskResult(BaseModel):
    task_id: str
    success: bool
    artifact: ExecutionArtifact
    attempt: int
    worker_id: str


def merge_results(left: dict[str, TaskResult] | None, right: dict[str, TaskResult] | None) -> dict[str, TaskResult]:
    return {**(left or {}), **(right or {})}


class AgentGraphState(TypedDict):
    run_id: str
    project_root: str
    user_prompt: str
    project_context: str
    plan: list[TaskSpec]
    max_retries: int
    artifacts: list[ExecutionArtifact]
    worker_results: Annotated[dict[str, TaskResult], merge_results]
    scheduled_task_ids: list[str]
    workspace: dict[str, Any]
    task_workspaces: dict[str, str]
    is_completed: bool
    final_summary: str
    review_approved: NotRequired[bool]
    review_feedback: NotRequired[str]
    review_retry_count: NotRequired[int]
    replan_count: NotRequired[int]
    settings: NotRequired[dict[str, Any]]


class WorkerState(TypedDict):
    run_id: str
    project_root: str
    project_context: str
    task: TaskSpec
    settings: dict[str, Any]
    worker_results: Annotated[dict[str, TaskResult], merge_results]

