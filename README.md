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
- Free-model-only discovery. Gemini uses a curated allowlist of free Flash models. OpenRouter models must be marked `:free` or provide zero pricing metadata. Other providers only show models where the API exposes explicit zero pricing; providers that do not expose pricing may show no models.
- Multi-conversation chat history.
- Agent mode with project creation, file read/write, static preview, and a limited, confirmation-gated command allowlist.
- Ten built-in Agent Skills (planning, frontend design/development, backend design/development, browser testing, debugging, code review, security review, and GitHub management).
- Import your own skills as a `.md` file or a `.zip` package containing one `SKILL.md`.
- Attach up to three files to a chat message (2 MB each; 4 MB total). Supported formats include common text/code files and PNG/JPG/WEBP/GIF images.
- Agent-generated project files can be returned as direct download links in chat.
- In-app GitHub MCP connection through the official hosted GitHub MCP server, with read-only mode enabled by default and confirmation before write actions.
- The chat transcript scrolls independently while the message composer remains fixed in the application layout.
- A Remote Browser / Computer Use panel is marked as planned Beta only. No remote browser service is connected in this release.

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

The core skills are stored in `skills/<skill-name>/SKILL.md` and are available immediately. Open **Agent tools → Agent skills → Upload skill** to add a personal skill. Custom uploads are stored under `user_skills/`, which is ignored by Git so private skills are not accidentally committed.

A skill is reusable instructions, not model fine-tuning. Agent mode loads relevant skill instructions during a task.

See [docs/skills.md](docs/skills.md).

## Chat attachments

The first release supports up to 3 attachments per message. Each file is limited to 2 MB and the message to 4 MB total. Text and code files are included in the model context; images are sent as image inputs and require a vision-capable model. PDF, DOCX, audio, video, and archive attachments are not supported as chat attachments yet. Skill ZIP uploads are a separate feature.

Uploads are stored in the active local project under `uploads/`. Agent-generated files can be returned with a download link using the project file tools.

## GitHub MCP

Open **Agent tools → GitHub MCP**, paste a fine-grained GitHub Personal Access Token, and click **Connect GitHub**. Keep **Read-only mode** enabled initially. This connects the Vibe Calling agent to the official hosted GitHub MCP service and loads the available tool schemas. If write access is deliberately enabled, each write-capable tool call asks for confirmation.

The PAT is stored in this browser's local storage and is not encrypted by this app. Scope it to only the repositories and permissions required. Do not paste it into the chat or commit it to the repository.

See [docs/agent-tools-and-mcp.md](docs/agent-tools-and-mcp.md).

## Important security boundaries

- The Python server binds to `127.0.0.1`; do not expose it to the public internet.
- Provider API keys and the GitHub PAT are stored in browser local storage. They persist after reloads but are not encrypted by this app. Avoid shared browser profiles.
- The local proxy never saves or logs provider request bodies or credentials. It restricts outbound provider URLs to HTTPS and blocks private-network targets.
- Project tools operate only inside `projects/<project-id>/` and reject traversal, symbolic links, and secret/private-key files.
- Approved project commands execute on the user's computer. The allowlist and confirmation dialog are safeguards, not an OS-level sandbox.
- GitHub MCP write actions are off by default. Only grant narrow permissions and approve actions you understand.
- Uploaded files are stored locally and are not executed by the upload feature.

## Known limitations

- Chat completions are non-streaming.
- Provider support for tool calls and images varies. A non-vision model may reject image attachments.
- Chat attachments do not yet support PDF, Word, audio, or video files.
- Project preview serves a static `index.html`. Dynamic frameworks that require long-running dev servers are not yet previewed automatically.
- Browser-testing skill guides testing, but this edition does not include a real browser automation engine or server-hosted computer use.
- Remote Browser / Computer Use is a planned Beta panel only; no browser session is currently running on a server.
- Free-model discovery is conservative. Providers that do not disclose free pricing may return an empty model list rather than showing unverified paid models.
- API provider feature support varies by model and account quota.

## Project files

- `index.html` — interface and embedded application script.
- `app.js` — editable source of the embedded application script; keep both copies synchronized.
- `styles.css` — visual system and layout.
- `server.py` — local server, provider proxy, skill manager, attachments, downloads, and GitHub MCP transport.
- `skills/` — built-in agent skills.
- `user_skills/` — imported personal skills (ignored by Git).
- `projects/` — agent-created projects and chat uploads.
- `tests/` — server safety and bundle consistency tests.

License: MIT
