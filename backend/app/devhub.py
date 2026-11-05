"""DEMO MODE transport.

Mimics the parts of Nexconn the app uses (direct + group channels, history,
typing) over a WebSocket so MandiLink can be developed and demoed locally
before Nexconn credentials are configured. With credentials set, the browser
talks to Nexconn directly through @nexconn/chat and this module is unused.
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections import defaultdict
from typing import Any

from fastapi import WebSocket
from sqlmodel import Session, select

from .db import engine
from .models import DevGroupMember, DevMessage

DIRECT, GROUP = 1, 3


def _to_client_content(message_type: str, content: dict[str, Any]) -> dict[str, Any]:
    if message_type == "RC:TxtMsg" and "content" in content and "text" not in content:
        out = {"text": content["content"]}
        if "extra" in content:
            out["extra"] = content["extra"]
        return out
    return content


def _conv_key(channel_type: int, a: str, b: str) -> str:
    if channel_type == DIRECT:
        x, y = sorted([a, b])
        return f"d:{x}|{y}"
    return f"g:{b}"


class DevHub:
    def __init__(self) -> None:
        self.sockets: dict[str, set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()
        self._last_ms = 0

    # ---------------------------------------------------------- membership
    def add_members(self, channel_id: str, user_ids: list[str]) -> None:
        with Session(engine) as s:
            for uid in set(user_ids):
                if s.get(DevGroupMember, (channel_id, uid)) is None:
                    s.add(DevGroupMember(channel_id=channel_id, user_id=uid))
            s.commit()

    def members(self, channel_id: str) -> list[str]:
        with Session(engine) as s:
            rows = s.exec(select(DevGroupMember).where(DevGroupMember.channel_id == channel_id)).all()
            return [r.user_id for r in rows]

    # ---------------------------------------------------------- sockets
    async def attach(self, user_id: str, ws: WebSocket) -> None:
        self.sockets[user_id].add(ws)

    def detach(self, user_id: str, ws: WebSocket) -> None:
        self.sockets[user_id].discard(ws)

    async def _emit(self, user_id: str, payload: dict[str, Any]) -> None:
        dead = []
        for ws in list(self.sockets.get(user_id, ())):
            try:
                await ws.send_text(json.dumps(payload, ensure_ascii=False))
            except Exception:  # noqa: BLE001 - socket already gone
                dead.append(ws)
        for ws in dead:
            self.sockets[user_id].discard(ws)

    # ---------------------------------------------------------- messaging
    def _store(self, channel_type: int, key: str, sender: str, mtype: str, content: dict[str, Any]) -> DevMessage:
        # Strictly increasing timestamps keep history in send order, even for
        # messages posted in the same millisecond (listing card + notice).
        self._last_ms = max(int(time.time() * 1000), self._last_ms + 1)
        msg = DevMessage(
            id=uuid.uuid4().hex[:20],
            channel_type=channel_type,
            channel_id=key,
            sender_id=sender,
            message_type=mtype,
            content_json=json.dumps(content, ensure_ascii=False),
            sent_time=self._last_ms,
        )
        with Session(engine) as s:
            s.add(msg)
            s.commit()
            s.refresh(msg)
        return msg

    @staticmethod
    def _wire(msg: DevMessage, channel_id_for_viewer: str) -> dict[str, Any]:
        return {
            "messageId": msg.id,
            "channelType": msg.channel_type,
            "channelId": channel_id_for_viewer,
            "senderUserId": msg.sender_id,
            "messageType": msg.message_type,
            "content": _to_client_content(msg.message_type, json.loads(msg.content_json)),
            "sentTime": msg.sent_time,
        }

    async def publish(
        self,
        channel_type: int,
        target_id: str,
        sender: str,
        message_type: str,
        content: dict[str, Any],
        echo_to_sender: bool = False,
    ) -> dict[str, Any]:
        """target_id: recipient userId for DIRECT, channelId for GROUP."""
        key = _conv_key(channel_type, sender, target_id)
        msg = self._store(channel_type, key, sender, message_type, content)
        if channel_type == DIRECT:
            await self._emit(target_id, {"op": "message", "message": self._wire(msg, sender)})
            own = self._wire(msg, target_id)
            if echo_to_sender:
                await self._emit(sender, {"op": "message", "message": own})
            return own
        wire = self._wire(msg, target_id)
        for uid in self.members(target_id):
            if uid != sender or echo_to_sender:
                await self._emit(uid, {"op": "message", "message": wire})
        return wire

    async def typing(self, channel_type: int, target_id: str, sender: str) -> None:
        if channel_type == DIRECT:
            await self._emit(target_id, {"op": "typing", "channelType": DIRECT, "channelId": sender, "userId": sender})
            return
        for uid in self.members(target_id):
            if uid != sender:
                await self._emit(uid, {"op": "typing", "channelType": GROUP, "channelId": target_id, "userId": sender})

    def history(self, viewer: str, channel_type: int, channel_id: str, limit: int = 50) -> list[dict[str, Any]]:
        key = _conv_key(channel_type, viewer, channel_id)
        with Session(engine) as s:
            rows = s.exec(
                select(DevMessage)
                .where(DevMessage.channel_id == key)
                .order_by(DevMessage.sent_time.desc())  # type: ignore[union-attr]
                .limit(limit)
            ).all()
        # From the viewer's perspective a direct channel is identified by the other user.
        return [self._wire(m, channel_id) for m in reversed(rows)]


hub = DevHub()
