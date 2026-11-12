import base64
import io
import re
import tempfile
import socket
import threading
import unittest
import urllib.error
import urllib.request
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


    def test_secret_directories_and_credential_files_are_blocked(self):
        for relative in (
            "secrets/config.yaml",
            ".secrets/api.json",
            ".aws/credentials",
            ".ssh/id_ecdsa",
            "credentials.yaml",
            "credentials.yml",
            "service-account.json",
            "token.json",
        ):
            with self.subTest(path=relative):
                with self.assertRaises(ValueError):
                    server.safe_workspace_path("demo", relative)

    def test_project_listing_skips_secret_directories(self):
        root = server.WORKSPACE_ROOT / "demo"
        for dirname in ("secrets", ".secrets", ".aws", ".ssh"):
            folder = root / dirname
            folder.mkdir(exist_ok=True)
            (folder / "credentials").write_text("private", encoding="utf-8")
        listed = [item["path"] for item in server.list_project_files("demo")]
        self.assertFalse(any(path.startswith(("secrets/", ".secrets/", ".aws/", ".ssh/")) for path in listed))

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

    def test_filename_search_finds_only_visible_workspace_files(self):
        root = server.WORKSPACE_ROOT / "demo"
        (root / "src").mkdir()
        (root / "src" / "main.py").write_text("needle = 'present'", encoding="utf-8")
        (root / ".env").write_text("needle=secret", encoding="utf-8")
        result = server.find_project_files("demo", "main")
        self.assertEqual([item["path"] for item in result], ["src/main.py"])

    def test_text_search_returns_paths_lines_and_excludes_secrets(self):
        root = server.WORKSPACE_ROOT / "demo"
        (root / "src").mkdir()
        (root / "src" / "main.py").write_text("first line\nneedle = 'visible'\nthird line", encoding="utf-8")
        (root / ".env").write_text("needle=secret", encoding="utf-8")
        result = server.search_project_text("demo", "needle")
        self.assertEqual(len(result["matches"]), 1)
        self.assertEqual(result["matches"][0]["path"], "src/main.py")
        self.assertEqual(result["matches"][0]["line"], 2)
        self.assertNotIn("secret", result["matches"][0]["text"])

    def test_python_project_script_is_allowed_but_path_escape_is_not(self):
        root = server.WORKSPACE_ROOT / "demo"
        (root / "check.py").write_text("print('ok')", encoding="utf-8")
        with patch.object(server.shutil, "which", return_value="/usr/bin/python"):
            completed = type("Completed", (), {"returncode": 0, "stdout": "ok", "stderr": ""})()
            with patch.object(server.subprocess, "run", return_value=completed) as run:
                result = server.run_project_command("demo", "python check.py")
        self.assertEqual(result["exit_code"], 0)
        run.assert_called_once()
        with self.assertRaises(ValueError):
            server.run_project_command("demo", "python ../outside.py")



class SelectedWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_roots = server.WORKSPACE_ROOTS
        self.old_registry = server.WORKSPACE_REGISTRY_FILE
        server.WORKSPACE_ROOTS = {}
        server.WORKSPACE_REGISTRY_FILE = Path(self.temp.name) / "workspace-roots.json"
        self.folder = Path(self.temp.name) / "existing-project"
        self.folder.mkdir()

    def tearDown(self):
        server.WORKSPACE_ROOTS = self.old_roots
        server.WORKSPACE_REGISTRY_FILE = self.old_registry
        self.temp.cleanup()

    def test_selected_folder_is_registered_and_persisted(self):
        selected = server.register_workspace_folder(str(self.folder))
        self.assertTrue(selected["id"].startswith("local-"))
        self.assertEqual(Path(selected["path"]), self.folder.resolve())
        self.assertEqual(server.project_dir(selected["id"]), self.folder.resolve())
        loaded = server.load_workspace_roots()
        self.assertEqual(loaded[selected["id"]]["path"], str(self.folder.resolve()))

    def test_selected_folder_allows_safe_relative_files_only(self):
        selected = server.register_workspace_folder(str(self.folder))
        (self.folder / "src").mkdir()
        (self.folder / "src" / "main.py").write_text("print('hello')", encoding="utf-8")
        _, target = server.safe_workspace_path(selected["id"], "src/main.py")
        self.assertEqual(target.read_text(encoding="utf-8"), "print('hello')")
        with self.assertRaises(ValueError):
            server.safe_workspace_path(selected["id"], "../outside.txt")
        with self.assertRaises(ValueError):
            server.safe_workspace_path(selected["id"], ".env")

    def test_selected_workspace_root_cannot_be_home_or_drive_root(self):
        with self.assertRaises(ValueError):
            server.register_workspace_folder(str(Path.home()))
        with self.assertRaises(ValueError):
            server.register_workspace_folder(str(Path(self.folder.anchor)))

    def test_duplicate_folder_selection_reuses_existing_id(self):
        first = server.register_workspace_folder(str(self.folder))
        second = server.register_workspace_folder(str(self.folder))
        self.assertEqual(first["id"], second["id"])
        self.assertTrue(second["existing"])


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
        self.assertIn("Provider does not support streaming", app)
        self.assertIn("reasoning_summary", app)
        self.assertIn("agentLiveReasoning", app)
        self.assertIn("agentLiveToolList", app)
        self.assertIn("self.handle_streaming_proxy(request)", server)
        self.assertIn("text/event-stream", server)
        self.assertIn("agent-live-reasoning", css)
        self.assertIn("agentLiveReasoning", html)
        self.assertIn("agentLivePlan", html)

    def test_long_running_agent_has_persistent_checkpoints_and_loop_guards(self):
        root = Path(__file__).resolve().parents[1]
        app = (root / "app.js").read_text(encoding="utf-8")
        self.assertIn("AGENT_MAX_TURNS_PER_RUN=500", app)
        self.assertIn("AGENT_MAX_TOOL_CALLS_PER_RUN=2000", app)
        self.assertIn("localStorage.setItem(AGENT_RESUME_KEY", app)
        self.assertIn("recoverInterruptedAgentTool", app)
        self.assertIn("repeatCount>=4", app)
        self.assertIn("recentToolOutcomes", app)
        self.assertIn("AUTOMATIC WORK LOG CHECKPOINT", app)
        self.assertIn("Resume saved task", app)
        self.assertNotIn("startStep+24", app)
        self.assertNotIn("n<startStep+24", app)
        self.assertIn("while(true){", app)
        self.assertIn("agentDeadlineReached(state)", app)
        self.assertIn("permissionWorkspaceId", app)
        self.assertIn("state.turnBudget=(", app)
        self.assertIn("state.toolBudget=(", app)
        self.assertIn("continuing autonomously", app)
        loop_start = app.index("async function runAgentLoop(state,spinner){")
        loop_end = app.index("async function send(text,attachments=[]){", loop_start)
        agent_loop = app[loop_start:loop_end]
        self.assertNotIn('pauseReason==="budget"', agent_loop)
        self.assertIn('state.turnBudget=(Number(state.turnBudget)||AGENT_MAX_TURNS_PER_RUN)+AGENT_MAX_TURNS_PER_RUN', agent_loop)
        self.assertIn('state.toolBudget=(Number(state.toolBudget)||AGENT_MAX_TOOL_CALLS_PER_RUN)+AGENT_MAX_TOOL_CALLS_PER_RUN', agent_loop)

    def test_new_workspace_tools_are_registered(self):
        root = Path(__file__).resolve().parents[1]
        app = (root / "app.js").read_text(encoding="utf-8")
        for name in (
            "workspace_create_project", "workspace_list_files", "workspace_find_files",
            "workspace_search_text", "workspace_create_directory", "workspace_move_file",
            "workspace_read_file", "workspace_write_file", "workspace_delete_file", "workspace_run_command",
            "workspace_preview", "workspace_start_project", "workspace_stop_project",
            "workspace_project_status", "workspace_read_memory", "workspace_update_memory",
            "runAgentLoop", "relevantSkillInstructions", "saveAgentResume", "continueAgentRun",
            "localStorage", "sessionStorage", "workspace_start_project", "workspace_stop_project",
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

    def test_research_api_route_is_registered_and_guarded(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / "server.py").read_text(encoding="utf-8")
        self.assertIn('"/api/research"', source)
        self.assertIn('def handle_research(self, payload):', source)
        self.assertIn('validate_research_url(final_url)', source)
        self.assertIn("MAX_RESEARCH_PAGE_BYTES", source)
        self.assertIn("class ResearchRedirectHandler", source)

    def test_research_mode_and_single_chat_delete_are_wired(self):
        root = Path(__file__).resolve().parents[1]
        app = (root / "app.js").read_text(encoding="utf-8")
        html = (root / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="researchMode"', html)
        self.assertIn('function deleteChat(chatIdToDelete)', app)
        self.assertIn('data-delete-chat=', app)
        self.assertIn('if(busy){toast("Wait for the active response to finish or stop it before deleting chats.");return}', app)
        self.assertIn('toolDef("web_search"', app)
        self.assertIn('toolDef("web_open"', app)
        self.assertIn("buildResearchSystemPrompt", app)
        self.assertIn("state.researchMode&&state.researchMode", app)
        self.assertIn('researchMode==="deep"', app)
        self.assertIn('write(KEYS.researchMode,researchMode)', app)

    def test_mcp_pagination_handshake_and_execution_errors_are_checked(self):
        root = Path(__file__).resolve().parents[1]
        app = (root / "app.js").read_text(encoding="utf-8")
        self.assertIn("result.nextCursor", app)
        self.assertIn("valid initialization response", app)
        self.assertIn("result.isError===true", app)
        self.assertIn("GitHub MCP verified", app)
        self.assertIn("Remote MCP verified", app)

    def test_index_exposes_new_controls(self):
        root = Path(__file__).resolve().parents[1]
        html = (root / "index.html").read_text(encoding="utf-8")
        for element_id in ("attachFiles", "fileInput", "skillsGrid", "skillFileInput",
                           "githubPatInput", "githubReadOnly", "connectGithubMcp",
                           "remoteMcpUrl", "remoteMcpToken", "remoteMcpReadOnly",
                           "saveRemoteMcpSettings", "connectRemoteMcp",
                           "nvidiaCatalogGrid", "researchMode", "remoteBrowserHeading", "startProjectBtn", "stopProjectBtn", "projectMemoryPreview", "projectRuntimeStatus",
                           "openWorkspaceFolderBtn", "workspaceSearchInput", "workspaceSearchBtn", "workspaceSearchResults",
                           "agentDuration", "agentPermissionMode", "agentRunClock", "agentRunUsage", "forgetWorkspaceBtn"):
            self.assertIn('id="' + element_id + '"', html)

    def test_private_workspace_registry_is_ignored_by_git(self):
        root = Path(__file__).resolve().parents[1]
        ignore = (root / ".gitignore").read_text(encoding="utf-8")
        self.assertIn(".workspace-roots.json", ignore)
        self.assertIn(".workspace-roots.json.tmp", ignore)

    def test_chat_switch_and_delete_are_blocked_during_active_response(self):
        root = Path(__file__).resolve().parents[1]
        app = (root / "app.js").read_text(encoding="utf-8")
        self.assertIn('if(busy){toast("Wait for the active response to finish or stop it before deleting chats.");return}', app)
        self.assertIn("before starting a new chat", app)
        self.assertIn("before switching chats", app)



    def test_new_chat_shortcut_is_cross_platform_and_visible_controls_are_real(self):
        root = Path(__file__).resolve().parents[1]
        app = (root / "app.js").read_text(encoding="utf-8")
        html = (root / "index.html").read_text(encoding="utf-8")
        self.assertIn('<kbd>Ctrl / ⌘ K</kbd>', html)
        self.assertIn('document.addEventListener("keydown"', app)
        self.assertIn('(!e.ctrlKey&&!e.metaKey)', app)
        self.assertIn('String(e.key).toLowerCase()!=="k"', app)
        self.assertIn('["INPUT","TEXTAREA","SELECT"].includes(tag)', app)
        self.assertIn('document.querySelector("dialog[open]")', app)
        self.assertNotIn('id="chatOptions"', html)
        self.assertNotIn('if(b.id==="chatOptions")', app)
        self.assertIn("23 built-in skills are ready", html)

class ResearchParsingTests(unittest.TestCase):
    def test_duckduckgo_parser_reads_title_and_snippet(self):
        html = (
            '<a class="result__a" href="https://example.com/story">Example result</a>'
            '<a class="result__snippet">A useful preview from the source.</a>'
        )
        parser = server.DuckDuckGoResultParser()
        parser.feed(html)
        self.assertEqual(len(parser.results), 1)
        self.assertEqual(parser.results[0]["title"], "Example result")
        self.assertIn("useful preview", parser.results[0]["snippet"])

    def test_duckduckgo_parser_keeps_results_without_snippets(self):
        parser = server.DuckDuckGoResultParser()
        parser.feed('<a class="result__a" href="https://example.com/without-snippet">Title only</a>')
        parser.close()
        self.assertEqual(len(parser.results), 1)
        self.assertEqual(parser.results[0]["snippet"], "")

    def test_research_page_parser_excludes_scripts_and_navigation(self):
        parser = server.ResearchPageParser()
        parser.feed(
            "<html><head><title>Trusted Title</title>"
            "<script>secretPrompt();</script></head><body>"
            "<nav>Navigation noise</nav><main><h1>Article</h1>"
            "<p>Readable article text.</p></main></body></html>"
        )
        extracted = " ".join(parser.text_parts)
        self.assertIn("Readable article text", extracted)
        self.assertNotIn("secretPrompt", extracted)
        self.assertNotIn("Navigation noise", extracted)

    def test_research_page_requires_supported_text_content_type(self):
        with self.assertRaisesRegex(ValueError, "supported text or HTML"):
            server.extract_research_page(b"binary", "application/pdf")

    def test_research_url_rejects_http_and_localhost_before_network_access(self):
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            server.validate_research_url("http://example.com/page")
        with self.assertRaisesRegex(ValueError, "Local and private"):
            server.validate_research_url("https://localhost/page")

    def test_research_result_unwraps_duckduckgo_https_destination(self):
        from urllib.parse import quote
        target = "https://example.com/article?id=1"
        wrapped = "https://duckduckgo.com/l/?uddg=" + quote(target, safe="")
        self.assertEqual(server.normalize_research_result_url(wrapped), target)

    def test_research_result_rejects_plain_http_destination(self):
        self.assertEqual(server.normalize_research_result_url("http://example.com/article"), "")




class PinnedHTTPSValidationTests(unittest.TestCase):
    def test_resolver_rejects_private_addresses(self):
        private_answer = [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("127.0.0.1", 443))]
        with patch("server.socket.getaddrinfo", return_value=private_answer):
            with self.assertRaisesRegex(ValueError, "non-public IP"):
                server.resolve_public_addresses("example.com", 443)

    def test_https_handler_revalidates_dns_before_opening_connection(self):
        request = server.urllib.request.Request("https://example.com/v1/chat/completions")
        private_answer = [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("10.0.0.5", 443))]
        handler = server.PinnedHTTPSHandler(context=server.ssl.create_default_context())
        with patch("server.socket.getaddrinfo", return_value=private_answer):
            with self.assertRaisesRegex(ValueError, "non-public IP"):
                handler.https_open(request)

    def test_connection_uses_only_the_validated_socket_address(self):
        address_info = (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", 443))

        class FakeSocket:
            def __init__(self):
                self.connected_to = None
                self.closed = False
            def settimeout(self, value):
                pass
            def connect(self, address):
                self.connected_to = address
            def close(self):
                self.closed = True

        class FakeTLSContext:
            verify_mode = server.ssl.CERT_REQUIRED
            check_hostname = True
            def wrap_socket(self, connection, server_hostname):
                self.server_hostname = server_hostname
                return connection

        fake_socket = FakeSocket()
        context = FakeTLSContext()
        connection = server.PinnedHTTPSConnection(
            "example.com", pinned_addresses=[address_info], context=context, timeout=3
        )
        with patch("server.socket.socket", return_value=fake_socket):
            connection.connect()
        self.assertEqual(fake_socket.connected_to, address_info[4])
        self.assertEqual(context.server_hostname, "example.com")


class PreviewIsolationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_root = server.WORKSPACE_ROOT
        server.WORKSPACE_ROOT = Path(self.temp.name)
        server.WORKSPACE_ROOT.mkdir(exist_ok=True)
        self.project = server.WORKSPACE_ROOT / "demo"
        self.project.mkdir()
        (self.project / "index.html").write_text("<h1>Isolated</h1>", encoding="utf-8")

    def tearDown(self):
        server.stop_project_preview("demo")
        server.WORKSPACE_ROOT = self.old_root
        self.temp.cleanup()

    def test_preview_rejects_traversal_and_private_files(self):
        self.assertEqual(server.safe_preview_file(self.project, "/").name, "index.html")
        with self.assertRaises(ValueError):
            server.safe_preview_file(self.project, "/../outside.txt")
        with self.assertRaises(ValueError):
            server.safe_preview_file(self.project, "/%2e%2e/outside.txt")
        with self.assertRaises(ValueError):
            server.safe_preview_file(self.project, "/.env")

    def test_preview_server_uses_a_separate_origin_and_serves_project(self):
        preview = server.start_project_preview("demo")
        self.assertNotEqual(preview["port"], server.PORT)
        with urllib.request.urlopen(preview["url"], timeout=3) as response:
            self.assertIn(b"Isolated", response.read())
            self.assertEqual(response.headers.get("X-Content-Type-Options"), "nosniff")

    def test_preview_server_does_not_serve_secret_files(self):
        (self.project / ".env").write_text("DO_NOT_SERVE=secret", encoding="utf-8")
        preview = server.start_project_preview("demo")
        with self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(preview["url"] + ".env", timeout=3)
        self.assertEqual(error.exception.code, 404)

    def test_main_app_origin_never_serves_project_html(self):
        httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{httpd.server_address[1]}/projects/demo/index.html"
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(url, timeout=3)
            self.assertEqual(error.exception.code, 404)
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)


class LocalOriginValidationTests(unittest.TestCase):
    def test_only_exact_http_app_origins_are_accepted(self):
        self.assertTrue(server.is_allowed_app_origin(f"http://127.0.0.1:{server.PORT}"))
        self.assertTrue(server.is_allowed_app_origin(f"http://localhost:{server.PORT}"))
        self.assertFalse(server.is_allowed_app_origin(f"https://127.0.0.1:{server.PORT}"))
        self.assertFalse(server.is_allowed_app_origin(f"https://localhost:{server.PORT}"))
        self.assertFalse(server.is_allowed_app_origin(f"http://127.0.0.1:{server.PORT}.evil.test"))
        self.assertFalse(server.is_allowed_app_origin(f"http://127.0.0.1:{server.PORT}/unexpected"))


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


class MCPCompatibilityDocumentationTests(unittest.TestCase):
    def test_mcp_protocol_revision_limit_is_explicit(self):
        root = Path(__file__).resolve().parents[1]
        docs = (root / "docs" / "agent-tools-and-mcp.md").read_text(encoding="utf-8")
        skill = (root / "skills" / "mcp-server-integration" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("2025-03-26", docs)
        self.assertIn("2026-07-28", docs)
        self.assertIn("has **not yet implemented or verified**", docs)
        self.assertIn("Mcp-Name", docs)
        self.assertIn("x-mcp-header", docs)
        self.assertIn("2025-11-25", skill)
        self.assertIn("Mcp-Param-*", skill)
        self.assertIn("protocol-level sessions", skill)


class AgentSkillTests(unittest.TestCase):

    def test_skills_document_has_valid_table_rows(self):
        document = (Path(server.ROOT) / "docs" / "skills.md").read_text(encoding="utf-8")
        self.assertNotIn("\\n|", document)
        self.assertIn("| `coding-mentor` |", document)
        self.assertIn("| `independent-code-review` |", document)
        self.assertIn("| `code-review-agent` |", document)
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
            "browser-visual-testing", "release-engineering", "web-research", "deep-research",
        }
        expected.update({"coding-mentor", "independent-code-review", "code-review-agent"})
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
        self.assertEqual(len(server.list_available_skills()), 23)

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
