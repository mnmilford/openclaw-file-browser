#!/usr/bin/env python3
import json
import contextlib
import errno
import heapq
import mimetypes
import os
import queue
import shutil
import socket
import sqlite3
import subprocess
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

try:
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer
except Exception:  # pragma: no cover - optional dependency safety
    FileSystemEventHandler = object
    Observer = None


def load_env_file(path):
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = value


def env_path(name, default):
    value = os.environ.get(name, "").strip()
    return Path(value).expanduser() if value else Path(default)


def env_str(name, default):
    value = os.environ.get(name, "").strip()
    return value if value else default


def env_int(name, default):
    value = os.environ.get(name, "").strip()
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


BASE_DIR = Path(__file__).resolve().parent
SEARCH_INDEX_DB = BASE_DIR / "search_index.db"
SEARCH_INDEX_LIMIT = 500
SEARCH_INDEX_BATCH_SIZE = 250
load_env_file(BASE_DIR / ".env")
load_env_file(BASE_DIR / ".env.local")
SEARCH_INDEX_SCAN_INTERVAL = env_int(
    "OPENCLAW_FILE_BROWSER_SEARCH_RESCAN_INTERVAL",
    1800,
)
INDEX_PATH = BASE_DIR / "index.html"
CHAT_PATH = BASE_DIR / "chat.html"
CHAT_TRANSCRIPT_PATH = BASE_DIR / "chat-transcript.html"
FILES_PATH = BASE_DIR / "files.html"
TRASH_DIR = BASE_DIR / ".trash"
PRIME_DIRECTORIES_PATH = BASE_DIR / "prime_directories.json"
FAVORITES_ORDER_PATH = BASE_DIR / "favorites_order.json"
UPLOADS_DIR = env_path("OPENCLAW_FILE_BROWSER_UPLOADS_DIR", str(BASE_DIR / "uploads"))
ROOT_HOME_DIR = env_path("OPENCLAW_FILE_BROWSER_HOME_DIR", "/root")
PROJECTS_DIR = env_path(
    "OPENCLAW_FILE_BROWSER_PROJECTS_DIR",
    str(ROOT_HOME_DIR / "Projects"),
)
LOCAL_DASHBOARD_DIR = env_path(
    "OPENCLAW_FILE_BROWSER_DASHBOARD_DIR",
    str(BASE_DIR),
)
OPENCLAW_INSTALL_DIR = env_path(
    "OPENCLAW_INSTALL_DIR",
    "/opt/openclaw",
)
OPENCLAW_HOME = env_path("OPENCLAW_HOME_DIR", "/root/.openclaw")
OPENCLAW_WORKSPACE = env_path("OPENCLAW_WORKSPACE_DIR", str(OPENCLAW_HOME / "workspace"))
OPENCLAW_RESEARCH_MEMORY = env_path(
    "OPENCLAW_RESEARCH_MEMORY_DIR",
    str(OPENCLAW_WORKSPACE / "memory" / "research"),
)
OPENCLAW_SESSIONS_DIR = env_path(
    "OPENCLAW_SESSIONS_DIR",
    str(OPENCLAW_HOME / "agents" / "main" / "sessions"),
)
PROJECT_OUTPUT_DIR = env_path(
    "OPENCLAW_FILE_BROWSER_PROJECT_DIR",
    str(PROJECTS_DIR / "deepfield-transmissions"),
)
OPENCLAW_SERVICE_NAME = env_str("OPENCLAW_SERVICE_NAME", "openclaw.service")
DASHBOARD_SERVICE_NAME = env_str(
    "OPENCLAW_FILE_BROWSER_SERVICE_NAME",
    "local-dashboard-1455.service",
)
GATEWAY_URL = env_str("OPENCLAW_GATEWAY_URL", "http://127.0.0.1:18789")
HOST = env_str("OPENCLAW_FILE_BROWSER_HOST", "127.0.0.1")
PORT = env_int("OPENCLAW_FILE_BROWSER_PORT", 1455)
ALLOWED_ACTIONS = {
    "restart_openclaw": ["systemctl", "restart", OPENCLAW_SERVICE_NAME],
}
ALLOWED_LOG_SERVICES = {OPENCLAW_SERVICE_NAME, DASHBOARD_SERVICE_NAME}
_SPURS_CACHE = {"ts": 0.0, "data": None}
_RECENT_CACHE = {"ts": 0.0, "limit": 0, "items": []}
_RECENT_LOCK = threading.Lock()
_PRIME_LOCK = threading.RLock()
_FAVORITES_ORDER_LOCK = threading.Lock()
RECENT_SCAN_TTL = 120
RECENT_ROOT_IDS = (
    "uploads",
    "dashboard",
    "workspace",
    "projects",
    "deepfield",
    "lil-mike-memory",
)
TEXT_EXTENSIONS = {
    ".c", ".cc", ".cfg", ".conf", ".cpp", ".css", ".csv", ".env", ".gitignore", ".go",
    ".h", ".html", ".ini", ".java", ".js", ".json", ".jsonl", ".log", ".md", ".mjs",
    ".py", ".rb", ".rs", ".sh", ".sql", ".svg", ".toml", ".ts", ".tsx", ".txt", ".xml",
    ".yaml", ".yml",
}
IMAGE_EXTENSIONS = {".avif", ".gif", ".jpeg", ".jpg", ".png", ".svg", ".webp"}
SKIP_NAMES = {".git", ".trash", "node_modules", "__pycache__", ".openclaw.bak.nested"}
FILE_LIST_LIMIT = 250
MAP_ROOT_ID = "root-home"
WATCH_ROOTS = {
    "root-home": {
        "label": "Root home",
        "path": ROOT_HOME_DIR,
        "description": "Broad droplet browser rooted at /root.",
    },
    "uploads": {
        "label": "Browser uploads",
        "path": UPLOADS_DIR,
        "description": "Files uploaded through the browser UI.",
    },
    "core-state": {
        "label": "Core state",
        "path": OPENCLAW_HOME,
        "description": "Main OpenClaw state, config, logs, cron, media.",
    },
    "workspace": {
        "label": "Workspace",
        "path": OPENCLAW_WORKSPACE,
        "description": "Agent workspace, skills, knowledge, scripts, memory.",
    },
    "dashboard": {
        "label": "Local dashboard",
        "path": LOCAL_DASHBOARD_DIR,
        "description": "Dashboard app source, uploads, and local UI assets.",
    },
    "projects": {
        "label": "Projects",
        "path": PROJECTS_DIR,
        "description": "Project repositories and non-OpenClaw working trees.",
    },
    "lil-mike-memory": {
        "label": "Research memory",
        "path": OPENCLAW_RESEARCH_MEMORY,
        "description": "Research notes, journals, and working topic outputs.",
    },
    "deepfield": {
        "label": "Deepfield repo",
        "path": PROJECT_OUTPUT_DIR,
        "description": "Primary Deepfield project repo and published assets.",
    },
    "opt-openclaw": {
        "label": "OpenClaw install",
        "path": OPENCLAW_INSTALL_DIR,
        "description": "Static install data under /opt/openclaw.",
    },
    "sessions": {
        "label": "Agent sessions",
        "path": OPENCLAW_SESSIONS_DIR,
        "description": "Session JSONL transcripts and agent execution history.",
    },
    "tmp": {
        "label": "Temp files",
        "path": Path("/tmp"),
        "description": "Temporary files, image previews, and scratch outputs.",
    },
}
SEARCH_INDEX_ROOT_IDS = (
    "uploads",
    "dashboard",
    "workspace",
    "lil-mike-memory",
    "deepfield",
    "sessions",
    "core-state",
    "projects",
    "opt-openclaw",
)
FAVORITES = [
    {
        "label": "/root",
        "root": "root-home",
        "path": "",
        "kind": "dir",
    },
    {
        "label": "OpenClaw config",
        "root": "core-state",
        "path": "openclaw.json",
        "kind": "file",
    },
    {
        "label": "OpenClaw logs",
        "root": "core-state",
        "path": "logs",
        "kind": "dir",
    },
    {
        "label": "Workspace memory",
        "root": "workspace",
        "path": "memory",
        "kind": "dir",
    },
    {
        "label": "Research journals",
        "root": "lil-mike-memory",
        "path": "private",
        "kind": "dir",
    },
    {
        "label": "Local dashboard",
        "root": "dashboard",
        "path": "",
        "kind": "dir",
    },
    {
        "label": "Projects",
        "root": "projects",
        "path": "",
        "kind": "dir",
    },
    {
        "label": "Deepfield research",
        "root": "deepfield",
        "path": "research",
        "kind": "dir",
    },
    {
        "label": "Deepfield assets",
        "root": "deepfield",
        "path": "instagram",
        "kind": "dir",
    },
    {
        "label": "OpenClaw install",
        "root": "opt-openclaw",
        "path": "",
        "kind": "dir",
    },
]


class SearchIndexEventHandler(FileSystemEventHandler):
    def __init__(self, manager):
        super().__init__()
        self.manager = manager

    def on_created(self, event):
        self.manager.enqueue_event("created", event.src_path, is_directory=event.is_directory)

    def on_modified(self, event):
        self.manager.enqueue_event("modified", event.src_path, is_directory=event.is_directory)

    def on_deleted(self, event):
        self.manager.enqueue_event("deleted", event.src_path, is_directory=event.is_directory)

    def on_moved(self, event):
        self.manager.enqueue_event(
            "moved",
            event.src_path,
            dest_path=event.dest_path,
            is_directory=event.is_directory,
        )


class SearchIndexManager:
    def __init__(self, db_path):
        self.db_path = Path(db_path)
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._rescan_now = threading.Event()
        self._queue = queue.Queue(maxsize=1024)
        self._observer = None
        self._threads = []
        self._started = False
        self._indexed_root_ids = tuple(
            root_id for root_id in SEARCH_INDEX_ROOT_IDS if root_id in WATCH_ROOTS
        )
        self._indexed_root_paths = {
            root_id: WATCH_ROOTS[root_id]["path"].resolve()
            for root_id in self._indexed_root_ids
        }
        self._root_match_order = sorted(
            self._indexed_root_ids,
            key=lambda root_id: len(self._indexed_root_paths[root_id].parts),
            reverse=True,
        )
        self._watch_paths = self._compute_watch_paths(self._indexed_root_ids)
        self._fallback_watch_paths = self._watch_paths
        self._init_db()

    def _connect(self):
        con = sqlite3.connect(str(self.db_path), timeout=30)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=NORMAL")
        con.execute("PRAGMA busy_timeout=5000")
        return con

    def _init_db(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as con:
            cur = con.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS files (
                    id INTEGER PRIMARY KEY,
                    root TEXT NOT NULL,
                    path TEXT NOT NULL,
                    name TEXT NOT NULL,
                    size INTEGER NOT NULL DEFAULT 0,
                    mtime REAL NOT NULL DEFAULT 0,
                    kind TEXT NOT NULL,
                    ext TEXT NOT NULL DEFAULT '',
                    UNIQUE(root, path)
                )
                """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_files_root_path ON files(root, path)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_files_kind ON files(kind)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_files_ext ON files(ext)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_files_mtime ON files(mtime DESC)")
            cur.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS files_fts
                USING fts5(name, path, tokenize='trigram', content='files', content_rowid='id')
                """
            )
            cur.execute(
                """
                CREATE TRIGGER IF NOT EXISTS files_ai AFTER INSERT ON files BEGIN
                    INSERT INTO files_fts(rowid, name, path) VALUES (new.id, new.name, new.path);
                END
                """
            )
            cur.execute(
                """
                CREATE TRIGGER IF NOT EXISTS files_ad AFTER DELETE ON files BEGIN
                    INSERT INTO files_fts(files_fts, rowid, name, path)
                    VALUES ('delete', old.id, old.name, old.path);
                END
                """
            )
            cur.execute(
                """
                CREATE TRIGGER IF NOT EXISTS files_au AFTER UPDATE ON files BEGIN
                    INSERT INTO files_fts(files_fts, rowid, name, path)
                    VALUES ('delete', old.id, old.name, old.path);
                    INSERT INTO files_fts(rowid, name, path) VALUES (new.id, new.name, new.path);
                END
                """
            )
            file_count = cur.execute("SELECT count(*) FROM files").fetchone()[0]
            fts_count = cur.execute("SELECT count(*) FROM files_fts").fetchone()[0]
            if file_count and not fts_count:
                cur.execute("INSERT INTO files_fts(files_fts) VALUES ('rebuild')")

    def _compute_watch_paths(self, root_ids=None):
        if root_ids is None:
            source_roots = WATCH_ROOTS.values()
        else:
            source_roots = [WATCH_ROOTS[root_id] for root_id in root_ids if root_id in WATCH_ROOTS]
        roots = sorted(
            {meta["path"].resolve() for meta in source_roots},
            key=lambda path: len(path.parts),
        )
        selected = []
        for root_path in roots:
            if any(self._is_relative_to(root_path, existing) for existing in selected):
                continue
            selected.append(root_path)
        return selected

    @staticmethod
    def _is_relative_to(path_obj, other):
        try:
            path_obj.relative_to(other)
            return True
        except ValueError:
            return False

    def _is_index_artifact(self, abs_path):
        try:
            resolved = str(Path(abs_path).resolve(strict=False))
        except Exception:
            resolved = os.path.abspath(abs_path)
        db_path = str(self.db_path)
        return resolved == db_path or resolved.startswith(db_path + "-")

    def _best_matching_root(self, abs_path):
        abs_path_obj = Path(abs_path).resolve(strict=False)
        for root_id in self._root_match_order:
            root_path = self._indexed_root_paths[root_id]
            if self._is_relative_to(abs_path_obj, root_path):
                return root_id, root_path
        return None, None

    def _iter_root_entries(self, root_id):
        root_path = self._indexed_root_paths.get(root_id)
        if root_path is None:
            return
        if not root_path.exists():
            return
        root_str = str(root_path)
        for dirpath, dirnames, filenames in os.walk(root_str, topdown=True):
            kept_dirs = []
            for dirname in dirnames:
                if dirname in SKIP_NAMES:
                    continue
                child_abs = os.path.join(dirpath, dirname)
                if self._is_index_artifact(child_abs) or os.path.islink(child_abs):
                    continue
                child_root_id, _ = self._best_matching_root(child_abs)
                if child_root_id != root_id:
                    continue
                kept_dirs.append(dirname)
                row = self._build_row(root_id, root_path, child_abs, is_dir=True)
                if row:
                    yield row
            dirnames[:] = kept_dirs

            for filename in filenames:
                if filename in SKIP_NAMES:
                    continue
                child_abs = os.path.join(dirpath, filename)
                if self._is_index_artifact(child_abs) or os.path.islink(child_abs):
                    continue
                row = self._build_row(root_id, root_path, child_abs, is_dir=False)
                if row:
                    yield row

    def _build_row(self, root_id, root_path, abs_path, is_dir):
        try:
            stat = os.stat(abs_path, follow_symlinks=False)
        except OSError:
            return None
        owner_root_id, _ = self._best_matching_root(abs_path)
        if owner_root_id != root_id:
            return None
        path_obj = Path(abs_path)
        name = path_obj.name
        if name in SKIP_NAMES:
            return None
        try:
            rel_path = str(path_obj.relative_to(root_path))
        except ValueError:
            return None
        if not rel_path or rel_path == ".":
            return None
        return {
            "root": root_id,
            "path": rel_path,
            "name": name,
            "size": 0 if is_dir else int(stat.st_size),
            "mtime": float(stat.st_mtime),
            "kind": "dir" if is_dir else _guess_kind(path_obj),
            "ext": "" if is_dir else path_obj.suffix.lower(),
        }

    def _matching_roots_for_path(self, abs_path):
        root_id, root_path = self._best_matching_root(abs_path)
        if root_id is None or root_path is None:
            return []
        return [(root_id, root_path)]

    def _upsert_rows(self, cur, rows):
        if not rows:
            return
        cur.executemany(
            """
            INSERT INTO files (root, path, name, size, mtime, kind, ext)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(root, path) DO UPDATE SET
                name=excluded.name,
                size=excluded.size,
                mtime=excluded.mtime,
                kind=excluded.kind,
                ext=excluded.ext
            WHERE files.name != excluded.name
               OR files.size != excluded.size
               OR files.mtime != excluded.mtime
               OR files.kind != excluded.kind
               OR files.ext != excluded.ext
            """,
            [
                (
                    row["root"],
                    row["path"],
                    row["name"],
                    row["size"],
                    row["mtime"],
                    row["kind"],
                    row["ext"],
                )
                for row in rows
            ],
        )

    def _remove_relative_path(self, cur, root_id, rel_path, recursive=False):
        rel_path = str(rel_path).strip()
        if not rel_path or rel_path == ".":
            cur.execute("DELETE FROM files WHERE root = ?", (root_id,))
            return
        if recursive:
            cur.execute(
                "DELETE FROM files WHERE root = ? AND (path = ? OR path LIKE ?)",
                (root_id, rel_path, rel_path + "/%"),
            )
            return
        cur.execute("DELETE FROM files WHERE root = ? AND path = ?", (root_id, rel_path))

    def _scan_root(self, root_id):
        root_meta = WATCH_ROOTS.get(root_id)
        if not root_meta or not root_meta["path"].exists():
            with self._lock:
                with self._connect() as con:
                    self._remove_relative_path(con.cursor(), root_id, "", recursive=True)
            return

        with self._lock:
            with self._connect() as con:
                cur = con.cursor()
                cur.execute("CREATE TEMP TABLE IF NOT EXISTS scan_seen(path TEXT PRIMARY KEY)")
                cur.execute("DELETE FROM scan_seen")
                batch = []
                seen_batch = []
                for row in self._iter_root_entries(root_id):
                    seen_batch.append((row["path"],))
                    current = cur.execute(
                        "SELECT mtime, size, kind, ext, name FROM files WHERE root = ? AND path = ?",
                        (root_id, row["path"]),
                    ).fetchone()
                    if (
                        current is None
                        or float(current["mtime"]) != row["mtime"]
                        or int(current["size"]) != row["size"]
                        or current["kind"] != row["kind"]
                        or current["ext"] != row["ext"]
                        or current["name"] != row["name"]
                    ):
                        batch.append(row)
                    if len(batch) >= SEARCH_INDEX_BATCH_SIZE:
                        self._upsert_rows(cur, batch)
                        batch.clear()
                        con.commit()
                    if len(seen_batch) >= SEARCH_INDEX_BATCH_SIZE:
                        cur.executemany("INSERT OR IGNORE INTO scan_seen(path) VALUES (?)", seen_batch)
                        seen_batch.clear()
                        con.commit()
                self._upsert_rows(cur, batch)
                if batch:
                    con.commit()
                if seen_batch:
                    cur.executemany("INSERT OR IGNORE INTO scan_seen(path) VALUES (?)", seen_batch)
                    con.commit()
                cur.execute(
                    "DELETE FROM files WHERE root = ? AND path NOT IN (SELECT path FROM scan_seen)",
                    (root_id,),
                )
                cur.execute("DELETE FROM scan_seen")
                con.commit()

    def _scan_all_roots(self):
        for root_id in self._indexed_root_ids:
            if self._stop_event.is_set():
                return
            try:
                self._scan_root(root_id)
            except Exception as exc:
                print(f"Search index scan failed for {root_id}: {exc}", flush=True)

    def _prune_index_roots(self):
        with self._lock:
            with self._connect() as con:
                cur = con.cursor()
                if self._indexed_root_ids:
                    placeholders = ", ".join("?" for _ in self._indexed_root_ids)
                    cur.execute(
                        f"DELETE FROM files WHERE root NOT IN ({placeholders})",
                        self._indexed_root_ids,
                    )
                else:
                    cur.execute("DELETE FROM files")
                con.commit()

    def _upsert_path(self, abs_path, recursive=False):
        if self._is_index_artifact(abs_path):
            return
        abs_path_obj = Path(abs_path)
        exists = abs_path_obj.exists()
        matches = self._matching_roots_for_path(abs_path)
        if not matches:
            return
        with self._lock:
            with self._connect() as con:
                cur = con.cursor()
                if not exists:
                    for root_id, root_path in matches:
                        try:
                            rel_path = str(abs_path_obj.resolve(strict=False).relative_to(root_path))
                        except ValueError:
                            continue
                        self._remove_relative_path(cur, root_id, rel_path, recursive=recursive)
                    con.commit()
                    return

                if recursive and abs_path_obj.is_dir():
                    for root_id, root_path in matches:
                        rows = []
                        root_row = self._build_row(root_id, root_path, str(abs_path_obj), is_dir=True)
                        if root_row:
                            rows.append(root_row)
                        for dirpath, dirnames, filenames in os.walk(str(abs_path_obj), topdown=True):
                            kept_dirs = []
                            for dirname in dirnames:
                                if dirname in SKIP_NAMES:
                                    continue
                                child_abs = os.path.join(dirpath, dirname)
                                if self._is_index_artifact(child_abs) or os.path.islink(child_abs):
                                    continue
                                child_root_id, _ = self._best_matching_root(child_abs)
                                if child_root_id != root_id:
                                    continue
                                kept_dirs.append(dirname)
                                row = self._build_row(root_id, root_path, child_abs, is_dir=True)
                                if row:
                                    rows.append(row)
                                    if len(rows) >= SEARCH_INDEX_BATCH_SIZE:
                                        self._upsert_rows(cur, rows)
                                        rows.clear()
                            dirnames[:] = kept_dirs
                            for filename in filenames:
                                if filename in SKIP_NAMES:
                                    continue
                                child_abs = os.path.join(dirpath, filename)
                                if self._is_index_artifact(child_abs) or os.path.islink(child_abs):
                                    continue
                                row = self._build_row(root_id, root_path, child_abs, is_dir=False)
                                if row:
                                    rows.append(row)
                                    if len(rows) >= SEARCH_INDEX_BATCH_SIZE:
                                        self._upsert_rows(cur, rows)
                                        rows.clear()
                        self._upsert_rows(cur, rows)
                    con.commit()
                    return

                is_dir = abs_path_obj.is_dir()
                rows = []
                for root_id, root_path in matches:
                    row = self._build_row(root_id, root_path, str(abs_path_obj), is_dir=is_dir)
                    if row:
                        rows.append(row)
                self._upsert_rows(cur, rows)
                con.commit()

    def _remove_path(self, abs_path, recursive=False):
        if self._is_index_artifact(abs_path):
            return
        abs_path_obj = Path(abs_path).resolve(strict=False)
        matches = self._matching_roots_for_path(abs_path_obj)
        if not matches:
            return
        with self._lock:
            with self._connect() as con:
                cur = con.cursor()
                for root_id, root_path in matches:
                    try:
                        rel_path = str(abs_path_obj.relative_to(root_path))
                    except ValueError:
                        continue
                    self._remove_relative_path(cur, root_id, rel_path, recursive=recursive)
                con.commit()

    def enqueue_event(self, op, src_path, dest_path=None, is_directory=False):
        if self._stop_event.is_set():
            return
        if self._is_index_artifact(src_path) or (dest_path and self._is_index_artifact(dest_path)):
            return
        try:
            self._queue.put_nowait(
                {
                    "op": op,
                    "src_path": src_path,
                    "dest_path": dest_path,
                    "is_directory": is_directory,
                }
            )
        except queue.Full:
            self._rescan_now.set()

    def _event_worker(self):
        while not self._stop_event.is_set():
            if self._rescan_now.is_set():
                self._rescan_now.clear()
                self._scan_all_roots()
            try:
                event = self._queue.get(timeout=1)
            except queue.Empty:
                continue
            try:
                op = event["op"]
                src_path = event["src_path"]
                dest_path = event.get("dest_path")
                is_directory = bool(event.get("is_directory"))
                if op == "deleted":
                    self._remove_path(src_path, recursive=is_directory)
                elif op == "moved":
                    self._remove_path(src_path, recursive=is_directory)
                    if dest_path:
                        self._upsert_path(dest_path, recursive=is_directory)
                elif op == "created":
                    self._upsert_path(src_path, recursive=is_directory)
                elif op == "modified":
                    if not is_directory:
                        self._upsert_path(src_path, recursive=False)
            except Exception as exc:
                print(f"Search index event failed: {exc}", flush=True)

    def _scheduled_rescan_worker(self):
        while not self._stop_event.wait(SEARCH_INDEX_SCAN_INTERVAL):
            try:
                self._scan_all_roots()
            except Exception as exc:
                print(f"Scheduled search index rescan failed: {exc}", flush=True)

    def _full_reindex_worker(self):
        try:
            self._scan_all_roots()
        except Exception as exc:
            print(f"Initial search index rebuild failed: {exc}", flush=True)

    def _build_observer(self, paths):
        handler = SearchIndexEventHandler(self)
        observer = Observer()
        try:
            for watch_path in paths:
                if watch_path.exists():
                    observer.schedule(handler, str(watch_path), recursive=True)
            observer.start()
            return observer
        except Exception:
            with contextlib.suppress(Exception):
                observer.stop()
            with contextlib.suppress(Exception):
                observer.join(timeout=2)
            raise

    def _start_watchdog(self):
        if Observer is None:
            print("watchdog is unavailable; search index will rely on scheduled rescans only", flush=True)
            return
        candidate_sets = [self._watch_paths]
        if self._fallback_watch_paths and self._fallback_watch_paths != self._watch_paths:
            candidate_sets.append(self._fallback_watch_paths)
        for paths in candidate_sets:
            try:
                self._observer = self._build_observer(paths)
                return
            except OSError as exc:
                if exc.errno == errno.ENOSPC:
                    print(
                        f"watchdog inotify limit reached for {[str(path) for path in paths]}; retrying with a smaller watch set",
                        flush=True,
                    )
                    continue
                raise
        print("watchdog could not start within inotify limits; scheduled rescans remain active", flush=True)

    def start(self):
        if self._started:
            return
        self._started = True
        self._stop_event.clear()
        self._rescan_now.clear()
        self._prune_index_roots()
        self._start_watchdog()
        for target in (self._full_reindex_worker, self._scheduled_rescan_worker, self._event_worker):
            thread = threading.Thread(target=target, daemon=True)
            thread.start()
            self._threads.append(thread)

    def stop(self):
        self._stop_event.set()
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=5)
            self._observer = None
        for thread in self._threads:
            thread.join(timeout=1)
        self._threads.clear()
        self._started = False

    @staticmethod
    def _parse_kind_filter(filters):
        kinds = filters.get("kind")
        if not kinds:
            return []
        if isinstance(kinds, str):
            values = kinds.split(",")
        else:
            values = []
            for value in kinds:
                values.extend(str(value).split(","))
        allowed = {"dir", "image", "text", "binary"}
        return [value.strip() for value in values if value.strip() in allowed]

    @staticmethod
    def _parse_ext_filter(ext_value):
        if not ext_value:
            return []
        parts = str(ext_value).strip().lower().split()
        values = []
        for part in parts:
            for chunk in part.split(","):
                chunk = chunk.strip()
                if not chunk:
                    continue
                values.append(chunk if chunk.startswith(".") else "." + chunk)
        return values

    @staticmethod
    def _fts_term(text):
        return '"' + str(text).replace('"', '""') + '"'

    def search(self, query, limit=50, filters=None):
        filters = filters or {}
        capped_limit = max(1, min(int(limit or 50), SEARCH_INDEX_LIMIT))
        sql = [
            """
            SELECT f.root, f.path, f.name, f.size, f.mtime, f.kind, f.ext
            FROM files AS f
            """
        ]
        params = []
        where = []
        order_by = "f.mtime DESC"
        query_text = str(query or "").strip()

        if query_text:
            query_like = f"%{query_text.lower()}%"
            if len(query_text) >= 3:
                sql.append("JOIN files_fts ON files_fts.rowid = f.id")
                where.append("files_fts MATCH ?")
                params.append(self._fts_term(query_text))
                where.append("(lower(f.name) LIKE ? OR lower(f.path) LIKE ?)")
                params.extend([query_like, query_like])
                order_by = "bm25(files_fts), f.mtime DESC"
            else:
                where.append("(lower(f.name) LIKE ? OR lower(f.path) LIKE ?)")
                params.extend([query_like, query_like])

        name_filter = str(filters.get("name", "")).strip()
        if name_filter:
            where.append("lower(f.name) LIKE ?")
            params.append(f"%{name_filter.lower()}%")

        raw_kind_filter = filters.get("kind")
        kind_values = self._parse_kind_filter(filters)
        if raw_kind_filter and not kind_values:
            return {"ok": True, "query": query_text, "results": []}
        if kind_values:
            where.append("f.kind IN ({})".format(", ".join("?" for _ in kind_values)))
            params.extend(kind_values)

        dotfiles = str(filters.get("dotfiles", "1")).strip().lower()
        if dotfiles in {"0", "false", "no"}:
            where.append("substr(f.name, 1, 1) != '.'")

        size_op = str(filters.get("size_op", "")).strip().lower()
        try:
            size_val = float(filters.get("size_val", 0) or 0)
        except (TypeError, ValueError):
            size_val = 0
        try:
            size_unit = float(filters.get("size_unit", 1024) or 1024)
        except (TypeError, ValueError):
            size_unit = 1024
        if size_op in {"gt", "lt"} and size_val > 0:
            threshold = size_val * size_unit
            where.append("(f.kind = 'dir' OR f.size {} ?)".format(">" if size_op == "gt" else "<"))
            params.append(threshold)

        try:
            mtime_days = int(filters.get("mtime_days", 0) or 0)
        except (TypeError, ValueError):
            mtime_days = 0
        if mtime_days > 0:
            cutoff = time.time() - (mtime_days * 86400)
            where.append("f.mtime >= ?")
            params.append(cutoff)

        ext_values = self._parse_ext_filter(filters.get("ext", ""))
        if ext_values:
            where.append("(f.kind = 'dir' OR f.ext IN ({}))".format(", ".join("?" for _ in ext_values)))
            params.extend(ext_values)

        if where:
            sql.append("WHERE " + " AND ".join(where))
        sql.append(f"ORDER BY {order_by}")
        sql.append("LIMIT ?")
        params.append(capped_limit)

        with self._connect() as con:
            rows = con.execute("\n".join(sql), params).fetchall()

        results = []
        for row in rows:
            root_path = WATCH_ROOTS.get(row["root"], {}).get("path")
            absolute_path = str((root_path / row["path"]).resolve()) if root_path else row["path"]
            results.append(
                {
                    "root": row["root"],
                    "path": row["path"],
                    "name": row["name"],
                    "size": int(row["size"]),
                    "modified": int(float(row["mtime"])),
                    "mtime": _iso_mtime(float(row["mtime"])),
                    "kind": row["kind"],
                    "ext": row["ext"],
                    "absolute_path": absolute_path,
                    "full_path": absolute_path,
                }
            )
        return {"ok": True, "query": query_text, "results": results}


SEARCH_INDEX = SearchIndexManager(SEARCH_INDEX_DB)


def parse_multipart(content_type, body):
    """Parse multipart/form-data. Returns list of (name, filename, data) tuples."""
    boundary = None
    for token in content_type.split(';'):
        token = token.strip()
        if token.startswith('boundary='):
            boundary = token[9:].strip('"')
            break
    if not boundary:
        return []
    delimiter = b'--' + boundary.encode()
    parts = []
    for segment in body.split(delimiter)[1:]:
        if segment.startswith(b'--'):
            break
        sep = b'\r\n\r\n' if b'\r\n\r\n' in segment else b'\n\n'
        if sep not in segment:
            continue
        headers_raw, data = segment.split(sep, 1)
        if data.endswith(b'\r\n'):
            data = data[:-2]
        elif data.endswith(b'\n'):
            data = data[:-1]
        name = filename = None
        for line in headers_raw.split(b'\r\n'):
            if line.lower().startswith(b'content-disposition:'):
                cd = line.decode('utf-8', errors='replace')
                for token in cd.split(';'):
                    token = token.strip()
                    if token.startswith('name='):
                        name = token[5:].strip('"')
                    elif token.startswith('filename='):
                        filename = token[9:].strip('"')
        if name:
            parts.append((name, filename, data))
    return parts


def upload_file(root_id, rel_dir, filename, data):
    """Write uploaded file to root/rel_dir/filename. Returns result dict."""
    MAX_SIZE = 50 * 1024 * 1024  # 50 MB
    if len(data) > MAX_SIZE:
        return {"ok": False, "message": "File too large (max 50 MB)"}
    if not filename:
        return {"ok": False, "message": "Missing filename"}
    safe_name = Path(filename).name
    if not safe_name or safe_name.startswith('.'):
        return {"ok": False, "message": "Invalid filename"}
    try:
        dest_dir = _resolve_within(root_id, rel_dir)
    except Exception:
        return {"ok": False, "message": "Invalid destination path"}
    if not dest_dir.exists():
        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            return {"ok": False, "message": f"Cannot create directory: {e}"}
    dest = dest_dir / safe_name
    try:
        dest.write_bytes(data)
    except OSError as e:
        return {"ok": False, "message": str(e)}
    _reset_recent_cache()
    
    # Trigger file upload event via cron wake
    try:
        subprocess.run(
            ["openclaw", "cron", "wake", "--text", f"New file uploaded: {safe_name} ({len(data)} bytes) from {root_id}/{rel_dir}"],
            timeout=2,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
    except Exception:
        pass  # Non-blocking — upload still succeeds even if event fails
    
    return {
        "ok": True,
        "message": "Uploaded",
        "filename": safe_name,
        "path": str(dest.relative_to(_safe_root(root_id).resolve())),
        "size": len(data),
    }


def create_text_file(root_id, rel_dir, filename, content):
    """Write text content to root/rel_dir/filename. Returns result dict."""
    MAX_SIZE = 10 * 1024 * 1024  # 10 MB
    if len(content.encode("utf-8")) > MAX_SIZE:
        return {"ok": False, "message": "Content too large (max 10 MB)"}
    if not filename:
        return {"ok": False, "message": "Missing filename"}
    safe_name = Path(filename).name
    if not safe_name or safe_name.startswith("."):
        return {"ok": False, "message": "Invalid filename"}
    try:
        dest_dir = _resolve_within(root_id, rel_dir)
    except Exception:
        return {"ok": False, "message": "Invalid destination path"}
    if not dest_dir.exists():
        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            return {"ok": False, "message": f"Cannot create directory: {e}"}
    dest = dest_dir / safe_name
    try:
        dest.write_text(content, encoding="utf-8")
    except OSError as e:
        return {"ok": False, "message": str(e)}
    _reset_recent_cache()
    return {
        "ok": True,
        "message": "Created",
        "filename": safe_name,
        "path": str(dest.relative_to(_safe_root(root_id).resolve())),
        "size": dest.stat().st_size,
    }


def run_cmd(cmd):
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, text=True, timeout=3)
        return out.strip()
    except Exception:
        return ""


def systemd_props(service_name):
    out = run_cmd(
        [
            "systemctl",
            "show",
            service_name,
            "--no-pager",
            "--property=ActiveState,SubState,NRestarts,ExecMainPID,MemoryCurrent,ActiveEnterTimestamp",
        ]
    )
    props = {}
    for line in out.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            props[k] = v
    return props


def human_bytes(num):
    if num < 1024:
        return f"{num} B"
    for unit in ["KiB", "MiB", "GiB", "TiB"]:
        num /= 1024.0
        if num < 1024:
            return f"{num:.1f} {unit}"
    return f"{num:.1f} PiB"


def safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def probe_gateway():
    try:
        req = urllib.request.Request(GATEWAY_URL, method="GET")
        with urllib.request.urlopen(req, timeout=2) as resp:
            return {"reachable": True, "code": resp.getcode(), "detail": "ok"}
    except urllib.error.HTTPError as e:
        # 401/403 still means the service is reachable.
        return {"reachable": True, "code": e.code, "detail": "auth required"}
    except Exception as e:
        return {"reachable": False, "code": None, "detail": str(e)}


def uptime_seconds():
    try:
        with open("/proc/uptime", "r", encoding="utf-8") as f:
            return int(float(f.read().split()[0]))
    except Exception:
        return 0


def format_uptime(seconds):
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    mins, _ = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours or days:
        parts.append(f"{hours}h")
    parts.append(f"{mins}m")
    return " ".join(parts)


def get_status():
    mem_total_kb = 0
    mem_avail_kb = 0
    swap_total_kb = 0
    swap_free_kb = 0
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    mem_total_kb = int(line.split()[1])
                elif line.startswith("MemAvailable:"):
                    mem_avail_kb = int(line.split()[1])
                elif line.startswith("SwapTotal:"):
                    swap_total_kb = int(line.split()[1])
                elif line.startswith("SwapFree:"):
                    swap_free_kb = int(line.split()[1])
    except Exception:
        pass

    mem_used_kb = max(mem_total_kb - mem_avail_kb, 0)
    swap_used_kb = max(swap_total_kb - swap_free_kb, 0)
    disk = shutil.disk_usage("/")
    gateway = probe_gateway()
    openclaw = systemd_props(OPENCLAW_SERVICE_NAME)
    dashboard = systemd_props(DASHBOARD_SERVICE_NAME)
    claude = get_claude_status()
    codex = get_codex_status()
    spurs = get_spurs_info()
    load1, load5, load15 = os.getloadavg()

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "hostname": socket.gethostname(),
        "host_uptime": format_uptime(uptime_seconds()),
        "load_avg": f"{load1:.2f}, {load5:.2f}, {load15:.2f}",
        "mem": {
            "used": human_bytes(mem_used_kb * 1024),
            "total": human_bytes(mem_total_kb * 1024),
        },
        "swap": {
            "used": human_bytes(swap_used_kb * 1024),
            "total": human_bytes(swap_total_kb * 1024),
        },
        "disk": {
            "used": human_bytes(disk.used),
            "total": human_bytes(disk.total),
            "free": human_bytes(disk.free),
        },
        "gateway": gateway,
        "openclaw": {
            "state": openclaw.get("ActiveState", "unknown"),
            "sub_state": openclaw.get("SubState", "unknown"),
            "restarts": openclaw.get("NRestarts", "0"),
            "pid": openclaw.get("ExecMainPID", "0"),
            "memory": human_bytes(safe_int(openclaw.get("MemoryCurrent", "0") or "0")),
            "active_since": openclaw.get("ActiveEnterTimestamp", ""),
        },
        "dashboard": {
            "state": dashboard.get("ActiveState", "unknown"),
            "sub_state": dashboard.get("SubState", "unknown"),
            "restarts": dashboard.get("NRestarts", "0"),
            "pid": dashboard.get("ExecMainPID", "0"),
            "memory": human_bytes(safe_int(dashboard.get("MemoryCurrent", "0") or "0")),
        },
        "claude": claude,
        "codex": codex,
        "spurs": spurs,
    }


def _fetch_json(url, timeout=6):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "local-dashboard/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def get_spurs_info():
    now = time.time()
    if _SPURS_CACHE["data"] and (now - _SPURS_CACHE["ts"]) < 600:
        return _SPURS_CACHE["data"]

    fallback = {
        "source": "espn",
        "record": "unavailable",
        "next_game": "unavailable",
        "next_tipoff_utc": "",
        "summary": "Could not fetch Spurs data right now.",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    url = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/24"
    payload = _fetch_json(url)
    if not payload:
        _SPURS_CACHE["ts"] = now
        _SPURS_CACHE["data"] = fallback
        return fallback

    team = payload.get("team", {})
    record = (
        team.get("record", {})
        .get("items", [{}])[0]
        .get("summary", "unavailable")
    )

    next_event = (team.get("nextEvent") or [{}])[0]
    competition = (next_event.get("competitions") or [{}])[0]
    competitors = competition.get("competitors") or []
    status_detail = (
        competition.get("status", {})
        .get("type", {})
        .get("shortDetail", "")
    )
    venue = competition.get("venue", {}).get("fullName", "")

    opponent = ""
    home_away = ""
    for comp in competitors:
        abbr = str(comp.get("team", {}).get("abbreviation", "")).upper()
        if abbr == "SA":
            home_away = comp.get("homeAway", "")
        else:
            opponent = comp.get("team", {}).get("displayName", "")

    next_game_name = next_event.get("name", "unavailable")
    next_tipoff_utc = next_event.get("date", "")

    if opponent:
        location = "home" if home_away == "home" else "away"
        short = f"{record} this season. Next {location} vs {opponent} ({status_detail}). Focus: pace + defense."
    else:
        short = f"{record} this season. Next game: {next_game_name}."
    if venue:
        short = f"{short} Venue: {venue}."

    data = {
        "source": "espn",
        "record": record,
        "next_game": next_game_name,
        "next_tipoff_utc": next_tipoff_utc,
        "status_detail": status_detail,
        "venue": venue,
        "summary": short,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    _SPURS_CACHE["ts"] = now
    _SPURS_CACHE["data"] = data
    return data


def _file_meta(path_obj):
    try:
        st = path_obj.stat()
        return {
            "exists": True,
            "size": st.st_size,
            "mtime": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
        }
    except FileNotFoundError:
        return {"exists": False, "size": 0, "mtime": ""}


def _iso_mtime(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _guess_kind(path_obj):
    suffix = path_obj.suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        return "image"
    if suffix in TEXT_EXTENSIONS:
        return "text"
    return "binary"


def _safe_root(root_id):
    root = WATCH_ROOTS.get(root_id)
    if not root:
        raise ValueError("Unknown root")
    return root["path"]


def _resolve_within(root_id, rel_path=""):
    root_path = _safe_root(root_id).resolve()
    candidate = (root_path / rel_path).resolve()
    candidate.relative_to(root_path)
    return candidate


def _coerce_bool(value, default=False):
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _normalize_rel_path(value):
    raw = str(value or "").strip().replace("\\", "/")
    if raw in {"", ".", "/"}:
        return ""
    normalized = str(Path(raw))
    if normalized == ".":
        return ""
    return normalized.replace("\\", "/")


def _prime_key(root_id, rel_path):
    return f"{root_id}:{rel_path}"


def _prime_label(root_id, rel_path):
    root_meta = WATCH_ROOTS.get(root_id, {})
    if rel_path:
        return Path(rel_path).name or rel_path
    return root_meta.get("label", root_id)


def _reset_recent_cache():
    with _RECENT_LOCK:
        _RECENT_CACHE["ts"] = 0.0
        _RECENT_CACHE["limit"] = 0
        _RECENT_CACHE["items"] = []


def _sanitize_prime_directory_item(item, require_existing=False):
    if not isinstance(item, dict):
        raise ValueError("Prime directory entries must be objects")
    root_id = str(item.get("root", "")).strip()
    if root_id not in WATCH_ROOTS:
        raise ValueError("Unknown root")
    rel_path = _normalize_rel_path(item.get("path", ""))
    target = _resolve_within(root_id, rel_path)
    if require_existing and (not target.exists() or not target.is_dir()):
        raise ValueError("Prime directory must point to an existing directory")
    return {
        "root": root_id,
        "path": rel_path,
        "include_subdirectories": _coerce_bool(item.get("include_subdirectories"), True),
        "pin_to_favorites": _coerce_bool(item.get("pin_to_favorites"), False),
    }


def _read_prime_directories_raw():
    with _PRIME_LOCK:
        if not PRIME_DIRECTORIES_PATH.exists():
            return []
        try:
            payload = json.loads(PRIME_DIRECTORIES_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
    items = payload.get("items", payload) if isinstance(payload, (dict, list)) else []
    if not isinstance(items, list):
        return []

    sanitized = []
    seen = set()
    for item in items:
        try:
            clean = _sanitize_prime_directory_item(item, require_existing=False)
        except Exception:
            continue
        key = _prime_key(clean["root"], clean["path"])
        if key in seen:
            continue
        seen.add(key)
        sanitized.append(clean)
    sanitized.sort(key=lambda item: (item["root"], item["path"]))
    return sanitized


def _write_prime_directories_raw(items):
    payload = {"items": items}
    PRIME_DIRECTORIES_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = PRIME_DIRECTORIES_PATH.with_suffix(".json.tmp")
    with _PRIME_LOCK:
        tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(tmp_path, PRIME_DIRECTORIES_PATH)


def _read_favorites_order():
    with _FAVORITES_ORDER_LOCK:
        if not FAVORITES_ORDER_PATH.exists():
            return []
        try:
            return json.loads(FAVORITES_ORDER_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []


def _write_favorites_order(order):
    with _FAVORITES_ORDER_LOCK:
        tmp_path = FAVORITES_ORDER_PATH.with_suffix(".json.tmp")
        tmp_path.write_text(json.dumps(order), encoding="utf-8")
        os.replace(tmp_path, FAVORITES_ORDER_PATH)


def save_favorites_order(order):
    if not isinstance(order, list) or not all(isinstance(k, str) for k in order):
        return {"ok": False, "message": "order must be a list of strings"}
    _write_favorites_order(order)
    return {"ok": True, "favorites": get_favorites()}


def get_prime_directories():
    items = []
    for item in _read_prime_directories_raw():
        root_id = item["root"]
        rel_path = item["path"]
        try:
            target = _resolve_within(root_id, rel_path)
            exists = target.exists() and target.is_dir()
            absolute_path = str(target)
        except Exception:
            exists = False
            absolute_path = ""
        root_meta = WATCH_ROOTS.get(root_id, {})
        items.append(
            {
                **item,
                "key": _prime_key(root_id, rel_path),
                "label": _prime_label(root_id, rel_path),
                "root_label": root_meta.get("label", root_id),
                "absolute_path": absolute_path,
                "exists": exists,
            }
        )
    return items


def get_favorites():
    # Prime Directories marked as pin_to_favorites are the exclusive source of truth
    by_key = {}
    for item in get_prime_directories():
        if not item["pin_to_favorites"] or not item["exists"]:
            continue
        key = f"{item['root']}::{item['path']}"
        if key not in by_key:
            by_key[key] = {
                "label": item["label"],
                "root": item["root"],
                "path": item["path"],
                "kind": "dir",
            }

    # Apply custom order; append any new favorites not yet in order list
    order = _read_favorites_order()
    ordered = [by_key[k] for k in order if k in by_key]
    ordered_keys = set(order)
    for k, fav in by_key.items():
        if k not in ordered_keys:
            ordered.append(fav)
    return ordered


def save_prime_directories(items):
    if not isinstance(items, list):
        return {"ok": False, "message": "Prime directories payload must be a list"}

    sanitized = []
    seen = set()
    for item in items:
        try:
            clean = _sanitize_prime_directory_item(item, require_existing=True)
        except Exception as exc:
            return {"ok": False, "message": str(exc)}
        key = _prime_key(clean["root"], clean["path"])
        if key in seen:
            continue
        seen.add(key)
        sanitized.append(clean)

    sanitized.sort(key=lambda item: (item["root"], item["path"]))
    try:
        _write_prime_directories_raw(sanitized)
    except OSError as exc:
        return {"ok": False, "message": str(exc)}
    _reset_recent_cache()
    return {
        "ok": True,
        "message": "Saved",
        "prime_directories": get_prime_directories(),
        "favorites": get_favorites(),
    }


def get_watch_roots():
    roots = []
    for root_id, meta in WATCH_ROOTS.items():
        path_obj = meta["path"]
        roots.append(
            {
                "id": root_id,
                "label": meta["label"],
                "description": meta["description"],
                "path": str(path_obj),
                "exists": path_obj.exists(),
            }
        )
    return {
        "roots": roots,
        "favorites": get_favorites(),
        "prime_directories": get_prime_directories(),
    }


def _directory_has_visible_children(path_obj):
    try:
        for child in path_obj.iterdir():
            if child.name in SKIP_NAMES:
                continue
            return True
    except OSError:
        return False
    return False


def _list_directory_entries(root_id, target):
    entries = []
    truncated = False
    root_path = _safe_root(root_id).resolve()
    try:
        for child in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
            if child.name in SKIP_NAMES:
                continue
            try:
                stat = child.stat()
            except OSError:
                continue
            rel_child = child.relative_to(root_path)
            is_dir = child.is_dir()
            entries.append(
                {
                    "name": child.name,
                    "path": str(rel_child),
                    "is_dir": is_dir,
                    "size": 0 if is_dir else stat.st_size,
                    "mtime": _iso_mtime(stat.st_mtime),
                    "kind": "dir" if is_dir else _guess_kind(child),
                    "has_children": _directory_has_visible_children(child) if is_dir else False,
                }
            )
            if len(entries) >= FILE_LIST_LIMIT:
                truncated = True
                break
    except OSError as e:
        return None, False, str(e)
    return entries, truncated, ""


def list_files(root_id, rel_path=""):
    try:
        target = _resolve_within(root_id, rel_path)
    except Exception:
        return {"ok": False, "message": "Invalid path", "entries": []}
    if not target.exists():
        return {"ok": False, "message": "Path not found", "entries": []}
    if not target.is_dir():
        return {"ok": False, "message": "Path is not a directory", "entries": []}

    entries, truncated, error = _list_directory_entries(root_id, target)
    if entries is None:
        return {"ok": False, "message": error, "entries": []}

    parent = ""
    if rel_path:
        parent = str(Path(rel_path).parent)
        if parent == ".":
            parent = ""
    return {
        "ok": True,
        "message": "ok",
        "root": root_id,
        "path": rel_path,
        "absolute_path": str(target),
        "parent": parent,
        "entries": entries,
        "truncated": truncated,
    }


def get_tree_branch(root_id, rel_path=""):
    if root_id != MAP_ROOT_ID:
        return {"ok": False, "message": "Map view is only available for /root", "entries": []}
    try:
        target = _resolve_within(root_id, rel_path)
    except Exception:
        return {"ok": False, "message": "Invalid path", "entries": []}
    if not target.exists():
        return {"ok": False, "message": "Path not found", "entries": []}
    if not target.is_dir():
        return {"ok": False, "message": "Path is not a directory", "entries": []}

    entries, truncated, error = _list_directory_entries(root_id, target)
    if entries is None:
        return {"ok": False, "message": error, "entries": []}

    parent = ""
    if rel_path:
        parent = str(Path(rel_path).parent)
        if parent == ".":
            parent = ""

    return {
        "ok": True,
        "message": "ok",
        "root": root_id,
        "path": rel_path,
        "absolute_path": str(target),
        "parent": parent,
        "entries": entries,
        "truncated": truncated,
    }


def read_file(root_id, rel_path="", full=False):
    try:
        target = _resolve_within(root_id, rel_path)
    except Exception:
        return {"ok": False, "message": "Invalid path"}
    if not target.exists():
        return {"ok": False, "message": "File not found"}
    if not target.is_file():
        return {"ok": False, "message": "Path is not a file"}

    kind = _guess_kind(target)
    stat = target.stat()
    payload = {
        "ok": True,
        "message": "ok",
        "root": root_id,
        "path": rel_path,
        "absolute_path": str(target),
        "name": target.name,
        "size": stat.st_size,
        "mtime": _iso_mtime(stat.st_mtime),
        "kind": kind,
    }
    if kind == "image":
        payload["raw_url"] = f"/api/file/raw?root={root_id}&path={rel_path}"
        return payload

    max_bytes = 10 * 1024 * 1024 if full else 200_000
    try:
        data = target.read_bytes()
    except OSError as e:
        return {"ok": False, "message": str(e)}

    if kind == "binary":
        payload["preview"] = "Binary preview disabled."
        return payload

    truncated = len(data) > max_bytes
    text = data[:max_bytes].decode("utf-8", errors="replace")
    payload["preview"] = text
    payload["truncated"] = truncated
    return payload


def save_text_file(root_id, rel_path, content, new_filename=None):
    """Overwrite a text file's content and optionally rename it."""
    MAX_SIZE = 10 * 1024 * 1024  # 10 MB
    if len(content.encode("utf-8")) > MAX_SIZE:
        return {"ok": False, "message": "Content too large (max 10 MB)"}
    try:
        target = _resolve_within(root_id, rel_path)
    except Exception:
        return {"ok": False, "message": "Invalid path"}
    if not target.exists() or not target.is_file():
        return {"ok": False, "message": "File not found"}
    try:
        target.write_text(content, encoding="utf-8")
    except OSError as e:
        return {"ok": False, "message": str(e)}
    if new_filename and new_filename != target.name:
        safe_name = Path(new_filename).name
        if not safe_name or safe_name.startswith("."):
            return {"ok": False, "message": "Invalid new filename"}
        new_path = target.parent / safe_name
        try:
            target.rename(new_path)
            target = new_path
        except OSError as e:
            return {"ok": False, "message": f"Saved but rename failed: {e}"}
    _reset_recent_cache()
    root_path = _safe_root(root_id).resolve()
    return {
        "ok": True,
        "message": "Saved",
        "filename": target.name,
        "path": str(target.relative_to(root_path)),
        "size": target.stat().st_size,
    }


def search_files(query, limit=50, filters=None):
    return SEARCH_INDEX.search(query, limit=limit, filters=filters or {})


def _dir_size(path_obj):
    """Recursively compute total size of a directory."""
    total = 0
    try:
        for item in path_obj.rglob("*"):
            if item.is_file():
                try:
                    total += item.stat().st_size
                except OSError:
                    pass
    except OSError:
        pass
    return total


def trash_move(items):
    """Move files/dirs to trash. items is a list of {root, path} dicts."""
    TRASH_DIR.mkdir(parents=True, exist_ok=True)
    results = []
    for item in items:
        root_id = item.get("root", "")
        rel_path = item.get("path", "")
        if not root_id or not rel_path:
            results.append({"ok": False, "message": "Missing root or path"})
            continue
        try:
            target = _resolve_within(root_id, rel_path)
        except Exception:
            results.append({"ok": False, "message": "Invalid path"})
            continue
        if not target.exists():
            results.append({"ok": False, "message": "Path not found"})
            continue

        ts = datetime.now(timezone.utc)
        ts_str = ts.strftime("%Y%m%d%H%M%S")
        original_name = target.name
        trash_name = f"{ts_str}_{original_name}"

        # Ensure uniqueness
        dest = TRASH_DIR / trash_name
        counter = 0
        while dest.exists() or (TRASH_DIR / f"{trash_name}.meta.json").exists():
            counter += 1
            trash_name = f"{ts_str}_{counter}_{original_name}"
            dest = TRASH_DIR / trash_name

        # Compute size before move
        if target.is_dir():
            size = _dir_size(target)
        else:
            try:
                size = target.stat().st_size
            except OSError:
                size = 0

        meta = {
            "original_root": root_id,
            "original_path": rel_path,
            "deleted_at": ts.isoformat(),
            "size": size,
            "is_dir": target.is_dir(),
            "trash_name": trash_name,
        }

        try:
            shutil.move(str(target), str(dest))
        except OSError as e:
            results.append({"ok": False, "message": str(e)})
            continue

        meta_path = TRASH_DIR / f"{trash_name}.meta.json"
        try:
            meta_path.write_text(json.dumps(meta), encoding="utf-8")
        except OSError:
            pass

        _reset_recent_cache()
        results.append({"ok": True, "message": "Moved to trash", "trash_name": trash_name})

    return {"ok": True, "results": results}


def trash_list():
    """List trash contents."""
    if not TRASH_DIR.exists():
        return {"ok": True, "items": [], "total_size": 0}
    items = []
    total_size = 0
    for meta_file in sorted(TRASH_DIR.glob("*.meta.json"), reverse=True):
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        trash_name = meta.get("trash_name", meta_file.stem.replace(".meta", ""))
        trash_path = TRASH_DIR / trash_name
        if not trash_path.exists():
            continue
        size = meta.get("size", 0)
        total_size += size
        items.append({
            "id": trash_name,
            "original_root": meta.get("original_root", ""),
            "original_path": meta.get("original_path", ""),
            "deleted_at": meta.get("deleted_at", ""),
            "size": size,
            "is_dir": meta.get("is_dir", False),
            "name": trash_name.split("_", 1)[-1] if "_" in trash_name else trash_name,
        })
    return {"ok": True, "items": items, "total_size": total_size}


def trash_restore(item_ids):
    """Restore items from trash to original location."""
    results = []
    for item_id in item_ids:
        # Validate item_id: must be a simple filename with no path separators
        safe_id = Path(item_id).name
        if safe_id != item_id or not safe_id:
            results.append({"ok": False, "message": "Invalid trash item id"})
            continue
        meta_path = TRASH_DIR / f"{safe_id}.meta.json"
        trash_path = TRASH_DIR / safe_id
        if not trash_path.exists():
            results.append({"ok": False, "message": "Trash item not found"})
            continue
        if not meta_path.exists():
            results.append({"ok": False, "message": "Metadata not found"})
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            results.append({"ok": False, "message": "Cannot read metadata"})
            continue

        root_id = meta.get("original_root", "")
        rel_path = meta.get("original_path", "")
        if not root_id or not rel_path:
            results.append({"ok": False, "message": "Missing original location in metadata"})
            continue

        try:
            dest = _resolve_within(root_id, rel_path)
        except Exception:
            results.append({"ok": False, "message": "Original root no longer valid"})
            continue

        if dest.exists():
            results.append({"ok": False, "message": f"Original path already exists: {rel_path}"})
            continue

        # Ensure parent directory exists
        dest.parent.mkdir(parents=True, exist_ok=True)

        try:
            shutil.move(str(trash_path), str(dest))
            meta_path.unlink(missing_ok=True)
        except OSError as e:
            results.append({"ok": False, "message": str(e)})
            continue

        _reset_recent_cache()
        results.append({"ok": True, "message": "Restored"})

    return {"ok": True, "results": results}


def trash_delete(item_ids):
    """Permanently delete specific items from trash."""
    results = []
    for item_id in item_ids:
        safe_id = Path(item_id).name
        if safe_id != item_id or not safe_id:
            results.append({"ok": False, "message": "Invalid trash item id"})
            continue
        meta_path = TRASH_DIR / f"{safe_id}.meta.json"
        trash_path = TRASH_DIR / safe_id
        if not trash_path.exists():
            results.append({"ok": False, "message": "Trash item not found"})
            continue
        try:
            if trash_path.is_dir():
                shutil.rmtree(str(trash_path))
            else:
                trash_path.unlink()
            meta_path.unlink(missing_ok=True)
        except OSError as e:
            results.append({"ok": False, "message": str(e)})
            continue
        _reset_recent_cache()
        results.append({"ok": True, "message": "Permanently deleted"})
    return {"ok": True, "results": results}


def trash_empty():
    """Permanently delete all trash contents."""
    if not TRASH_DIR.exists():
        return {"ok": True, "message": "Trash is already empty", "deleted": 0}
    count = 0
    for item in list(TRASH_DIR.iterdir()):
        try:
            if item.is_dir():
                shutil.rmtree(str(item))
            else:
                item.unlink()
            count += 1
        except OSError:
            pass
    if count:
        _reset_recent_cache()
    return {"ok": True, "message": f"Emptied trash ({count} items removed)", "deleted": count}


def recent_changes(limit=40):
    max_files = max(10, min(limit, 100))
    now = time.time()
    if _RECENT_CACHE["items"] and _RECENT_CACHE["limit"] >= max_files:
        if (now - _RECENT_CACHE["ts"]) < RECENT_SCAN_TTL:
            return {"ok": True, "items": _RECENT_CACHE["items"][:max_files], "cached": True}

    if not _RECENT_LOCK.acquire(blocking=False):
        return {"ok": True, "items": _RECENT_CACHE["items"][:max_files], "cached": True}

    try:
        now = time.time()
        if _RECENT_CACHE["items"] and _RECENT_CACHE["limit"] >= max_files:
            if (now - _RECENT_CACHE["ts"]) < RECENT_SCAN_TTL:
                return {"ok": True, "items": _RECENT_CACHE["items"][:max_files], "cached": True}

        prime_directories = [item for item in get_prime_directories() if item.get("exists")]
        if not prime_directories:
            _RECENT_CACHE["ts"] = time.time()
            _RECENT_CACHE["limit"] = max_files
            _RECENT_CACHE["items"] = []
            return {"ok": True, "items": [], "cached": False}

        recent_heap = []
        seen_paths = set()
        counter = 0
        for prime in prime_directories:
            root_id = prime["root"]
            base = Path(prime["absolute_path"])
            if not base.exists():
                continue
            root_base = _safe_root(root_id).resolve()

            def consider_file(path_obj):
                nonlocal counter
                abs_path = str(path_obj)
                if abs_path in seen_paths:
                    return
                try:
                    stat = path_obj.stat()
                except OSError:
                    return
                seen_paths.add(abs_path)
                rel_path = str(path_obj.relative_to(root_base))
                item = {
                    "root": root_id,
                    "label": f"Prime · {prime['label']}",
                    "path": rel_path,
                    "absolute_path": abs_path,
                    "mtime": _iso_mtime(stat.st_mtime),
                    "size": stat.st_size,
                    "kind": _guess_kind(path_obj),
                }
                entry = (stat.st_mtime, counter, item)
                counter += 1
                if len(recent_heap) < max_files:
                    heapq.heappush(recent_heap, entry)
                elif entry[0] > recent_heap[0][0]:
                    heapq.heapreplace(recent_heap, entry)

            if prime["include_subdirectories"]:
                for dirpath, dirnames, filenames in os.walk(base):
                    dirnames[:] = [d for d in dirnames if d not in SKIP_NAMES]
                    for name in filenames:
                        if name in SKIP_NAMES:
                            continue
                        consider_file(Path(dirpath) / name)
                continue

            try:
                for child in base.iterdir():
                    if child.name in SKIP_NAMES or not child.is_file():
                        continue
                    consider_file(child)
            except OSError:
                continue

        items = [item for _, _, item in sorted(recent_heap, key=lambda row: row[0], reverse=True)]
        _RECENT_CACHE["ts"] = time.time()
        _RECENT_CACHE["limit"] = max_files
        _RECENT_CACHE["items"] = items
        return {"ok": True, "items": items, "cached": False}
    finally:
        _RECENT_LOCK.release()


def _tail_lines(path_obj, lines=20):
    if not path_obj.exists():
        return []
    n = max(1, min(lines, 200))
    try:
        out = subprocess.check_output(["tail", "-n", str(n), str(path_obj)], text=True, timeout=4)
        return [ln for ln in out.splitlines() if ln.strip()]
    except Exception:
        return []


def get_claude_status():
    cli_path = shutil.which("claude") or ""
    if not cli_path:
        fallback = Path("/root/.local/bin/claude")
        if fallback.exists():
            cli_path = str(fallback)
    cli_version = run_cmd([cli_path, "--version"]) if cli_path else ""
    hist_path = Path("/root/.claude/history.jsonl")
    settings_path = Path("/root/.claude/settings.json")
    local_settings_path = Path("/root/.claude/settings.local.json")
    root_state_path = Path("/root/.claude.json")

    hist_meta = _file_meta(hist_path)
    settings_meta = _file_meta(settings_path)
    local_settings_meta = _file_meta(local_settings_path)
    root_state_meta = _file_meta(root_state_path)

    entries = 0
    last_event = {"timestamp": "", "project": "", "session_id": "", "preview": ""}
    if hist_meta["exists"]:
        try:
            with hist_path.open("r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        entries += 1
        except Exception:
            entries = 0

        tail = _tail_lines(hist_path, 1)
        if tail:
            try:
                obj = json.loads(tail[0])
                ts_ms = int(obj.get("timestamp", 0))
                ts_iso = (
                    datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).isoformat()
                    if ts_ms > 0
                    else ""
                )
                preview = str(obj.get("display", "")).strip().replace("\n", " ")
                if len(preview) > 140:
                    preview = preview[:137] + "..."
                last_event = {
                    "timestamp": ts_iso,
                    "project": str(obj.get("project", "")),
                    "session_id": str(obj.get("sessionId", "")),
                    "preview": preview,
                }
            except Exception:
                pass

    proc_count_txt = run_cmd(["bash", "-lc", "ps -ef | rg -i '(^|/)claude(\\s|$)' | rg -v 'rg -i' | wc -l"])
    try:
        proc_count = int(proc_count_txt or "0")
    except ValueError:
        proc_count = 0

    return {
        "cli_path": cli_path,
        "cli_version": cli_version,
        "process_count": proc_count,
        "history": {"entries": entries, **hist_meta},
        "settings": settings_meta,
        "settings_local": local_settings_meta,
        "root_state": root_state_meta,
        "last_event": last_event,
    }


def get_codex_status():
    cli_path = shutil.which("codex") or ""
    if not cli_path:
        fallback = Path("/usr/bin/codex")
        if fallback.exists():
            cli_path = str(fallback)
    cli_version = run_cmd([cli_path, "--version"]) if cli_path else ""

    hist_path = Path("/root/.codex/history.jsonl")
    config_path = Path("/root/.codex/config.toml")
    version_path = Path("/root/.codex/version.json")
    auth_path = Path("/root/.codex/auth.json")

    hist_meta = _file_meta(hist_path)
    config_meta = _file_meta(config_path)
    version_meta = _file_meta(version_path)
    auth_meta = _file_meta(auth_path)

    entries = 0
    last_event = {"timestamp": "", "project": "/root", "session_id": "", "preview": ""}
    if hist_meta["exists"]:
        try:
            with hist_path.open("r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        entries += 1
        except Exception:
            entries = 0

        tail = _tail_lines(hist_path, 1)
        if tail:
            try:
                obj = json.loads(tail[0])
                ts = int(obj.get("ts", 0))
                ts_iso = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat() if ts > 0 else ""
                preview = str(obj.get("text", "")).strip().replace("\n", " ")
                if len(preview) > 140:
                    preview = preview[:137] + "..."
                last_event = {
                    "timestamp": ts_iso,
                    "project": "/root",
                    "session_id": str(obj.get("session_id", "")),
                    "preview": preview,
                }
            except Exception:
                pass

    proc_count_txt = run_cmd(["bash", "-lc", "ps -ef | rg -i '(^|/)codex(\\s|$)' | rg -v 'rg -i' | wc -l"])
    try:
        proc_count = int(proc_count_txt or "0")
    except ValueError:
        proc_count = 0

    return {
        "cli_path": cli_path,
        "cli_version": cli_version,
        "process_count": proc_count,
        "history": {"entries": entries, **hist_meta},
        "config": config_meta,
        "version_file": version_meta,
        "auth_file": auth_meta,
        "last_event": last_event,
    }


def run_action(action_name):
    cmd = ALLOWED_ACTIONS.get(action_name)
    if not cmd:
        return {"ok": False, "message": "Action not allowed"}
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=20, check=False)
        ok = proc.returncode == 0
        msg = "Action completed" if ok else (proc.stderr.strip() or proc.stdout.strip() or "Action failed")
        return {"ok": ok, "message": msg, "return_code": proc.returncode}
    except Exception as e:
        return {"ok": False, "message": str(e)}


def read_logs(service_name, lines):
    if service_name not in ALLOWED_LOG_SERVICES:
        return {"ok": False, "message": "Service not allowed", "logs": ""}
    n = max(10, min(lines, 200))
    try:
        proc = subprocess.run(
            ["journalctl", "-u", service_name, "-n", str(n), "--no-pager", "-o", "short-iso"],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
        if proc.returncode != 0:
            return {"ok": False, "message": proc.stderr.strip() or "Failed to read logs", "logs": ""}
        return {"ok": True, "message": "ok", "logs": proc.stdout}
    except Exception as e:
        return {"ok": False, "message": str(e), "logs": ""}


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, data, code=200):
        payload = json.dumps(data).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _send_file(self, path):
        if not path.exists():
            self.send_error(404, "Not Found")
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_bytes(self, data, content_type):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/status":
            self._send_json(get_status())
            return
        if parsed.path == "/api/files/roots":
            self._send_json(get_watch_roots())
            return
        if parsed.path == "/api/files/list":
            q = parse_qs(parsed.query)
            root_id = q.get("root", ["workspace"])[0]
            rel_path = q.get("path", [""])[0]
            self._send_json(list_files(root_id, rel_path))
            return
        if parsed.path == "/api/files/tree":
            q = parse_qs(parsed.query)
            root_id = q.get("root", [MAP_ROOT_ID])[0]
            rel_path = q.get("path", [""])[0]
            self._send_json(get_tree_branch(root_id, rel_path))
            return
        if parsed.path == "/api/files/file":
            q = parse_qs(parsed.query)
            root_id = q.get("root", ["workspace"])[0]
            rel_path = q.get("path", [""])[0]
            full = q.get("full", ["0"])[0] == "1"
            self._send_json(read_file(root_id, rel_path, full=full))
            return
        if parsed.path == "/api/files/search":
            q = parse_qs(parsed.query)
            query = q.get("q", [""])[0].strip()
            try:
                limit = int(q.get("limit", ["50"])[0])
            except ValueError:
                limit = 50
            filters = {
                "name": q.get("name", [""])[0].strip(),
                "kind": q.get("kind", []),
                "dotfiles": q.get("dotfiles", ["1"])[0].strip(),
                "size_op": q.get("size_op", [""])[0].strip(),
                "size_val": q.get("size_val", ["0"])[0].strip(),
                "size_unit": q.get("size_unit", ["1024"])[0].strip(),
                "mtime_days": q.get("mtime_days", ["0"])[0].strip(),
                "ext": q.get("ext", [""])[0].strip(),
            }
            self._send_json(search_files(query, limit=limit, filters=filters))
            return
        if parsed.path == "/api/trash":
            self._send_json(trash_list())
            return
        if parsed.path == "/api/files/recent":
            q = parse_qs(parsed.query)
            try:
                limit = int(q.get("limit", ["40"])[0])
            except ValueError:
                limit = 40
            self._send_json(recent_changes(limit))
            return
        if parsed.path == "/api/file/raw":
            q = parse_qs(parsed.query)
            root_id = q.get("root", ["workspace"])[0]
            rel_path = q.get("path", [""])[0]
            try:
                target = _resolve_within(root_id, rel_path)
            except Exception:
                self.send_error(400, "Invalid path")
                return
            if not target.exists() or not target.is_file():
                self.send_error(404, "Not Found")
                return
            mime, _ = mimetypes.guess_type(str(target))
            self._send_bytes(target.read_bytes(), mime or "application/octet-stream")
            return
        if parsed.path == "/api/claude/history":
            q = parse_qs(parsed.query)
            try:
                lines = int(q.get("lines", ["40"])[0])
            except ValueError:
                lines = 40
            path = Path("/root/.claude/history.jsonl")
            tail = _tail_lines(path, lines)
            payload = {"ok": True, "message": "ok", "lines": tail}
            self._send_json(payload)
            return
        if parsed.path == "/api/codex/history":
            q = parse_qs(parsed.query)
            try:
                lines = int(q.get("lines", ["40"])[0])
            except ValueError:
                lines = 40
            path = Path("/root/.codex/history.jsonl")
            tail = _tail_lines(path, lines)
            payload = {"ok": True, "message": "ok", "lines": tail}
            self._send_json(payload)
            return
        if parsed.path == "/api/logs":
            q = parse_qs(parsed.query)
            service_name = q.get("service", [OPENCLAW_SERVICE_NAME])[0]
            try:
                lines = int(q.get("lines", ["80"])[0])
            except ValueError:
                lines = 80
            self._send_json(read_logs(service_name, lines))
            return
        if parsed.path == "/" or parsed.path.startswith("/index.html"):
            self._send_file(INDEX_PATH)
            return
        if parsed.path == "/chat" or parsed.path == "/chat.html":
            self._send_file(CHAT_PATH)
            return
        if parsed.path == "/chat-transcript" or parsed.path == "/chat-transcript.html":
            self._send_file(CHAT_TRANSCRIPT_PATH)
            return
        if parsed.path == "/files" or parsed.path == "/files.html":
            self._send_file(FILES_PATH)
            return
        self.send_error(404, "Not Found")

    def do_POST(self):
        if self.path == "/api/files/upload":
            try:
                body_len = int(self.headers.get("Content-Length", "0"))
                if body_len > 52 * 1024 * 1024:
                    self._send_json({"ok": False, "message": "Payload too large"}, code=413)
                    return
                body = self.rfile.read(body_len)
                content_type = self.headers.get("Content-Type", "")
                parts = parse_multipart(content_type, body)
                fields = {}
                file_entry = None
                for name, fname, data in parts:
                    if fname is not None:
                        file_entry = (fname, data)
                    else:
                        fields[name] = data.decode("utf-8", errors="replace").strip()
                root_id = fields.get("root", "workspace")
                rel_dir = fields.get("path", "")
                if not file_entry:
                    self._send_json({"ok": False, "message": "No file in upload"}, code=400)
                    return
                filename, file_data = file_entry
                self._send_json(upload_file(root_id, rel_dir, filename, file_data))
            except Exception as e:
                self._send_json({"ok": False, "message": str(e)}, code=500)
            return
        if self.path == "/api/files/save":
            try:
                body_len = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(body_len)
                payload = json.loads(body.decode("utf-8"))
                root_id = str(payload.get("root", "workspace"))
                rel_path = str(payload.get("path", ""))
                content = str(payload.get("content", ""))
                new_filename = payload.get("new_filename") or None
                if new_filename:
                    new_filename = str(new_filename)
                self._send_json(save_text_file(root_id, rel_path, content, new_filename))
            except Exception as e:
                self._send_json({"ok": False, "message": str(e)}, code=500)
            return
        if self.path == "/api/files/create":
            try:
                body_len = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(body_len)
                payload = json.loads(body.decode("utf-8"))
                root_id = str(payload.get("root", "workspace"))
                rel_dir = str(payload.get("path", "uploads"))
                filename = str(payload.get("filename", ""))
                content = str(payload.get("content", ""))
                self._send_json(create_text_file(root_id, rel_dir, filename, content))
            except Exception as e:
                self._send_json({"ok": False, "message": str(e)}, code=500)
            return
        if self.path == "/api/files/prime-directories":
            try:
                body_len = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(body_len)
                payload = json.loads(body.decode("utf-8"))
                self._send_json(save_prime_directories(payload.get("items", [])))
            except Exception as e:
                self._send_json({"ok": False, "message": str(e)}, code=500)
            return
        if self.path == "/api/files/favorites/reorder":
            try:
                body_len = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(body_len)
                payload = json.loads(body.decode("utf-8"))
                self._send_json(save_favorites_order(payload.get("order", [])))
            except Exception as e:
                self._send_json({"ok": False, "message": str(e)}, code=500)
            return
        if self.path == "/api/files/delete":
            try:
                body_len = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(body_len)
                payload = json.loads(body.decode("utf-8"))
                items = payload.get("items", [])
                if not items:
                    self._send_json({"ok": False, "message": "No items specified"}, code=400)
                    return
                self._send_json(trash_move(items))
            except Exception as e:
                self._send_json({"ok": False, "message": str(e)}, code=500)
            return
        if self.path == "/api/trash/restore":
            try:
                body_len = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(body_len)
                payload = json.loads(body.decode("utf-8"))
                items = payload.get("items", [])
                if not items:
                    self._send_json({"ok": False, "message": "No items specified"}, code=400)
                    return
                self._send_json(trash_restore(items))
            except Exception as e:
                self._send_json({"ok": False, "message": str(e)}, code=500)
            return
        if self.path == "/api/trash/empty":
            try:
                self._send_json(trash_empty())
            except Exception as e:
                self._send_json({"ok": False, "message": str(e)}, code=500)
            return
        if self.path == "/api/trash/delete":
            try:
                body_len = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(body_len)
                payload = json.loads(body.decode("utf-8"))
                items = payload.get("items", [])
                if not items:
                    self._send_json({"ok": False, "message": "No items specified"}, code=400)
                    return
                self._send_json(trash_delete(items))
            except Exception as e:
                self._send_json({"ok": False, "message": str(e)}, code=500)
            return
        if self.path != "/api/action":
            self.send_error(404, "Not Found")
            return
        try:
            body_len = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(body_len) if body_len > 0 else b"{}"
            payload = json.loads(body.decode("utf-8"))
            action_name = str(payload.get("action", "")).strip()
        except Exception:
            self._send_json({"ok": False, "message": "Invalid JSON body"}, code=400)
            return
        self._send_json(run_action(action_name))

    def log_message(self, fmt, *args):
        return


def main():
    SEARCH_INDEX.start()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    server.daemon_threads = True
    print(f"Serving dashboard on http://{HOST}:{PORT}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        SEARCH_INDEX.stop()


if __name__ == "__main__":
    main()
