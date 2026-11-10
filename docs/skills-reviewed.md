# UI/UX skills reviewed for Vibe Calling

These public agent-skill references were fetched and inspected before the interface update. Their instructions were treated as design guidance, not executed as shell commands.

## Skills and references

1. **UI/UX architecture — Emmraan/agent-skills**
   - https://github.com/Emmraan/agent-skills/tree/main/skills/design-ux/ui-ux
   - Used for task-first UX, navigation clarity, information hierarchy, interaction feedback, empty/error/loading states, accessibility, and usability review.
   - License declared in the skill: MIT.

2. **Web Interface Guidelines — Vercel**
   - https://github.com/vercel-labs/agent-skills/tree/main/skills/web-design-guidelines
   - https://github.com/vercel-labs/web-interface-guidelines
   - Used for semantic controls, visible keyboard focus, labelled inputs, inline form errors, reduced-motion support, button hover/active states, and cache/performance checks.

3. **Frontend design — alt-code-ai/agent**
   - https://github.com/alt-code-ai/agent/tree/main/skills/frontend-design
   - Used for committing to a coherent product-specific visual direction, avoiding generic decorative styling, and using restrained motion instead of random animation.

4. **Frontend UI engineering — Addy Osmani**
   - https://github.com/addyosmani/agent-skills/tree/main/skills/frontend-ui-engineering
   - Used for accessible and responsive implementation, focused component behavior, state feedback, and avoiding unnecessary frontend dependencies.

5. **UX usability foundations — hueyexe**
   - https://github.com/hueyexe/frontend-agent-skills/tree/main/ux-usability-foundations
   - Used for making actions discoverable and giving immediate receipt, progress, success, and error feedback.

## Applied to this project

- Each button gets a visible press acknowledgement; hover, active, focus, disabled, and reduced-motion states are defined.
- Provider testing displays validation, in-progress, success, or actionable error feedback.
- Provider saving preserves discovered model IDs and rolls the UI back if browser storage fails.
- The incomplete emergency interaction fallback has been removed; startup problems now show a diagnostic message instead of pretending the app is functional.
- App assets use content-versioned URLs, and the local server sends no-cache headers for HTML, JavaScript, and CSS to prevent stale code from being reused.
- This remains a local-first, no-framework frontend with a Python localhost proxy.

## Verification status

JavaScript syntax and required UI element IDs are checked before each release. Manual browser click-through and live provider requests still need to be exercised on the user's computer and network; syntax checks alone are not described as proof of runtime success.


## Debugging, code review, and research references added

6. **Systematic debugging — obra/superpowers**
   - https://github.com/obra/superpowers/tree/main/skills/systematic-debugging
   - Used for root-cause-first investigation, falsifiable hypotheses, one-variable experiments, and regression tests. The repository LICENSE was inspected and identified as MIT. The skill was rewritten in the project's own wording rather than copied verbatim.

7. **Code review and quality — Addy Osmani**
   - https://github.com/addyosmani/agent-skills/tree/main/skills/code-review-and-quality
   - Used for five review axes: correctness, readability, architecture, security, and performance; findings should include location, evidence, impact, and a structural remedy. The repository LICENSE was inspected and identified as MIT.

8. **Web Interface Guidelines — Vercel**
   - https://github.com/vercel-labs/agent-skills/tree/main/skills/web-design-guidelines
   - Used as a checklist source for semantic controls, keyboard focus, form errors, reduced motion, responsive states, and direct guideline refresh. The project's skill content was rewritten as local guidance; the Vercel skill points to the separately maintained Web Interface Guidelines source.

9. **UX usability foundations — hueyexe**
   - https://github.com/hueyexe/frontend-agent-skills/tree/main/ux-usability-foundations
   - Used for user-journey mapping, discoverability, task feedback, recovery, and practical prioritization.

10. **Interface review — jakubkrehel/skills**
    - https://github.com/jakubkrehel/skills
    - Used as an additional perspective for interface critique, accessibility, hierarchy, and interaction clarity.

The Debugging, Code Review, Frontend Design, UX Review, and Web Research instructions in this repository were expanded using these principles in original wording. A separate deep-research skill was added for multi-query investigations, primary-source prioritization, date awareness, cross-checking, and evidence synthesis.
