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
3. Create the uploads directory if needed:

```bash
mkdir -p uploads
```

4. Start the server:

```bash
python3 server.py
```

5. Open the served address in your browser and visit `/files`.

## Configuration

This project is intentionally simple. The main customization point is `server.py`.

- `WATCH_ROOTS` controls which directories appear in the browser.
- `FAVORITES` controls the quick links shown in the UI.
- `ALLOWED_ACTIONS` and `ALLOWED_LOG_SERVICES` control the optional service management endpoints used by the companion dashboard pages.

If you are publishing or sharing your setup, review those paths and labels first.

## Notes

- The default configuration assumes an OpenClaw install rooted at `/root/.openclaw`.
- The repo ignores runtime uploads and Python cache files by default.
- This is intended for trusted local or self-hosted environments, not an internet-hardened public file manager.
