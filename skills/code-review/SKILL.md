---
name: code-review
description: Review code changes for correctness, regressions, maintainability, error handling, performance, and test coverage before release.
---

# Code review

Review the diff, not only the intended feature.

Check runtime correctness, edge cases, state ownership, backwards compatibility, validation, escaping, file size limits, API contracts, authentication, timeouts, provider compatibility, accessibility, responsive layout, scrolling, cache behavior, embedded bundle synchronization, tests, unused code, dependencies, secrets, and documentation drift.

Classify findings as blocker, high, medium, or low. Cite exact files/functions and explain practical impact. Do not approve a change just because CI passes; CI is not proof of real-world behavior.
