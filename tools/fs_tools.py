"""File operations restricted to a single project root."""

from __future__ import annotations

import os
from pathlib import Path


def _safe_path(project_root: str, relative_path: str) -> Path:
    root = Path(project_root).resolve(strict=True)
    candidate = (root / relative_path).resolve(strict=False)
    try:
        common = Path(os.path.commonpath((str(root), str(candidate))))
    except ValueError as exc:
        raise PermissionError("Access outside project root is forbidden") from exc
    if common != root:
        raise PermissionError("Access outside project root is forbidden")
    return candidate


def read_file(project_root: str, relative_path: str, max_bytes: int = 1_000_000) -> str:
    path = _safe_path(project_root, relative_path)
    if not path.is_file():
        raise FileNotFoundError(f"File not found: {relative_path}")
    if path.stat().st_size > max_bytes:
        raise ValueError(f"File exceeds {max_bytes} byte read limit: {relative_path}")
    return path.read_text(encoding="utf-8")


def write_file(project_root: str, relative_path: str, content: str) -> str:
    path = _safe_path(project_root, relative_path)
    existed = path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    action = "updated" if existed else "created"
    return f"Successfully {action} {relative_path} ({len(content)} characters)"


def patch_file(project_root: str, relative_path: str, old_text: str, new_text: str) -> str:
    content = read_file(project_root, relative_path)
    occurrences = content.count(old_text)
    if occurrences != 1:
        raise ValueError(
            f"Patch requires exactly one match in {relative_path}; found {occurrences}"
        )
    updated = content.replace(old_text, new_text, 1)
    return write_file(project_root, relative_path, updated)


def list_files(
    project_root: str,
    relative_path: str = ".",
    ignored: list[str] | None = None,
    max_files: int = 500,
) -> list[str]:
    root = Path(project_root).resolve(strict=True)
    start = _safe_path(project_root, relative_path)
    if not start.is_dir():
        raise NotADirectoryError(relative_path)
    ignored_names = set(ignored or [])
    results: list[str] = []
    for current, directories, filenames in os.walk(start):
        directories[:] = sorted(name for name in directories if name not in ignored_names)
        for filename in sorted(filenames):
            results.append(str((Path(current) / filename).relative_to(root)))
            if len(results) >= max_files:
                return results
    return results

