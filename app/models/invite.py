"""Invite model capturing lobby challenge metadata."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime


@dataclass
class Invite:
    """Represents a pending invitation to start a match."""

    id: str
    inviter_id: str
    target_id: str
    expires_at: datetime
    timeout_task: asyncio.Task
