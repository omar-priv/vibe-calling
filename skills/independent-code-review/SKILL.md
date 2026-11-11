---
name: Independent Code Review
description: Review existing code independently and skeptically for correctness, security, errors, maintainability, and performance.
---

# Independent Code Review

Review code as if another person wrote it. Do not assume the code is correct or that the original intent is fully understood. Prefer evidence over opinions.

## Review order
1. Correctness: logic, boundary conditions, off-by-one errors, and missing cases.
2. Security: injection, XSS, unsafe deserialization, secrets, and validation.
3. Error handling: silent failures, swallowed exceptions, and unclear errors.
4. Readability: names, long functions, nesting, and magic numbers.
5. Performance: obvious inefficiencies, especially loops and database/network calls.
6. Maintainability: coupling, tests, and unclear responsibilities.

## Required output

### Summary
One concise paragraph describing quality and the main residual risks.

### Findings
Classify issues as Critical, Major, Minor, or Suggestion. For each finding include:
- Location: function, line, or narrow code area.
- Why it is a problem and the concrete impact.
- Suggested fix, with a small code example when useful.

### Positive Notes
Mention 1–3 things done well.

## Rules
- Never claim ownership of the reviewed code.
- Never rewrite an entire file unless explicitly asked.
- State assumptions when context is incomplete.
- Review real callers and consumers, not just the changed lines.
- Respond in the user's language and stay constructive.
