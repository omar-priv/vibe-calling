#!/usr/bin/env python3
"""Detached local Agent worker. Runs independently of the Vibe Calling browser tab."""
from __future__ import annotations

import json
import os
import re
import shlex
import signal
import socket
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import server
import agent_runtime as runtime

HEARTBEAT_SECONDS = 4
MAX_TURNS = 500
MAX_TOOL_CALLS = 2000


def event(job_id: str, kind: str, message: str, payload: Any = None) -> None:
    runtime.add_event(job_id, kind, message, payload)


def checkpoint(job_id: str, data: dict) -> None:
    data["updated_at"] = time.time()
    runtime.set_checkpoint(job_id, data)


def is_cancelled(job_id: str) -> bool:
    return runtime.cancel_requested(job_id)


def provider_completion(job: dict, history: list, tools: list) -> dict:
    provider = job["payload"]["provider"]
    parts, host, port, prefix = server.validate_target(provider.get("baseUrl", ""))
    url = "https://" + host + ((":" + str(port)) if port != 443 else "") + (prefix + "/chat/completions")
    body = {
        "model": provider["model"],
        "messages": history,
        "temperature": 0.7,
        "tools": tools,
        "tool_choice": "auto",
        "stream": False,
    }
    headers = {
        "Authorization": "Bearer " + job["api_key"],
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    custom_name = provider.get("customHeader", "")
    custom_value = provider.get("customHeaderValue", "")
    if custom_name:
        if not server.HEADER_NAME_RE.fullmatch(str(custom_name)) or "\r" in str(custom_value) or "\n" in str(custom_value):
            raise ValueError("Invalid custom provider header.")
        headers[str(custom_name)] = str(custom_value)[:4096]
    request = urllib.request.Request(url, data=server.json_bytes(body), headers=headers, method="POST")
    try:
        with server.OPENER.open(request, timeout=120) as response:
            raw = response.read(8 * 1024 * 1024 + 1)
            if len(raw) > 8 * 1024 * 1024:
                raise ValueError("Provider response exceeded the 8 MB worker limit.")
    except urllib.error.HTTPError as exc:
        raw = exc.read(256 * 1024)
        message = raw.decode("utf-8", errors="replace")[:2000]
        raise RuntimeError("Provider returned HTTP " + str(exc.code) + ": " + message)
    except urllib.error.URLError as exc:
        raise RuntimeError("Provider connection failed: " + str(exc.reason)) from exc
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("Provider returned invalid JSON.") from exc
    if isinstance(value, dict) and value.get("error"):
        raise RuntimeError(str(value["error"])[:2000])
    choices = value.get("choices") if isinstance(value, dict) else None
    if not choices or not isinstance(choices[0], dict) or not isinstance(choices[0].get("message"), dict):
        raise RuntimeError("Provider response did not contain a chat completion message.")
    return choices[0]["message"]


def _project(args: dict, payload: dict) -> str:
    value = args.get("project") or payload.get("activeProject")
    if not isinstance(value, str) or not value:
        raise ValueError("Select or open a workspace before using project tools.")
    server.project_dir(value)
    return value


def _approval_required(name: str, args: dict, payload: dict) -> tuple[bool, str]:
    project = args.get("project") or payload.get("activeProject") or ""
    trusted = payload.get("permissionMode") == "trusted" and project and project == payload.get("permissionWorkspaceId")
    if name == "workspace_terminal":
        return (True, "A terminal command runs with your Windows account's permissions. This is not an OS filesystem sandbox.")
    if name in {"workspace_delete_file", "workspace_move_file", "workspace_run_command", "workspace_start_project"}:
        return (not trusted, "This action can change files or execute project code on your Windows account.")
    if name.startswith("computer_") and name not in {"computer_list_windows", "computer_inspect_window", "computer_screenshot"}:
        return (True, "This action will click or type into a real Windows application.")
    if name.startswith("browser_") and name not in {"browser_snapshot", "browser_screenshot"}:
        return (True, "This action will interact with a real browser page.")
    return (False, "")


def _confirm(job_id: str, name: str, args: dict, reason: str) -> bool:
    approval_id = runtime.create_approval(job_id, {
        "tool": name,
        "arguments": {k: (str(v)[:500] if isinstance(v, str) else v) for k, v in list(args.items())[:12]},
        "reason": reason,
    })
    event(job_id, "waiting_approval", "Waiting for approval: " + name, {"approval_id": approval_id, "tool": name})
    approved = runtime.wait_for_approval(job_id, approval_id, lambda: is_cancelled(job_id), timeout=3600)
    if not approved:
        with runtime.connect() as db:
            db.execute("UPDATE jobs SET status='running',updated_at=? WHERE id=? AND status='awaiting_approval'",
                       (time.time(), job_id))
        event(job_id, "approval_denied", "Action was not approved.")
    else:
        with runtime.connect() as db:
            db.execute("UPDATE jobs SET status='running',updated_at=? WHERE id=? AND status='awaiting_approval'",
                       (time.time(), job_id))
    return approved


def execute_tool(job_id: str, name: str, args: dict, payload: dict) -> str:
    if not isinstance(args, dict):
        raise ValueError("Tool arguments must be a JSON object.")
    needs_approval, reason = _approval_required(name, args, payload)
    if needs_approval and not _confirm(job_id, name, args, reason):
        return "User denied this action. Do not retry it unless the user explicitly asks."
    if is_cancelled(job_id):
        return "Task was cancelled before this action started."

    if name == "calculator":
        expression = str(args.get("expression", ""))
        if not re.fullmatch(r"[\d\s.+\-*/()%]+", expression) or not expression.strip():
            raise ValueError("Only basic arithmetic is supported.")
        import ast
        def evaluate(node):
            if isinstance(node, ast.Expression): return evaluate(node.body)
            if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)): return node.value
            if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
                value = evaluate(node.operand); return value if isinstance(node.op, ast.UAdd) else -value
            if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod, ast.Pow)):
                left, right = evaluate(node.left), evaluate(node.right)
                if isinstance(node.op, ast.Add): return left + right
                if isinstance(node.op, ast.Sub): return left - right
                if isinstance(node.op, ast.Mult): return left * right
                if isinstance(node.op, ast.Div): return left / right
                if isinstance(node.op, ast.Mod): return left % right
                if abs(right) > 100 or abs(left) > 1000000000: raise ValueError("Arithmetic exponent or value is too large.")
                return left ** right
            raise ValueError("Unsupported arithmetic expression.")
        return str(evaluate(ast.parse(expression, mode="eval")))

    if name == "get_current_datetime":
        return time.strftime("%Y-%m-%d %H:%M:%S %Z", time.localtime())

    if name in {"skill_list", "skill_read"}:
        if name == "skill_list":
            return "\n".join(item["id"] + " · " + item["name"] + " — " + item["description"]
                             for item in server.list_available_skills()) or "No skills installed."
        return server.read_available_skill(args.get("id"))

    if name.startswith("browser_") or name.startswith("computer_"):
        import agent_automation
        if name.startswith("browser_"):
            if not agent_automation.capabilities()["browser"]:
                raise RuntimeError("Install the optional Playwright dependencies before using Browser Automation.")
            return agent_automation.browser_tool(name, args, job_id)
        if not agent_automation.capabilities()["computer"]:
            raise RuntimeError("Install the optional pywinauto dependencies on Windows before using Computer Use.")
        return agent_automation.computer_tool(name, args, job_id)

    if name == "workspace_list_projects":
        items = []
        for item in server.WORKSPACE_ROOT.iterdir():
            if item.is_dir() and not item.is_symlink():
                items.append(item.name + " · " + str(item))
        for key, value in server.WORKSPACE_ROOTS.items():
            items.append(key + " · " + value["name"] + " · " + value["path"])
        return "\n".join(items) or "No projects exist yet."
    if name == "workspace_create_project":
        label = str(args.get("name", "")).strip()
        if not label or len(label) > 100:
            raise ValueError("Enter a project name from 1 to 100 characters.")
        slug = re.sub(r"[^a-z0-9._-]+", "-", label.lower()).strip("-._")[:50] or ("project-" + uuid.uuid4().hex[:8])
        target = server.project_dir(slug, must_exist=False)
        if target.exists():
            raise ValueError("A project with that name already exists.")
        target.mkdir(parents=True)
        server.write_project_memory(slug, {"goal": "Project created by background Agent.", "summary": "New project.",
                                           "stack": [], "decisions": [], "completed": ["Created project folder."],
                                           "next_steps": ["Inspect requirements and implement the requested work."]})
        payload["activeProject"] = slug
        return "Created project " + slug + " at " + str(target)
    if name == "workspace_list_files":
        return "\n".join(item["path"] + " (" + str(item["bytes"]) + " bytes)"
                         for item in server.list_project_files(_project(args, payload))) or "Project is empty."
    if name == "workspace_find_files":
        return "\n".join(item["path"] for item in server.find_project_files(_project(args, payload), args.get("query", ""))) or "No matching files."
    if name == "workspace_search_text":
        result = server.search_project_text(_project(args, payload), args.get("query", ""))
        return json.dumps(result, ensure_ascii=False)[:24000]
    if name == "workspace_read_file":
        project = _project(args, payload)
        relative = str(args.get("path", ""))
        _, target = server.safe_workspace_path(project, relative)
        if not target.is_file() or target.stat().st_size > server.MAX_WORKSPACE_FILE_BYTES:
            raise ValueError("File does not exist or exceeds the 2 MB read limit.")
        return "FILE: " + relative + "\n" + target.read_text(encoding="utf-8")
    if name == "workspace_write_file":
        project = _project(args, payload)
        relative = str(args.get("path", ""))
        _, target = server.safe_workspace_path(project, relative)
        value = args.get("content")
        if not isinstance(value, str) or len(value.encode("utf-8")) > server.MAX_WORKSPACE_FILE_BYTES:
            raise ValueError("File content must be text no larger than 2 MB.")
        target.parent.mkdir(parents=True, exist_ok=True)
        _, target = server.safe_workspace_path(project, relative)
        target.write_text(value, encoding="utf-8", newline="\n")
        return "Saved " + relative + " (" + str(target.stat().st_size) + " bytes)."
    if name == "workspace_create_directory":
        project = _project(args, payload)
        _, target = server.safe_workspace_path(project, args.get("path"))
        if target.exists() and not target.is_dir():
            raise ValueError("A file already exists at that path.")
        target.mkdir(parents=True, exist_ok=True)
        return "Created directory " + str(args.get("path"))
    if name == "workspace_move_file":
        project = _project(args, payload)
        source_rel = str(args.get("source", ""))
        dest_rel = str(args.get("destination", ""))
        _, source = server.safe_workspace_path(project, source_rel)
        _, destination = server.safe_workspace_path(project, dest_rel)
        if not source.is_file() or source.is_symlink() or destination.exists() or destination.is_symlink():
            raise ValueError("Source must exist and destination must be unused.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        _, destination = server.safe_workspace_path(project, dest_rel)
        source.replace(destination)
        return "Moved " + source_rel + " to " + dest_rel
    if name == "workspace_delete_file":
        project = _project(args, payload)
        _, target = server.safe_workspace_path(project, args.get("path"))
        if not target.is_file() or target.is_symlink():
            raise ValueError("Only an individual regular file can be deleted.")
        target.unlink()
        return "Deleted " + str(args.get("path"))
    if name == "workspace_run_command":
        result = server.run_project_command(_project(args, payload), args.get("command"))
        if result["exit_code"] != 0:
            raise RuntimeError("Command failed with exit code " + str(result["exit_code"]) + ":\n" + result["output"])
        return "Command succeeded.\n" + result["output"]
    if name == "workspace_terminal":
        result = server.run_guarded_terminal(_project(args, payload), args.get("command"))
        if result["exit_code"] != 0:
            raise RuntimeError("Terminal command failed with exit code " + str(result["exit_code"]) +
                               (" (timed out)" if result.get("timed_out") else "") + ":\n" + result["output"])
        return "Terminal command completed (exit code 0).\n" + result["output"]
    if name == "workspace_start_project":
        result = server.start_project_server(_project(args, payload))
        return "Started " + str(result.get("runtime")) + " at " + str(result.get("url"))
    if name == "workspace_stop_project":
        project = _project(args, payload)
        result = server.stop_project_server(project)
        server.stop_project_preview(project)
        return "Project server stopped." if result.get("stopped") else "No project server was running."
    if name == "workspace_project_status":
        result = server.project_server_status(_project(args, payload))
        return json.dumps(result, ensure_ascii=False)
    if name == "workspace_read_memory":
        return json.dumps(server.read_project_memory(_project(args, payload)), ensure_ascii=False, indent=2)
    if name == "workspace_update_memory":
        project = _project(args, payload)
        memory = {k: args[k] for k in ("summary", "goal", "stack", "decisions", "completed", "next_steps") if k in args}
        return json.dumps(server.write_project_memory(project, memory), ensure_ascii=False)
    if name == "workspace_preview":
        project = _project(args, payload)
        status = server.project_server_status(project)
        if status["running"]:
            return "Preview URL: " + str(status["url"])
        return "Preview URL: " + str(server.start_project_preview(project)["url"])
    raise ValueError("Unsupported background Agent tool: " + name)


def run_job(job_id: str) -> None:
    job = runtime.load_job_for_worker(job_id)
    if not job:
        return
    payload = job["payload"]
    cp = job["checkpoint"] or {}
    history = cp.get("history") if isinstance(cp.get("history"), list) else payload.get("history", [])
    tools = payload.get("tools", [])
    turns = int(cp.get("turns", 0))
    tool_calls = int(cp.get("tool_calls", 0))
    max_runtime = int(payload.get("maxRuntimeMs", 0) or 0)
    deadline = int(payload.get("deadlineAt", 0) or 0)
    if max_runtime:
        # Re-base the run window when the job is first picked up or resumed.
        if not deadline or cp.get("resume_window"):
            deadline = int(time.time() * 1000) + max_runtime
        cp.pop("resume_window", None)
        payload["deadlineAt"] = deadline
    else:
        payload["deadlineAt"] = 0

    pending = cp.get("pending_tool_call")
    if pending:
        call_id = str(pending.get("id", ""))
        history.append({"role": "tool", "tool_call_id": call_id,
                        "content": "The background worker restarted while this tool was running. Its outcome is unknown. Inspect the current workspace or application state before deciding whether to retry."})
        event(job_id, "recovery", "Recovered an interrupted tool call without replaying it.")
        cp["pending_tool_call"] = None
        cp["history"] = history
        checkpoint(job_id, cp)

    event(job_id, "progress", "Agent task resumed in the independent Windows worker.")
    try:
        while True:
            if is_cancelled(job_id):
                runtime.complete_job(job_id, "cancelled", error="Stopped by the user.")
                return
            if payload.get("deadlineAt") and int(time.time() * 1000) >= int(payload["deadlineAt"]):
                runtime.complete_job(job_id, "paused", error="Configured Agent run window expired. Resume to start another time window.")
                return
            if turns >= MAX_TURNS:
                turns = 0
                cp.update({"history": history, "turns": turns, "tool_calls": tool_calls})
                checkpoint(job_id, cp)
                event(job_id, "checkpoint", "Automatic checkpoint saved after 500 model turns; continuing.")
            if tool_calls >= MAX_TOOL_CALLS:
                tool_calls = 0
                cp.update({"history": history, "turns": turns, "tool_calls": tool_calls})
                checkpoint(job_id, cp)
                event(job_id, "checkpoint", "Automatic checkpoint saved after 2,000 tool calls; continuing.")

            turns += 1
            cp.update({"history": history, "turns": turns, "tool_calls": tool_calls})
            checkpoint(job_id, cp)
            event(job_id, "model", "Contacting model · turn " + str(turns))
            message = provider_completion(job, history, tools)
            history.append(message)
            cp.update({"history": history, "turns": turns, "tool_calls": tool_calls})
            checkpoint(job_id, cp)

            calls = message.get("tool_calls")
            if isinstance(calls, list) and calls:
                for call in calls:
                    if is_cancelled(job_id):
                        break
                    function = call.get("function", {}) if isinstance(call, dict) else {}
                    name = str(function.get("name", ""))
                    call_id = str(call.get("id", ""))[:200]
                    try:
                        args = json.loads(function.get("arguments") or "{}")
                        if not isinstance(args, dict):
                            raise ValueError("Tool arguments must be an object.")
                        cp["pending_tool_call"] = {"id": call_id, "name": name, "args": args}
                        cp["history"] = history
                        checkpoint(job_id, cp)
                        with runtime.connect() as db:
                            db.execute("UPDATE jobs SET current_tool_json=?,updated_at=? WHERE id=?",
                                       (json.dumps({"name": name}, ensure_ascii=False),
                                        time.time(), job_id))
                        event(job_id, "tool_start", "Running tool: " + name, {"tool": name})
                        try:
                            output = execute_tool(job_id, name, args, payload)
                        except Exception as exc:
                            output = "TOOL ERROR: " + str(exc)[:3000]
                            event(job_id, "tool_error", name + " failed. See the encrypted task history for details.")
                        history.append({"role": "tool", "tool_call_id": call_id, "content": str(output)[:30000]})
                        cp["pending_tool_call"] = None
                        cp["history"] = history
                        tool_calls += 1
                        cp["tool_calls"] = tool_calls
                        checkpoint(job_id, cp)
                        with runtime.connect() as db:
                            db.execute("UPDATE jobs SET current_tool_json=NULL,status='running',updated_at=? WHERE id=?",
                                       (time.time(), job_id))
                        event(job_id, "tool_result", "Tool finished: " + name, {"tool": name})
                    except Exception as exc:
                        history.append({"role": "tool", "tool_call_id": call_id, "content": "Tool execution failed: " + str(exc)[:2000]})
                        cp["pending_tool_call"] = None
                        cp["history"] = history
                        checkpoint(job_id, cp)
                continue

            answer = message.get("content")
            if not isinstance(answer, str) or not answer.strip():
                history.append({"role": "user", "content": "Your previous response was empty. Continue the task and do not claim completion until the requested work is verified."})
                cp.update({"history": history, "turns": turns, "tool_calls": tool_calls})
                checkpoint(job_id, cp)
                continue
            runtime.complete_job(job_id, "completed", result=answer)
            return
    except Exception as exc:
        detail = str(exc)[:3500]
        cp.update({"history": history, "turns": turns, "tool_calls": tool_calls})
        try:
            checkpoint(job_id, cp)
        except Exception:
            pass
        runtime.complete_job(job_id, "failed", error=detail)
        event(job_id, "error", "Background Agent failed. The encrypted task checkpoint was retained.")
    finally:
        try:
            import agent_automation
            agent_automation.cleanup_browser_session(job_id)
        except Exception:
            pass


def main() -> int:
    runtime.initialize()
    pid = os.getpid()
    runtime.mark_running_jobs_interrupted()
    last_activity = time.monotonic()
    runtime.worker_heartbeat(pid)
    last_heartbeat = 0.0
    try:
        while True:
            now = time.monotonic()
            if now - last_heartbeat >= HEARTBEAT_SECONDS:
                runtime.worker_heartbeat(pid)
                last_heartbeat = now
            job_id = runtime.claim_next_job(pid)
            if job_id:
                last_activity = time.monotonic()
                run_job(job_id)
                last_activity = time.monotonic()
                continue
            if now - last_activity >= runtime.WORKER_IDLE_SECONDS:
                if runtime.release_worker_if_idle(pid):
                    return 0
                last_activity = time.monotonic()
            time.sleep(0.7)
    finally:
        runtime.worker_stopped(pid)


if __name__ == "__main__":
    raise SystemExit(main())
