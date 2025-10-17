# Karo Backend

This FastAPI service exposes a single WebSocket endpoint used by the caro (gomoku) game lobby and matches.

## Requirements

- Python 3.10+
- Dependencies listed in `requirements.txt`

The repository already includes a virtual environment under `Scripts/`. If you prefer a fresh environment, you can remove it and create your own.

## Setup

```pwsh
# From the repo root
Set-Location karo-be
python -m venv .venv  # optional if you want a clean env
.\.venv\Scripts\Activate.ps1  # or use the bundled Scripts\Activate.ps1
pip install --upgrade pip
pip install -r requirements.txt
```

## Run the server

```pwsh
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

The WebSocket endpoint is exposed at `ws://localhost:8000/ws`.

## Development notes

- Each connected player registers a unique display name via the WebSocket.
- Lobby presence, invites, active game state, timers, and chat messages are all delivered through JSON messages documented in the shared protocol.
- Game boards are 25×25, turns time out after 30 seconds, and invites expire after 20 seconds.

Use `python -m compileall app` to perform a quick syntax check if you do not have a test harness available.
