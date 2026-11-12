# Agent workspace, skills, attachments, and GitHub MCP

## Agent Skills

Built-in skills are stored in `skills/<skill-name>/SKILL.md`. They are immediately available without downloads or setup. The current set is:

- project-planning
- frontend-design
- frontend-development
- backend-design
- backend-development
- browser-testing
- debugging
- code-review
- security-review
- github-management

Agent mode receives the skill catalog and can call `skill_list` and `skill_read` to load the relevant instruction files before design or implementation. The catalog now includes focused debugging, code-review, frontend-design, UX-review, web-research, and deep-research instructions. Skills are task instructions and reference material, not model fine-tuning.

### Import a custom skill

Open **Agent tools → Agent skills → Upload skill**. Accepted formats:

- One UTF-8 `.md` file with YAML frontmatter containing `name` and `description`.
- A `.zip` containing exactly one `SKILL.md` file, optionally with Markdown/text reference files.

Scripts and executable files are deliberately not accepted in skill archives. The upload is size-limited, rejects traversal and symbolic links, and is installed under `user_skills/`. This folder is ignored by Git so imported personal skills are not committed accidentally.

Example:

```markdown
---
name: research-helper
description: Research a topic using primary sources and verify claims.
---

# Research helper

1. Search official sources first.
2. Compare dates and cross-check claims.
3. State uncertainty and cite evidence.
```

The complete built-in catalog also includes visual-reference-research, UX-review, accessibility-review, performance-engineering, API integration, MCP server integration, browser visual testing, release engineering, web-research, and deep-research. See docs/skills.md for the 23-skill list and docs/skills-reviewed.md for the public references inspected when strengthening the local debugging, review, and design guidance.

## Chat attachments and generated files

The chat composer accepts up to 3 files per message, at most 2 MB per file and 4 MB total. Supported file types are common text/code formats and PNG/JPG/WEBP/GIF images. Text files are inserted into the message context; images are passed as image inputs, so the selected model must support vision. PDF, DOCX, audio, video, and archive attachments are not yet supported.

Uploaded files are stored in the active local project under `uploads/`. The agent can read supported text files and images. The agent can use `workspace_download_file` to return a file download link to the user. The download route is confined to the selected project workspace and enforces a size limit.

## Local project workspace

Agent mode can:
- Create and list projects, or open an existing folder using the native Windows folder picker.
- List, find, and search text in supported UTF-8 files.
- Read and write files, create directories, move/rename files, and delete individual files.
- Preview a static `index.html` from a separate ephemeral localhost origin.
- Run the supported command allowlist, including project scripts, linters and tests.
- Keep project memory and resumable task checkpoints.
- Run for a selected window (1, 3, 5, 8 hours, or no time cap) and show a live timer, turn count and tool count.

Agent-created projects live under `projects/<project-id>/`. A folder selected by the user is registered by a generated ID in `.workspace-roots.json`; that file contains absolute paths and is ignored by Git. The model can only address the folder selected by the user, not supply an arbitrary filesystem root. Both workspace types reject path traversal, symbolic links, `.env` and credential files, common secret directories such as `secrets/`, `.aws/`, `.ssh/`, `.kube/`, private keys, and dependency/build folders. Individual workspace text files are limited to 2 MB. File search skips ignored folders and binary files.

### Approval profiles

- **Confirm actions** (default): file edits inside the selected workspace are allowed, while delete, move/rename, project commands, and starting a development server ask for confirmation.
- **Autonomous · active folder**: after a separate warning and user consent, the agent may delete/move files and run allowlisted project commands without repeating confirmations, but only inside the exact workspace selected when that task started. The permission does not follow the agent if it creates or selects another project.
- GitHub MCP and remote MCP write actions retain their own per-call approval controls.

The Python server binds only to `127.0.0.1`. Project commands execute on the user's computer. The standard command allowlist and confirmation prompts are not an OS-level sandbox. The detached background worker persists jobs/checkpoints in SQLite and protects task payloads, checkpoints, provider keys, and final results with the current Windows user's DPAPI. Closing the browser tab does not stop an accepted background task. The worker is not installed as a Windows Service and does not survive logoff/reboot as a running process; after an interruption, review and resume the saved task. Guarded Terminal is a one-command, no-shell-chaining tool that always asks for approval and remains in the user's Windows security context. Windows Job Objects constrain process trees and memory/process counts where supported; they do not isolate files or networking. See `docs/background-agent-runtime.md` for exact limits. Browser automation and Windows Computer Use are now optional local features, not hosted services.

## What is MCP?

MCP stands for **Model Context Protocol**. It is a standard way for an AI host to connect to external tool providers. An MCP server can expose tools, resources, and prompt templates. The host discovers the tools and their input schemas, then lets the model choose a tool call. Vibe Calling validates the initialize response, reads paginated tools/list results (up to 100 tools), rejects an empty tool list, uses unique model-facing function names, and propagates tool-level isError results back to Agent mode. MCP is a connector protocol, not a model or an autonomous agent by itself.

## GitHub MCP inside Vibe Calling

Vibe Calling includes an in-app client for the official hosted GitHub MCP endpoint:

- Endpoint: `https://api.githubcopilot.com/mcp/`
- Transport: Streamable HTTP
- Toolsets requested: `repos,issues,pull_requests`
- Read-only mode: enabled by default
- Authentication: GitHub fine-grained Personal Access Token supplied by the user

### Connect

1. Open **Agent tools → GitHub MCP**.
2. Create a fine-grained GitHub token scoped only to the repositories you want the agent to access.
3. Paste it into the token field.
4. Leave **Read-only mode** checked and choose **Connect / Verify**.
5. After the verification message reports that tools are available, enable Agent mode in Chat and ask it to inspect one of your repositories.

The token is stored in browser local storage so the connection can persist after reload. It is not encrypted by this app. Avoid shared browser profiles; do not send the token in chat or commit it to source control.

### Write access

Read-only mode sends the server's read-only header and blocks non-read-only tools in the Vibe Calling client. To allow GitHub write operations:

1. Make sure the fine-grained token has only the specific write permissions you need.
2. Turn off read-only mode and save settings.
3. Reconnect GitHub so the remote service receives the updated mode.
4. Confirm each write-capable GitHub tool call individually.

A GitHub MCP server can expose many capabilities. Vibe Calling currently limits tool schemas passed to the model and does not expose every GitHub toolset.

### Existing VS Code-compatible configuration

The repository also keeps `.vscode/mcp.json` as an optional, read-only configuration for external MCP-compatible hosts. This is separate from the in-app MCP client.

**Never paste a GitHub token into a source file, issue, chat transcript, or commit.** If a token is exposed, revoke it and create a replacement.

## Local Browser Automation and Windows Computer Use

Both features are optional and disabled by default. Install them with `install-automation.bat`; this installs Playwright, Chromium, and pywinauto. Browser Automation uses a dedicated Vibe Calling profile and public HTTP/HTTPS URLs only. It does not reuse Chrome/Edge cookies. Navigation requests are checked to block local/private destinations; page clicks, form entry, key presses, and closing the session require approval. Windows Computer Use uses the UI Automation backend first and can inspect visible windows and accessible controls. Every click, text entry, and key combination requires approval. Desktop automation requires the user's Windows session to remain logged in, unlocked, and awake. These tools act on real applications and websites, not a virtual desktop.

## Web Research and Deep Research

The chat composer contains a Research selector with three modes:

- **Off**: normal chat or Agent behavior is unchanged.
- **Web Research**: quick lookup. The model normally performs one focused search (up to five results) and opens the best one or two sources when details need verification. Use this for straightforward questions and current news.
- **Deep Research**: a multi-stage investigation. The model breaks the question into sub-questions, runs at least three distinct searches, opens at least four useful sources when accessible, prioritizes primary sources, cross-checks independent evidence, separates publication dates from event dates, and synthesizes a cited report.

Both research modes use the selected provider/model and the same local agent streaming/runtime loop. Research mode exposes only the dedicated web_search and web_open tools; project editing and MCP tools are not offered in that session. Answers can cite sources using Markdown HTTPS links, which open in a new browser tab.

### Search backend and boundaries

The local Python server queries DuckDuckGo's public HTML search page; no paid search API key is required. Search may be rate-limited, blocked, incomplete, or temporarily unavailable. Search snippets are leads, not evidence: the model should open useful results before relying on detailed claims. Deep Research consumes more provider tokens and requests than Web Research; the model's context window, provider quota, and rate limits still apply.

The local research reader accepts HTTPS URLs only, resolves hosts before connecting, rejects localhost/private/non-public IPs, validates redirects, limits page reads to 1 MB, and extracts text rather than executing page scripts. It supports HTML and common text/JSON/XML content types. It is not a full browser: JavaScript-only pages, paywalls, CAPTCHAs, and some anti-bot responses may not provide readable content. The research engine must disclose missing sources and must never invent citations or dates. Page content is untrusted data, not instructions.

## References

- [MCP architecture](https://modelcontextprotocol.io/docs/learn/architecture)
- [GitHub MCP remote server](https://github.com/github/github-mcp-server/blob/main/docs/remote-server.md)
- [GitHub MCP server configuration](https://github.com/github/github-mcp-server/blob/main/docs/server-configuration.md)

## Connect another remote MCP server

The **Connect another MCP server** panel supports remote MCP servers using **Streamable HTTP over HTTPS**. It is separate from the GitHub MCP integration above.

1. Copy the server's Streamable HTTP endpoint URL from its official setup page.
2. Enter a connection name and the full HTTPS endpoint URL in **Agent tools**.
3. Paste a bearer token only when the MCP provider requires it. OAuth sign-in, custom authentication headers, and local `stdio` processes are not supported by this connector.
4. Keep **Read-only mode** enabled and click **Connect MCP**.
5. Enable Agent mode in Chat. The remote server's discovered tools will be offered to the model.

The remote URL is validated for HTTPS and public network addressing. Localhost and private-network destinations are blocked. The server receives requests and the bearer token, so connect only servers you trust. The token is stored in this browser's local storage without encryption. Do not use a shared browser profile.

Read-only mode blocks tools not explicitly marked `readOnlyHint: true`. Because MCP annotations are advisory and supplied by the remote server, every remote `tools/call` still requires a per-call confirmation, even when a tool is labeled read-only. When write mode is enabled, every call also requires confirmation. A remote server may not enforce Vibe Calling's UI policy itself, so keep server permissions and token scopes narrow.

This connector targets **remote Streamable HTTP**. A local MCP server that requires `stdio` must be launched and supervised by a local process manager; entering its command into this URL field will not work. Remote Browser / Computer Use remains a separate planned Beta feature.

### Protocol revision compatibility

The current in-app GitHub and remote MCP clients initialize with protocol version `2025-03-26` and preserve an optional `Mcp-Session-Id` returned by the server. This is the earlier Streamable HTTP revision.

The official MCP specification revision `2026-07-28` changes the transport contract: it removes protocol-level sessions and requires per-request protocol metadata, including `MCP-Protocol-Version`, `Mcp-Method`, and (for applicable methods) `Mcp-Name`. It also defines schema-driven `x-mcp-header` parameters that clients must validate and forward as `Mcp-Param-*` headers. Vibe Calling has **not yet implemented or verified** that newer request profile. A server advertising “Streamable HTTP” is therefore not, by itself, proof of compatibility; use a server that accepts the `2025-03-26` revision with this build.

References: [MCP Streamable HTTP specification, 2026-07-28](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2026-07-28/basic/transports/streamable-http.mdx) · [GitHub MCP Streamable HTTP server notes](https://github.com/github/github-mcp-server/blob/main/docs/streamable-http.md).



## Agent execution, long-running tasks, continuation, project runtime, and memory

Agent mode preloads up to four relevant built-in skills for the current request, allowing design, UX, and frontend implementation guidance to be combined when needed. Skill IDs are instructions, not function calls: the agent reads them with skill_read({id}). If a model mistakenly emits a built-in skill ID as a tool name, the client resolves it by reading that skill instead of treating it as an unknown tool.

Long-running tasks are no longer stopped after 24 model turns. The Agent automatically saves a checkpoint every 500 model turns and every 2,000 tool calls, then extends its working budget and continues without asking the user to press Continue. These are rolling checkpoint intervals, not a total task limit or a claim of completion. The Agent still pauses for a detected tool loop, repeated empty model responses, a real provider/local error, Stop, or a task-specific safety blocker. The saved checkpoint lets the user resume after those interruptions.

Background Agent checkpoints are stored in the local SQLite runtime database rather than browser localStorage. The worker saves history after model responses, before executing each tool, and after tool results. If the worker restarts while a tool is running, that tool is marked as outcome-unknown and is never automatically replayed. Resume adds an explicit note to the model history telling the agent to inspect the current project or application state first. This avoids duplicate file writes, commands, or desktop/browser actions.

A loop guard pauses the task when an identical tool call (same tool, inputs, and output) appears at least four times within the last 12 tool calls, including alternating tool cycles. Repeated empty model responses also pause the run. Older conversation/tool history is periodically compacted into a factual work-log checkpoint to control context and browser storage growth; the agent is instructed to re-open files and verify state instead of trusting compacted details as current truth.

Stopping a background task sets a durable cancellation request; the worker stops at the next safe checkpoint. Completed project changes remain saved. A provider configuration is copied into the worker job and its API key is DPAPI-protected for the current Windows account. The detached process can continue when the browser tab or local UI server closes, provided Windows remains powered on and the user's session stays active. It is not automatically restarted after logoff, shutdown, or reboot. Queued and interrupted jobs remain in the local database and can be resumed from Agent tools.

Each project can store a small JSON memory file at .vibe/memory.json. This folder is hidden from normal project file listings and is not exposed to ordinary workspace read/write tools. The memory contains the goal, summary, stack, decisions, completed work, and next steps. Use workspace_read_memory and workspace_update_memory to maintain it across separate conversations and sessions on the same local workspace.

### Running a project

The workspace can start supported project development servers after a user confirmation:

- Vite projects using an npm `dev` or `start` script.
- Next.js projects using an npm `dev` or `start` script.
- Python FastAPI projects with a conventional `app` object, using Uvicorn.
- Python Flask projects using the Flask CLI.

The server binds to `127.0.0.1` on a dynamically selected port. Readiness is confirmed by an actual TCP connection before a start operation reports success. The Agent tools workspace panel can display the project runtime and memory, and provides Start app / Stop app controls. The server tracks child process groups so stopping a project also stops its development-server subprocesses. Projects with unrecognized Python or Node entry points are not reported as ready; add a static `index.html` for static preview or use a supported development server.

Build/test/package installation commands remain allowlisted and require explicit per-command approval. `python -m pip install -r requirements.txt` is supported only when that file exists in the selected project. A command with a non-zero exit code is returned to the model as a failed tool result, not as a successful tool call.


## Live Agent activity and provider streaming

Agent mode requests OpenAI-compatible chat completions with `stream: true`. The local proxy relays Server-Sent Events incrementally instead of buffering the full model response. The client renders text as it arrives, accumulates streamed tool-call deltas, and displays actual tool starts/results in a live execution log.

If the provider emits explicit reasoning-summary fields in streaming deltas (for example `reasoning_content`, `reasoning`, or `reasoning_summary` as text), Vibe Calling displays them in a separate **Model reasoning summary** panel. It does not infer or reveal private hidden chain-of-thought. Providers that do not expose such a field still show streamed assistant commentary/plans when supplied, plus real tool execution updates.

If the provider does not return SSE, the client accepts a normal JSON completion as a compatibility fallback. Non-Agent chat behavior remains unchanged. Streaming depends on the selected provider supporting OpenAI-compatible streaming; if unsupported, the provider may return an error or a non-streaming response.
