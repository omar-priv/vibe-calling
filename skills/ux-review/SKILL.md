---
name: UX Review
description: Audit workflows, information architecture, interaction friction, and interface consistency before changing UI code.
---
# UX Review

## Audit process
1. Map the primary user journeys from entry to successful completion.
2. Identify the user goal, available action, feedback, error recovery, and exit path for every important screen.
3. Check hierarchy, labels, empty/loading/error/success states, keyboard flow, responsive layout, and content density.
4. Prioritize issues by user impact and frequency; distinguish blockers from polish.
5. Recommend the smallest coherent set of changes that removes friction without disrupting familiar behavior.
6. Implement only after tracing the relevant HTML, CSS, JavaScript, and event handlers.
7. Re-check the same journeys after changes.

## Deliverable
For each issue include: location, observed behavior, user impact, severity, proposed fix, and verification method.

## Guardrails
- Do not call a preference a usability defect without explaining the task impact.
- Avoid decorative controls that do nothing.
- Preserve working keyboard and mobile behavior.
- Do not claim user testing unless actual users were observed.
