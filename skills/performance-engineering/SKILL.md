---
name: Performance Engineering
description: Find and fix front-end and back-end performance bottlenecks with measurement and low-risk changes.
---
# Performance Engineering

## Method
1. Reproduce the slowdown and define a measurable baseline.
2. Inspect CPU, memory, network requests, request size, DOM size, blocking tasks, and server timings where tools permit.
3. Separate startup cost, steady-state interaction cost, and long-running task cost.
4. Prefer reducing duplicate work, payload size, unnecessary rendering, synchronous I/O, and unbounded loops before adding dependencies.
5. Use cancellation, timeouts, pagination, bounded concurrency, and cleanup for long-running operations.
6. Retest on the weakest supported device and with realistic data.
7. Record before/after measurements and remaining bottlenecks.

## Guardrails
- Do not optimize by deleting essential functionality.
- Avoid adding heavy libraries to a lightweight app without evidence.
- Do not claim a speed improvement without a repeatable measurement.
- Keep resource and memory limits explicit for agent tools and remote sessions.
