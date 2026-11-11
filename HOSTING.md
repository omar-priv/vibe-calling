# Vibe Calling — Hosted Edition

This is a separate, private, single-owner deployment edition. It does not replace the Windows/local edition.

## What is ready

- Uses the existing UI and same-origin API requests.
- Requires a private access password and a signed, expiring HttpOnly session cookie.
- Rejects missing or cross-origin browser Origin headers on login and state-changing requests.
- Applies security response headers and limits failed login attempts.
- Stores projects and imported skills under VIBE_DATA_DIR for persistence across restarts when a persistent disk is mounted.
- Uses the Python standard library server and requires no Docker, Node.js, or npm to run the application.
- Keeps the existing local server.py and start.bat behavior unchanged.

## Important security limitation

**Hosted project preview is deliberately disabled.** The UI stores provider API keys and MCP tokens in browser localStorage. Serving generated project HTML/JavaScript on the same origin would let project code potentially read those credentials. The local edition avoids this by previewing on a separate localhost port; the hosted edition does not yet provide an isolated preview origin. Do not re-enable /projects/... on the app origin as a shortcut.

Agent project file read/write, download and allowlisted commands remain available after sign-in. Remember that approved commands execute on the hosted server; the allowlist and confirmation dialog are not an OS-level sandbox. Do not run untrusted project code or install arbitrary dependencies on this personal service.

## Deploy on Render (no Docker)

1. Merge the Hosted Edition pull request into main.
2. In Render, choose **New → Blueprint** and connect this GitHub repository using the main branch.
3. Render reads render.yaml; it creates a Python web service and a 1 GB persistent disk.
4. Set VIBE_ACCESS_PASSWORD to a unique password of at least 14 characters when prompted. Do not reuse your GitHub, email, or school password.
5. Keep the generated VIBE_SESSION_SECRET private. Keep VIBE_DATA_DIR set to /var/data.
6. Deploy, wait for /__health to pass, open the HTTPS onrender.com address, and sign in.
7. Add provider API keys from the Providers screen. The current UI stores provider and MCP tokens in this browser's localStorage; they are not encrypted by the app. Use a private browser profile and sign out on shared devices.

### Cost and free-tier reality

The Blueprint uses Render's smallest paid web-service plan (0.5c-512mb) and a 1 GB persistent disk. Render lists the web service at about US$7/month and SSD storage at US$0.25/GB/month, so the configured baseline is about US$7.25/month before tax or future price changes. Confirm the amount in Render before creating the service.

This is **not a zero-cost persistent deployment**. Render's free web service cannot attach a persistent disk, and its filesystem is ephemeral. Without persistent storage, projects and custom skills may be lost when the instance restarts or redeploys.

## Known limitations

- This is a private single-owner workspace, not a multi-user SaaS. Do not share its password.
- The smallest service has 512 MB RAM. Large builds, dependency installations, and long-running coding tasks can exceed its resources. It is a lightweight personal host, not a remote build farm.
- Hosted static project previews are disabled until a genuinely separate origin and lifecycle are implemented.
- The GitHub and remote MCP connectors store their tokens in browser localStorage, not encrypted storage.
- The service must remain single-instance while using its attached persistent disk.
- Remote Browser / Computer Use is still a planned Beta panel; it is not implemented by this deployment.
- A passing health check proves only that the web process responds. It does not prove that every provider, model, MCP server, or project command works.

## Local smoke test for hosted mode

Set the following environment variables before running:

- VIBE_ACCESS_PASSWORD: at least 14 characters.
- VIBE_SESSION_SECRET: at least 32 random characters.
- VIBE_DATA_DIR: a writable folder such as ./hosted-data.
- VIBE_COOKIE_SECURE=0: only for local HTTP testing; never use this on Render.
- PORT: optional; defaults to 10000.

Run python hosted_server.py, then open http://127.0.0.1:10000. Browser login and API POST requests must include the exact same-origin Origin header. The regular Windows launcher and local server.py are unchanged.

## Rollback

To stop using the hosted edition, suspend/delete the Render service and retain or download the persistent disk data first. To restore a previous release, redeploy the previous known-good Git commit from Render. The local Windows edition remains available from the repository's main branch through start.bat.
