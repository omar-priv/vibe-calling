# Vibe Calling — UI smoke test report

Date: 2026-11-07

## Automated checks completed

The current `app.js` was syntax-compiled. The page's inline diagnostic scripts were syntax-compiled. A lightweight isolated DOM/event harness then initialized the app and simulated the following interactions:

| Check | Result |
|---|---|
| App initialization reaches the ready flag | PASS |
| New conversation creates and stores a chat | PASS |
| Welcome provider action opens provider dialog | PASS |
| Providers navigation switches view | PASS |
| Settings action switches view | PASS |
| Agent tools quick toggle changes state | PASS |
| Explore / Build / Review suggestion buttons populate the composer | PASS |
| Provider Test Connection sends a local `/api/proxy` request | PASS (mock provider response) |
| Successful model discovery is retained for Save Provider | PASS |
| Save Provider persists one provider and updates the count to 1 | PASS |
| Button acknowledgement animation is wired | PASS |
| Reduced-motion CSS variant exists | PASS |
| App and stylesheet URLs match the current content hashes | PASS |
| Local server disables caching for HTML, JS, and CSS | PASS |
| Incomplete emergency UI fallback is removed | PASS |

## Not yet verified

- A real Chromium/Firefox click-through on the user's PC.
- A live request to NVIDIA NIM using the user's private API key.
- Streaming, image/file uploads, speech, or web search (not part of the current implementation).

The provider request in this smoke test used a mocked successful response. It proves the frontend event wiring and save flow in the isolated harness; it does **not** prove live provider credentials or internet connectivity.
