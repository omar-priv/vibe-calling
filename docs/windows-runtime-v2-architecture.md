# Windows Agent Runtime v2 — Architecture and Implementation Plan

Status: design baseline only. This document is not evidence that any runtime capability has been implemented or tested.

## Product requirements

The Windows/local edition must support:
- Agent tasks that continue after all browser tabs close.
- Durable task queue, checkpoints, logs, stop/resume, crash recovery and restart recovery.
- Real browser automation.
- Real interactive desktop automation.
- A genuine OS-enforced sandbox, not merely a command allowlist.
- Existing chat, providers, skills, attachments, GitHub MCP, remote MCP, project workspace and UI.
- A strictly separate Hosted edition. No local Windows process execution, desktop control or local browser profile access from hosted_server.py.

## Critical design correction: do not make the Windows service interactive

Windows services run in Session 0 and cannot directly interact with the logged-in user's desktop on supported Windows versions. Therefore desktop automation must run in a per-user interactive-session companion process. A service may be used for machine-level orchestration only if genuinely needed, but the preferred first implementation is a per-user Task Scheduler logon task with restart-on-failure and a tray/CLI control surface.

References:
- https://learn.microsoft.com/en-us/windows/win32/services/interactive-services
- https://learn.microsoft.com/en-us/windows/win32/taskschd/about-the-task-scheduler

## Proposed process layout

1. Vibe Calling UI: existing HTML/CSS/JS. It becomes a client only; it must not own the agent's execution loop.
2. Local API: existing server.py, loopback-only, authenticated with a random per-install local secret and strict Origin/Host checks.
3. Agent worker: separate Python process, started at user logon and supervised/restarted. It owns the task state machine and provider/tool loop.
4. Durable state: SQLite database under the user's local app-data directory, not inside a selected project. Use WAL, migrations, transactionally claimed jobs, unique tool-call IDs, lease expiry and idempotency keys.
5. Browser automation adapter: Playwright Python. Use an isolated persistent profile by default; access to the user's existing browser profile requires explicit opt-in. Keep browser downloads in a dedicated staging directory.
6. Computer-use adapter: pywinauto UIA/Win32 for semantic controls; a screenshot/input backend may supplement it. Execute only in the logged-in interactive session.
7. Sandbox launcher: a separate restricted execution component. Never silently fall back to running an unsafe command as the normal user.

## Project selection

### Browser automation
Preferred base: https://github.com/microsoft/playwright-python
- Apache-2.0.
- Supports Chromium, Firefox and WebKit on Windows.
- Start with Chromium to keep installation size and resource use lower.
- Provide navigation, accessibility/DOM inspection, click, fill/type, keypress, wait, screenshot, tab management and bounded download/upload.
- Enforce navigation policy, private-network restrictions, download destination policy, action timeouts and audit logs.

Browser Use (https://github.com/browser-use/browser-use, MIT) is an optional higher-level agent adapter, not a required dependency for the first stable release. Avoid adopting it wholesale until dependency footprint, Python compatibility, memory usage and tool protocol integration are tested against this app.

### Computer use
Preferred base: https://github.com/pywinauto/pywinauto
- BSD-3-Clause.
- Use UI Automation (uia) first, Win32 backend as a fallback.
- Add screenshot/OCR and raw mouse/keyboard only as a separately permissioned fallback.
- Include a global emergency stop, foreground-window verification, per-action confirmation policy and visible activity indicator.
- Do not claim support for secure desktop/UAC prompts or elevated applications unless specifically tested.

### Background lifecycle
Use Windows Task Scheduler 2.0 for per-user logon startup and restart-on-failure. Provide install, start, stop, status, logs and uninstall scripts. The task must run only as the current user, not LocalSystem. A browser close must not stop the worker. A Windows logoff/reboot will stop the interactive desktop worker; queued work must persist and resume on next logon. Do not promise execution while the PC is powered off or the user is logged off.

### Sandbox
OpenHands documentation confirms Docker as the recommended sandbox boundary; its local runtime explicitly has no sandbox isolation:
- https://github.com/OpenHands/docs/blob/main/openhands/usage/sandboxes/docker.mdx
- https://github.com/OpenHands/docs/blob/main/openhands/usage/v0/runtimes/V0_local.mdx

The user prefers no Docker, so evaluate Windows AppContainer/restricted-token execution as the native route:
- https://learn.microsoft.com/en-us/windows/win32/api/userenv/nf-userenv-createappcontainerprofile

AppContainer implementation requires careful token creation, profile/capability configuration, filesystem ACLs, network capabilities, child-process handling and verification. Do not claim that AppContainer alone solves every isolation problem. If native sandbox implementation cannot pass security tests, expose sandboxed execution as unavailable; never downgrade to host execution without an explicit, clearly labeled unsafe override.

## Task state machine

States: queued, running, waiting_for_approval, paused, completed, failed, cancelled, interrupted.
- Each task has a durable task ID, conversation ID, workspace ID, deadline, current step, provider/model snapshot, checkpoint and event log.
- Claim jobs transactionally; use a renewable worker lease.
- Tool calls have unique IDs and recorded intent/result. Destructive operations must not be repeated after uncertain worker restarts.
- Persist before/after each side-effecting tool action.
- Redact provider keys, MCP tokens, cookies and secrets from logs and model-visible errors.
- API endpoints expose list/get/create/pause/resume/cancel and event streaming.
- The UI may disconnect/reconnect without changing task state.

## Security requirements

- Bind local API to 127.0.0.1 only.
- Require a per-install random secret; do not rely on Origin checks as authentication.
- Keep provider keys and browser cookies out of project workspaces and task logs.
- Deny access to credential stores, private keys, browser profile databases, OS configuration and paths outside explicit workspace mounts.
- Validate paths after resolving symlinks/reparse points; protect against junction and TOCTOU escapes.
- Sandbox network defaults to deny; allow explicit domains only if the implementation can enforce it at OS level.
- Enforce process-tree cleanup, CPU/memory/time limits and bounded output.
- Require confirmation for external side effects, account actions, purchases, publishing, destructive file operations and sending messages.
- Keep Hosted edition unable to invoke any local worker or desktop/browser APIs.

## Acceptance criteria before release

1. Close every Vibe Calling browser tab; a running test task continues and appears after reopening.
2. Kill the worker mid-task; it restarts and resumes safely with no duplicate destructive operation.
3. Reboot/log off/log on; persisted queued tasks recover as documented.
4. Playwright can navigate a local test site, inspect controls, click/type, screenshot and download to the allowed staging folder.
5. pywinauto can open Notepad, locate a control by UIA, type a test string and verify the result; emergency stop works.
6. Sandbox tests prove access outside the workspace and secret paths is denied, network policy is enforced, child processes are terminated, and time/resource limits work.
7. Run existing unit tests on Ubuntu and Windows CI; add Windows-specific lifecycle, worker recovery and adapter tests.
8. Perform a real Windows 10/11 smoke test on a non-CI machine.
9. Verify hosted workflow/deployment and ensure hosted_server.py has no import or execution path into Windows-only modules.
10. Publish a versioned ZIP/installer and GitHub Release only after all checks pass.

## Current implementation status

Nothing in this design file installs dependencies or implements the features above. The existing release remains unchanged until code, tests and Windows verification are complete.
