---
name: UX Review
description: Audit complete user journeys for clarity, discoverability, feedback, accessibility, recovery, and interaction friction.
---

# UX review

## Map the journey
For the requested feature, map the steps from entry to successful completion. For each step identify:
- The user's goal and the action they need.
- Whether the action is discoverable and correctly named.
- What feedback appears immediately and what happens on success or failure.
- How the user recovers, cancels, goes back, or exits.

## Review the workflow
- Check information architecture, navigation consistency, terminology, and whether the primary action is obvious.
- Check loading, empty, partial, success, error, disabled, permission-denied, and offline states.
- Check keyboard flow, visible focus, screen-reader labels/status, contrast, touch targets, and narrow screens.
- Check data loss risk, destructive confirmations, undo/recovery, duplicate actions, and whether progress survives reloads where promised.
- Avoid decorative or inert controls. Every visible action must work or be clearly marked unavailable/planned.
- Do not confuse personal preference with a usability defect; explain the task impact.

## Prioritization
Rank by how much the issue blocks the user's goal, how frequently it occurs, and how many screens it affects. Prefer one systemic fix over multiple cosmetic patches.

## Verification
Re-run the same journey after implementation. Check desktop and mobile widths, keyboard-only operation, and failure recovery where practical. Never claim usability testing unless actual users were observed.
