"""Tool-calling implementation agent."""

from __future__ import annotations

import json
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

from agents.base import BaseAgent
from core.agent_profiles import AgentProfile
from core.config import load_tool_config
from core.events import EventSink, emit
from core.state import ExecutionArtifact, TaskResult, WorkerState
from tools.bash_tools import run_command
from tools.fs_tools import list_files, patch_file, read_file, write_file


TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a UTF-8 project file.",
            "parameters": {
                "type": "object",
                "properties": {"relative_path": {"type": "string"}},
                "required": ["relative_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Create or fully replace a UTF-8 project file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "relative_path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["relative_path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "patch_file",
            "description": "Replace one exact, unique text block in a project file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "relative_path": {"type": "string"},
                    "old_text": {"type": "string"},
                    "new_text": {"type": "string"},
                },
                "required": ["relative_path", "old_text", "new_text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List project files recursively.",
            "parameters": {
                "type": "object",
                "properties": {"relative_path": {"type": "string", "default": "."}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Run one allowlisted command without a shell.",
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
        },
    },
]


def _message_dict(message: Any) -> dict[str, Any]:
    if isinstance(message, dict):
        return message
    if hasattr(message, "model_dump"):
        return message.model_dump(exclude_none=True)
    result = {"role": "assistant", "content": getattr(message, "content", None)}
    tool_calls = getattr(message, "tool_calls", None)
    if tool_calls:
        result["tool_calls"] = tool_calls
    return result


def _tool_calls(message: Any) -> list[Any]:
    if isinstance(message, dict):
        return message.get("tool_calls") or []
    return getattr(message, "tool_calls", None) or []


def _field(value: Any, name: str) -> Any:
    return value.get(name) if isinstance(value, dict) else getattr(value, name)


class ExecutorAgent(BaseAgent):
    def __init__(self, gateway, profiles: dict[str, AgentProfile], sink: EventSink):
        super().__init__(gateway)
        self.profiles = profiles
        self.sink = sink

    def __call__(self, state: WorkerState) -> dict[str, Any]:
        task = state["task"]
        profile_name = {
            "research": "explorer", "design": "explorer", "test": "tester",
            "integrate": "integrator",
        }.get(task.kind, "implementer")
        profile = self.profiles[profile_name]
        task.status = "running"
        task.attempts += 1
        artifact = ExecutionArtifact(task_id=task.id)
        root = state["project_root"]
        worker_id = f"worker-{task.id}-{task.attempts}"
        emit(self.sink, state["run_id"], "task.started", worker_id,
             task_id=task.id, attempt=task.attempts)
        config = load_tool_config()
        max_read = int(config.get("filesystem", {}).get("max_read_bytes", 1_000_000))
        ignored = config.get("filesystem", {}).get("ignored_directories", [])

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": profile.instructions()},
            {
                "role": "user",
                "content": (
                    f"PROJECT CONTEXT:\n{state['project_context']}\n\n"
                    f"CURRENT SUBTASK:\n{task.model_dump_json(indent=2)}\n\n"
                    f"PREVIOUS FAILURE FEEDBACK:\n{task.failure or ''}"
                ),
            },
        ]

        def ensure_write_scope(relative_path: str) -> None:
            scopes = task.write_scope or task.target_files
            if not scopes:
                raise PermissionError("Task has no declared write scope")
            if not any(
                relative_path == scope
                or fnmatch(relative_path, scope)
                or relative_path.startswith(scope.rstrip("*/") + "/")
                for scope in scopes
            ):
                raise PermissionError(
                    f"Write outside task scope rejected: {relative_path}; scope={scopes}"
                )

        def dispatch(name: str, arguments: dict[str, Any]) -> Any:
            emit(self.sink, state["run_id"], "tool.started", worker_id,
                 task_id=task.id, tool=name)
            if name == "read_file":
                result = read_file(root, arguments["relative_path"], max_read)
            elif name == "list_files":
                result = list_files(root, arguments.get("relative_path", "."), ignored)
            elif name == "run_command":
                result = run_command(root, arguments["command"], tool_config=config)
                artifact.command_outputs.append({"command": arguments["command"], **result})
            elif name in {"write_file", "patch_file"}:
                relative_path = arguments["relative_path"]
                ensure_write_scope(relative_path)
                existed = (Path(root) / relative_path).resolve(strict=False).is_file()
                if name == "write_file":
                    result = write_file(root, relative_path, arguments["content"])
                else:
                    result = patch_file(
                        root, relative_path, arguments["old_text"], arguments["new_text"]
                    )
                collection = artifact.files_modified if existed else artifact.files_created
                if relative_path not in collection:
                    collection.append(relative_path)
            else:
                raise ValueError(f"Unknown tool: {name}")
            emit(self.sink, state["run_id"], "tool.completed", worker_id,
                 task_id=task.id, tool=name)
            return result

        max_steps = min(
            profile.max_turns,
            int(state.get("settings", {}).get("system", {}).get("max_executor_steps", 20)),
        )
        allowed_schemas = [
            schema for schema in TOOL_SCHEMAS
            if schema["function"]["name"] in profile.tools
        ]
        try:
            for _ in range(max_steps):
                response = self.gateway.completion(
                    profile.model_role, messages, tools=allowed_schemas
                )
                message = self.gateway.message(response)
                messages.append(_message_dict(message))
                calls = _tool_calls(message)
                if not calls:
                    break
                for call in calls:
                    function = _field(call, "function")
                    name = _field(function, "name")
                    raw_arguments = _field(function, "arguments")
                    arguments = raw_arguments if isinstance(raw_arguments, dict) else json.loads(raw_arguments)
                    try:
                        result = dispatch(name, arguments)
                    except Exception as exc:
                        result = {"error": f"{type(exc).__name__}: {exc}"}
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": _field(call, "id"),
                            "name": name,
                            "content": json.dumps(result, ensure_ascii=False),
                        }
                    )
            else:
                artifact.error_log = f"Executor exceeded {max_steps} tool-call steps"
        except Exception as exc:
            artifact.error_log = f"Executor failed: {type(exc).__name__}: {exc}"

        if not artifact.error_log:
            for command in task.verification_commands:
                emit(self.sink, state["run_id"], "command.started", worker_id,
                     task_id=task.id, command=command)
                result = run_command(root, command, tool_config=config)
                artifact.command_outputs.append(
                    {"command": command, "phase": "verifier", **result}
                )
                emit(self.sink, state["run_id"], "command.completed", worker_id,
                     task_id=task.id, command=command, exit_code=result["exit_code"])
                if result["exit_code"] != 0:
                    artifact.error_log = (
                        result["stderr"] or result["stdout"] or "Verification failed"
                    )
                    break

        success = artifact.error_log is None
        emit(self.sink, state["run_id"],
             "task.completed" if success else "task.failed", worker_id,
             task_id=task.id, attempt=task.attempts,
             error=artifact.error_log or "")
        result = TaskResult(
            task_id=task.id,
            success=success,
            artifact=artifact,
            attempt=task.attempts,
            worker_id=worker_id,
        )
        return {"worker_results": {task.id: result}}

