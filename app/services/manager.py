"""Connection manager coordinating lobby, games, and chat."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set

from fastapi import WebSocket

from app.core.config import INVITE_TIMEOUT_SECONDS, MOVE_TIMEOUT_SECONDS
from app.core.time import to_iso, utcnow
from app.models.client import Client
from app.models.game import GameState
from app.models.invite import Invite


class ConnectionManager:
    """Manage websocket clients and orchestrate game flow."""

    def __init__(self) -> None:
        self.clients: Dict[str, Client] = {}
        self.name_to_id: Dict[str, str] = {}
        self.invites: Dict[str, Invite] = {}
        self.games: Dict[str, GameState] = {}
        self.lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> Client:
        await websocket.accept()
        client_id = uuid.uuid4().hex
        client = Client(id=client_id, websocket=websocket)
        async with self.lock:
            self.clients[client_id] = client
        return client

    async def disconnect(self, client: Client) -> None:
        name_known = client.name is not None
        async with self.lock:
            if client.id in self.clients:
                del self.clients[client.id]
            if client.name:
                self.name_to_id.pop(client.name.lower(), None)
        await self._cleanup_invites_for_client(client.id)
        await self._handle_disconnect_game(client)
        if name_known:
            await self.broadcast_lobby({
                "type": "user_left",
                "userId": client.id,
            })

    async def register_name(self, client: Client, name: str) -> Optional[str]:
        clean = name.strip()
        if not (3 <= len(clean) <= 20):
            return "invalid_name"
        key = clean.lower()
        async with self.lock:
            if key in self.name_to_id:
                return "name_taken"
            client.name = clean
            client.state = "lobby"
            self.name_to_id[key] = client.id
            users = [self._user_summary(c) for c in self.clients.values() if c.id != client.id and c.name]
        await client.send({
            "type": "join_ok",
            "self": {"id": client.id, "name": client.name},
            "users": users,
        })
        await self.broadcast_lobby({
            "type": "user_joined",
            "user": self._user_summary(client),
        }, exclude={client.id})
        return None

    async def broadcast_lobby(self, message: Dict[str, Any], exclude: Optional[Set[str]] = None) -> None:
        if exclude is None:
            exclude = set()
        coros = []
        async with self.lock:
            for client in self.clients.values():
                if client.id in exclude:
                    continue
                if client.state == "lobby":
                    coros.append(client.send(message))
        if coros:
            await asyncio.gather(*coros, return_exceptions=True)

    async def broadcast_all(self, message: Dict[str, Any], exclude: Optional[Set[str]] = None) -> None:
        if exclude is None:
            exclude = set()
        async with self.lock:
            recipients = [c for c in self.clients.values() if c.id not in exclude and c.name]
        coros = [client.send(message) for client in recipients]
        if coros:
            await asyncio.gather(*coros, return_exceptions=True)

    async def broadcast_game(self, game_id: str, message: Dict[str, Any]) -> None:
        async with self.lock:
            game = self.games.get(game_id)
            if not game:
                return
            recipients = [self.clients.get(cid) for cid in game.players.values()]
        coros: List[Any] = []
        for client in recipients:
            if client:
                coros.append(client.send(message))
        if coros:
            await asyncio.gather(*coros, return_exceptions=True)

    def _user_summary(self, client: Client) -> Dict[str, Any]:
        return {
            "id": client.id,
            "name": client.name,
            "inGame": client.state == "game",
        }

    async def _safe_send(self, client: Optional[Client], message: Dict[str, Any]) -> bool:
        if not client:
            return False
        try:
            await client.send(message)
            return True
        except Exception:
            return False

    async def send_error(self, client: Client, scope: str, message: str) -> None:
        await client.send({"type": "error", "scope": scope, "message": message})

    async def handle_invite(self, client: Client, payload: Dict[str, Any]) -> None:
        if client.state != "lobby":
            await self.send_error(client, "invite", "Bạn không ở trong sảnh")
            return
        target_id = payload.get("targetId")
        if not target_id:
            await self.send_error(client, "invite", "Missing targetId")
            return
        async with self.lock:
            target = self.clients.get(target_id)
            if not target or target.state != "lobby":
                await self.send_error(client, "invite", "Người chơi không khả dụng")
                return
            if target.id == client.id:
                await self.send_error(client, "invite", "Không thể tự mời chính mình")
                return
            invite_id = uuid.uuid4().hex
            expires_at = utcnow() + timedelta(seconds=INVITE_TIMEOUT_SECONDS)
            task = asyncio.create_task(self._expire_invite(invite_id, expires_at))
            self.invites[invite_id] = Invite(
                id=invite_id,
                inviter_id=client.id,
                target_id=target.id,
                expires_at=expires_at,
                timeout_task=task,
            )
            inviter_summary = self._user_summary(client)
        await target.send({
            "type": "invite_received",
            "inviteId": invite_id,
            "from": inviter_summary,
            "expiresAt": to_iso(expires_at),
        })
        await client.send({
            "type": "invite_pending",
            "inviteId": invite_id,
            "targetId": target_id,
            "expiresAt": to_iso(expires_at),
        })

    async def handle_invite_response(self, client: Client, payload: Dict[str, Any]) -> None:
        invite_id = payload.get("inviteId")
        accepted = payload.get("accepted")
        if invite_id is None or accepted is None:
            await self.send_error(client, "invite", "Thiếu thông tin phản hồi")
            return
        inviter = None
        async with self.lock:
            invite = self.invites.get(invite_id)
            inviter = self.clients.get(invite.inviter_id) if invite else None
        if not invite or invite.target_id != client.id:
            await self.send_error(client, "invite", "Lời mời không hợp lệ")
            return
        cleared = await self._clear_invite(invite_id)
        if not cleared:
            await self.send_error(client, "invite", "Lời mời đã hết hạn")
            return
        if not inviter or inviter.state != "lobby" or client.state != "lobby":
            await self.send_error(client, "invite", "Người mời không còn khả dụng")
            if inviter:
                await self.send_error(inviter, "invite", "Lời mời đã hết hiệu lực")
            return
        if not accepted:
            await inviter.send({"type": "invite_declined", "inviteId": invite_id})
            return
        await self._start_game(inviter, client)

    async def _start_game(self, player_x: Client, player_o: Client) -> None:
        game_id = uuid.uuid4().hex
        game = GameState(id=game_id, players={"x": player_x.id, "o": player_o.id})
        timeout_at = game.turn_deadline
        game.turn_timer = asyncio.create_task(self._handle_move_timeout(game_id, timeout_at))
        async with self.lock:
            self.games[game_id] = game
            player_x.state = "game"
            player_o.state = "game"
            player_x.game_id = game_id
            player_o.game_id = game_id

        await self.broadcast_lobby({
            "type": "user_updated",
            "user": self._user_summary(player_x),
        })
        await self.broadcast_lobby({
            "type": "user_updated",
            "user": self._user_summary(player_o),
        })

        payload = {
            "type": "game_start",
            "gameId": game_id,
            "players": {
                "x": {"id": player_x.id, "name": player_x.name},
                "o": {"id": player_o.id, "name": player_o.name},
            },
            "boardSize": len(game.board),
            "turn": game.turn,
            "turnDeadline": to_iso(game.turn_deadline),
        }
        await self.broadcast_game(game_id, payload)

    async def handle_move(self, client: Client, payload: Dict[str, Any]) -> None:
        game_id = payload.get("gameId")
        raw_x = payload.get("x")
        raw_y = payload.get("y")
        if game_id is None or raw_x is None or raw_y is None:
            await self.send_error(client, "move", "Thiếu thông tin nước đi")
            return
        try:
            x = int(raw_x)
            y = int(raw_y)
        except (TypeError, ValueError):
            await self.send_error(client, "move", "Tọa độ không hợp lệ")
            return
        game = self.games.get(game_id)
        if not game or client.id not in game.players.values():
            await self.send_error(client, "move", "Ván đấu không tồn tại")
            return
        mark = next((m for m, cid in game.players.items() if cid == client.id), None)
        if mark != game.turn:
            await self.send_error(client, "move", "Chưa tới lượt của bạn")
            return
        if utcnow() > game.turn_deadline:
            await self._finish_game(game, winner=self._opponent_mark(mark), reason="timeout")
            return
        if not game.place_mark(mark, x, y):
            await self.send_error(client, "move", "Nước đi không hợp lệ")
            return

        if game.turn_timer:
            game.turn_timer.cancel()

        winning_line = game.check_winner(mark, x, y)
        if winning_line:
            await self.broadcast_game(game_id, {
                "type": "move_result",
                "gameId": game_id,
                "move": {"player": mark, "x": x, "y": y},
                "nextTurn": None,
                "turnDeadline": None,
                "winningLine": winning_line,
            })
            await self._finish_game(game, winner=mark, reason="five_in_a_row")
            return

        if game.is_draw():
            await self.broadcast_game(game_id, {
                "type": "move_result",
                "gameId": game_id,
                "move": {"player": mark, "x": x, "y": y},
                "nextTurn": None,
                "turnDeadline": None,
            })
            await self._finish_game(game, winner=None, reason="draw")
            return

        game.turn = self._opponent_mark(mark)
        game.turn_deadline = utcnow() + timedelta(seconds=MOVE_TIMEOUT_SECONDS)
        game.turn_timer = asyncio.create_task(self._handle_move_timeout(game_id, game.turn_deadline))
        await self.broadcast_game(game_id, {
            "type": "move_result",
            "gameId": game_id,
            "move": {"player": mark, "x": x, "y": y},
            "nextTurn": game.turn,
            "turnDeadline": to_iso(game.turn_deadline),
        })

    async def handle_chat(self, client: Client, payload: Dict[str, Any]) -> None:
        game_id = payload.get("gameId")
        text = payload.get("text")
        if not game_id or text is None:
            await self.send_error(client, "chat", "Tin nhắn không hợp lệ")
            return
        game = self.games.get(game_id)
        if not game or client.id not in game.players.values():
            await self.send_error(client, "chat", "Không thể gửi tin nhắn")
            return
        player_mark = next(m for m, cid in game.players.items() if cid == client.id)
        await self.broadcast_game(game_id, {
            "type": "chat_message",
            "gameId": game_id,
            "from": {"player": player_mark, "name": client.name},
            "text": str(text),
            "sentAt": to_iso(utcnow()),
        })

    async def handle_lobby_chat(self, client: Client, payload: Dict[str, Any]) -> None:
        text = payload.get("text")
        if text is None:
            await self.send_error(client, "lobby_chat", "Tin nhắn không hợp lệ")
            return
        if not client.name:
            await self.send_error(client, "lobby_chat", "Bạn chưa đăng ký tên")
            return
        clean = str(text).strip()
        if not clean:
            await self.send_error(client, "lobby_chat", "Tin nhắn không được để trống")
            return
        if len(clean) > 300:
            clean = clean[:300]
        message = {
            "type": "lobby_chat",
            "from": self._user_summary(client),
            "text": clean,
            "sentAt": to_iso(utcnow()),
        }
        await self.broadcast_all(message)

    async def handle_surrender(self, client: Client, payload: Dict[str, Any]) -> None:
        game_id = payload.get("gameId") or client.game_id
        if not game_id:
            await self.send_error(client, "surrender", "Bạn không ở trong trận đấu")
            return
        game = self.games.get(game_id)
        if not game or client.id not in game.players.values():
            await self.send_error(client, "surrender", "Ván đấu không tồn tại")
            return
        mark = next((m for m, cid in game.players.items() if cid == client.id), None)
        if not mark:
            await self.send_error(client, "surrender", "Không xác định được người chơi")
            return
        await self.broadcast_game(game_id, {
            "type": "surrender",
            "gameId": game_id,
            "player": mark,
        })
        await self._finish_game(game, winner=self._opponent_mark(mark), reason="surrender")

    async def _expire_invite(self, invite_id: str, deadline: datetime) -> None:
        await asyncio.sleep(max(0, (deadline - utcnow()).total_seconds()))
        invite = self.invites.get(invite_id)
        if not invite:
            return
        inviter = self.clients.get(invite.inviter_id)
        target = self.clients.get(invite.target_id)
        invite = await self._clear_invite(invite_id)
        if not invite:
            return
        async with self.lock:
            inviter = self.clients.get(invite.inviter_id)
            target = self.clients.get(invite.target_id)
        if inviter:
            await inviter.send({"type": "invite_declined", "inviteId": invite_id, "reason": "timeout"})
        if target:
            await target.send({"type": "invite_cancelled", "inviteId": invite_id})

    async def _clear_invite(self, invite_id: str) -> Optional[Invite]:
        async with self.lock:
            invite = self.invites.pop(invite_id, None)
        if invite and not invite.timeout_task.done():
            invite.timeout_task.cancel()
        return invite

    async def _cleanup_invites_for_client(self, client_id: str) -> None:
        async with self.lock:
            to_remove = [
                iid for iid, inv in self.invites.items() if inv.inviter_id == client_id or inv.target_id == client_id
            ]
        for invite_id in to_remove:
            invite = await self._clear_invite(invite_id)
            if not invite:
                continue
            async with self.lock:
                inviter = self.clients.get(invite.inviter_id)
                target = self.clients.get(invite.target_id)
            if inviter and inviter.id != client_id:
                await inviter.send({"type": "invite_declined", "inviteId": invite_id, "reason": "cancelled"})
            if target and target.id != client_id:
                await target.send({"type": "invite_cancelled", "inviteId": invite_id})

    async def _handle_move_timeout(self, game_id: str, deadline: datetime) -> None:
        await asyncio.sleep(max(0, (deadline - utcnow()).total_seconds()))
        async with self.lock:
            game = self.games.get(game_id)
            if not game or game.turn_deadline != deadline:
                return
        current_mark = game.turn
        await self.broadcast_game(game_id, {
            "type": "move_result",
            "gameId": game_id,
            "move": None,
            "nextTurn": None,
            "turnDeadline": None,
            "timeout": {"player": current_mark} if current_mark else None,
        })
        await self._finish_game(game, winner=self._opponent_mark(current_mark), reason="timeout")

    async def _finish_game(self, game: GameState, winner: Optional[str], reason: str) -> None:
        if game.result_reason is not None:
            return
        current_task = asyncio.current_task()
        if game.turn_timer and not game.turn_timer.done() and game.turn_timer is not current_task:
            game.turn_timer.cancel()
        game.turn_timer = None
        game.winner = winner
        game.result_reason = reason
        await self.broadcast_game(game.id, {
            "type": "game_over",
            "gameId": game.id,
            "result": {
                "winner": winner,
                "reason": reason,
            },
        })
        async with self.lock:
            players = []
            for mark, client_id in game.players.items():
                client = self.clients.get(client_id)
                if client:
                    client.state = "lobby"
                    client.game_id = None
                players.append((mark, client))
            self.games.pop(game.id, None)
            all_users = [self._user_summary(c) for c in self.clients.values() if c.name]
        for mark, client in players:
            if not client:
                continue
            await self._safe_send(client, {
                "type": "return_to_lobby",
            })
            await self._safe_send(client, {
                "type": "game_result",
                "gameId": game.id,
                "you": mark,
                "winner": winner,
                "reason": reason,
            })
            await self._safe_send(client, {
                "type": "lobby_snapshot",
                "users": [u for u in all_users if u["id"] != client.id],
            })
            await self.broadcast_lobby({
                "type": "user_updated",
                "user": self._user_summary(client),
            }, exclude={client.id})

    async def _handle_disconnect_game(self, client: Client) -> None:
        if not client.game_id:
            return
        game = self.games.get(client.game_id)
        if not game:
            return
        player_mark = next((m for m, cid in game.players.items() if cid == client.id), None)
        if not player_mark:
            return
        winner_mark = self._opponent_mark(player_mark)
        await self._finish_game(game, winner=winner_mark, reason="disconnect")

    def _opponent_mark(self, mark: str) -> Optional[str]:
        return "o" if mark == "x" else ("x" if mark == "o" else None)
