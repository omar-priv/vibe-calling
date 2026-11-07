# Vibe Calling — Local Proxy Edition

A lightweight local AI chat workspace for OpenAI-compatible providers, including NVIDIA NIM, Gemini, OpenAI, OpenRouter, Groq, and custom HTTPS endpoints.

## Run on Windows

1. Download the repository using **Code → Download ZIP** and extract it to a new folder.
2. Double-click `start.bat`.
3. Keep the server window open while using the app.
4. Keep the black server window open; it prints the exact local URL and opens it. If port 8765 is already occupied by an older server, this copy automatically uses the next available port.
5. Open the `/__health` path on the exact URL printed in the black window to verify the correct copy is running.
6. Open **Providers → Add provider**, enter your Base URL and API key, then use **Test connection** and **Save provider**.


For NVIDIA NIM, use `https://integrate.api.nvidia.com/v1`.

## Features

- Multiple OpenAI-compatible providers and manually selected model IDs.
- Provider model discovery via the local proxy.
- Multi-conversation chat history.
- Optional model tool-calling for the built-in local tools (calculator, date/time, and notes).
- Animated click acknowledgement plus hover, keyboard-focus, loading, success, and error states.
- Reduced-motion support and responsive layout.
- No external JavaScript framework or database required.

## Files

- `index.html` — app interface and provider dialog
- `styles.css` — visual system, responsive layout, and interaction states
- `app.js` — chat, provider, and local tool logic
- `server.py` — localhost web server and HTTPS API proxy
- `start.bat` — Windows launcher
- `docs/skills-reviewed.md` — UI/UX skill references reviewed and applied
- `docs/qa-smoke-test.md` — interaction and save-flow smoke test results

## Important security note

This edition is designed for personal use on the same computer. The Python server binds only to `127.0.0.1`; do not expose it to the public internet. API keys remain in this browser's local storage and are not encrypted by the app. Do not use it in a shared browser profile.

The proxy forwards requests to HTTPS provider endpoints and blocks local/private-network targets. GitHub Pages alone cannot run this Python proxy; run the included launcher on your computer.

## Current limitations

- Chat requests are non-streaming.
- No image/file upload, voice, or built-in web search.
- Agent tools are limited to the local tools provided by this app; it does not have unrestricted computer or terminal access.
- Provider feature support varies by model.

License: MIT
