# Agent workspace and MCP

## What changed in Vibe Calling

Agent mode now has local project tools. The agent can:

- Create and list project folders.
- List project files and read UTF-8 text files.
- Create or replace project files and parent folders.
- Return a local preview URL when the project contains index.html.
- Delete individual files only after a confirmation dialog.
- Run a limited set of build/test commands only after a confirmation dialog.

All agent-managed projects live under projects/<project-id>/. File tools reject paths that try to leave the project, symbolic links, secret files such as .env, and private-key formats. Individual workspace files are limited to 2 MB. Dependency/build folders are omitted from file listings.

### Important execution boundary

This is a local-first personal tool, not a virtual machine or operating-system sandbox. Approved commands and project scripts execute on the user's computer. The current allowlist is deliberately small:

- npm install or npm ci
- npm run build, npm run test, or npm run lint
- npx playwright test
- python -m compileall, python -m pytest, or python -m unittest
- Read-only git status, git diff, and git log --oneline -5/-10

Long-running development servers are not launched as background processes yet. The current preview button serves a static project's index.html through Vibe Calling's local server. Dynamic frameworks that need npm run dev require a managed preview runner in a later phase. If Node/npm is not installed, the project can still generate static HTML/CSS/JS, but npm-based build commands will report that the executable is missing.

## MCP explained

MCP means **Model Context Protocol**. Think of it as a standard connector between an AI application (the host/client) and external tool providers (MCP servers).

Instead of hard-coding a separate integration for every service, the AI application can connect to an MCP server and discover the capabilities it exposes:

- **Tools:** actions the agent can invoke, such as reading a repository file or creating an issue.
- **Resources:** information the server exposes for the model/application to read.
- **Prompts:** reusable task templates or workflows.

The normal flow is:

1. The host connects to an MCP server.
2. It discovers available tools and their input schemas.
3. The model chooses a tool and produces structured arguments.
4. The host sends the tool call to the MCP server.
5. The server returns a result, which the model uses to continue the task.

MCP is not itself an AI model and does not magically make an agent autonomous. The host still decides which servers/tools are enabled, how secrets are stored, and which actions need user approval.

## GitHub MCP configuration

This repository includes .vscode/mcp.json for the official hosted GitHub MCP server:

- Server URL: https://api.githubcopilot.com/mcp/
- Transport: Streamable HTTP.
- Enabled toolsets: repositories, issues, and pull requests.
- Default safety: read-only mode.
- Authentication: asks the compatible host for a GitHub Personal Access Token; no token is stored in this repository.

### Connect it in an MCP-compatible host

1. Open this repository as a workspace in a host that supports remote MCP servers and the VS Code .vscode/mcp.json format.
2. When prompted, provide a fine-grained GitHub PAT scoped only to the repository/repositories you want the agent to access.
3. Start/enable the github MCP server in the host's MCP tools panel.
4. Confirm that the GitHub tools load. The committed config includes X-MCP-Readonly: true so it can inspect repositories, issues, and pull requests but cannot modify them.
5. Only when you deliberately need write access, edit the config to remove the read-only header and grant the PAT the narrow write permissions needed for the task. Do not use a broad classic token unless necessary.

**Never paste a GitHub token into a source file, issue, chat transcript, or commit.** If a token is ever exposed, revoke it and create a replacement.

### Is GitHub MCP already connected inside Vibe Calling?

Not yet. The committed .vscode/mcp.json is for MCP-compatible host applications that read this config. Vibe Calling's built-in agent currently uses its own native local workspace tools; it does not yet load arbitrary MCP servers dynamically. A future MCP client layer can connect remote MCP servers directly from Vibe Calling without changing the workspace tools.

## Useful official references

- [MCP architecture](https://modelcontextprotocol.io/docs/learn/architecture)
- [MCP specification](https://modelcontextprotocol.io/specification/2025-11-25)
- [GitHub MCP remote server](https://github.com/github/github-mcp-server/blob/main/docs/remote-server.md)
- [GitHub MCP configuration guide](https://github.com/github/github-mcp-server/blob/main/docs/server-configuration.md)
- [GitHub MCP setup for Codex](https://github.com/github/github-mcp-server/blob/main/docs/installation-guides/install-codex.md)
