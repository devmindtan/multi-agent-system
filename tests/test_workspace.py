from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from core.workspace import (
    create_run_workspace,
    create_task_worktree,
    finalize_workspace,
    integrate_task,
)


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


class WorkspaceTests(unittest.TestCase):
    def test_two_isolated_changes_integrate_and_apply(self) -> None:
        with tempfile.TemporaryDirectory() as project_dir, tempfile.TemporaryDirectory() as runtime_dir:
            project = Path(project_dir)
            git(project, "init")
            (project / "base.txt").write_text("base\n", encoding="utf-8")
            git(project, "add", "base.txt")
            git(project, "-c", "user.name=Test", "-c", "user.email=test@localhost",
                "commit", "-m", "base")

            workspace = create_run_workspace(str(project), runtime_dir, "run-1")
            first = Path(create_task_worktree(workspace, "a", 1))
            second = Path(create_task_worktree(workspace, "b", 1))
            (first / "a.txt").write_text("a\n", encoding="utf-8")
            (second / "b.txt").write_text("b\n", encoding="utf-8")
            integrate_task(workspace, "a", str(first), ["a.txt"])
            integrate_task(workspace, "b", str(second), ["b.txt"])
            patch = finalize_workspace(workspace, runtime_dir, "run-1", True)

            self.assertTrue(Path(patch).is_file())
            self.assertEqual((project / "a.txt").read_text(encoding="utf-8"), "a\n")
            self.assertEqual((project / "b.txt").read_text(encoding="utf-8"), "b\n")

    def test_change_outside_scope_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as project_dir, tempfile.TemporaryDirectory() as runtime_dir:
            project = Path(project_dir)
            git(project, "init")
            (project / "base.txt").write_text("base\n", encoding="utf-8")
            git(project, "add", "base.txt")
            git(project, "-c", "user.name=Test", "-c", "user.email=test@localhost",
                "commit", "-m", "base")
            workspace = create_run_workspace(str(project), runtime_dir, "run-scope")
            worker = Path(create_task_worktree(workspace, "scoped", 1))
            (worker / "forbidden.txt").write_text("no\n", encoding="utf-8")
            with self.assertRaises(PermissionError):
                integrate_task(workspace, "scoped", str(worker), ["allowed.txt"])
            finalize_workspace(workspace, runtime_dir, "run-scope", False)

    def test_empty_implementation_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as project_dir, tempfile.TemporaryDirectory() as runtime_dir:
            project = Path(project_dir)
            git(project, "init")
            (project / "base.txt").write_text("base\n", encoding="utf-8")
            git(project, "add", "base.txt")
            git(project, "-c", "user.name=Test", "-c", "user.email=test@localhost",
                "commit", "-m", "base")
            workspace = create_run_workspace(str(project), runtime_dir, "run-empty")
            worker = create_task_worktree(workspace, "empty", 1)
            with self.assertRaisesRegex(ValueError, "no scoped file changes"):
                integrate_task(workspace, "empty", worker, ["base.txt"])
            finalize_workspace(workspace, runtime_dir, "run-empty", False)


if __name__ == "__main__":
    unittest.main()
