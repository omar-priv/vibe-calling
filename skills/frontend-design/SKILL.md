---
name: frontend-design
description: Design coherent, product-specific interfaces with clear hierarchy, accessible interactions, responsive layouts, and complete UI states.
---

# Frontend design

## Recon before design
- Inspect existing screens, navigation, typography, spacing, colors, tokens, components, and interaction patterns before editing.
- Identify the main user task and the product's existing visual language. Extend it instead of replacing it without reason.
- Check the actual HTML/CSS/JavaScript structure and existing browser support. Avoid adding frameworks or packages for visual polish alone.

## Visual system
- Establish a clear hierarchy: page purpose, primary action, supporting actions, content, and metadata.
- Use consistent spacing, readable line length, typography scale, restrained colors, semantic status colors, and predictable component states.
- Prefer alignment, whitespace, and typography over unnecessary cards, gradients, shadows, glows, or decoration.
- Keep labels explicit. Icons alone are not a substitute for accessible names.
- Make interactive elements visually distinct from static text.

## Interaction states
Design and implement loading, empty, success, error, disabled, selected, hover, active, and visible keyboard-focus states.
- Give immediate feedback when an action starts and a clear result when it completes.
- Destructive actions need a clear label and confirmation or a reversible recovery path.
- Long-running work needs visible progress, a stop action, and recoverable errors.
- Preserve transcript scroll position and keep chat composition usable while content grows.

## Responsive and accessible behavior
- Check narrow viewports, including 320px width, long titles, long URLs, large text, and 200% zoom.
- Use semantic HTML and native controls where appropriate.
- Ensure all actions work by keyboard and have visible focus indicators.
- Verify readable contrast, accessible names, labels, status announcements, and reduced-motion behavior.
- Do not communicate state through color or animation alone.

## Verification
- Inspect rendered UI at desktop and mobile widths when a browser is available.
- Test keyboard navigation, focus, hover/active, loading/error/empty states, and overflow.
- Report visual claims as unverified when only source code was inspected.
