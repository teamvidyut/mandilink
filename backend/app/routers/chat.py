"""Chat glue: conversation list, profiles for the SDK, translation, and the
post-send hook that drives the AI assistant and escalation.

The browser sends every message through the Nexconn Chat SDK first; it then
calls /api/chat/after-send so the server can (a) count it for traction
analytics and (b) let Mandi Mitra respond through the Nexconn server API.
"""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlmodel import Session, col, or_, select

from .. import llm, mandi
from ..agent import run_agent, variants
from ..db import get_session
from ..lang import SMART, crop_name, localise, nfc, rx
from ..models import Deal, Listing, Room, RoomMember, Ticket, User
from ..nexconn import DIRECT, GROUP, MSG_VOICE, TEXT, nexconn, text_content
from ..security import current_user
from ..services import BOT_ID, escalate, log_event
from ..translate import translate

router = APIRouter(prefix="/api", tags=["chat"])

_MENTION = rx(r"@(mandi|mitra|ai)\b|^/ai\b|মান্ডি মিত্র|मंडी मित्र", re.I)
_AUTO_ESCALATE = rx(r"fraud|cheat|scam|not paid|প্রতারণা|ঠকিয়েছে|টাকা দেয়নি|धोखा|ठगी|पैसे नहीं", re.I)


@router.get("/conversations")
def conversations(user: User = Depends(current_user), session: Session = Depends(get_session)):
    out: list[dict] = []
    if user.role != "agent":
        out.append({"channelType": DIRECT, "channelId": BOT_ID, "kind": "assistant", "title": "Mandi Mitra",
                    "subtitle": "AI assistant · prices, buyers, help", "emoji": "🤖"})
    deals = session.exec(
        select(Deal).where(or_(Deal.buyer_id == user.id, Deal.seller_id == user.id)).order_by(col(Deal.updated_at).desc())
    ).all()
    for d in deals:
        li = session.get(Listing, d.listing_id)
        other = session.get(User, d.seller_id if d.buyer_id == user.id else d.buyer_id)
        out.append({
            "channelType": GROUP, "channelId": d.id, "kind": "deal",
            "title": other.name if other else "Deal",
            "subtitle": crop_name(li.crop, user.language) if li else "",
            "emoji": "🤝", "status": d.status, "updatedAt": int(d.updated_at.timestamp() * 1000),
        })
    if user.role == "agent":
        tickets = session.exec(select(Ticket).where(Ticket.agent_id == user.id, Ticket.status != "resolved")).all()
        for t in tickets:
            owner = session.get(User, t.user_id)
            out.append({"channelType": GROUP, "channelId": t.channel_id, "kind": "support",
                        "title": f"#{t.id} · {owner.name if owner else ''}", "subtitle": t.reason[:60], "emoji": "🎧"})
    else:
        tickets = session.exec(
            select(Ticket).where(Ticket.user_id == user.id, Ticket.deal_id == None, Ticket.status != "resolved")  # noqa: E711
        ).all()
        for t in tickets:
            out.append({"channelType": GROUP, "channelId": t.channel_id, "kind": "support",
                        "title": "MandiLink Support", "subtitle": f"Ticket #{t.id} · {t.status}", "emoji": "🎧"})
        rooms = session.exec(select(Room).join(RoomMember, RoomMember.room_id == Room.id).where(RoomMember.user_id == user.id)).all()
        for r in rooms:
            out.append({"channelType": GROUP, "channelId": r.id, "kind": "room", "title": r.name,
                        "subtitle": r.topic, "emoji": r.emoji})
    return out


@router.get("/profiles")
def profiles(ids: str = Query(..., max_length=4000), _: User = Depends(current_user),
             session: Session = Depends(get_session)):
    out = {}
    for uid in {i for i in ids.split(",") if i}:
        u = session.get(User, uid)
        if u:
            out[uid] = {"id": u.id, "name": u.name, "role": u.role, "language": u.language,
                        "district": u.district, "avatarUrl": u.avatar_url}
    return out


class TranslateIn(BaseModel):
    text: str = Field(max_length=2000)
    target: str | None = Field(default=None, pattern=r"^(en|hi|bn)$")
    source_hint: str | None = Field(default=None, pattern=r"^(en|hi|bn)$")


@router.post("/translate")
async def translate_endpoint(body: TranslateIn, user: User = Depends(current_user), session: Session = Depends(get_session)):
    tr = await translate(session, body.text, body.target or user.language, body.source_hint)
    if tr.translated and tr.engine != "cache":
        log_event(session, user.id, "translation")
    return {"text": tr.text, "source": tr.source, "target": tr.target, "translated": tr.translated, "engine": tr.engine}


class AfterSendIn(BaseModel):
    channel_type: int
    channel_id: str
    text: str = Field(default="", max_length=4000)
    message_type: str = TEXT


def _check_member(session: Session, user: User, channel_type: int, channel_id: str) -> str:
    """Return the conversation kind if `user` belongs to it."""
    if channel_type == DIRECT:
        if channel_id == BOT_ID:
            return "assistant"
        return "direct"
    deal = session.get(Deal, channel_id)
    if deal:
        if user.id in (deal.buyer_id, deal.seller_id):
            return "deal"
        t = session.exec(select(Ticket).where(Ticket.channel_id == channel_id, Ticket.agent_id == user.id)).first()
        if t:
            return "support"
        raise HTTPException(403, "Not a member of this deal")
    if session.get(RoomMember, (channel_id, user.id)):
        return "room"
    t = session.exec(select(Ticket).where(Ticket.channel_id == channel_id)).first()
    if t and user.id in (t.user_id, t.agent_id):
        return "support"
    raise HTTPException(403, "Not a member of this conversation")


async def _assistant_reply(session: Session, user: User, text: str, channel_type: int, channel_id: str,
                           deal_id: str | None) -> dict:
    state = await run_agent(session, user, text, deal_id=deal_id)
    reply = state.get("reply", "")
    extra: dict = {"lang": state.get("lang", "en"), "ai": True, "intent": state.get("intent")}
    if channel_type == GROUP and not llm.enabled():
        extra["variants"] = variants(state)
    if channel_type == DIRECT:
        await nexconn.send_direct(BOT_ID, [user.id], TEXT, text_content(reply, extra), push_content=reply[:80])
    else:
        await nexconn.send_group(BOT_ID, channel_id, TEXT, text_content(reply, extra), push_content=reply[:80])
    log_event(session, user.id, "ai_reply", channel_id)
    ticket_id = None
    if state.get("escalate"):
        t = await escalate(session, user, state.get("escalate_reason") or text, state.get("priority", "normal"),
                           deal_id=deal_id, summary=text)
        ticket_id = t.id
    return {"replied": True, "intent": state.get("intent"), "escalated": bool(state.get("escalate")), "ticketId": ticket_id}


@router.post("/chat/after-send")
async def after_send(body: AfterSendIn, user: User = Depends(current_user), session: Session = Depends(get_session)):
    kind = _check_member(session, user, body.channel_type, body.channel_id)
    log_event(session, user.id, "message_sent", body.channel_id)
    text = nfc(body.text).strip()
    # Voice messages carry their AI transcript as `text`, so they get the same AI and support handling.
    if not text or body.message_type not in (TEXT, MSG_VOICE):
        return {"replied": False}
    if kind == "assistant":
        return await _assistant_reply(session, user, text, DIRECT, BOT_ID, None)
    if kind == "deal":
        if _AUTO_ESCALATE.search(text):
            t = await escalate(session, user, text, "high", deal_id=body.channel_id, summary=text)
            return {"replied": False, "escalated": True, "ticketId": t.id}
        if _MENTION.search(text):
            clean = _MENTION.sub("", text).strip() or text
            return await _assistant_reply(session, user, clean, GROUP, body.channel_id, body.channel_id)
    if kind == "room" and _MENTION.search(text):
        clean = _MENTION.sub("", text).strip() or text
        return await _assistant_reply(session, user, clean, GROUP, body.channel_id, None)
    return {"replied": False}


class AskIn(BaseModel):
    channel_id: str
    question: str = Field(default="", max_length=500)


@router.post("/chat/ask-ai")
async def ask_ai(body: AskIn, user: User = Depends(current_user), session: Session = Depends(get_session)):
    """'Ask Mandi Mitra' chip inside a deal room: fair-price advice for this deal."""
    kind = _check_member(session, user, GROUP, body.channel_id)
    if kind != "deal":
        raise HTTPException(400, "Ask AI is available inside deal rooms")
    q = body.question or "What is a fair price for this deal?"
    return await _assistant_reply(session, user, q, GROUP, body.channel_id, body.channel_id)


@router.get("/chat/suggestions")
async def suggestions(channel_id: str, user: User = Depends(current_user), session: Session = Depends(get_session)):
    """Context-aware quick replies in the viewer's language. In deal rooms they
    carry the AI fair price, so a buyer can counter in one tap. Every line is in
    the offline phrasebook, so the other side always reads it translated."""
    lang = user.language
    if channel_id == BOT_ID:
        return {"replies": []}
    kind = _check_member(session, user, GROUP, channel_id)
    if kind == "support" and user.role == "agent":
        return {"replies": [localise(p, lang) for p in SMART["agent"]]}
    if kind != "deal":
        return {"replies": []}
    deal = session.get(Deal, channel_id)
    listing = session.get(Listing, deal.listing_id) if deal else None
    if not deal or not listing:
        return {"replies": []}
    side = "buyer" if user.id == deal.buyer_id else "seller"
    status = deal.status if deal.status in ("negotiating", "proposed", "agreed", "completed") else "negotiating"
    info = await mandi.get_price(listing.crop)
    ask = listing.price_per_kg
    fair = round(max(info.min_per_kg, (ask + info.modal_per_kg) / 2), 1) if info else round(ask * 0.95, 1)
    fair = min(fair, ask)
    floor = round(max(fair, ask * 0.97), 1)
    out = [localise(p, lang, fair=fair, floor=floor) for p in SMART[f"{side}_{status}"]]
    return {"replies": out, "fairPrice": fair}


class HelpIn(BaseModel):
    channel_id: str | None = None
    reason: str = Field(default="Needs help from a person", max_length=300)


@router.post("/support/request")
async def request_help(body: HelpIn, user: User = Depends(current_user), session: Session = Depends(get_session)):
    deal_id = None
    if body.channel_id:
        if _check_member(session, user, GROUP, body.channel_id) == "deal":
            deal_id = body.channel_id
    t = await escalate(session, user, body.reason, "normal", deal_id=deal_id)
    return {"ticketId": t.id, "channelId": t.channel_id, "status": t.status}
