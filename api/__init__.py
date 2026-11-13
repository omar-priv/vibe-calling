"""Worker management API for the Windows Agent Runtime v2.

Connects the background worker (worker.py) to the existing local server
(server.py) and the browser UI (app.js). The API exposes task lifecycle,
adapter status, and task-event logs so the agent and the user can manage
background work independently of any open browser tab.
"""
