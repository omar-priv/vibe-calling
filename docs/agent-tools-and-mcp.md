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


## Agent execution, continuation, project runtime, and memory

Agent mode now preloads up to three relevant built-in skills for the current request. Skill IDs are instructions, not function calls: the agent reads them with `skill_read({id})`. If a model mistakenly emits a built-in skill ID as a tool name, the client resolves it by reading that skill instead of treating it as an unknown tool.

The agent has a bounded 24-step tool cycle. When the cycle ends without a final answer, or the provider/network request fails after the task context is created, the application preserves the conversation history, provider/model selection, tool results, and next step in the current browser session. A **Continue task** action resumes that state. The **Stop** control aborts the current request; completed project file changes remain saved. A provider must still be configured in the browser to resume a task.

Each project can store a small JSON memory file at `.vibe/memory.json`. This folder is hidden from normal project file listings and is not exposed to ordinary workspace read/write tools. The memory contains the goal, summary, stack, decisions, completed work, and next steps. Use `workspace_read_memory` and `workspace_update_memory` to maintain it across separate conversations and sessions on the same local workspace.

### Running a project

The workspace can start supported project development servers after a user confirmation:

- Vite projects using an npm `dev` or `start` script.
- Next.js projects using an npm `dev` or `start` script.
- Python FastAPI projects with a conventional `app` object, using Uvicorn.
- Python Flask projects using the Flask CLI.

The server binds to `127.0.0.1` on a dynamically selected port. Readiness is confirmed by an actual TCP connection before a start operation reports success. The Agent tools workspace panel can display the project runtime and memory, and provides Start app / Stop app controls. The server tracks child process groups so stopping a project also stops its development-server subprocesses. Projects with unrecognized Python or Node entry points are not reported as ready; add a static `index.html` for static preview or use a supported development server.

Build/test/package installation commands remain allowlisted and require explicit per-command approval. `python -m pip install -r requirements.txt` is supported only when that file exists in the selected project. A command with a non-zero exit code is returned to the model as a failed tool result, not as a successful tool call.
