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
- Multi-conversation chat history.
- Agent mode with long-running, resumable tasks with automatic checkpoints every 500 model turns / 2,000 tool calls, project creation, file read/write, static preview, and a limited, confirmation-gated command allowlist.
- Nineteen built-in Agent Skills covering planning, visual-reference research, UX, frontend/backend development, accessibility, API/MCP integration, browser testing, debugging, performance, security, code review, web research, and release management.
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

The 19 built-in skills are stored in `skills/<skill-name>/SKILL.md` and are available immediately. Open **Agent tools → Agent skills → Upload skill** to add a personal skill. Custom uploads are stored under `user_skills/`, which is ignored by Git so private skills are not accidentally committed.

A skill is reusable instructions, not model fine-tuning. Agent mode loads relevant skill instructions during a task.

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
- The local proxy never saves or logs provider request bodies or credentials. It restricts outbound provider URLs to HTTPS and blocks private-network targets.
- Project tools operate only inside `projects/<project-id>/` and reject traversal, symbolic links, and secret/private-key files.
- Approved project commands execute on the user's computer. The allowlist and confirmation dialog are safeguards, not an OS-level sandbox.
- GitHub and remote MCP write actions are off by default. Only grant narrow permissions and approve actions you understand.
- The generic remote MCP connector supports HTTPS Streamable HTTP with optional Bearer authentication; OAuth and local stdio processes are not supported.
- Uploaded files are stored locally and are not executed by the upload feature.

## Known limitations

- Agent mode streams responses when the selected provider supports OpenAI-compatible SSE; regular chat remains non-streaming.
- Provider support for tool calls and images varies. A non-vision model may reject image attachments.
- Chat attachments do not yet support PDF, Word, audio, or video files.
- Static projects can be previewed from `index.html`. The workspace can also start supported Vite, Next.js, FastAPI, and Flask development servers after explicit approval. Other runtimes are not automatically supported.
- Browser-testing skill guides testing, but this edition does not include a real browser automation engine or server-hosted computer use.
- Remote Browser / Computer Use is a planned Beta panel only; no browser session is currently running on a server.
- Free-model discovery is conservative. Providers that do not disclose free pricing may return an empty model list rather than showing unverified paid models.
- API provider feature support varies by model and account quota.

## Project files

- `index.html` — interface and embedded application script.
- `app.js` — editable source of the embedded application script; keep both copies synchronized.
- `styles.css` — visual system and layout.
- `server.py` — local server, provider proxy, skill manager, attachments, downloads, project memory/runtime controls, GitHub MCP, and remote MCP transport.
- `skills/` — built-in agent skills.
- `user_skills/` — imported personal skills (ignored by Git).
- `projects/` — agent-created projects and chat uploads.
- `tests/` — server safety and bundle consistency tests.

License: MIT
