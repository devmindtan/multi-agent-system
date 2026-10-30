"""Git worktree isolation and deterministic integration for parallel writers."""

from __future__ import annotations

import subprocess
from fnmatch import fnmatch
from pathlib import Path
from typing import Any


def _git(root: str | Path, *arguments: str, input_bytes: bytes | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(root), *arguments], input=input_bytes,
        capture_output=True, text=input_bytes is None, check=False,
    )


def is_git_repository(project_root: str) -> bool:
    result = _git(project_root, "rev-parse", "--show-toplevel")
    return result.returncode == 0 and Path(result.stdout.strip()).resolve() == Path(project_root).resolve()


def create_run_workspace(project_root: str, runtime_root: str | Path, run_id: str) -> dict[str, Any]:
    if not is_git_repository(project_root):
        return {"mode": "shared", "project_root": project_root}
    status = _git(project_root, "status", "--porcelain")
    if status.returncode != 0:
        raise RuntimeError(status.stderr.strip())
    if status.stdout.strip():
        raise RuntimeError("Git project must have a clean working tree before parallel execution")
    base = _git(project_root, "rev-parse", "HEAD")
    if base.returncode != 0:
        raise RuntimeError(base.stderr.strip())
    workspace_root = Path(runtime_root) / "workspaces" / run_id
    workspace_root.mkdir(parents=True, exist_ok=True)
    integration = workspace_root / "integration"
    result = _git(project_root, "worktree", "add", "--detach", str(integration), base.stdout.strip())
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip())
    return {
        "mode": "worktree", "project_root": project_root,
        "base_sha": base.stdout.strip(), "root": str(workspace_root),
        "integration_root": str(integration), "task_roots": {},
    }


def create_task_worktree(workspace: dict[str, Any], task_id: str, attempt: int) -> str:
    if workspace["mode"] == "shared":
        return workspace["project_root"]
    integration = workspace["integration_root"]
    head = _git(integration, "rev-parse", "HEAD")
    path = Path(workspace["root"]) / f"{task_id}-attempt-{attempt}"
    result = _git(workspace["project_root"], "worktree", "add", "--detach", str(path), head.stdout.strip())
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip())
    workspace["task_roots"][f"{task_id}:{attempt}"] = str(path)
    return str(path)


def integrate_task(
    workspace: dict[str, Any], task_id: str, task_root: str,
    allowed_scopes: list[str] | None = None, require_changes: bool = True,
) -> str | None:
    if workspace["mode"] == "shared":
        return None
    tracked = _git(task_root, "diff", "--name-only", "HEAD")
    untracked = _git(task_root, "ls-files", "--others", "--exclude-standard")
    untracked_paths = {line for line in untracked.stdout.splitlines() if line}
    generated = {
        path for path in untracked_paths
        if "__pycache__" in Path(path).parts or ".pytest_cache" in Path(path).parts
        or path.endswith((".pyc", ".pyo")) or path in {".coverage"}
    }
    for relative_path in generated:
        candidate = Path(task_root) / relative_path
        if candidate.is_file():
            candidate.unlink()
    changed = {
        line for line in tracked.stdout.splitlines() if line
    } | (untracked_paths - generated)
    if require_changes and not changed:
        raise ValueError(f"Task {task_id} produced no scoped file changes")
    scopes = allowed_scopes or []
    outside = [
        path for path in changed
        if not any(
            path == scope or fnmatch(path, scope)
            or path.startswith(scope.rstrip("*/") + "/")
            for scope in scopes
        )
    ]
    if outside:
        raise PermissionError(f"Task {task_id} changed files outside its scope: {outside}")
    add = _git(task_root, "add", "-A")
    if add.returncode != 0:
        raise RuntimeError(add.stderr.strip())
    staged = _git(task_root, "diff", "--cached", "--quiet")
    if staged.returncode == 0:
        if require_changes:
            raise ValueError(f"Task {task_id} produced no staged changes")
        return None
    commit = _git(
        task_root, "-c", "user.name=Local Multi-Agent", "-c",
        "user.email=local-agent@localhost", "commit", "-m", f"agent: {task_id}",
    )
    if commit.returncode != 0:
        raise RuntimeError(commit.stderr.strip())
    sha = _git(task_root, "rev-parse", "HEAD").stdout.strip()
    cherry_pick = _git(workspace["integration_root"], "cherry-pick", sha)
    if cherry_pick.returncode != 0:
        _git(workspace["integration_root"], "cherry-pick", "--abort")
        raise RuntimeError(f"Integration conflict for {task_id}: {cherry_pick.stderr.strip()}")
    return sha


def finalize_workspace(
    workspace: dict[str, Any], artifact_dir: str | Path, run_id: str, apply_changes: bool
) -> str | None:
    if workspace.get("mode") != "worktree":
        return None
    diff = _git(
        workspace["integration_root"], "diff", "--binary", workspace["base_sha"], "HEAD"
    )
    if diff.returncode != 0:
        raise RuntimeError(diff.stderr.strip())
    artifact_path = Path(artifact_dir) / f"{run_id}.patch"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(diff.stdout, encoding="utf-8")
    if apply_changes and diff.stdout:
        apply = _git(workspace["project_root"], "apply", "--3way", input_bytes=diff.stdout.encode())
        if apply.returncode != 0:
            error = apply.stderr.decode() if isinstance(apply.stderr, bytes) else apply.stderr
            raise RuntimeError(f"Could not apply integrated patch: {error.strip()}")
    for path in list(workspace["task_roots"].values()) + [workspace["integration_root"]]:
        _git(workspace["project_root"], "worktree", "remove", "--force", path)
    _git(workspace["project_root"], "worktree", "prune")
    return str(artifact_path)
