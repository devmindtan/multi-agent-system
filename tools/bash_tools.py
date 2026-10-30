"""Shell-free command execution constrained by a configurable allowlist."""

from __future__ import annotations

import shlex
import shutil
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
    sandboxed_arguments = arguments
    if command_config.get("sandbox_with_bubblewrap", True):
        bubblewrap = shutil.which("bwrap")
        if bubblewrap:
            sandboxed_arguments = [
                bubblewrap, "--die-with-parent", "--ro-bind", "/", "/",
                "--tmpfs", "/tmp", "--bind", str(root), str(root),
                "--chdir", str(root), "--proc", "/proc", "--dev", "/dev",
                "--setenv", "HOME", "/tmp/home", "--", *arguments,
            ]
        elif command_config.get("sandbox_required", False):
            return {
                "exit_code": -1, "stdout": "",
                "stderr": "Command rejected: bubblewrap sandbox is required but unavailable",
            }
    try:
        process = subprocess.run(
            sandboxed_arguments,
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
