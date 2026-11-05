from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session, col, func, select

import re

from .. import llm, mandi
from ..db import get_session
from ..lang import LANG_NAMES, crop_name, nfc, rx
from ..models import BuyRequest, Deal, Event, Feedback, Listing, Review, Ticket, User
from ..security import current_user, require_agent
from ..services import claim_ticket, resolve_ticket, trust

router = APIRouter(prefix="/api", tags=["support"])


def _ticket_out(session: Session, t: Ticket) -> dict:
    owner = session.get(User, t.user_id)
    agent = session.get(User, t.agent_id) if t.agent_id else None
    ctx = None
    if t.deal_id:
        d = session.get(Deal, t.deal_id)
        li = session.get(Listing, d.listing_id) if d else None
        if d and li:
            ctx = {"crop": crop_name(li.crop, "en"), "status": d.status, "askPrice": li.price_per_kg,
                   "offerPrice": d.proposed_price_per_kg, "offerQty": d.proposed_qty_kg}
    return {
        "id": t.id, "channelId": t.channel_id, "dealId": t.deal_id, "reason": t.reason, "summary": t.summary,
        "priority": t.priority, "status": t.status,
        "user": {"id": owner.id, "name": owner.name, "role": owner.role, "language": owner.language,
                 "district": owner.district} if owner else None,
        "agent": {"id": agent.id, "name": agent.name} if agent else None,
        "deal": ctx,
        "createdAt": int(t.created_at.timestamp() * 1000),
        "updatedAt": int(t.updated_at.timestamp() * 1000),
    }


@router.get("/support/tickets")
def tickets(agent: User = Depends(require_agent), session: Session = Depends(get_session)):
    rows = session.exec(select(Ticket).order_by(col(Ticket.created_at).desc()).limit(100)).all()
    order = {"open": 0, "assigned": 1, "resolved": 2}
    rows = sorted(rows, key=lambda t: (order.get(t.status, 3), t.priority != "high", -t.created_at.timestamp()))
    return [_ticket_out(session, t) for t in rows]


@router.post("/support/tickets/{ticket_id}/claim")
async def claim(ticket_id: int, agent: User = Depends(require_agent), session: Session = Depends(get_session)):
    t = session.get(Ticket, ticket_id)
    if not t:
        raise HTTPException(404, "Ticket not found")
    if t.agent_id and t.agent_id != agent.id:
        raise HTTPException(409, "Already claimed by another agent")
    await claim_ticket(session, t, agent)
    return _ticket_out(session, t)


@router.post("/support/tickets/{ticket_id}/resolve")
async def resolve(ticket_id: int, agent: User = Depends(require_agent), session: Session = Depends(get_session)):
    t = session.get(Ticket, ticket_id)
    if not t or t.agent_id != agent.id:
        raise HTTPException(404, "Ticket not found")
    await resolve_ticket(session, t, agent)
    return _ticket_out(session, t)


_CATEGORIES = [
    ("payment", rx(r"pay|paid|money|upi|টাকা|পেমেন্ট|पैसे|भुगतान", re.I)),
    ("fraud", rx(r"fraud|cheat|scam|প্রতারণা|ঠকিয়েছে|धोखा|ठगी", re.I)),
    ("quality", rx(r"quality|rotten|bad|damage|weight|মান|পচা|খারাপ|गुणवत्ता|खराब|सड़", re.I)),
    ("delivery", rx(r"deliver|late|transport|truck|ডেলিভারি|দেরি|डिलीवरी|देर", re.I)),
    ("price", rx(r"price|rate|দাম|দর|भाव|कीमत", re.I)),
]
_PLAYBOOK = {
    "payment": "Confirm the agreed amount from the deal card, ask the buyer for the UPI/transaction reference, and set a payment deadline in the chat.",
    "fraud": "Treat as urgent: pause the seller's listings if needed, collect evidence (photos, receipts) and do not let either side pay outside the chat.",
    "quality": "Ask for photos of the goods and the weighing slip; propose a partial refund or re-grade against the agreed grade.",
    "delivery": "Agree a new delivery date and transport in the chat; Mandi Mitra can re-post the deal card with updated terms.",
    "price": "Show both sides the mandi band and the AI fair price; suggest meeting in the middle.",
    "other": "Greet the user in their language, ask what happened, and summarise the next step in one message.",
}


@router.get("/support/tickets/{ticket_id}/brief")
async def brief(ticket_id: int, agent: User = Depends(require_agent), session: Session = Depends(get_session)):
    """AI case brief for the agent: who, what, the deal facts, fair price and a
    suggested next step. Deterministic facts; an LLM (if set) only rewords."""
    t = session.get(Ticket, ticket_id)
    if not t:
        raise HTTPException(404, "Ticket not found")
    owner = session.get(User, t.user_id)
    text = nfc(f"{t.reason} {t.summary}")
    category = next((name for name, rx in _CATEGORIES if rx.search(text)), "other")
    facts: list[str] = []
    if owner:
        facts.append(f"{owner.name} · {owner.role} · writes in {LANG_NAMES.get(owner.language, owner.language)}"
                     + (f" · {owner.district}" if owner.district else ""))
    fair = None
    if t.deal_id and (d := session.get(Deal, t.deal_id)) and (li := session.get(Listing, d.listing_id)):
        facts.append(f"Deal: {crop_name(li.crop, 'en')}, asking ₹{li.price_per_kg:g}/kg, status {d.status}")
        if d.proposed_price_per_kg:
            facts.append(f"Last offer: {d.proposed_qty_kg or 0:g} kg @ ₹{d.proposed_price_per_kg:g}/kg "
                         f"= ₹{round((d.proposed_qty_kg or 0) * d.proposed_price_per_kg):,}")
        info = await mandi.get_price(li.crop)
        if info:
            fair = round(max(info.min_per_kg, (li.price_per_kg + info.modal_per_kg) / 2), 1)
            facts.append(f"Mandi band ₹{info.min_per_kg:g}–₹{info.max_per_kg:g}/kg ({'live' if info.live else 'estimate'}); "
                         f"fair ≈ ₹{fair:g}/kg")
        for uid in (d.buyer_id, d.seller_id):
            tr = trust(session, uid)
            u = session.get(User, uid)
            if u:
                facts.append(f"{u.name}: {tr['deals']} deals, rating {tr['rating'] or '—'}")
    action = _PLAYBOOK[category]
    headline = f"{category.title()} issue" + (" · urgent" if t.priority == "high" else "")
    if llm.enabled():
        polished = await llm.complete(
            "You brief a customer-support agent of an Indian farm marketplace. In at most 2 short sentences, "
            "summarise the user's problem and the best next step. Use only the facts given.",
            f"Complaint: {text}\nFacts: {facts}\nPlaybook: {action}",
            temperature=0.2,
        )
        if polished:
            action = polished
    return {"category": category, "headline": headline, "facts": facts, "suggestedAction": action,
            "userLanguage": owner.language if owner else "en", "fairPrice": fair}


class FeedbackIn(BaseModel):
    rating: int = Field(ge=1, le=5)
    comment: str = Field(default="", max_length=1000)


@router.post("/feedback")
def feedback(body: FeedbackIn, user: User = Depends(current_user), session: Session = Depends(get_session)):
    session.add(Feedback(user_id=user.id, rating=body.rating, comment=body.comment.strip()))
    session.commit()
    return {"ok": True}


@router.get("/metrics")
def metrics(session: Session = Depends(get_session)):
    """Public traction numbers (no personal data) for the judges' write-up."""
    now = datetime.now(timezone.utc)
    week = now - timedelta(days=7)
    # Demo accounts (ids "u_demo_*") never count as traction.
    real_user = ~col(User.id).startswith("u_demo")
    real_event = ~col(Event.user_id).startswith("u_demo")
    people = select(func.count()).select_from(User).where(col(User.role).in_(["farmer", "buyer"]), real_user)

    def count(kind: str, since: datetime | None = None) -> int:
        q = select(func.count()).select_from(Event).where(Event.kind == kind, real_event)
        if since:
            q = q.where(Event.created_at >= since)
        return int(session.exec(q).one())

    active_7d = session.exec(
        select(func.count(func.distinct(Event.user_id))).where(Event.created_at >= week, Event.kind == "message_sent", real_event)
    ).one()
    series = []
    for i in range(13, -1, -1):
        day = (now - timedelta(days=i)).date()
        start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
        end = start + timedelta(days=1)
        msgs = session.exec(select(func.count()).select_from(Event).where(
            Event.kind == "message_sent", Event.created_at >= start, Event.created_at < end, real_event)).one()
        users = session.exec(select(func.count(func.distinct(Event.user_id))).where(
            Event.kind == "message_sent", Event.created_at >= start, Event.created_at < end, real_event)).one()
        series.append({"date": day.isoformat(), "messages": int(msgs), "activeUsers": int(users)})
    ratings = session.exec(select(func.avg(Feedback.rating), func.count()).select_from(Feedback).where(
        ~col(Feedback.user_id).startswith("u_demo"))).one()
    closed = session.exec(select(Deal).where(col(Deal.status).in_(["agreed", "completed"]),
                                             ~col(Deal.buyer_id).startswith("u_demo"))).all()
    gmv = sum((d.proposed_qty_kg or 0) * (d.proposed_price_per_kg or 0) for d in closed)
    kg = sum(d.proposed_qty_kg or 0 for d in closed)
    langs = {lg: int(session.exec(select(func.count()).select_from(User).where(
        User.language == lg, col(User.role).in_(["farmer", "buyer"]), real_user)).one()) for lg in ("bn", "hi", "en")}
    trade_rating = session.exec(select(func.avg(Review.stars), func.count()).select_from(Review).where(
        ~col(Review.from_user).startswith("u_demo"))).one()
    return {
        "gmvRs": round(gmv),
        "kgTraded": round(kg),
        "dealsCompleted": count("deal_completed"),
        "requests": int(session.exec(select(func.count()).select_from(BuyRequest).where(
            ~col(BuyRequest.buyer_id).startswith("u_demo"))).one()),
        "languages": langs,
        "tradeRating": round(float(trade_rating[0]), 2) if trade_rating[0] else None,
        "tradeReviews": int(trade_rating[1]),
        "users": int(session.exec(people).one()),
        "farmers": int(session.exec(select(func.count()).select_from(User).where(User.role == "farmer", real_user)).one()),
        "buyers": int(session.exec(select(func.count()).select_from(User).where(User.role == "buyer", real_user)).one()),
        "activeUsers7d": int(active_7d),
        "messages": count("message_sent"),
        "translations": count("translation"),
        "aiReplies": count("ai_reply"),
        "voiceNotes": count("voice_note"),
        "dealsOpened": count("deal_opened"),
        "dealsAgreed": count("deal_agreed"),
        "tickets": count("ticket"),
        "ticketsResolved": count("ticket_resolved"),
        "listings": int(session.exec(select(func.count()).select_from(Listing).where(
            ~col(Listing.seller_id).startswith("u_demo"))).one()),
        "feedbackAvg": round(float(ratings[0]), 2) if ratings[0] else None,
        "feedbackCount": int(ratings[1]),
        "series": series,
    }


@router.get("/feedback/recent")
def recent_feedback(_: User = Depends(current_user), session: Session = Depends(get_session)):
    rows = session.exec(select(Feedback).order_by(col(Feedback.created_at).desc()).limit(20)).all()
    return [{"rating": f.rating, "comment": f.comment, "at": int(f.created_at.timestamp() * 1000)} for f in rows]
