"""DEMO MODE endpoints (active only when no Nexconn credentials are configured)."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from sqlmodel import Session

from ..db import engine, get_session
from ..devhub import DIRECT, GROUP, hub
from ..models import User
from ..nexconn import nexconn
from ..security import current_user, decode_session_token

router = APIRouter(prefix="/api/dev", tags=["demo-mode"])


def _ensure_demo() -> None:
    if not nexconn.demo_mode:
        raise HTTPException(404, "Demo transport disabled: Nexconn is configured")


@router.get("/history")
def history(channel_type: int, channel_id: str, limit: int = Query(default=50, le=200),
            user: User = Depends(current_user), _s: Session = Depends(get_session)):
    _ensure_demo()
    if channel_type == GROUP and user.id not in hub.members(channel_id):
        raise HTTPException(403, "Not a member")
    return hub.history(user.id, channel_type, channel_id, limit)


@router.websocket("/ws")
async def ws(websocket: WebSocket, token: str):
    if not nexconn.demo_mode:
        await websocket.close(code=4404)
        return
    try:
        user_id = decode_session_token(token)
    except HTTPException:
        await websocket.close(code=4401)
        return
    with Session(engine) as s:
        if s.get(User, user_id) is None:
            await websocket.close(code=4401)
            return
    await websocket.accept()
    await hub.attach(user_id, websocket)
    try:
        while True:
            data = json.loads(await websocket.receive_text())
            op = data.get("op")
            ctype = int(data.get("channelType", DIRECT))
            cid = str(data.get("channelId", ""))
            if ctype == GROUP and user_id not in hub.members(cid):
                await websocket.send_text(json.dumps({"op": "error", "reqId": data.get("reqId"), "code": 403}))
                continue
            if op == "send":
                msg = await hub.publish(ctype, cid, user_id, data.get("messageType", "RC:TxtMsg"), data.get("content", {}))
                await websocket.send_text(json.dumps({"op": "ack", "reqId": data.get("reqId"), "message": msg},
                                                     ensure_ascii=False))
            elif op == "typing":
                await hub.typing(ctype, cid, user_id)
            elif op == "ping":
                await websocket.send_text('{"op":"pong"}')
    except (WebSocketDisconnect, RuntimeError, json.JSONDecodeError):
        pass
    finally:
        hub.detach(user_id, websocket)
