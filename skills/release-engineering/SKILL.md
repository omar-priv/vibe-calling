---
name: Release Engineering
description: Prepare safe GitHub releases using isolated branches, CI checks, focused diffs, rollback paths, and clear release notes.
---
# Release Engineering

## Workflow
1. Inspect repository status, default branch, recent commits, open PRs, and existing CI before editing.
2. Create a focused branch from the current default branch. Never overwrite unrelated work.
3. Make minimal, logically grouped commits and keep generated/source bundles synchronized.
4. Run targeted tests locally or in CI: syntax, unit, integration, security, and bundle-parity checks.
5. Inspect the diff for secrets, unrelated files, accidental generated artifacts, and breaking changes.
6. Open a PR with scope, risks, limitations, test evidence, and rollback instructions.
7. Merge only when checks pass and the change is reviewed; verify the resulting default-branch commit and CI run.
8. Give the user exact upgrade and backup steps.

## Guardrails
- Do not force-push or delete branches as a shortcut.
- Never claim CI passed until the final commit's run is green.
- Do not deploy automatically unless the user requested deployment.
