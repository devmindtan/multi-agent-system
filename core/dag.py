"""Deterministic task graph validation and scheduling helpers."""

from __future__ import annotations

from fnmatch import fnmatch

from core.state import TaskSpec


def validate_plan(tasks: list[TaskSpec]) -> None:
    if not tasks:
        raise ValueError("Task graph is empty")
    ids = [task.id for task in tasks]
    if len(ids) != len(set(ids)):
        raise ValueError("Task ids must be unique")
    known = set(ids)
    for task in tasks:
        missing = set(task.dependencies) - known
        if missing:
            raise ValueError(f"Task {task.id} has unknown dependencies: {sorted(missing)}")
        if task.id in task.dependencies:
            raise ValueError(f"Task {task.id} depends on itself")
    visiting: set[str] = set()
    visited: set[str] = set()
    by_id = {task.id: task for task in tasks}

    def visit(task_id: str) -> None:
        if task_id in visiting:
            raise ValueError(f"Task graph contains a cycle at {task_id}")
        if task_id in visited:
            return
        visiting.add(task_id)
        for dependency in by_id[task_id].dependencies:
            visit(dependency)
        visiting.remove(task_id)
        visited.add(task_id)

    for task_id in ids:
        visit(task_id)


def scopes_overlap(first: TaskSpec, second: TaskSpec) -> bool:
    for left in first.write_scope or first.target_files:
        for right in second.write_scope or second.target_files:
            if left == right or fnmatch(left, right) or fnmatch(right, left):
                return True
            if left.startswith(right.rstrip("*/") + "/") or right.startswith(left.rstrip("*/") + "/"):
                return True
    return False


def ready_tasks(tasks: list[TaskSpec], limit: int) -> list[TaskSpec]:
    completed = {task.id for task in tasks if task.status == "completed"}
    candidates = [task for task in tasks if task.status == "pending" and set(task.dependencies) <= completed]
    selected: list[TaskSpec] = []
    for task in candidates:
        if all(not scopes_overlap(task, current) for current in selected):
            selected.append(task)
        if len(selected) >= limit:
            break
    return selected
