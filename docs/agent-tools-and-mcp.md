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
