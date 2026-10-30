from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.bash_tools import run_command
from tools.fs_tools import list_files, patch_file, read_file, write_file


class FileToolsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = self.temp.name

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_file_lifecycle(self) -> None:
        write_file(self.root, "src/example.txt", "before")
        self.assertEqual(read_file(self.root, "src/example.txt"), "before")
        patch_file(self.root, "src/example.txt", "before", "after")
        self.assertEqual(read_file(self.root, "src/example.txt"), "after")
        self.assertEqual(list_files(self.root), ["src/example.txt"])

    def test_path_traversal_is_rejected(self) -> None:
        with self.assertRaises(PermissionError):
            write_file(self.root, "../escape.txt", "no")

    def test_similar_prefix_path_is_rejected(self) -> None:
        sibling = f"{self.root}-other/file.txt"
        with self.assertRaises(PermissionError):
            read_file(self.root, sibling)


class CommandToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_allowlisted_command_runs_without_shell(self) -> None:
        result = run_command(self.temp.name, "python3 -c 'print(42)'")
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(result["stdout"].strip(), "42")

    def test_unknown_executable_is_rejected(self) -> None:
        result = run_command(self.temp.name, "sh -c 'echo unsafe'")
        self.assertEqual(result["exit_code"], -1)
        self.assertIn("not allowed", result["stderr"])


if __name__ == "__main__":
    unittest.main()

