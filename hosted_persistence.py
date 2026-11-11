"""Neon-backed persistence for the hosted workspace.

Render Free has an ephemeral filesystem. Neon is the durable source of truth;
the local folders used by server.py are only a temporary working cache.
"""
import hashlib
import os
from pathlib import Path, PurePosixPath

import server as core

MAX_TOTAL_BYTES = 400 * 1024 * 1024
MAX_PROJECT_BYTES = 100 * 1024 * 1024
MAX_PROJECT_FILES = 4000
MAX_SKILL_BYTES = 3 * 1024 * 1024
MAX_SINGLE_FILE_BYTES = core.MAX_WORKSPACE_FILE_BYTES
CHUNK_SIZE = 8


class NeonWorkspaceStore:
    def __init__(self, database_url):
        if not isinstance(database_url, str) or not database_url.strip():
            raise ValueError("NEON_DATABASE_URL is required for persistent hosted storage.")
        self.database_url = database_url.strip()

    def _connect(self):
        try:
            import psycopg
        except ImportError as exc:
            raise RuntimeError("The PostgreSQL driver is missing. Install requirements-hosted.txt.") from exc
        return psycopg.connect(self.database_url, connect_timeout=10)

    @staticmethod
    def validate_project_id(project_id):
        if not isinstance(project_id, str) or not core.PROJECT_ID_RE.fullmatch(project_id):
            raise ValueError("Invalid project ID for persistent storage.")
        return project_id

    @staticmethod
    def validate_relative_path(relative_path, allow_memory=True):
        if not isinstance(relative_path, str) or not relative_path or len(relative_path) > 500:
            raise ValueError("Invalid persisted file path.")
        if "\\" in relative_path or "\x00" in relative_path:
            raise ValueError("Invalid persisted file path.")
        path = PurePosixPath(relative_path)
        parts = path.parts
        if path.is_absolute() or not parts or any(p in {"", ".", ".."} for p in parts):
            raise ValueError("Persisted paths must remain inside one project.")
        if relative_path.startswith("/") or ":" in parts[0]:
            raise ValueError("Persisted paths must be relative.")
        if allow_memory and parts == (".vibe", "memory.json"):
            return relative_path
        for part in parts:
            if core.blocked_workspace_name(part):
                raise ValueError("Secret and private paths cannot be persisted.")
        return relative_path

    @staticmethod
    def _digest_file(path):
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(128 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
        return digest.hexdigest()

    def ensure_schema(self):
        statements = [
            """CREATE TABLE IF NOT EXISTS vibe_projects (
                project_id TEXT PRIMARY KEY,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )""",
            """CREATE TABLE IF NOT EXISTS vibe_project_files (
                project_id TEXT NOT NULL REFERENCES vibe_projects(project_id) ON DELETE CASCADE,
                path TEXT NOT NULL,
                content BYTEA NOT NULL,
                sha256 TEXT NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (project_id, path)
            )""",
            """CREATE TABLE IF NOT EXISTS vibe_custom_skill_files (
                skill_id TEXT NOT NULL,
                path TEXT NOT NULL,
                content BYTEA NOT NULL,
                sha256 TEXT NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (skill_id, path)
            )""",
        ]
        with self._connect() as conn:
            with conn.cursor() as cur:
                for statement in statements:
                    cur.execute(statement)

    def ping(self):
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                return cur.fetchone()[0] == 1

    def _other_storage_bytes(self, cur, excluded_project=None):
        if excluded_project is None:
            cur.execute("SELECT COALESCE(SUM(octet_length(content)), 0) FROM vibe_project_files")
        else:
            cur.execute(
                "SELECT COALESCE(SUM(octet_length(content)), 0) FROM vibe_project_files WHERE project_id <> %s",
                (excluded_project,),
            )
        project_bytes = int(cur.fetchone()[0] or 0)
        cur.execute("SELECT COALESCE(SUM(octet_length(content)), 0) FROM vibe_custom_skill_files")
        skill_bytes = int(cur.fetchone()[0] or 0)
        return project_bytes + skill_bytes

    def _collect_project_files(self, project_root):
        root = Path(project_root)
        if root.is_symlink() or not root.is_dir():
            raise ValueError("The hosted project directory is missing or unsafe.")
        items = []
        total = 0
        for current, dirs, filenames in os.walk(root, topdown=True, followlinks=False):
            current_path = Path(current)
            relative_parts = current_path.relative_to(root).parts
            safe_dirs = []
            for name in dirs:
                candidate = current_path / name
                if candidate.is_symlink():
                    continue
                if name == ".vibe" and not relative_parts:
                    safe_dirs.append(name)
                    continue
                if name in core.IGNORED_DIRS or core.blocked_workspace_name(name):
                    continue
                safe_dirs.append(name)
            dirs[:] = safe_dirs
            for filename in filenames:
                path = current_path / filename
                if path.is_symlink() or not path.is_file():
                    continue
                relative = path.relative_to(root).as_posix()
                is_memory = relative == ".vibe/memory.json"
                if relative.startswith(".vibe/") and not is_memory:
                    continue
                if is_memory:
                    if path.stat().st_size > core.MAX_PROJECT_MEMORY_BYTES:
                        raise ValueError("Project memory is too large to persist.")
                else:
                    self.validate_relative_path(relative, allow_memory=False)
                size = path.stat().st_size
                if size > MAX_SINGLE_FILE_BYTES:
                    raise ValueError("A project file exceeds the 2 MB hosted persistence limit: " + relative)
                total += size
                if total > MAX_PROJECT_BYTES:
                    raise ValueError("A project exceeds the 100 MB hosted storage limit.")
                items.append((relative, path, size, self._digest_file(path)))
                if len(items) > MAX_PROJECT_FILES:
                    raise ValueError("A project exceeds the 4,000-file hosted persistence limit.")
        return items, total

    def _collect_skill_files(self, skills_root):
        root = Path(skills_root)
        root.mkdir(parents=True, exist_ok=True)
        if root.is_symlink():
            raise ValueError("The custom skills directory cannot be a symbolic link.")
        items = []
        total = 0
        for folder in sorted(root.iterdir(), key=lambda p: p.name.lower()):
            if not folder.is_dir() or folder.is_symlink() or not core.SKILL_NAME_RE.fullmatch(folder.name):
                continue
            skill_file = folder / "SKILL.md"
            if not skill_file.is_file() or skill_file.is_symlink():
                continue
            for current, dirs, filenames in os.walk(folder, topdown=True, followlinks=False):
                current_path = Path(current)
                dirs[:] = [
                    name for name in dirs
                    if not (current_path / name).is_symlink()
                    and not core.blocked_workspace_name(name)
                    and name not in core.IGNORED_DIRS
                ]
                for filename in filenames:
                    path = current_path / filename
                    if path.is_symlink() or not path.is_file():
                        continue
                    relative = path.relative_to(folder).as_posix()
                    self.validate_relative_path(relative, allow_memory=False)
                    if path.suffix.lower() not in core.SKILL_ALLOWED_EXTENSIONS:
                        raise ValueError("A custom skill contains an unsupported file type.")
                    size = path.stat().st_size
                    if size > 256 * 1024:
                        raise ValueError("A custom skill file exceeds 256 KB.")
                    total += size
                    if total > MAX_SKILL_BYTES:
                        raise ValueError("Custom skills exceed the 3 MB hosted storage limit.")
                    items.append((folder.name, relative, path, size, self._digest_file(path)))
        return items, total

    def sync_project(self, project_id, project_root):
        project_id = self.validate_project_id(project_id)
        items, project_size = self._collect_project_files(project_root)
        with self._connect() as conn:
            with conn.cursor() as cur:
                other_bytes = self._other_storage_bytes(cur, excluded_project=project_id)
                if other_bytes + project_size > MAX_TOTAL_BYTES:
                    raise ValueError("Hosted Neon storage limit reached (400 MB). Remove unused files or projects.")
                cur.execute(
                    "INSERT INTO vibe_projects(project_id) VALUES (%s) "
                    "ON CONFLICT(project_id) DO UPDATE SET updated_at = NOW()",
                    (project_id,),
                )
                cur.execute(
                    "SELECT path, sha256 FROM vibe_project_files WHERE project_id = %s",
                    (project_id,),
                )
                existing = dict(cur.fetchall())
                current_paths = {item[0] for item in items}
                for old_path in existing:
                    if old_path not in current_paths:
                        cur.execute(
                            "DELETE FROM vibe_project_files WHERE project_id = %s AND path = %s",
                            (project_id, old_path),
                        )
                for relative, path, size, digest in items:
                    if existing.get(relative) == digest:
                        continue
                    content = path.read_bytes()
                    if len(content) != size or hashlib.sha256(content).hexdigest() != digest:
                        raise ValueError("A project file changed while it was being saved. Retry the save.")
                    cur.execute(
                        """INSERT INTO vibe_project_files(project_id, path, content, sha256)
                           VALUES (%s, %s, %s, %s)
                           ON CONFLICT(project_id, path) DO UPDATE
                           SET content = EXCLUDED.content, sha256 = EXCLUDED.sha256, updated_at = NOW()""",
                        (project_id, relative, content, digest),
                    )
        return {"files": len(items), "bytes": project_size}

    def sync_skills(self, skills_root):
        items, skill_size = self._collect_skill_files(skills_root)
        with self._connect() as conn:
            with conn.cursor() as cur:
                other_bytes = self._other_storage_bytes(cur)
                cur.execute("SELECT COALESCE(SUM(octet_length(content)), 0) FROM vibe_custom_skill_files")
                old_skill_bytes = int(cur.fetchone()[0] or 0)
                if other_bytes - old_skill_bytes + skill_size > MAX_TOTAL_BYTES:
                    raise ValueError("Hosted Neon storage limit reached (400 MB). Remove unused files or projects.")
                cur.execute("SELECT skill_id, path, sha256 FROM vibe_custom_skill_files")
                existing = {(row[0], row[1]): row[2] for row in cur.fetchall()}
                current_keys = {(item[0], item[1]) for item in items}
                for old_skill, old_path in existing:
                    if (old_skill, old_path) not in current_keys:
                        cur.execute(
                            "DELETE FROM vibe_custom_skill_files WHERE skill_id = %s AND path = %s",
                            (old_skill, old_path),
                        )
                for skill_id, relative, path, size, digest in items:
                    if existing.get((skill_id, relative)) == digest:
                        continue
                    content = path.read_bytes()
                    if len(content) != size or hashlib.sha256(content).hexdigest() != digest:
                        raise ValueError("A custom skill changed while it was being saved. Retry the upload.")
                    cur.execute(
                        """INSERT INTO vibe_custom_skill_files(skill_id, path, content, sha256)
                           VALUES (%s, %s, %s, %s)
                           ON CONFLICT(skill_id, path) DO UPDATE
                           SET content = EXCLUDED.content, sha256 = EXCLUDED.sha256, updated_at = NOW()""",
                        (skill_id, relative, content, digest),
                    )
        return {"files": len(items), "bytes": skill_size}

    def _restore_file(self, root, owner, relative, content):
        self.validate_relative_path(relative, allow_memory=True)
        target_root = Path(root) / owner
        if target_root.is_symlink():
            raise ValueError("A restored workspace directory is unsafe.")
        target_root.mkdir(parents=True, exist_ok=True)
        target_root = target_root.resolve()
        parts = PurePosixPath(relative).parts
        cursor = target_root
        for part in parts[:-1]:
            cursor = cursor / part
            if cursor.exists() and cursor.is_symlink():
                raise ValueError("A restored workspace path contains a symbolic link.")
            cursor.mkdir(exist_ok=True)
        target = cursor / parts[-1]
        if target.is_symlink():
            raise ValueError("A restored workspace file is a symbolic link.")
        target.resolve().relative_to(target_root)
        target.write_bytes(bytes(content))

    def restore_all(self, projects_root, skills_root):
        projects = Path(projects_root)
        skills = Path(skills_root)
        projects.mkdir(parents=True, exist_ok=True)
        skills.mkdir(parents=True, exist_ok=True)
        if projects.is_symlink() or skills.is_symlink():
            raise ValueError("Hosted cache directories cannot be symbolic links.")
        restored_projects = 0
        restored_project_files = 0
        restored_skill_files = 0
        with self._connect() as conn:
            with conn.cursor(name="vibe_restore_projects") as cur:
                cur.execute("SELECT project_id FROM vibe_projects ORDER BY project_id")
                while True:
                    ids = cur.fetchmany(64)
                    if not ids:
                        break
                    for (project_id,) in ids:
                        self.validate_project_id(project_id)
                        (projects / project_id).mkdir(exist_ok=True)
                        restored_projects += 1
                        cursor_name = "vibe_restore_" + hashlib.sha1(project_id.encode()).hexdigest()[:16]
                        with conn.cursor(name=cursor_name) as file_cur:
                            file_cur.execute(
                                "SELECT path, content FROM vibe_project_files WHERE project_id = %s ORDER BY path",
                                (project_id,),
                            )
                            while True:
                                rows = file_cur.fetchmany(CHUNK_SIZE)
                                if not rows:
                                    break
                                for relative, content in rows:
                                    self._restore_file(projects, project_id, relative, content)
                                    restored_project_files += 1
            with conn.cursor(name="vibe_restore_skills") as cur:
                cur.execute(
                    "SELECT skill_id, path, content FROM vibe_custom_skill_files ORDER BY skill_id, path"
                )
                while True:
                    rows = cur.fetchmany(CHUNK_SIZE)
                    if not rows:
                        break
                    for skill_id, relative, content in rows:
                        if not core.SKILL_NAME_RE.fullmatch(skill_id):
                            raise ValueError("A saved custom skill ID is invalid.")
                        if Path(relative).suffix.lower() not in core.SKILL_ALLOWED_EXTENSIONS:
                            raise ValueError("A saved custom skill contains an unsupported file type.")
                        self._restore_file(skills, skill_id, relative, content)
                        restored_skill_files += 1
        return {
            "projects": restored_projects,
            "project_files": restored_project_files,
            "skill_files": restored_skill_files,
        }
