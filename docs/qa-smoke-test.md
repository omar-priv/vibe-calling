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


## 2026-11-07 — Static JavaScript load fix

- Removed the external `app.js` network request from the HTML page. The app bundle is embedded directly in `index.html`, so the browser no longer needs to fetch the separate JavaScript file or negotiate its MIME type.
- Kept `app.js` as a source copy; the embedded bundle was copied from it and syntax-compiled.
- Added explicit JS/CSS/HTML MIME types to the local server for browsers that still request standalone assets.
- Added a local `/__health` endpoint to report whether the server's extracted folder contains the expected project files.
- The HTML now contains no emergency-mode fallback banner and no external JavaScript script tag.


## 2026-11-07 — Failed app.js request eliminated

- Confirmed the previous page still relied on an external `<script src="./app.js">" request`; this could fail independently of the HTML page.
- Embedded the current `app.js` byte-for-byte in `index.html`. The standalone `app.js` remains as the editable source copy, but the page now has zero external JavaScript script requests.
- Added explicit JavaScript, CSS, and HTML MIME types to the Python server.
- Added `/__health` to report the local folder and the presence/size of the expected project files.
- The launcher now scans localhost ports 8765 through 878? No. It tries 8765 through 878? It tries the next 24 ports if the first is already in use, preventing a previous Vibe Calling process from making the new copy appear to be the old one.
- Verified that the inline application script syntax-compiles and matches the separate source file exactly.


## 2026-11-09 — Agent workspace and GitHub MCP

- Added local project create/list/read/write/delete/preview operations under the projects directory.
- Added an allowlisted command runner with explicit confirmation for each run.
- Added GitHub-hosted MCP configuration for MCP-compatible hosts; it is read-only by default and contains no credential value.
- Added automated tests for path traversal rejection, secret filtering, shell command rejection, embedded JavaScript parity, and tool registration.
- GitHub Actions passed Python compilation, Node JavaScript syntax checking, and the workspace unit tests on the pull request branch.
- Not yet verified in a live browser on the user's Windows machine. GitHub MCP authentication also requires the user to provide a fine-grained GitHub PAT in a compatible MCP host.
