# Vibe Calling — Local Proxy Edition

A lightweight local AI chat workspace for OpenAI-compatible providers, including NVIDIA NIM, Gemini, OpenAI, OpenRouter, Groq, and custom HTTPS endpoints.

## Run on Windows

1. Download the repository using **Code → Download ZIP** and extract it.
2. Double-click `start.bat`.
3. Keep the server window open while using the app.
4. Open `http://127.0.0.1:8765` if the browser does not open automatically.
5. Add your provider URL and API key in the Providers section.

For NVIDIA NIM, use `https://integrate.api.nvidia.com/v1`.

## Files

- `index.html` — app interface
- `styles.css` — styling
- `app.js` — chat and provider logic
- `server.py` — local proxy and static server
- `start.bat` — Windows launcher

## Important security note

This edition is designed for personal use on the same computer. The Python server binds only to `127.0.0.1`; do not expose it to the public internet. API keys remain in the browser's local storage and are not encrypted by the app. Do not use a shared browser profile.

The proxy forwards requests to HTTPS provider endpoints and blocks local/private-network targets. GitHub Pages alone cannot run this Python proxy; run the included launcher on your computer.

## Current limitations

- Non-streaming chat requests.
- No image/file upload, voice, or web search.
- Agent tools are limited to the local tools provided by the app.
- Provider feature support varies by model.

License: MIT
