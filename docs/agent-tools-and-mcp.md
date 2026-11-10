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

Agent mode receives the skill catalog and can call `skill_list` and `skill_read` to load the relevant instruction files before design or implementation. Skills are task instructions and reference material, not model fine-tuning.

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

## Chat attachments and generated files

The chat composer accepts up to 3 files per message, at most 2 MB per file and 4 MB total. Supported file types are common text/code formats and PNG/JPG/WEBP/GIF images. Text files are inserted into the message context; images are passed as image inputs, so the selected model must support vision. PDF, DOCX, audio, video, and archive attachments are not yet supported.

Uploaded files are stored in the active local project under `uploads/`. The agent can read supported text files and images. The agent can use `workspace_download_file` to return a file download link to the user. The download route is confined to the selected project workspace and enforces a size limit.

## Local project workspace

Agent mode can:

- Create and list projects.
- List, read, and write UTF-8 project files.
- Preview a static `index.html`.
- Delete an individual file only after a confirmation dialog.
- Run a small command allowlist only after user approval.

Projects live under `projects/<project-id>/`. Filesystem access blocks parent traversal, absolute paths, symbolic links, secrets such as `.env`, private keys, and dependency/build folders. Individual workspace text files are limited to 2 MB.

### Execution boundary

The Python server binds only to `127.0.0.1`. Approved project scripts and commands execute on the user's computer. The command allowlist is not an OS-level sandbox. Dynamic preview servers, unrestricted terminals, and actual browser automation are not available yet.

## What is MCP?

MCP stands for **Model Context Protocol**. It is a standard way for an AI host to connect to external tool providers. An MCP server can expose tools, resources, and prompt templates. The host discovers the tools and their input schemas, then lets the model choose a tool call. MCP is a connector protocol, not a model or an autonomous agent by itself.

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
4. Leave **Read-only mode** checked and choose **Connect GitHub**.
5. Once the MCP tool list is loaded, enable Agent mode in Chat and ask it to inspect one of your repositories.

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

## Remote browser / computer use

The UI contains a clearly marked planned Beta panel for a server-hosted browser. It is not connected in this release. A real implementation needs disposable isolated browser sessions, strict network and file boundaries, resource limits, screenshots, action APIs, session expiry, and cleanup. It must not control the user's personal computer or share browser state across sessions.

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

Read-only mode allows only tools explicitly marked `readOnlyHint: true`. Other tools are blocked until read-only mode is turned off; each write-capable or unclassified tool call then needs a separate confirmation. A remote server may not enforce the Vibe Calling UI's policy itself, so keep server permissions and token scopes narrow.

This connector targets **remote Streamable HTTP**. A local MCP server that requires `stdio` must be launched and supervised by a local process manager; entering its command into this URL field will not work. Remote Browser / Computer Use remains a separate planned Beta feature.


## Agent execution, long-running tasks, continuation, project runtime, and memory

Agent mode preloads up to three relevant built-in skills for the current request. Skill IDs are instructions, not function calls: the agent reads them with skill_read({id}). If a model mistakenly emits a built-in skill ID as a tool name, the client resolves it by reading that skill instead of treating it as an unknown tool.

Long-running tasks are no longer stopped after 24 model turns. Each active run has a safety budget of 500 model turns and 2,000 tool calls. Reaching the budget creates a checkpoint, not a success result; Continue task adds another 500 turns and 2,000 tool calls. The run continues automatically between these checkpoints while the app is open.

The task checkpoint is stored in browser localStorage and survives page reloads and browser restarts in the same browser profile. If the page is closed during a tool call, that call is marked as having an unknown outcome and is not automatically replayed, because replaying a file write or command could duplicate a side effect. The agent is instructed to inspect the current project state before deciding what to do next. A saved task can be resumed from its conversation.

A loop guard pauses the task when the same tool is called three times consecutively with identical inputs and the same result. Repeated empty model responses also pause the run. Older conversation/tool history is periodically compacted into a factual work-log checkpoint to control context and browser storage growth; the agent is instructed to re-open files and verify state instead of trusting compacted details as current truth.

Stopping a run aborts the active model request. Completed project changes remain saved. A provider must still be configured in the browser to resume a task. This is not a background worker: the browser tab and local Vibe Calling server must remain running for the agent to make progress. Closing the browser pauses execution; the task can be resumed later, but it does not continue while the browser is closed.

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
