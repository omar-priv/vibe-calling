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


## 2026-11-10 — Agent reliability work (automated scope)

The reliability branch adds:
- Skill preloading based on the user's request and a compatibility fallback when the model mistakenly calls a skill ID as a tool.
- A 24-step Agent tool cycle with progress, Stop, and resumable Continue task state held in the browser session.
- Differentiated provider timeout/network, local workspace timeout/filesystem, validation, and unexpected error responses.
- Project memory stored under hidden `.vibe/memory.json`, with validation and atomic updates.
- Supported project runtime start/status/stop operations for Vite, Next.js, FastAPI, and Flask, including readiness probing and process-tree shutdown.
- Command failure propagation so non-zero exit codes reach the model as tool failures.

Automated Python/Node checks and browser interactions must be reported from the actual CI run. This repository update has not been tested in the user's local Windows environment or with their NVIDIA API key. The local-only server is still bound to `127.0.0.1`; public hosting is not part of this reliability test.


## Live Agent activity smoke test

1. Select an OpenAI-compatible provider/model that supports streaming and enable Agent Mode.
2. Ask the agent to inspect a project, make a small change, and run a test.
3. Confirm the activity panel appears immediately.
4. Confirm assistant commentary appears under **Live response / plan** while tokens arrive.
5. If the provider returns an explicit reasoning summary, confirm it appears separately under **Model reasoning summary**. If it does not, the section should remain hidden; do not fabricate reasoning.
6. Confirm each actual tool call appears in the execution log and changes to completed/failed when the tool returns.
7. Confirm Stop cancels an in-flight stream, Continue task still resumes a paused task, and the final assistant answer is displayed normally.
8. Repeat with a provider that does not support streaming; verify a clear error or JSON compatibility fallback and no false claim of live reasoning.


## Long-running Agent runtime smoke test

1. Start an Agent task that requires multiple inspect/edit/test tool calls and confirm it continues beyond the former 24-turn limit without showing a manual Continue prompt at turn 24.
2. Confirm the progress label counts model turns and tool calls, and that streamed plans and real tool execution results continue to appear.
3. Confirm the same identical tool request/result repeating four times within a rolling window of 12 tool calls pauses the Agent with a loop-prevention notice.
4. Confirm two empty model responses pause the task rather than being presented as success.
5. Reload the same localhost origin/port while a task checkpoint exists; confirm the task's conversation is selected and a Resume saved task action appears.
6. Resume the task and confirm it continues from the saved history. On the 500-turn or 2,000-tool-call budget checkpoint, Continue task must add another 500 turns and 2,000 tool calls.
7. Interrupt the browser while a tool is executing. On resume, confirm that the uncertain tool is not automatically replayed and that the model is told to inspect the project state first.
8. Confirm that closing the browser pauses execution; Vibe Calling is not a background worker and does not execute while the browser is closed.

Automated CI validates syntax and static safety checks. Live provider behavior, browser reload behavior, and the long-run smoke test above still require manual validation with a configured provider.


## 2026-11-11 — Preview isolation and review pipeline

- Static project previews now use a separate ephemeral localhost port, separating their browser origin from the app origin and its localStorage.
- The main app server no longer exposes the `/projects/` tree; project previews reject traversal, symbolic links, and secret/private paths.
- POST APIs now require JSON and validate the exact HTTP localhost Origin when an Origin header is present.
- Remote MCP tool calls require per-call approval, including tools described as read-only by the remote server.
- Regenerating a message preserves its original attachment references.
- Added coding-mentor, independent-code-review, and adversarial second-pass review skills; Agent routing now loads them for matching requests.
- Added regression tests for preview isolation, blocked secret paths, origin validation, skill catalog, and attachment/review routing.
- CI checks Python compilation, JavaScript syntax, and the Python unittest suite. No real browser, Windows machine, or live provider/MCP session is implied by those automated checks.


## 2026-11-11 — Secret directory and credential-file boundaries

- Workspace path checks now block common secret directories and credential filenames, including YAML credentials, service-account JSON, and token JSON.
- Recursive file listings now skip directories identified as sensitive, not just build/dependency directories.
- Regression tests cover secret-path reads and listings that previously could expose these paths.
- Documentation now states that outbound HTTPS bypasses environment/system proxy settings as part of IP pinning; proxy-only network configurations are not supported.


## 2026-11-11 — Keyboard shortcut and truthful controls

- Wired the advertised new-chat shortcut to both Ctrl+K (Windows/Linux) and Command+K (macOS).
- The shortcut ignores editable fields and open dialogs, and gives feedback instead of switching chats during an active response.
- Removed the inactive Chat options placeholder rather than presenting a control that only says the feature is coming soon.
- Corrected the Agent skills panel count from 20 to the actual 23 bundled skills.
- Added a regression test for shortcut behavior, shortcut labeling, skill count, and removal of the inert control.
- Kept `app.js` and the embedded script in `index.html` byte-for-byte synchronized.
