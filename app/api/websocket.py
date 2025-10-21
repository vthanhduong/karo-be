"""Websocket endpoint wiring for the caro backend."""

from __future__ import annotations

import json
from typing import Any, Dict

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from app.services import manager


def register_websocket_routes(app: FastAPI) -> None:
    """Attach websocket handlers to the provided FastAPI application."""

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:  # noqa: WPS430
        client = await manager.connect(websocket)
        try:
            async for text_message in websocket.iter_text():
                try:
                    payload: Dict[str, Any] = json.loads(text_message)
                except json.JSONDecodeError:
                    await manager.send_error(client, "general", "Dữ liệu không hợp lệ")
                    continue
                msg_type = payload.get("type")

                if client.state == "awaiting_name" and msg_type != "join_request":
                    await manager.send_error(client, "join", "Bạn cần đăng ký tên trước")
                    continue

                if msg_type == "join_request":
                    error = await manager.register_name(client, str(payload.get("name", "")))
                    if error:
                        await client.send({"type": "join_error", "reason": error})
                        await websocket.close()
                        break
                    continue

                if msg_type == "invite_sent":
                    await manager.handle_invite(client, payload)
                elif msg_type == "invite_response":
                    await manager.handle_invite_response(client, payload)
                elif msg_type == "game_move":
                    await manager.handle_move(client, payload)
                elif msg_type == "chat_message":
                    await manager.handle_chat(client, payload)
                elif msg_type == "lobby_chat":
                    await manager.handle_lobby_chat(client, payload)
                elif msg_type == "surrender":
                    await manager.handle_surrender(client, payload)
                elif msg_type == "lobby_filter":
                    query = str(payload.get("query", "")).strip().lower()
                    async with manager.lock:
                        users = [manager._user_summary(c) for c in manager.clients.values() if c.name]
                    if query:
                        users = [u for u in users if query in u["name"].lower()]
                    await client.send({"type": "lobby_snapshot", "users": users})
                else:
                    await manager.send_error(client, "general", "Loại sự kiện không được hỗ trợ")
        except WebSocketDisconnect:
            pass
        finally:
            await manager.disconnect(client)
