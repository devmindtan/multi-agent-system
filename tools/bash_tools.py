"""Shell-free command execution constrained by a configurable allowlist."""

from __future__ import annotations

import shlex
import subprocess
from pathlib import Path
from typing import Any

from core.config import load_tool_config


def run_command(
    project_root: str,
    command: str,
    timeout: int | None = None,
    tool_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    config = tool_config or load_tool_config()
    command_config = config.get("commands", {})
    try:
        arguments = shlex.split(command)
    except ValueError as exc:
        return {"exit_code": -1, "stdout": "", "stderr": f"Invalid command: {exc}"}
    if not arguments:
        return {"exit_code": -1, "stdout": "", "stderr": "Empty command rejected"}

    executable = Path(arguments[0]).name
    allowed = set(command_config.get("allowed_executables", []))
    if executable not in allowed:
        return {
            "exit_code": -1,
            "stdout": "",
            "stderr": f"Command rejected: executable '{executable}' is not allowed",
        }
    denied = set(command_config.get("denied_arguments", []))
    matched = denied.intersection(arguments[1:])
    if matched:
        return {
            "exit_code": -1,
            "stdout": "",
            "stderr": f"Command rejected: denied argument(s): {', '.join(sorted(matched))}",
        }

    root = Path(project_root).resolve(strict=True)
    effective_timeout = timeout or int(command_config.get("timeout_seconds", 90))
    try:
        process = subprocess.run(
            arguments,
            cwd=root,
            capture_output=True,
            text=True,
            timeout=effective_timeout,
            shell=False,
            check=False,
        )
        return {
            "exit_code": process.returncode,
            "stdout": process.stdout,
            "stderr": process.stderr,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "exit_code": -1,
            "stdout": exc.stdout or "",
            "stderr": f"Command timed out after {effective_timeout} seconds",
        }
    except OSError as exc:
        return {"exit_code": -1, "stdout": "", "stderr": str(exc)}


def run_linter(project_root: str, command: str = "ruff check .") -> dict[str, Any]:
    return run_command(project_root, command)


def run_tests(project_root: str, command: str = "pytest") -> dict[str, Any]:
    return run_command(project_root, command)
