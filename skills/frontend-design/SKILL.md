---
name: frontend-design
description: Design distinctive, coherent, accessible interfaces and inspect layout, hierarchy, spacing, typography, color, and responsive behavior before implementing UI.
---

# Frontend design

1. Inspect the existing UI, page structure, CSS tokens, interaction states, and target viewport before changing the visual language.
2. Define a clear visual direction fitting the product. Avoid generic gradients, random glow, excessive rounded cards, emoji-only navigation, and decorative clutter.
3. Establish hierarchy: one primary action per area, clear page titles, readable body text, restrained metadata, and consistent spacing.
4. Use a small design system for surfaces, borders, text, muted colors, accents, semantic states, spacing, radii, and typography.
5. Design empty, loading, success, error, disabled, hover, keyboard-focus, and narrow-screen states.
6. Keep navigation and primary actions predictable. Do not hide essential controls behind unexplained icons.
7. For chat interfaces, keep the shell fixed to the viewport, scroll the transcript independently, and keep the composer visible. Preserve scroll position unless the user is already near the bottom.
8. Prefer existing dependencies and CSS. Do not add a framework solely for visual polish.

Review: verify hierarchy, contrast, line lengths, alignment, mobile overflow, keyboard focus, labels, reduced-motion support, and long-content behavior.
