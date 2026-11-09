---
name: project-planning
description: Turn a vague product request into a practical implementation plan before coding. Use for new websites, apps, redesigns, or multi-file changes.
---

# Project planning

1. Restate the outcome in concrete user-visible behavior. Separate must-have, later beta, and out-of-scope work.
2. Inspect the existing repository before proposing a stack. Read the entry point, architecture, dependencies, tests, and run instructions.
3. Map each requirement to existing code, missing code, affected files, and risks. Do not claim a feature exists because documentation says so.
4. Identify constraints: operating system, runtime, network, storage, API compatibility, security, and the user's skill level.
5. Choose the smallest coherent implementation. Avoid replacing the stack or adding dependencies without a reason.
6. Write an ordered plan with acceptance checks, then execute ordinary implementation work without unnecessary approval requests.
7. When blocked, deliver the working subset and clearly identify the blocker.

Quality bar: prefer a complete small feature over disconnected placeholders. Preserve working behavior. Never invent tests, provider capabilities, website inspection, or deployment status. Distinguish implemented, locally tested, CI-tested, and untested.
