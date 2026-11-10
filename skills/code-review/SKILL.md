---
name: Code Review
description: Review the complete change for correctness, regressions, architecture, security, performance, accessibility, and test quality before release.
---

# Code review

Review the diff and its real consumers, not just the feature description or the changed lines.

## Five review axes
1. Correctness: requirements, data contracts, edge cases, errors, cancellation, concurrency, persistence, and backward compatibility.
2. Readability: clear naming, focused functions, straightforward control flow, no dead code, no duplicate policy, and no unnecessary abstraction.
3. Architecture: ownership of state, boundaries between UI/backend/provider, coupling, duplicated logic, and whether the change increases or reduces concepts.
4. Security: authentication and authorization, secret storage/logging, XSS, SSRF, path traversal, unsafe redirects, prompt injection, untrusted API/MCP results, and destructive actions.
5. Performance and UX: unbounded loops, large payloads, repeated requests, rendering/scroll behavior, keyboard access, contrast, responsive layout, and reduced motion.

## Review procedure
- Read the full diff, the surrounding implementation, direct callers/consumers, and relevant project guidance.
- Compare behavior before and after. Identify removed safeguards and ensure there is an equivalent replacement.
- Inspect happy paths and failure paths: invalid/empty inputs, provider errors, timeouts, retries, cancellation, partial results, stale sessions, reloads, and storage failure.
- Verify that tests exercise behavior rather than merely asserting that a string or function name exists.
- Check that duplicated bundles, docs, generated assets, model/tool schemas, and migrations remain synchronized.
- Check new controls are wired and have loading, disabled, success, error, keyboard, and narrow-screen states.
- Never treat a passing CI run as proof of live provider, MCP, or browser behavior.

## Findings
Classify each finding as blocker, high, medium, or low. For every finding include:
- Exact file/function/line or a narrow location.
- The concrete failure and user/security impact.
- A reproducible scenario or supporting evidence.
- A focused fix and the test that should guard it.

Avoid style-only preferences unless they cause measurable complexity or inconsistency. Do not invent defects to fill a report. Do not approve a change simply because its intent is good or CI passes.

## Review verdict
State whether the change is safe to merge, what must be fixed first, what was verified, and what could not be tested. If asked only to review, do not edit files.
