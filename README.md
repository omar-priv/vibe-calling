# Vibe Calling

A lightweight, local-first AI chat and coding-agent workspace for OpenAI-compatible providers. It uses a small Python server and a self-contained HTML/CSS/JavaScript interface.

## Run on Windows

1. Download this branch as a ZIP and extract it, or clone the repository.
2. Double-click `start.bat`.
3. Keep the server window open. Vibe Calling opens at the local URL printed by the launcher (normally `http://127.0.0.1:8765`).
4. Add a provider, enter the HTTPS Base URL and API key, test the connection, and save it.
5. Choose one of the models identified as free, then enable Agent mode when you want project tools.

No Node.js, npm, Docker, frontend build, or database is required to run the application itself. Node is only needed for some project build/test commands that an agent may run inside a project.

## Features

- Multiple OpenAI-compatible providers; provider keys and settings are saved automatically in this browser.
- Free-model-only discovery. NVIDIA NIM has a curated, newest-first catalog of 12 Free Endpoint models with documented Chat Completions examples. Gemini uses a curated Flash allowlist. OpenRouter models must be marked `:free` or provide zero pricing metadata. Other providers require explicit zero pricing metadata.
- Multi-conversation chat history with individual conversation deletion.
- Quick Web Research and Deep Research modes in the chat composer. Both use the selected model; search runs through the local DuckDuckGo HTML connector and cite opened HTTPS sources.
- Agent mode with resumable, long-running tasks, automatic checkpoints every 500 model turns / 2,000 tool calls, configurable run windows (1, 3, 5, 8 hours or no time limit), visible runtime/tool counters, project memory, and stop/resume controls.
- Open an existing local project folder through the native Windows folder picker; registered folder paths stay in a private local registry ignored by Git. The Agent can list, search, read, write, create, move, and delete supported project files inside the selected workspace.
- Twenty-three built-in Agent Skills covering planning, coding mentorship, independent/adversarial review, visual-reference research, UX, frontend/backend development, accessibility, API/MCP integration, browser testing, debugging, performance, security, code review, web research, and release management.
- Import your own skills as a `.md` file or a `.zip` package containing one `SKILL.md`.
- Attach up to three files to a chat message (2 MB each; 4 MB total). Supported formats include common text/code files and PNG/JPG/WEBP/GIF images.
- Agent-generated project files can be returned as direct download links in chat.
- In-app GitHub MCP plus configurable remote Streamable HTTP MCP connections. Read-only mode is enabled by default; write-capable or unclassified tools require per-call confirmation.
- The chat transcript scrolls independently while the message composer remains fixed in the application layout.
- A Remote Browser / Computer Use panel is marked as planned Beta only. No remote browser service is connected in this release.

## NVIDIA free chat catalog

The Providers page includes 12 curated NVIDIA NIM Free Endpoint models sorted by the catalog's latest-update order. They are included only when a programmatic Chat Completions example is documented. Specialized models such as embeddings, rerankers, and parsing endpoints are excluded from the chat selector; models marked as free but without API access are also excluded. The catalog is a snapshot and NVIDIA can change endpoint access, identifiers, quotas, or availability.

Free Endpoint access is intended for development and prototyping, not guaranteed unlimited production traffic. NVIDIA may throttle or rate-limit calls. You still need your own NVIDIA API key. Add an NVIDIA NIM provider using `https://integrate.api.nvidia.com/v1`, then test and save it.

## Free model filter

The UI intentionally hides models unless their free status can be identified. Gemini models currently recognized by the built-in allowlist include:

- `gemini-3.8-flash`
- `gemini-3.6-flash`
- `gemini-3.5-flash-lite`
- `gemini-3.1-flash-lite`
- `gemini-3-flash-preview`
- `gemini-2.5-flash`
- `gemini-2.5-flash-lite`

Gemini 3.7 Flash is not listed separately because Google documents it as deprecated and directs requests to Gemini 3.8 Flash. Free-tier quotas and availability can change; check the provider's current pricing and quota page before relying on a model.

## Skills

The 23 built-in skills are stored in `skills/<skill-name>/SKILL.md` and are available immediately. Open **Agent tools → Agent skills → Upload skill** to add a personal skill. Custom uploads are stored under `user_skills/`, which is ignored by Git so private skills are not accidentally committed.

A skill is reusable instructions, not model fine-tuning. Agent mode loads relevant skill instructions during a task. Deep Research loads the dedicated multi-source research workflow.

See [docs/skills.md](docs/skills.md).

## Chat attachments

The first release supports up to 3 attachments per message. Each file is limited to 2 MB and the message to 4 MB total. Text and code files are included in the model context; images are sent as image inputs and require a vision-capable model. PDF, DOCX, audio, video, and archive attachments are not supported as chat attachments yet. Skill ZIP uploads are a separate feature.

Uploads are stored in the active local project under `uploads/`. Agent-generated files can be returned with a download link using the project file tools.

## GitHub MCP

Open **Agent tools → GitHub MCP**, paste a fine-grained GitHub Personal Access Token, and click **Connect GitHub**. Keep **Read-only mode** enabled initially. This connects the Vibe Calling agent to the official hosted GitHub MCP service and loads the available tool schemas. If write access is deliberately enabled, each write-capable tool call asks for confirmation.

The PAT is stored in this browser's local storage and is not encrypted by this app. Scope it to only the repositories and permissions required. Do not paste it into the chat or commit it to the repository.

### Other remote MCP servers

Open **Agent tools → Connect another MCP server**. Enter a connection name and the remote MCP server's Streamable HTTP HTTPS endpoint. Add a bearer token only if required by that server, leave read-only mode enabled, save, and connect. Then enable Agent mode in Chat. Local `stdio` servers, OAuth sign-in, and custom authentication headers are not supported by this connector. Tokens are stored in browser local storage without encryption.

See [docs/agent-tools-and-mcp.md](docs/agent-tools-and-mcp.md) for the setup and security details.

## Important security boundaries

- The Python server binds to `127.0.0.1`; do not expose it to the public internet.
- Provider API keys, the GitHub PAT, and remote MCP bearer tokens are stored in browser local storage. They persist after reloads but are not encrypted by this app. Avoid shared browser profiles.
- The local proxy never saves or logs provider request bodies or credentials. It restricts outbound requests to HTTPS and pins each validated public IP at connection time to prevent DNS-rebinding SSRF. Outbound HTTPS deliberately bypasses system proxy environment variables; proxy-only networks are not supported in this build.
- Workspace tools operate only inside an agent-created project or a folder explicitly selected through the native folder picker. They reject path traversal, symbolic links, common secret directories (`secrets`, `.aws`, `.ssh`, `.kube`, and similar), credential files, and private keys. Selected folder paths are stored in `.workspace-roots.json`, which is ignored by Git. Static project previews run on a separate ephemeral localhost port (a separate browser origin), so project JavaScript cannot read Vibe Calling's localStorage. Preview still executes the project's own code; preview only projects you trust.
- Approved project commands execute on the user's computer. Confirm mode asks before command execution, deletion, file moves, and starting project servers. Trusted mode can skip those repeated prompts only for the workspace that was selected when the task began; it does not sandbox executed code. The allowlist and confirmation dialog are safeguards, not an OS-level sandbox. Static preview isolates the browser origin only; it is not a process/container sandbox and does not make hostile project code safe to run.
- GitHub and remote MCP write actions are off by default. Remote MCP tool calls require per-call confirmation even when the remote server labels a tool read-only, because that annotation is advisory. Only grant narrow permissions and approve actions you understand.
- The generic remote MCP connector supports HTTPS Streamable HTTP with optional Bearer authentication; OAuth and local stdio processes are not supported.
- Uploaded files are stored locally and are not executed by the upload feature.

## Known limitations

- Agent mode streams responses when the selected provider supports OpenAI-compatible SSE; regular chat remains non-streaming.
- Provider support for tool calls and images varies. A non-vision model may reject image attachments.
- Chat attachments do not yet support PDF, Word, audio, or video files.
- Static projects can be previewed from `index.html`. The workspace can also start supported Vite, Next.js, FastAPI, and Flask development servers. Other runtimes are not automatically detected.
- Free-model discovery is conservative. Providers that do not disclose free pricing may return an empty model list rather than showing unverified paid models.
- API provider feature support varies by model and account quota.
- **Sandboxed terminal execution is disabled.** The current code does not establish a Windows AppContainer/restricted token or enforce filesystem/network isolation. The separate `workspace_run_command` tool is allowlisted and confirmation-gated, but it runs under the signed-in Windows user's normal permissions and is not a sandbox.
- Computer use (pywinauto) requires the logged-in user's interactive desktop session; it does not support secure-desktop/UAC prompts or elevated applications unless specifically tested.

## Deployment editions

### Local Windows edition
The default edition remains local-first. On Windows, extract the repository and run start.bat. It uses Python 3 and does not require Node.js, npm, or Docker. The local server binds only to 127.0.0.1 and keeps local project preview/runtime behavior.

### Free Hosted edition
A separate private hosted launcher is provided in hosted_server.py. It is designed for Render Free plus Neon Free Postgres, with project files and imported skills persisted in the database. It does not replace or modify server.py or start.bat. Because free hosts sleep and have quota limits, the service is not always-on. Hosted project execution and preview are disabled until a properly isolated runtime is available. See HOSTING.md for free setup, quotas, limits, and security boundaries.

### Windows Agent Runtime v2 (local Windows edition)
The local edition includes a separate Windows worker process and local Browser/Computer adapters. The worker persists queued tasks and executes tool calls already stored in a task checkpoint. **It does not yet own the LLM conversation loop or generate further model turns by itself.** The interactive Agent model loop still runs in the browser tab; closing that tab pauses model-driven reasoning, even though a separately queued worker process can remain alive and finish the tool calls already placed in its queue.

- **Windows Background Worker** — Python module `worker.worker`, launched in the signed-in user's interactive session. SQLite task queue (WAL), leases, checkpoints, recovery, stop/resume/cancel, event logs, and install/start/stop/uninstall scripts under `install/`. Startup and recovery still require a real Windows 10/11 smoke test.
- **Local Browser Automation** — Playwright Chromium: tabs, navigation, DOM inspection, click/type/scroll, screenshots, and bounded upload/download. Uses a Vibe Calling profile by default; using a supplied profile is opt-in. Browser actions run on a dedicated adapter thread; file upload/download ask for confirmation.
- **Local Computer Use** — pywinauto UI Automation: inspect windows/elements, click/type, screenshots, hotkeys, and emergency stop. Runs only in the signed-in interactive desktop session. Desktop click/type/hotkey actions ask for confirmation; secure desktop/UAC and elevated applications are not supported unless separately verified.
- **Sandboxed terminal** — disabled in this build. The existing code does not yet enforce AppContainer/restricted-token, filesystem, or network isolation. Do not treat workspace path validation or process cleanup as a security boundary. The separate workspace command runner is allowlisted and asks for approval, but executes with the user's normal Windows permissions.
- **Remote Browser / Computer Use** — still a planned Beta feature; no hosted remote-browser service is connected.

The API exposes `/api/worker/execute` for local adapter actions and `/api/capabilities` for availability reporting. The Hosted edition remains separate and cannot invoke local worker or desktop/browser APIs.

## Project files

- `index.html` — interface and embedded application script.
- `app.js` — editable source of the embedded application script; keep both copies synchronized.
- `styles.css` — visual system and layout.
- `server.py` — local server, provider proxy, skill manager, attachments, downloads, project memory/runtime controls, GitHub MCP, and remote MCP transport.
- `skills/` — built-in agent skills.
- `user_skills/` — imported personal skills (ignored by Git).
- `projects/` — agent-created projects and chat uploads.
- `tests/` — server safety, bundle consistency, worker recovery, sandbox security, and adapter integration tests.
- `worker/` — background worker (task state machine, SQLite task store, execution loop).
- `adapters/` — local Browser/Computer adapters and a disabled sandbox placeholder.
- `api/` — worker/task management API bridging the worker to server.py and the UI.
- `install/` — Windows installer and control scripts (install.bat, start-worker.bat, stop-worker.bat, uninstall.bat, requirements-windows.txt).

License: MIT
