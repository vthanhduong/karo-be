"""Game state tracking for an active caro match."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from app.core.config import BOARD_SIZE, MOVE_TIMEOUT_SECONDS
from app.core.time import utcnow


@dataclass
class GameState:
    """In-memory representation of a running caro match."""

    id: str
    players: Dict[str, str]  # mark -> client_id
    board: List[List[str]] = field(
        default_factory=lambda: [["" for _ in range(BOARD_SIZE)] for _ in range(BOARD_SIZE)]
    )
    turn: str = "x"
    turn_deadline: datetime = field(
        default_factory=lambda: utcnow() + timedelta(seconds=MOVE_TIMEOUT_SECONDS)
    )
    turn_timer: Optional[asyncio.Task] = None
    winner: Optional[str] = None
    result_reason: Optional[str] = None

    def place_mark(self, mark: str, x: int, y: int) -> bool:
        if not (0 <= x < BOARD_SIZE and 0 <= y < BOARD_SIZE):
            return False
        if self.board[y][x]:
            return False
        self.board[y][x] = mark
        return True

    def check_winner(self, mark: str, x: int, y: int) -> Optional[List[Dict[str, int]]]:
        directions = [(1, 0), (0, 1), (1, 1), (1, -1)]
        for dx, dy in directions:
            count = 1
            cells = [(x, y)]
            for sign in (-1, 1):
                nx, ny = x, y
                while True:
                    nx += dx * sign
                    ny += dy * sign
                    if 0 <= nx < BOARD_SIZE and 0 <= ny < BOARD_SIZE and self.board[ny][nx] == mark:
                        count += 1
                        cells.append((nx, ny))
                    else:
                        break
            if count >= 5:
                return [{"x": cx, "y": cy} for cx, cy in cells]
        return None

    def is_draw(self) -> bool:
        return all(cell for row in self.board for cell in row)
