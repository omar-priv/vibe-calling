---
name: backend-development
description: Implement reliable Python APIs, local proxy operations, file storage, validation, and external service integrations.
---

# Backend development

1. Read the current server and tests before editing. Preserve existing routes and local-only assumptions unless requirements change.
2. Keep handlers small: parse, validate, run one action, and return structured JSON.
3. Validate types, lengths, encoding, IDs, paths, MIME types, and request sizes on the server.
4. Use pathlib containment checks and reject symlinks for user project files.
5. Never log credentials, request bodies, private URLs, uploaded content, or MCP authorization headers.
6. Use HTTPS, block non-public IPs where applicable, and do not follow unvalidated redirects.
7. Apply bounded timeouts and response-size limits. Avoid leaking secrets or stack traces in errors.
8. Avoid non-standard Python packages unless dependencies are declared and documented.
9. Add allowed and rejected unit tests, especially traversal, secrets, oversized files, and malformed input.
10. Never claim concurrency, process isolation, or sandboxing the implementation does not provide.
