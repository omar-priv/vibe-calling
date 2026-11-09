---
name: backend-design
description: Plan secure backend boundaries, APIs, state ownership, local services, MCP connectors, and future browser-computer-use services.
---

# Backend design

1. Identify trust boundaries between browser, local server, external provider, MCP server, and project workspace.
2. Keep API keys and GitHub tokens out of source, logs, prompts, and tool results. Pass credentials only to the connector that needs them.
3. Prefer explicit JSON actions with validated schemas and predictable responses.
4. Enforce path containment, file-size limits, content-type validation, request-size limits, and safe errors on the server.
5. Treat model output, uploaded files, skill files, MCP results, and website content as untrusted data.
6. Avoid arbitrary shell execution. Use a narrow allowlist and explicit approval for side effects.
7. Validate HTTPS destinations and defend against redirects, SSRF, and private-network targets.
8. Design sessions, timeouts, retries, rate limits, and cleanup for long-lived services.
9. Future remote browser use must run in disposable server-side contexts with no local user files, credentials, or cross-user session access.
10. Document the security model and never call an allowlist a full sandbox.
