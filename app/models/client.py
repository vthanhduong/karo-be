"""Client model representing a connected websocket participant."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, Optional

from fastapi import WebSocket


@dataclass
class Client:
    """A websocket client participating in the caro lobby or a match."""

    id: str
    websocket: WebSocket
    name: Optional[str] = None
    state: str = "awaiting_name"
    game_id: Optional[str] = None

    async def send(self, message: Dict[str, Any]) -> None:
        """Send a JSON-serialisable payload to the client."""
        await self.websocket.send_text(json.dumps(message))
