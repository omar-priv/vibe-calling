import base64
import io
import re
import tempfile
import unittest
from unittest.mock import patch
import zipfile
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

    def test_project_memory_roundtrip_is_hidden_from_normal_file_listing(self):
        memory = {
            "goal": "Build a small dashboard.",
            "summary": "The UI is implemented.",
            "stack": ["HTML", "CSS", "JavaScript"],
            "decisions": ["No external dependencies."],
            "completed": ["Created the first page."],
            "next_steps": ["Add validation tests."],
        }
        saved = server.write_project_memory("demo", memory)
        loaded = server.read_project_memory("demo")
        self.assertEqual(saved["goal"], memory["goal"])
        self.assertEqual(loaded["stack"], memory["stack"])
        paths = [item["path"] for item in server.list_project_files("demo")]
        self.assertNotIn(".vibe/memory.json", paths)

    def test_project_memory_rejects_invalid_field_types(self):
        with self.assertRaisesRegex(ValueError, "stack must be a list"):
            server.write_project_memory("demo", {"stack": "not-a-list"})

    def test_project_memory_rejects_corrupt_json(self):
        folder = server.WORKSPACE_ROOT / "demo" / ".vibe"
        folder.mkdir()
        (folder / "memory.json").write_text("{broken", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "corrupt"):
            server.read_project_memory("demo")

    def test_pip_requirements_command_is_allowlisted_only_when_file_exists(self):
        (server.WORKSPACE_ROOT / "demo" / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
        completed = type("Completed", (), {"returncode": 0, "stdout": "installed", "stderr": ""})()
        with patch.object(server.shutil, "which", return_value="/usr/bin/python"):
            with patch.object(server.subprocess, "run", return_value=completed) as run:
                result = server.run_project_command("demo", "python -m pip install -r requirements.txt")
        self.assertEqual(result["exit_code"], 0)
        run.assert_called_once()

    def test_project_runtime_rejects_unknown_python_entrypoint(self):
        (server.WORKSPACE_ROOT / "demo" / "main.py").write_text("print('not a web server')", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "not recognized as FastAPI or Flask"):
            server.start_project_server("demo")



class FrontendBundleTests(unittest.TestCase):
    def test_embedded_script_matches_editable_source(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / "app.js").read_text(encoding="utf-8").strip()
        html = (root / "index.html").read_text(encoding="utf-8")
        match = re.search(r"<script>\s*([\s\S]*?)\s*</script>", html)
        self.assertIsNotNone(match, "index.html must contain its self-contained app script")
        self.assertEqual(source, match.group(1).strip())

    def test_live_agent_streaming_and_activity_ui_are_present(self):
        root = Path(__file__).resolve().parents[1]
        app = (root / "app.js").read_text(encoding="utf-8")
        server = (root / "server.py").read_text(encoding="utf-8")
        html = (root / "index.html").read_text(encoding="utf-8")
        css = (root / "styles.css").read_text(encoding="utf-8")
        self.assertIn("async function apiStream", app)
        self.assertIn("reasoning_summary", app)
        self.assertIn("agentLiveReasoning", app)
        self.assertIn("agentLiveToolList", app)
        self.assertIn("self.handle_streaming_proxy(request)", server)
        self.assertIn("text/event-stream", server)
        self.assertIn("agent-live-reasoning", css)
        self.assertIn("agentLiveReasoning", html)
        self.assertIn("agentLivePlan", html)

    def test_new_workspace_tools_are_registered(self):
        root = Path(__file__).resolve().parents[1]
        app = (root / "app.js").read_text(encoding="utf-8")
        for name in (
            "workspace_create_project", "workspace_list_files", "workspace_read_file",
            "workspace_write_file", "workspace_delete_file", "workspace_run_command",
            "workspace_preview", "workspace_start_project", "workspace_stop_project",
            "workspace_project_status", "workspace_read_memory", "workspace_update_memory",
            "runAgentLoop", "relevantSkillInstructions", "saveAgentResume", "continueAgentRun",
            "sessionStorage", "workspace_start_project", "workspace_stop_project",
            "workspace_read_memory", "workspace_update_memory",
            "if(data.exit_code!==0)", "skill_list", "skill_read", "workspace_download_file",
            "upload_attachment", "read_attachment_base64", "connectGitHubMcp",
            "connectRemoteMcp", "callRemoteMcpTool", "NVIDIA_FREE_CHAT_MODELS",
        ):
            self.assertIn(name, app)

    def test_chat_upload_and_download_api_routes_exist(self):
        root = Path(__file__).resolve().parents[1]
        server_source = (root / "server.py").read_text(encoding="utf-8")
        self.assertIn('if action == "upload_attachment":', server_source)
        self.assertIn('if action == "read_attachment_base64":', server_source)
        self.assertIn('request_path.startswith("/api/download/")', server_source)
        self.assertIn('elif route == "/api/skills":', server_source)
        self.assertIn('self.handle_github_mcp(payload)', server_source)
        self.assertIn('self.handle_remote_mcp(payload)', server_source)
        self.assertIn('def validate_remote_mcp_payload(payload):', server_source)

    def test_index_exposes_new_controls(self):
        root = Path(__file__).resolve().parents[1]
        html = (root / "index.html").read_text(encoding="utf-8")
        for element_id in ("attachFiles", "fileInput", "skillsGrid", "skillFileInput",
                           "githubPatInput", "githubReadOnly", "connectGithubMcp",
                           "remoteMcpUrl", "remoteMcpToken", "remoteMcpReadOnly",
                           "saveRemoteMcpSettings", "connectRemoteMcp",
                           "nvidiaCatalogGrid", "remoteBrowserHeading", "startProjectBtn", "stopProjectBtn", "projectMemoryPreview", "projectRuntimeStatus"):
            self.assertIn('id="' + element_id + '"', html)


class RemoteMCPValidationTests(unittest.TestCase):
    def valid_message(self):
        return {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}

    def test_remote_mcp_rejects_non_https_url(self):
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            server.validate_remote_mcp_payload({
                "url": "http://example.com/mcp",
                "message": self.valid_message(),
            })

    def test_remote_mcp_rejects_localhost(self):
        with self.assertRaisesRegex(ValueError, "Local and private"):
            server.validate_remote_mcp_payload({
                "url": "https://localhost/mcp",
                "message": self.valid_message(),
            })

    def test_remote_mcp_rejects_unsupported_method_without_network_access(self):
        message = {"jsonrpc": "2.0", "id": 1, "method": "resources/read", "params": {}}
        with self.assertRaisesRegex(ValueError, "Unsupported MCP method"):
            server.validate_remote_mcp_payload({
                "url": "https://example.com/mcp",
                "message": message,
            })

    def test_remote_mcp_requires_json_rpc(self):
        with self.assertRaisesRegex(ValueError, "JSON-RPC"):
            server.validate_remote_mcp_payload({
                "url": "https://example.com/mcp",
                "message": {"method": "tools/list"},
            })


class AgentSkillTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_user_skills = server.USER_SKILLS_ROOT
        server.USER_SKILLS_ROOT = Path(self.temp.name) / "user_skills"

    def tearDown(self):
        server.USER_SKILLS_ROOT = self.old_user_skills
        self.temp.cleanup()

    def test_bundled_core_skills_are_present(self):
        skill_ids = {item["id"] for item in server.list_available_skills()}
        expected = {
            "project-planning", "frontend-design", "frontend-development",
            "backend-design", "backend-development", "browser-testing",
            "debugging", "code-review", "security-review", "github-management",
            "visual-reference-research", "ux-review", "accessibility-review",
            "performance-engineering", "api-integration", "mcp-server-integration",
            "browser-visual-testing", "release-engineering", "web-research",
        }
        self.assertTrue(expected.issubset(skill_ids))

    def test_upload_and_read_custom_markdown_skill(self):
        content = (
            "---\nname: Research Helper\ndescription: Verify information and cite reliable sources.\n---\n"
            "# Research workflow\nCheck primary sources first.\n"
        ).encode("utf-8")
        encoded = base64.b64encode(content).decode("ascii")
        result = server.install_skill_upload("research-helper.md", encoded)
        self.assertEqual(result["id"], "custom:research-helper")
        self.assertIn("primary sources", server.read_available_skill("custom:research-helper"))

    def test_all_builtin_skills_are_counted(self):
        self.assertEqual(len(server.list_available_skills()), 19)

    def test_zip_skill_rejects_parent_traversal(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("my-skill/SKILL.md",
                             "---\nname: My Skill\ndescription: A safe test skill.\n---\n")
            archive.writestr("my-skill/../outside.txt", "should not extract")
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        with self.assertRaises(ValueError):
            server.install_skill_upload("my-skill.zip", encoded)

if __name__ == "__main__":
    unittest.main()
