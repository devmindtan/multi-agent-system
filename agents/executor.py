"""Tool-calling implementation agent."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from agents.base import BaseAgent
from core.config import load_tool_config
from core.state import AgentGraphState, ExecutionArtifact
from tools.bash_tools import run_command
from tools.fs_tools import list_files, patch_file, read_file, write_file


EXECUTOR_PROMPT = """You are an expert Software Engineer implementing one subtask.
Focus only on the current subtask. Read existing files before editing. Use the
provided tools for every filesystem change and command. Keep changes minimal and
idiomatic. Do not merely describe a change: perform it. Run the verification command
when useful, then respond with a brief completion summary.
"""


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
    def __call__(self, state: AgentGraphState) -> dict[str, Any]:
        task = state["plan"][state["current_task_index"]]
        task.status = "in_progress"
        artifact = ExecutionArtifact(task_id=task.id)
        root = state["project_root"]
        config = load_tool_config()
        max_read = int(config.get("filesystem", {}).get("max_read_bytes", 1_000_000))
        ignored = config.get("filesystem", {}).get("ignored_directories", [])

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": EXECUTOR_PROMPT},
            {
                "role": "user",
                "content": (
                    f"PROJECT CONTEXT:\n{state['project_context']}\n\n"
                    f"CURRENT SUBTASK:\n{task.model_dump_json(indent=2)}\n\n"
                    f"PREVIOUS FAILURE FEEDBACK:\n{state.get('review_feedback', '')}"
                ),
            },
        ]

        def dispatch(name: str, arguments: dict[str, Any]) -> Any:
            if name == "read_file":
                return read_file(root, arguments["relative_path"], max_read)
            if name == "list_files":
                return list_files(root, arguments.get("relative_path", "."), ignored)
            if name == "run_command":
                result = run_command(root, arguments["command"], tool_config=config)
                artifact.command_outputs.append({"command": arguments["command"], **result})
                return result
            if name in {"write_file", "patch_file"}:
                relative_path = arguments["relative_path"]
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
                return result
            raise ValueError(f"Unknown tool: {name}")

        max_steps = int(state.get("settings", {}).get("system", {}).get("max_executor_steps", 20))
        try:
            for _ in range(max_steps):
                response = self.gateway.completion("executor", messages, tools=TOOL_SCHEMAS)
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

        return {"plan": state["plan"], "artifacts": [*state["artifacts"], artifact]}

