---
name: browser-testing
description: Verify real web UI behavior, responsive layout, keyboard interaction, forms, downloads, uploads, and browser console errors.
---

# Browser testing

1. Identify the run command and check whether required runtimes and browsers are installed.
2. Start the app and confirm its health endpoint before UI tests.
3. Test first load, provider save, model selection, send, agent tool call, upload, download, settings, and refresh persistence.
4. Verify transcript scrolling is independent from page scrolling and the composer stays visible.
5. Test narrow viewports, keyboard-only use, focus visibility, empty/loading/error states, and long messages.
6. Check browser console and network errors. Capture screenshots only when a real browser tool is available.
7. Run existing Playwright tests first when Playwright is installed. Add focused regression tests.
8. If browser automation is unavailable, say so. A static preview, syntax check, or mocked DOM test is not visual browser verification.

Report each check as passed, failed, blocked, or not run. Never report a simulation as a real browser test.
