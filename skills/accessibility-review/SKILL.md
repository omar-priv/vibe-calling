---
name: Accessibility Review
description: Review and improve semantic HTML, keyboard access, focus behavior, contrast, labels, and reduced-motion support.
---
# Accessibility Review

## Checklist
- Prefer semantic elements and native controls.
- Give every form control a persistent visible or programmatic label.
- Ensure buttons and links have clear names and real actions.
- Keep keyboard navigation logical; provide visible focus indicators.
- Manage focus when opening/closing dialogs and after navigation.
- Make dynamic status and error messages available to assistive technology without excessive announcements.
- Check color contrast and never rely on color alone to communicate state.
- Support zoom, narrow viewports, reduced motion, and touch target spacing.
- Use appropriate alternative text for meaningful images; decorative images should not add noise.
- Avoid nested interactive elements and invalid ARIA.

## Verification
Run available automated checks, inspect DOM semantics, and manually test keyboard-only flows. State what was and was not tested. Do not claim WCAG conformance from a partial review.
