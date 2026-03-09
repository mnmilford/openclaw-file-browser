# OpenClaw File Browser

OpenClaw File Browser is a lightweight local web app for browsing OpenClaw state, workspace files, session transcripts, and uploads from a single page.

It is designed for self-hosted OpenClaw setups where you want a fast read-first file browser with:

- multiple watch roots
- favorites for common folders
- text and image preview
- a floating image window
- lightweight upload and file creation endpoints

## What is in this repo

- `files.html`: the file browser UI
- `server.py`: a small Python HTTP server that serves the UI and exposes file APIs
- `index.html`, `chat.html`, `chat-transcript.html`: optional companion dashboard pages

## Quick start

1. Make sure Python 3.11+ is available.
2. Review the paths in `WATCH_ROOTS` and `FAVORITES` inside `server.py`.
3. Copy the example env file and adjust it for your machine:

```bash
cp .env.example .env.local
```

4. Create the uploads directory if needed:

```bash
mkdir -p uploads
```

5. Start the server:

```bash
python3 server.py
```

6. Open the served address in your browser and visit `/files`.

## Configuration

This project is intentionally simple. The main customization point is the environment.

- `.env.example` documents the supported environment variables.
- `server.py` auto-loads `.env` and `.env.local` if present.
- `OPENCLAW_HOME_DIR`, `OPENCLAW_WORKSPACE_DIR`, `OPENCLAW_RESEARCH_MEMORY_DIR`, and `OPENCLAW_SESSIONS_DIR` control the main OpenClaw watch roots.
- `OPENCLAW_FILE_BROWSER_UPLOADS_DIR` and `OPENCLAW_FILE_BROWSER_PROJECT_DIR` control browser-local and project-specific roots.
- `OPENCLAW_SERVICE_NAME`, `OPENCLAW_FILE_BROWSER_SERVICE_NAME`, and `OPENCLAW_GATEWAY_URL` control the optional status and log endpoints used by the companion dashboard pages.

`WATCH_ROOTS` and `FAVORITES` still live in `server.py`, but the default paths now come from environment variables.

If you are publishing or sharing your setup, review those paths and labels first.

## Notes

- The default configuration assumes an OpenClaw install rooted at `/root/.openclaw`.
- The repo ignores runtime uploads and Python cache files by default.
- This is intended for trusted local or self-hosted environments, not an internet-hardened public file manager.
- The included license is MIT because it is the least-friction choice for a small reusable infrastructure tool.
