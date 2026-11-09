# Vibe Calling — Local Proxy Edition

A lightweight local AI chat and project-building workspace for OpenAI-compatible providers, including NVIDIA NIM, Gemini, OpenAI, OpenRouter, Groq, and custom HTTPS endpoints.

## Run on Windows

1. Download the repository using **Code → Download ZIP** and extract it to a new folder.
2. Double-click `start.bat`.
3. Keep the black server window open. It prints the exact local URL and opens it in your browser. If port 8765 is occupied by an older server, this copy automatically uses the next available port.
4. To confirm the correct copy is running, append `/__health` to the exact URL printed in that black window. The page should return JSON with `"status": "ok"` and the project files.
5. Open **Providers → Add provider**, enter your Base URL and API key, then use **Test connection** and **Save provider**.

For NVIDIA NIM, use `https://integrate.api.nvidia.com/v1`.

## Features

- Agent workspace tools: create projects, list/read/write files, preview static websites, and run an allowlisted set of build/test commands.
- Agent file operations stay inside projects/<project-id>/; secrets and symbolic links are blocked. Deleting files and executing commands require user confirmation.
- GitHub MCP configuration template for MCP-compatible hosts is in .vscode/mcp.json (read-only by default). See docs/agent-tools-and-mcp.md.

- Multiple OpenAI-compatible providers and manually selected model IDs.
- Provider model discovery via the local proxy.
- Multi-conversation chat history.
- Optional model tool-calling for the built-in local tools (calculator, date/time, and notes).
- Animated click acknowledgement plus hover, keyboard-focus, loading, success, and error states.
- Reduced-motion support and responsive layout.
- No external JavaScript framework or database required.

## Files

- `index.html` — app interface, provider dialog, and embedded app bundle (the page does not need to fetch a separate JavaScript file).
- `styles.css` — visual system, responsive layout, and interaction states.
- `app.js` — editable source copy of the chat, provider, and local tool logic.
- `server.py` — localhost web server and HTTPS API proxy.
- `start.bat` — Windows launcher.
- `docs/skills-reviewed.md` — UI/UX skill references reviewed and applied.
- `docs/qa-smoke-test.md` — interaction and save-flow smoke test results.
- `docs/agent-tools-and-mcp.md` — agent workspace tools, MCP explanation, and GitHub MCP setup.

## Important security note

This edition is designed for personal use on the same computer. The Python server binds only to `127.0.0.1`; do not expose it to the public internet. API keys remain in this browser's local storage and are not encrypted by the app. Do not use it in a shared browser profile.

The proxy forwards requests to HTTPS provider endpoints and blocks local/private-network targets. GitHub Pages alone cannot run this Python proxy; run the included launcher on your computer.

Agent workspace commands execute on your computer inside the selected project folder. They are allowlisted and ask for confirmation, but they are not an OS-level sandbox. Do not approve commands or dependencies from projects you do not trust.

## Current limitations

- Chat requests are non-streaming.
- No image/file upload, voice, or built-in web search.
- Agent tools are limited to the local tools provided by this app; it does not have unrestricted computer or terminal access.
- Provider feature support varies by model.

License: MIT
