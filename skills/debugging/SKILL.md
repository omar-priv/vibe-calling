---
name: debugging
description: Diagnose bugs by reproducing them, tracing the responsible code path, checking logs and state, and adding a regression test.
---

# Debugging

1. Reproduce the reported behavior or isolate the failing path before editing.
2. Read the relevant source, callers, state transitions, and server response. Do not assume prior diagnoses are correct.
3. Separate symptoms from root causes. Check console/server output, HTTP status, storage, and provider responses.
4. Form the smallest hypothesis and test it. Avoid unrelated refactors.
5. Fix the root cause with explicit error handling; never hide errors behind fake success messages.
6. Add a regression test that fails before the fix where practical.
7. Run the smallest relevant test, then the available suite if safe and affordable.
8. Report cause, changed files, tests actually run, and anything still unverified.
