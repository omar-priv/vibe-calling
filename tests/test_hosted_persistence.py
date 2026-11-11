import tempfile
import unittest
from pathlib import Path

from hosted_persistence import NeonWorkspaceStore


class PersistencePathTests(unittest.TestCase):
    def test_regular_project_paths_are_allowed(self):
        self.assertEqual(NeonWorkspaceStore.validate_relative_path("src/main.py"), "src/main.py")
        self.assertEqual(NeonWorkspaceStore.validate_relative_path(".vibe/memory.json"), ".vibe/memory.json")

    def test_secret_and_traversal_paths_are_rejected(self):
        for path in ("../outside.txt", "/etc/passwd", ".env", "secrets/token.json", "id_rsa", "a/../b"):
            with self.subTest(path=path):
                with self.assertRaises(ValueError):
                    NeonWorkspaceStore.validate_relative_path(path)

    def test_custom_skill_id_must_be_valid(self):
        self.assertEqual(NeonWorkspaceStore.validate_project_id("project-1"), "project-1")
        with self.assertRaises(ValueError):
            NeonWorkspaceStore.validate_project_id("../project")

    def test_collector_excludes_dependencies_and_only_persists_memory_file(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "src").mkdir()
            (root / "src" / "app.py").write_text("print('ok')", encoding="utf-8")
            (root / "node_modules").mkdir()
            (root / "node_modules" / "dependency.js").write_text("ignored", encoding="utf-8")
            (root / ".vibe").mkdir()
            (root / ".vibe" / "memory.json").write_text("{}", encoding="utf-8")
            (root / ".vibe" / "other.txt").write_text("not persisted", encoding="utf-8")
            store = NeonWorkspaceStore("postgresql://not-used-in-this-test")
            items, total = store._collect_project_files(root)
            names = {item[0] for item in items}
            self.assertIn("src/app.py", names)
            self.assertIn(".vibe/memory.json", names)
            self.assertNotIn("node_modules/dependency.js", names)
            self.assertNotIn(".vibe/other.txt", names)
            self.assertEqual(total, len(b"print('ok')") + len(b"{}"))


if __name__ == "__main__":
    unittest.main()
