"""Repository rules and compact tree discovery."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from core.config import load_tool_config
from core.state import AgentGraphState
from tools.fs_tools import read_file


DEFAULT_CONTEXT = """No project-specific context file was found.
Follow the existing code style, make minimal scoped changes, and do not modify
generated files or secrets. Prefer deterministic tests for all behavior changes.
"""


def _tree(root: Path, ignored: set[str], max_depth: int, max_files: int) -> str:
    lines: list[str] = []
    seen = 0
    for current, directories, filenames in os.walk(root):
        current_path = Path(current)
        depth = len(current_path.relative_to(root).parts)
        directories[:] = sorted(
            name for name in directories if name not in ignored and depth < max_depth
        )
        if depth > max_depth:
            continue
        indent = "  " * depth
        if depth:
            lines.append(f"{indent}{current_path.name}/")
        for filename in sorted(filenames):
            if filename in ignored:
                continue
            lines.append(f"{indent}  {filename}")
            seen += 1
            if seen >= max_files:
                lines.append("... tree truncated ...")
                return "\n".join(lines)
    return "\n".join(lines) or "(empty repository)"


def context_loader_node(state: AgentGraphState) -> dict[str, Any]:
    root = Path(state["project_root"]).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise NotADirectoryError(str(root))
    settings = state.get("settings", {})
    system = settings.get("system", {})
    tool_config = load_tool_config()
    ignored = set(tool_config.get("filesystem", {}).get("ignored_directories", []))

    rules = DEFAULT_CONTEXT
    for filename in ("project_context.md", ".agent-rules"):
        candidate = root / filename
        if candidate.is_file():
            rules = read_file(str(root), filename)
            break
    repository_tree = _tree(
        root,
        ignored,
        int(system.get("context_max_depth", 6)),
        int(system.get("context_max_files", 500)),
    )
    return {
        "project_root": str(root),
        "project_context": f"PROJECT RULES:\n{rules}\n\nREPOSITORY TREE:\n{repository_tree}",
    }

