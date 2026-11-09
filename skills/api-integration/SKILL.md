---
name: API Integration
description: Integrate external APIs safely with authentication, provider-specific behavior, timeouts, error handling, and documented limits.
---
# API Integration

## Workflow
1. Read the official API documentation and inspect working examples for the exact endpoint and model.
2. Confirm base URL, HTTP method, request schema, authentication, required headers, response format, rate limits, and terms.
3. Separate discovery metadata from actual runtime compatibility. A model appearing in a catalog does not prove it supports the endpoint used by the app.
4. Keep secrets out of source files, logs, URLs, and chat history. Send them only over HTTPS.
5. Validate outbound destinations and prevent SSRF, redirects to untrusted hosts, oversized payloads, and unbounded response reads.
6. Handle 401/403, 404, 409, 429, 5xx, timeouts, malformed JSON, and streaming responses clearly.
7. Test success and failure paths with mocks or safe probes; never spend user quota accidentally.

## Deliverable
Document exact endpoints, scopes, rate-limit caveats, feature gaps, test coverage, and user setup steps.
