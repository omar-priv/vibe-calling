# Background Agent Runtime and Security Boundaries

## Architecture

The local edition has four cooperating parts:

1. server.py exposes a loopback-only API and validates requests.
2. agent_runtime.py stores jobs, encrypted payloads/checkpoints/results, approval requests, and a small event journal in SQLite under %LOCALAPPDATA%\VibeCalling\agent-runtime.sqlite3.
3. agent_worker.py is started as a detached process when a job is queued. It reads the job from SQLite, calls the configured OpenAI-compatible provider, runs supported tools, and writes checkpoints/events back to SQLite.
4. agent_automation.py provides optional Playwright and pywinauto adapters. They are loaded only when their corresponding dependencies are installed and the user has enabled the feature.

The browser is an operator surface, not the process that owns the job. It polls the worker for progress and pending approvals. Closing the browser tab only stops that tab's polling; it does not terminate the worker.

## Job lifecycle and recovery

- A job is inserted in SQLite before the worker is launched.
- Provider API keys are protected with Windows DPAPI for the current Windows user. The provider request payload, conversation/checkpoint history, and final result are also DPAPI-protected at rest.
- The worker saves history after every model response, before every tool side effect, and after each tool result.
- Approval requests are durable. A reconnecting UI can retrieve pending approvals and display them again.
- A user cancellation is durable and checked between model calls and tool calls. It does not forcibly interrupt a model HTTP request or a native desktop action already in progress.
- A worker crash/restart never blindly replays a tool call that was already marked as started. The job is paused and the model receives a tool result that explicitly says the outcome is unknown. The agent must inspect the actual state before choosing whether to retry.
- A completed, paused, failed, or cancelled result remains in SQLite and appears in the chat that created it when the UI reconnects.
- The worker shuts down after 45 seconds with no queued work to avoid staying resident forever on low-memory machines.

The worker is detached from the browser and main UI server, but it is not a Windows Service or scheduled startup task. It operates only while the computer is awake and the Windows user session remains available. Logging out, shutting down, sleeping, or rebooting suspends or terminates it. Interrupted tasks persist and require a user to reopen the app and resume after reviewing the saved state.

## Provider and local data storage

The worker database is placed in the current user's local application-data folder. Windows DPAPI protects:

- Provider API keys copied into a job.
- Provider request settings and the conversation history captured for that job.
- Model/tool checkpoint history.
- Final Agent response text.

DPAPI protection is bound to the Windows user context. It is not a portable backup format; copying the database to another Windows account or machine does not guarantee that it can be decrypted there. SQLite event metadata (tool names, timestamps, status, and error summaries) remains queryable so the UI can show progress. Approval records redact common text/secret fields before persistence.

The existing web application still stores provider configuration and GitHub/remote MCP tokens in browser localStorage, as documented elsewhere. Background-worker encryption does not change that separate browser-storage behavior.

## Browser Automation

Browser Automation is opt-in. Install the optional dependencies and Chromium with install-automation.bat, restart Vibe Calling, and enable the checkbox under Agent tools.

- It uses a dedicated Vibe Calling browser profile under %LOCALAPPDATA%\VibeCalling\browser-profile; it never points Playwright at the user's normal Chrome/Edge profile.
- Only HTTP and HTTPS public web destinations are allowed. Localhost, .local, private, link-local, reserved, and non-global IP destinations are rejected. Each browser request is routed through the URL guard before it is allowed to continue.
- browser_open navigates; browser_snapshot reads page title/URL/visible text; browser_click, browser_fill, and browser_press act on one unique CSS locator; browser_screenshot saves a local PNG; browser_close ends the dedicated session.
- Click, fill, key-press, and close actions always request user approval. Trusted workspace mode does not bypass these prompts.
- The browser is visible. It can open pages and preserve its own profile state; it does not have access to the user's normal browser cookies or extensions.
- This is browser automation, not a security boundary for websites. Do not sign in to sensitive accounts or submit financial/irreversible forms unless you understand and approve the action.

## Windows Computer Use

Computer Use is opt-in and requires pywinauto on Windows.

- computer_list_windows and computer_inspect_window inspect visible application windows and UI Automation controls.
- computer_screenshot saves a screenshot of a selected application window.
- computer_click, computer_type, and computer_press_keys perform approved actions against an accessible control.
- Control discovery prioritizes UI Automation names and automation IDs. Applications built around custom canvases, games, remote desktops, or non-accessible drawing surfaces may expose few or no usable controls.
- Actions happen in the real, logged-in Windows desktop session. The session must be unlocked and the computer awake. This is not a virtual desktop and it does not continue interacting after logoff or while Windows is locked.
- Every action that clicks, types, or sends keys requires explicit approval, even in Trusted mode. Inspection does not intentionally retrieve edit-control values/password contents.

## Guarded Terminal and process limits

The old allowlist remains the preferred route for common install/build/test/lint operations. A new workspace_terminal tool can run one command at a time when the user enables Guarded Terminal.

- Every Guarded Terminal command requires explicit approval, including in Trusted mode.
- It rejects shell chaining/operators and environment-variable expansion. It does not launch a shell to interpret a compound command.
- The working directory is the selected workspace. The inherited environment is reduced to common operating-system/toolchain variables; temporary files are directed to the workspace's .vibe/tmp.
- On Windows, agent_process.py creates a Windows Job Object and applies process-count and job-memory limits, then closes the job to terminate child processes on timeout. The default job-memory ceiling is 1.5 GiB and active-process ceiling is 32; command timeouts are bounded by the existing 600-second maximum.
- If the Windows API cannot create or assign the Job Object, the command is not silently promoted to an unrestricted terminal.
- Job Objects control process lifetime/resources. They do not restrict filesystem access, registry access, network access, or the Windows identity of the launched process. A command still has the current Windows user's permissions. User approval and path validation are additional safeguards, not a kernel filesystem sandbox.

Guarded Terminal is more capable than the allowlist, but it is intentionally not an unattended unrestricted PowerShell/CMD session. A shell can execute arbitrary scripts, chain commands, expand environment variables, and reach outside the workspace. That would contradict the current security boundary on a Windows 10 device without a verified isolation backend.

## Why a full OS sandbox is not enabled here

A true sandbox must be enforced by Windows, not by Python code that asks a model to behave. Microsoft documents AppContainer/Win32 isolation and the Microsoft Execution Containers (MXC) project as approaches for policy-based file, network, and process isolation. MXC's Windows ProcessContainer availability depends on supported Windows 11 builds and release-specific backend support. Windows Sandbox also has host OS, virtualization, and hardware prerequisites, and is too resource-heavy to make a mandatory dependency for the low-memory Windows 10 baseline this edition targets.

For that reason this build does not claim that Job Objects, a workspace working directory, or a confirmation dialog are equivalent to a sandbox. A future sandbox backend should:

1. Detect host OS build, edition, virtualization, and required Windows features at runtime.
2. Use a maintained and supported OS isolation API/runtime, not a homemade token filter.
3. Mount only the selected project as an explicitly scoped read/write directory.
4. Deny access to user profile secrets, browser profiles, SSH keys, credentials, and unrelated workspaces.
5. Deny network by default, with explicit per-task egress policy where needed.
6. Keep provider keys and approval state in the trusted host process, outside the sandbox.
7. Apply CPU, memory, process-count, disk, and wall-clock limits.
8. Fail closed when isolation is unavailable. Never silently fall back to running an untrusted command as the current Windows user while showing a “Sandboxed” badge.

Current references used for design:
- Microsoft Execution Containers: https://github.com/microsoft/mxc
- MXC platform support: https://learn.microsoft.com/en-us/windows/apps/develop/mxc/platform-support
- AppContainer implementation guidance: https://learn.microsoft.com/en-us/windows/win32/secauthz/implementing-an-appcontainer
- Windows Job Objects: https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects
- Playwright Python: https://github.com/microsoft/playwright-python
- pywinauto and Microsoft's AutoGenesis pywinauto MCP server: https://github.com/pywinauto/pywinauto and https://github.com/microsoft/AutoGenesis/tree/main/pywinauto-mcp-server
- Windows-MCP and FastCUA for observe/inspect/act/verify patterns: https://github.com/CursorTouch/Windows-MCP and https://github.com/Guojiz/FastCUA. FastCUA is experimental and its Windows 11 focus is not treated as a production dependency here.

## Background worker limitations

- Background worker provider calls are non-streaming; the UI polls progress.
- The background worker supports local workspace tools, the optional local browser/desktop tools, and the guarded terminal. Research tools and external GitHub/remote MCP calls remain in the browser Agent loop for now.
- The worker runs one task at a time per local installation.
- Browser/computer dependencies are optional and installed separately.
- A machine crash or forced termination can leave a tool action with an unknown outcome. It is surfaced as unknown and must be inspected before resuming.
- This release does not implement a Windows Service, automatic startup after reboot, or a true filesystem/network sandbox.
