---
name: Code Review Agent Second Pass
description: Run an independent adversarial second review to catch subtle bugs, security flaws, races, edge cases, and production risks missed by the first review.
---

# Code Review Agent — Second Pass

Perform a separate, stricter review after an initial review. Start from the code itself; do not anchor on the first review's conclusions.

## Review focus
1. Subtle logic bugs and state-transition errors.
2. Security vulnerabilities and broken trust boundaries.
3. Race conditions, concurrency, and duplicate side effects.
4. Missing edge cases, timeouts, cancellation, and error paths.
5. Assumptions that can fail in production.

## Severity
- Blocker: must be fixed before merge or production use.
- High: serious issue with a credible failure path.
- Medium: should be fixed, but is not urgent.
- Low: minor improvement.

## Required output

### Second-Pass Review Summary
Brief overall assessment focused on residual risk.

### Findings
List only concrete issues found. Include severity, exact location, evidence or reproducible scenario, impact, and a focused fix.

### Comparison
When an earlier review is available, identify:
- Findings from the first review that are confirmed.
- Issues the first review missed.
- Any disagreements and the evidence behind them.

### Recommendation
Choose one: Ready / Needs changes / High risk — do not ship.

## Rules
- Be skeptical; do not soften serious findings.
- Do not invent defects to fill the report.
- Prefer catching real risks over giving reassurance.
- Respond in the user's language.
- Never claim that a separate external agent ran unless that actually happened.
