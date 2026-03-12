#!/usr/bin/env python3
import json
import mimetypes
import os
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


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
load_env_file(BASE_DIR / ".env")
load_env_file(BASE_DIR / ".env.local")
INDEX_PATH = BASE_DIR / "index.html"
CHAT_PATH = BASE_DIR / "chat.html"
CHAT_TRANSCRIPT_PATH = BASE_DIR / "chat-transcript.html"
FILES_PATH = BASE_DIR / "files.html"
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
TEXT_EXTENSIONS = {
    ".c", ".cc", ".cfg", ".conf", ".cpp", ".css", ".csv", ".env", ".gitignore", ".go",
    ".h", ".html", ".ini", ".java", ".js", ".json", ".jsonl", ".log", ".md", ".mjs",
    ".py", ".rb", ".rs", ".sh", ".sql", ".svg", ".toml", ".ts", ".tsx", ".txt", ".xml",
    ".yaml", ".yml",
}
IMAGE_EXTENSIONS = {".avif", ".gif", ".jpeg", ".jpg", ".png", ".svg", ".webp"}
SKIP_NAMES = {".git", "node_modules", "__pycache__", ".openclaw.bak.nested"}
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
}
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
    return {"roots": roots, "favorites": FAVORITES}


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
    root_path = _safe_root(root_id).resolve()
    return {
        "ok": True,
        "message": "Saved",
        "filename": target.name,
        "path": str(target.relative_to(root_path)),
        "size": target.stat().st_size,
    }


def search_files(query, limit=50):
    """Search for files matching query across all watch roots."""
    query_lower = query.lower()
    results = []
    
    for root_id, root_config in WATCH_ROOTS.items():
        root_path = root_config["path"]
        if not root_path.exists():
            continue
        
        try:
            for item in root_path.rglob("*"):
                if item.is_dir():
                    continue
                if item.name.lower().startswith('.'):
                    continue
                    
                # Check if query matches filename or path
                if query_lower in item.name.lower() or query_lower in str(item).lower():
                    try:
                        rel_path = str(item.relative_to(root_path))
                        stat = item.stat()
                        results.append({
                            "root": root_id,
                            "path": rel_path,
                            "name": item.name,
                            "size": stat.st_size,
                            "modified": int(stat.st_mtime),
                            "full_path": str(item),
                        })
                    except Exception:
                        pass
                    
                    if len(results) >= limit:
                        break
            if len(results) >= limit:
                break
        except Exception:
            pass
    
    return {"ok": True, "query": query, "results": results[:limit]}


def recent_changes(limit=40):
    files = []
    max_files = max(10, min(limit, 100))
    for root_id, meta in WATCH_ROOTS.items():
        base = meta["path"]
        if not base.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in SKIP_NAMES]
            for name in filenames:
                if name in SKIP_NAMES:
                    continue
                path_obj = Path(dirpath) / name
                try:
                    stat = path_obj.stat()
                except OSError:
                    continue
                rel_path = str(path_obj.relative_to(base))
                files.append(
                    {
                        "root": root_id,
                        "label": meta["label"],
                        "path": rel_path,
                        "absolute_path": str(path_obj),
                        "mtime": _iso_mtime(stat.st_mtime),
                        "size": stat.st_size,
                        "kind": _guess_kind(path_obj),
                    }
                )
    files.sort(key=lambda item: item["mtime"], reverse=True)
    return {"ok": True, "items": files[:max_files]}


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
            if not query:
                self._send_json({"ok": False, "message": "Missing query parameter 'q'"}, code=400)
                return
            try:
                limit = int(q.get("limit", ["50"])[0])
            except ValueError:
                limit = 50
            self._send_json(search_files(query, limit=limit))
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
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    server.daemon_threads = True
    print(f"Serving dashboard on http://{HOST}:{PORT}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
