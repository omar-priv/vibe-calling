import tempfile
import unittest
from pathlib import Path

import server


class WorkspaceBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_root = server.WORKSPACE_ROOT
        server.WORKSPACE_ROOT = Path(self.temp.name)
        server.WORKSPACE_ROOT.mkdir(exist_ok=True)
        (server.WORKSPACE_ROOT / "demo").mkdir()

    def tearDown(self):
        server.WORKSPACE_ROOT = self.old_root
        self.temp.cleanup()

    def test_project_id_rejects_traversal(self):
        with self.assertRaises(ValueError):
            server.project_dir("../outside")

    def test_project_file_path_rejects_parent_traversal(self):
        with self.assertRaises(ValueError):
            server.safe_workspace_path("demo", "../outside.txt")

    def test_project_file_path_rejects_absolute_path(self):
        with self.assertRaises(ValueError):
            server.safe_workspace_path("demo", "/outside.txt")

    def test_secret_files_are_blocked(self):
        with self.assertRaises(ValueError):
            server.safe_workspace_path("demo", ".env")
        with self.assertRaises(ValueError):
            server.safe_workspace_path("demo", "certs/private.pem")

    def test_lists_project_files_but_skips_secrets_and_dependencies(self):
        root = server.WORKSPACE_ROOT / "demo"
        (root / "index.html").write_text("<h1>Hello</h1>", encoding="utf-8")
        (root / ".env").write_text("SECRET=value", encoding="utf-8")
        (root / "node_modules").mkdir()
        (root / "node_modules" / "hidden.js").write_text("ignored", encoding="utf-8")
        paths = [item["path"] for item in server.list_project_files("demo")]
        self.assertIn("index.html", paths)
        self.assertNotIn(".env", paths)
        self.assertNotIn("node_modules/hidden.js", paths)

    def test_command_runner_rejects_shell_commands(self):
        with self.assertRaises(ValueError):
            server.run_project_command("demo", "python -m pytest; whoami")

    def test_command_runner_rejects_arbitrary_python_code(self):
        with self.assertRaises(ValueError):
            server.run_project_command("demo", "python -c print(1)")


if __name__ == "__main__":
    unittest.main()
