# OpenClaw File Browser

OpenClaw File Browser is a small self-hosted dashboard for browsing an OpenClaw machine from the browser. It is built as a plain Python HTTP server plus static HTML pages, with no frontend build step and no framework dependency.

The repo started as a filesystem browser, but it now also includes companion dashboard pages for host status, OpenClaw health, logs, and quick launch links.

## What it does

The main `/files` experience is designed for a trusted personal server where you want fast access to the working filesystem around OpenClaw:

- browse multiple watch roots such as `/root`, OpenClaw state, workspace files, sessions, projects, uploads, and `/opt/openclaw`
- jump through curated favorites for common folders and files
- search files across all watch roots
- inspect directories with breadcrumbs and recent-change feeds
- preview text, markdown, images, and basic binary metadata
- open a fullscreen visual map of `/root` with pan, zoom, and lazy folder expansion
- upload files into the currently open directory
- create new markdown files from the browser
- edit and save existing text files
- use a desktop floating image window or mobile inline image preview
- use a mobile-friendly layout with bottom navigation and touch-sized controls

## Included pages

- `files.html` at `/files`
  - primary file browser UI
  - watch roots, favorites, search, directory tree, recent files, preview pane
  - fullscreen `/root` map view
  - upload and file creation/edit flows

- `index.html` at `/`
  - companion dashboard / status board
  - host, disk, memory, gateway, and service status
  - Claude and Codex history summaries
  - OpenClaw log access and restart action
  - links into the file browser and chat launcher

- `chat.html` at `/chat`
  - lightweight launcher page for opening live OpenClaw chat

- `chat-transcript.html` at `/chat-transcript`
  - static transcript/reference page

- `server.py`
  - serves all pages
  - exposes the JSON endpoints used by the browser and dashboard

## Key file-browser features

### Filesystem browsing

- configurable watch roots with labels and descriptions
- one-click favorites
- directory listing with breadcrumbs and parent navigation
- recent file feed across all configured roots
- filename/path search across roots
- per-directory entry cap to keep large folders responsive

### Preview and editing

- text preview for common source, config, log, and markup files
- markdown rendering for `.md` and `.markdown`
- image preview through raw file endpoints
- floating desktop image viewer with drag/resize
- inline mobile image preview
- edit/save flow for text files
- quick-create modal for new markdown files

### Visual map view

- `Map View` button in the file-browser header
- fullscreen, pannable map of `/root`
- lazy loading of folder branches through `/api/files/tree`
- click folders to expand/collapse descendants
- select a node and jump back into the normal browser view
- touch-friendly behavior for mobile and tablet browsing

### Mobile behavior

- bottom nav to switch between roots, browse, recent, and preview
- compact sticky headers
- larger touch targets for directory entries and actions
- mobile back button inside preview
- swipe-based panel navigation outside modal/map contexts

## HTTP API

The app is intentionally small and uses direct JSON endpoints:

- `GET /api/status`
  - host stats, gateway reachability, OpenClaw/dashboard service info, Claude/Codex summaries, Spurs info

- `GET /api/files/roots`
  - watch roots and favorites

- `GET /api/files/list?root=<id>&path=<relative>`
  - normal directory listing

- `GET /api/files/tree?root=root-home&path=<relative>`
  - lazy branch loading for the fullscreen `/root` map

- `GET /api/files/file?root=<id>&path=<relative>&full=0|1`
  - file preview payload

- `GET /api/file/raw?root=<id>&path=<relative>`
  - raw file bytes, mainly for image preview

- `GET /api/files/search?q=<query>&limit=<n>`
  - cross-root filename/path search

- `GET /api/files/recent?limit=<n>`
  - recent files across configured roots

- `POST /api/files/upload`
  - multipart upload into the selected directory

- `POST /api/files/create`
  - create a new text/markdown file

- `POST /api/files/save`
  - overwrite an existing text file, optionally renaming it

- `GET /api/logs?service=<name>&lines=<n>`
  - journal output for approved services

- `GET /api/claude/history?lines=<n>`
- `GET /api/codex/history?lines=<n>`

- `POST /api/action`
  - currently used for approved actions such as restarting OpenClaw

## Quick start

1. Make sure Python 3.11+ is available.
2. Copy the example environment file:

```bash
cp .env.example .env.local
```

3. Review the path values in `.env.local`.
4. Create the uploads directory if needed:

```bash
mkdir -p uploads
```

5. Start the server:

```bash
python3 server.py
```

6. Open the served address and visit:
   - `/files` for the file browser
   - `/` for the status/dashboard page

## Configuration

The app loads `.env` and `.env.local` automatically.

### Network and service settings

- `OPENCLAW_FILE_BROWSER_HOST`
- `OPENCLAW_FILE_BROWSER_PORT`
- `OPENCLAW_GATEWAY_URL`
- `OPENCLAW_SERVICE_NAME`
- `OPENCLAW_FILE_BROWSER_SERVICE_NAME`

### Core OpenClaw paths

- `OPENCLAW_FILE_BROWSER_HOME_DIR`
- `OPENCLAW_HOME_DIR`
- `OPENCLAW_WORKSPACE_DIR`
- `OPENCLAW_RESEARCH_MEMORY_DIR`
- `OPENCLAW_SESSIONS_DIR`

### Browser-local and project paths

- `OPENCLAW_FILE_BROWSER_UPLOADS_DIR`
- `OPENCLAW_FILE_BROWSER_DASHBOARD_DIR`
- `OPENCLAW_FILE_BROWSER_PROJECTS_DIR`
- `OPENCLAW_FILE_BROWSER_PROJECT_DIR`
- `OPENCLAW_INSTALL_DIR`

The default watch-root and favorite definitions still live in `server.py`, but the path defaults are driven by these environment variables.

## Operational notes

- This is for trusted, self-hosted environments. It is not a hardened public file manager.
- Path access is constrained to configured watch roots.
- Hidden/internal names such as `.git`, `node_modules`, `__pycache__`, and `.openclaw.bak.nested` are skipped in listings.
- Large directories are capped per response to protect UI responsiveness.
- The `/root` map view is intentionally limited to the `root-home` watch root.
- Uploads and file creation/editing are real write operations on the host.

## Development notes

- No frontend build step is required.
- The UI is a single static HTML file with inline CSS and JavaScript.
- Restart the running dashboard service after changing `server.py`, since the Python process must reload to expose new backend endpoints.

## License

MIT
