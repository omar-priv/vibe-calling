# Vibe Calling — Free Hosted Edition

This is a separate hosted edition. The Windows/local edition remains the default and is not changed.

## Zero-cost architecture

- Web host: Render Free Python web service. No Docker, npm, or paid instance.
- Persistent database: Neon Free Postgres. Project files, uploads, project memory, and imported custom skills are saved to Neon. The local folders used by the hosted process are only a temporary cache.
- Application: the existing Vibe Calling UI, served by hosted_server.py behind a private password.
- Local edition: server.py and start.bat continue to bind to 127.0.0.1 and keep their existing local preview/runtime behavior.

The included Render Blueprint uses the Free compute plan and does not attach a paid persistent disk. It does not configure paid services or a payment method.

## Create the free services

### 1. Create a Neon database

1. Open https://neon.com/ and create a Free project.
2. Open the project's connection details and copy the PostgreSQL connection string.
3. Keep the connection string private. It is the credential for the hosted workspace database.

Neon Free currently provides 100 compute-hours per project per month, 1 GB database storage per project, and 5 GB public network transfer per project per month. Compute scales to zero after five minutes of inactivity. When the Free compute or transfer allowance is exhausted, the database suspends until the monthly reset; writes that exceed the storage cap fail. Neon documents that Free-plan overages are not billed and quota suspension does not delete existing data. Check the current limits before deployment.

### 2. Deploy the Render Blueprint

1. Open https://dashboard.render.com/blueprints.
2. Choose New Blueprint Instance and connect the GitHub repository after this pull request is merged to main.
3. Render reads render.yaml and creates one Python Web Service on the Free compute plan.
4. Set the NEON_DATABASE_URL secret to the connection string copied from Neon.
5. Set VIBE_ACCESS_PASSWORD to a unique password of at least 14 characters.
6. Keep the generated VIBE_SESSION_SECRET; do not replace it with a public or reused password.
7. Deploy and open the service's HTTPS onrender.com URL. Sign in with the password you chose.

Do not add a payment method or upgrade the Render service. Render documents that a Free web service sleeps after 15 minutes without inbound traffic, takes about one minute to start on the next request, and loses local filesystem changes when it sleeps or restarts. Render provides 750 free instance-hours per workspace per calendar month. When no payment method is attached, exhausting the included bandwidth suspends free services for the remainder of the month; exhausting build minutes disables new builds. This means zero hosting cost within the free limits, but not guaranteed always-on availability.

## What is persisted

- Project folders and editable project files.
- Uploaded chat attachments stored inside projects.
- The hidden .vibe/memory.json file for each project.
- Imported custom skills and their supported text reference files.

The app synchronizes changes to Neon before confirming a successful write. The hosted cache is restored from Neon at service startup. The application enforces a 400 MB total workspace quota (below Neon's 1 GB per-project storage ceiling), a 100 MB per-project quota, a 2 MB maximum persisted project file, and a 3 MB custom-skills quota. Build and dependency directories are excluded from persistence.

## Hosted-only limitations

The hosted edition intentionally disables project runtime start/stop/status, project preview, and remote command execution. The earlier hosted draft returned 127.0.0.1 URLs to remote users, which point to the user's own computer rather than the hosted server. Running untrusted project commands on the public free web instance is also not a safe substitute for a sandbox. These features remain available in the separate local Windows edition. Hosted Agent mode can still create projects, read/write files, preserve project memory, upload attachments, import skills, use configured AI providers, and use Web Research and MCP subject to provider support and free quotas.

The web service is a private single-owner workspace, not a multi-user SaaS. Provider API keys and MCP tokens are stored by the current UI in browser localStorage and are not encrypted by the app. Use a private browser profile, do not use shared computers, and sign out after use.

## Free service limits and recovery

- Render Free sleeps after 15 minutes idle and may take around one minute to wake.
- Render can restart free instances; its local disk is ephemeral. Neon is the persistent source of truth.
- Render Free includes 750 instance-hours per workspace per calendar month.
- Neon Free includes 100 CU-hours per project per month, 1 GB database storage per project, and 5 GB public transfer per project per month.
- If Neon reaches its compute or network quota, its compute suspends until reset; hosted API operations that require the database will return an error until the database is available again.
- If Render's free build or bandwidth allowance is exhausted, Render may disable builds or suspend the service for the rest of the month when no payment method is attached.
- The app uses no paid persistent disk, paid database, paid VM, or paid custom domain.

## Deploy verification

A green GitHub Actions run verifies syntax, unit tests, and configuration. It is not proof that Render or Neon have been connected. After creating the free services and entering the private secrets, verify login, create a project, write a file, let Render sleep or restart, and confirm that the project and file return from Neon.

## Local Windows edition

Nothing in this hosted setup changes the local launcher. For Windows, download or clone the main branch and double-click start.bat. It continues to use server.py on 127.0.0.1, with local project preview and local command execution.
