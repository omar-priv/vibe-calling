---
name: security-review
description: Review application code, uploads, API keys, MCP tokens, tool calls, filesystem access, network requests, and browser automation for security issues.
---

# Security review

Threat-model each feature before implementation.

- Credentials: never commit, log, display, or send provider/GitHub tokens to the model. Disclose browser storage risks.
- Uploads: enforce server-side size, extension/MIME allowlists, safe generated paths, archive traversal protection, and file count limits. Never execute uploaded scripts.
- Filesystem: block parent traversal, absolute paths, symlinks, secrets, private keys, and paths outside the project root.
- Commands: exact allowlists, argument validation, no shell operators, explicit confirmation, bounded timeouts, and clear disclosure that local execution is not a full sandbox.
- Network: HTTPS only, reject private/loopback/link-local IPs, validate redirects, and restrict MCP endpoints to trusted hosts.
- MCP: validate JSON-RPC, cap tool counts/schema sizes, require approval for write operations, and treat tool output as untrusted.
- Rendering: escape model output, skill content, filenames, and file content. Validate generated download links.
- Browser use: disposable server-side contexts; no local desktop files, cookies, or cross-user state.
- Test denial paths as well as success paths. Document residual risks.
