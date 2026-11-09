---
name: Browser Visual Testing
description: Verify real UI behavior and visual regressions in a browser using deterministic journeys and screenshots.
---
# Browser Visual Testing

## Workflow
1. Confirm a real browser automation runtime is available; if not, state the limitation and use only the tests that are available.
2. Start the app from its documented launcher and verify its health endpoint.
3. Test first load, provider setup, model selection, chat send, attachment flow, Agent tool calls, dialogs, navigation, and mobile viewport.
4. Capture screenshots at defined viewport sizes before and after changes when possible.
5. Check scrolling boundaries, sticky/fixed elements, focus states, overflow, empty/loading/error states, and browser console errors.
6. Keep tests deterministic: isolate storage, mock APIs where appropriate, and avoid consuming paid/free quota unexpectedly.
7. Report browser, viewport, steps, evidence, and failures.

## Guardrails
- A CSS parse or JavaScript syntax check is not visual browser testing.
- A static screenshot does not prove interactions work.
- Never say Playwright passed unless it was actually run.
