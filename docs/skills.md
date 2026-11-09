# Vibe Calling Agent Skills

The following skills are bundled in the repository and are available immediately through Agent mode:

| Skill | Purpose |
|---|---|
| `project-planning` | Inspect a project, map requirements, plan changes, and define acceptance checks |
| `frontend-design` | Design hierarchy, visual direction, accessibility, responsive layout, and UI states |
| `frontend-development` | Implement frontend state, forms, chat, attachments, and accessible interactions |
| `backend-design` | Plan trust boundaries, API shape, network controls, storage, and secure service design |
| `backend-development` | Implement Python APIs, validation, local files, and external service integrations |
| `browser-testing` | Test actual UI behavior, responsiveness, keyboard flows, downloads, uploads, and console errors |
| `debugging` | Reproduce bugs, find root causes, implement fixes, and add regression tests |
| `code-review` | Review diffs for correctness, regressions, maintainability, and coverage |
| `security-review` | Threat-model credentials, uploads, MCP tools, network calls, filesystem, and computer use |
| `github-management` | Inspect repositories, create branches, review changes, and manage PR/CI workflows |

## How the agent uses them

The Agent receives the skill names and summaries. Before substantial design or code changes, it should read the most relevant one to three skill files using the built-in `skill_read` tool, inspect the project, then work through a concise plan and verification steps.

Skills provide reusable instructions; they do not retrain the underlying model.

## Add your own skill

Use **Agent tools → Agent skills → Upload skill** and provide either:

- A single `.md` file with YAML frontmatter containing `name` and `description`.
- A `.zip` archive containing one `SKILL.md` and optional Markdown/text references.

Personal skills are stored in `user_skills/` and ignored by Git by default.
