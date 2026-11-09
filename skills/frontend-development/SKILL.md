---
name: frontend-development
description: Implement production-minded frontend features in the project's current stack, including state, forms, chat, uploads, accessibility, and responsive behavior.
---

# Frontend development

1. Read existing HTML, JavaScript, and CSS. Preserve the architecture unless migration is necessary.
2. Locate the source of truth for state and persistence. Avoid duplicate stores.
3. Escape untrusted text; never insert uploaded content or model output as raw HTML.
4. Give every visible control a real action, loading/disabled state, and useful error message.
5. Keep keyboard support, labels, visible focus, and reduced-motion support.
6. For uploads, validate count, size, MIME/extension, and display names. Never trust client-provided paths.
7. Keep chat transcript scrolling separate from page scrolling and keep the composer reachable.
8. Keep large payloads out of persistent browser storage unless there is a deliberate size strategy.
9. Update embedded/generated source copies whenever the project maintains duplicate bundles.
10. Run available syntax and interaction tests. State what was not tested in a real browser.
