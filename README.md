# Karo Backend

FastAPI service providing the websocket lobby and realtime caro (gomoku) gameplay.

## Requirements

- Python 3.10+
- Dependencies listed in `requirements.txt`

The repository currently includes a ready-made virtual environment under `Scripts/`. You can reuse it or delete it and provision your own.

## Project layout

```text
app/
  api/            # FastAPI/WebSocket wiring
  core/           # shared config and time helpers
  models/         # dataclasses representing clients, invites, games
  services/       # connection manager orchestrating lobby + games
  main.py         # tiny app factory that wires everything together
```

Key tuning knobs live in `app/core/config.py` (board size, invite timeout, move deadline).

## Setup

```pwsh
# From the repo root
Set-Location karo-be
python -m venv .venv      # optional if you want a clean env
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
- Lobby presence, invites, active game state, timers, and chat messages are exchanged through JSON payloads handled by `ConnectionManager`.
- Game boards default to 17×17, turns time out after 30 seconds, and invites expire after 20 seconds (configurable in `app/core/config.py`).
- Use `python -m compileall app` for a quick syntax check if you do not have a dedicated test harness.
