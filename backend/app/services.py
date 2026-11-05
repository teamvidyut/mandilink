"""Domain services shared by the routers: bootstrap, deals, support escalation."""
from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timezone

from sqlmodel import Session, func, select

from .config import get_settings
from .lang import LANG_NAMES, crop_name
from .models import BuyRequest, Deal, Event, Listing, Review, Room, RoomMember, Ticket, User
from .nexconn import GROUP, MSG_DEAL, MSG_LISTING, MSG_NOTICE, TEXT, nexconn, text_content
from .security import hash_pin

log = logging.getLogger("mandilink.services")

BOT_ID = "mandi-mitra"
BOT_NAME = "Mandi Mitra (AI)"
BOT_AVATAR = ""

ROOMS = [
    ("room-potato-hooghly", "Potato traders · Hooghly", "Daily potato bhav, cold-storage stock, transport", "🥔"),
    ("room-paddy-bengal", "Paddy & rice · Bengal", "Aman/Boro paddy, rice mills, MSP updates", "🌾"),
    ("room-veg-kolkata", "Vegetables · Kolkata markets", "Koley Market, Sealdah, Howrah wholesale", "🥬"),
]


def channel_id(base: str) -> str:
    """Nexconn channel id for this deployment (see Settings.channel_namespace)."""
    ns = get_settings().channel_namespace.strip()
    return f"{base}-{ns}" if ns else base


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(5)}"


def log_event(session: Session, user_id: str, kind: str, channel_id: str = "") -> None:
    session.add(Event(user_id=user_id, kind=kind, channel_id=channel_id))
    session.commit()


def now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------- bootstrap
async def bootstrap(session: Session) -> None:
    """Idempotent: bot user, support agent, community rooms."""
    s = get_settings()
    if session.get(User, BOT_ID) is None:
        session.add(User(id=BOT_ID, name=BOT_NAME, phone="bot", pin_hash="!", role="bot", language="en"))
        session.commit()
    try:
        await nexconn.issue_token(BOT_ID, BOT_NAME, BOT_AVATAR)  # registers the bot as a Nexconn user
    except Exception as exc:  # noqa: BLE001
        log.error("Could not register bot with Nexconn: %s", exc)

    agent = session.exec(select(User).where(User.phone == "9000000000")).first()
    if agent is None:
        agent = User(id="agent-riya", name="Riya · MandiLink Support", phone="9000000000",
                     pin_hash=hash_pin(s.support_agent_pin), role="agent", language="en")
        session.add(agent)
        session.commit()

    for base_id, name, topic, emoji in ROOMS:
        rid = channel_id(base_id)
        if session.get(Room, rid) is None:
            try:
                await nexconn.create_group(rid, name, BOT_ID, [])
            except Exception as exc:  # noqa: BLE001 - may already exist on Nexconn
                log.info("Room %s create: %s", rid, exc)
            session.add(Room(id=rid, name=name, topic=topic, emoji=emoji))
            session.commit()


async def join_default_rooms(session: Session, user: User) -> None:
    for room in session.exec(select(Room)).all():
        if session.get(RoomMember, (room.id, user.id)):
            continue
        try:
            await nexconn.join_group(room.id, [user.id])
        except Exception as exc:  # noqa: BLE001
            log.warning("join room %s failed: %s", room.id, exc)
            continue
        session.add(RoomMember(room_id=room.id, user_id=user.id))
        session.commit()


# ---------------------------------------------------------------- deals
def listing_card(listing: Listing, seller: User, price: dict | None) -> dict:
    return {
        "listingId": listing.id,
        "crop": listing.crop,
        "cropNames": {lg: crop_name(listing.crop, lg) for lg in ("en", "hi", "bn")},
        "variety": listing.variety,
        "quantityKg": listing.quantity_kg,
        "pricePerKg": listing.price_per_kg,
        "district": listing.district,
        "grade": listing.grade,
        "photoUrl": listing.photo_url,
        "sellerName": seller.name,
        "mandi": price,
    }


async def open_deal(session: Session, buyer: User, listing: Listing, price: dict | None) -> Deal:
    deal_id = channel_id(f"deal_{listing.id}_{buyer.id}")
    existing = session.get(Deal, deal_id)
    if existing:
        return existing
    seller = session.get(User, listing.seller_id)
    assert seller is not None
    name = f"{crop_name(listing.crop, 'en')} · {seller.name} ↔ {buyer.name}"
    await nexconn.create_group(deal_id, name[:60], BOT_ID, [buyer.id, seller.id])
    deal = Deal(id=deal_id, listing_id=listing.id, buyer_id=buyer.id, seller_id=seller.id)  # type: ignore[arg-type]
    session.add(deal)
    session.commit()
    await nexconn.send_group(BOT_ID, deal_id, MSG_LISTING, listing_card(listing, seller, price),
                             push_content=f"New enquiry for your {listing.crop}")
    await nexconn.send_group(
        BOT_ID, deal_id, MSG_NOTICE,
        {"kind": "deal_opened", "buyer": buyer.name, "seller": seller.name},
        push_content="Deal room opened",
    )
    log_event(session, buyer.id, "deal_opened", deal_id)
    return deal


def deal_card(deal: Deal, listing: Listing) -> dict:
    return {
        "dealId": deal.id,
        "status": deal.status,
        "crop": listing.crop,
        "cropNames": {lg: crop_name(listing.crop, lg) for lg in ("en", "hi", "bn")},
        "quantityKg": deal.proposed_qty_kg,
        "pricePerKg": deal.proposed_price_per_kg,
        "totalRs": round((deal.proposed_qty_kg or 0) * (deal.proposed_price_per_kg or 0)),
        "proposedBy": deal.proposed_by,
        "buyerAccepted": deal.buyer_accepted,
        "sellerAccepted": deal.seller_accepted,
        "buyerId": deal.buyer_id,
        "sellerId": deal.seller_id,
        "updatedAt": int(deal.updated_at.timestamp() * 1000) if deal.updated_at else 0,
        "agreedAt": int(deal.agreed_at.timestamp() * 1000) if deal.agreed_at else None,
    }


# ---------------------------------------------------------------- trust
def trust(session: Session, user_id: str) -> dict:
    """Trust score shown next to every trader: completed deals + star rating."""
    agg = session.exec(select(func.avg(Review.stars), func.count()).select_from(Review).where(Review.to_user == user_id)).one()
    done = session.exec(
        select(func.count()).select_from(Deal).where(
            (Deal.seller_id == user_id) | (Deal.buyer_id == user_id),
            Deal.status.in_(["agreed", "completed"]),  # type: ignore[attr-defined]
        )
    ).one()
    u = session.get(User, user_id)
    rating = round(float(agg[0]), 1) if agg[0] else None
    deals = int(done)
    reviews = int(agg[1])
    badge = "top" if rating and rating >= 4.5 and reviews >= 3 else "trusted" if deals >= 1 else "new"
    return {
        "rating": rating, "reviews": reviews, "deals": deals, "badge": badge,
        "since": int(u.created_at.timestamp() * 1000) if u else None,
    }


def receipt(session: Session, deal: Deal, listing: Listing) -> dict:
    """A shareable deal slip (no phone numbers)."""
    buyer, seller = session.get(User, deal.buyer_id), session.get(User, deal.seller_id)
    when = deal.agreed_at or deal.updated_at
    return {
        **deal_card(deal, listing),
        "receiptNo": f"ML-{when:%y%m%d}-{int(hashlib.sha1(deal.id.encode()).hexdigest(), 16) % 100000:05d}" if when else deal.id,
        "variety": listing.variety,
        "grade": listing.grade,
        "askPricePerKg": listing.price_per_kg,
        "buyer": {"name": buyer.name, "district": buyer.district} if buyer else None,
        "seller": {"name": seller.name, "district": seller.district} if seller else None,
        "pickupDistrict": listing.district,
    }


# ---------------------------------------------------------------- buy requests
REQUEST_PING = {
    "en": "📢 New buyer request: {buyer} wants {qty:g} kg {crop}{price}{where}. Open Market → Wanted to respond.",
    "hi": "📢 नई खरीद माँग: {buyer} को {qty:g} किलो {crop} चाहिए{price}{where}। जवाब देने के लिए मार्केट → माँग खोलें।",
    "bn": "📢 নতুন ক্রেতার চাহিদা: {buyer} {qty:g} কেজি {crop} চান{price}{where}। উত্তর দিতে মার্কেট → চাহিদা খুলুন।",
}


async def notify_request(session: Session, req: BuyRequest, buyer: User) -> int:
    """Ping matching farmers through Nexconn direct messages, each in their own
    language: first farmers already selling this crop, then nearby farmers."""
    sellers = {li.seller_id for li in session.exec(select(Listing).where(Listing.crop == req.crop)).all()}
    q = select(User).where(User.role == "farmer")
    farmers = [f for f in session.exec(q).all() if f.id in sellers or (req.district and f.district.lower() == req.district.lower())]
    if not farmers:
        farmers = list(session.exec(q.limit(50)).all())
    by_lang: dict[str, list[str]] = {}
    for f in farmers[:100]:
        by_lang.setdefault(f.language if f.language in LANG_NAMES else "en", []).append(f.id)
    for lg, ids in by_lang.items():
        price = f" @ ₹{req.target_price_per_kg:g}/kg" if req.target_price_per_kg else ""
        where = f" ({req.district})" if req.district else ""
        msg = REQUEST_PING[lg].format(buyer=buyer.name, qty=req.quantity_kg, crop=crop_name(req.crop, lg), price=price, where=where)
        try:
            await nexconn.send_direct(BOT_ID, ids, TEXT, text_content(msg, {"lang": lg, "requestId": req.id, "ai": True}),
                                      push_content=msg[:80])
        except Exception as exc:  # noqa: BLE001 - a failed ping must not fail the request
            log.warning("request ping failed: %s", exc)
    return sum(len(v) for v in by_lang.values())


# ---------------------------------------------------------------- support
async def escalate(session: Session, user: User, reason: str, priority: str = "normal",
                   deal_id: str | None = None, summary: str = "") -> Ticket:
    open_t = session.exec(
        select(Ticket).where(Ticket.user_id == user.id, Ticket.status != "resolved", Ticket.deal_id == deal_id)
    ).first()
    if open_t:
        return open_t
    if deal_id:
        channel_id = deal_id
    else:
        channel_id = new_id("support")
        await nexconn.create_group(channel_id, f"Support · {user.name}"[:60], BOT_ID, [user.id])
    ticket = Ticket(user_id=user.id, channel_id=channel_id, deal_id=deal_id, reason=reason[:300],
                    summary=summary[:500], priority=priority)
    session.add(ticket)
    session.commit()
    session.refresh(ticket)
    await nexconn.send_group(BOT_ID, channel_id, MSG_NOTICE,
                             {"kind": "ticket_opened", "ticketId": ticket.id, "priority": priority},
                             push_content="Connecting you to a support agent")
    # Real-time ping to every support agent through Nexconn direct messages.
    agents = session.exec(select(User).where(User.role == "agent")).all()
    if agents:
        await nexconn.send_direct(
            BOT_ID, [a.id for a in agents], TEXT,
            text_content(f"🆘 New {priority} ticket #{ticket.id} from {user.name}: {reason[:120]}",
                         {"ticketId": ticket.id}),
            push_content=f"New support ticket #{ticket.id}",
        )
    log_event(session, user.id, "ticket", channel_id)
    return ticket


async def claim_ticket(session: Session, ticket: Ticket, agent: User) -> Ticket:
    if ticket.agent_id is None:
        await nexconn.join_group(ticket.channel_id, [agent.id])
        ticket.agent_id = agent.id
        ticket.status = "assigned"
        ticket.updated_at = now()
        session.add(ticket)
        session.commit()
        await nexconn.send_group(BOT_ID, ticket.channel_id, MSG_NOTICE,
                                 {"kind": "agent_joined", "agent": agent.name, "ticketId": ticket.id},
                                 push_content=f"{agent.name} joined")
    return ticket


async def resolve_ticket(session: Session, ticket: Ticket, agent: User) -> Ticket:
    ticket.status = "resolved"
    ticket.updated_at = now()
    session.add(ticket)
    session.commit()
    await nexconn.send_group(BOT_ID, ticket.channel_id, MSG_NOTICE,
                             {"kind": "ticket_resolved", "agent": agent.name, "ticketId": ticket.id},
                             push_content="Support ticket resolved")
    log_event(session, agent.id, "ticket_resolved", ticket.channel_id)
    return ticket


async def post_deal_card(deal: Deal, listing: Listing) -> None:
    card = deal_card(deal, listing)
    await nexconn.send_group(BOT_ID, deal.id, MSG_DEAL, card,
                             push_content=f"Deal update: {card['quantityKg']:g} kg @ ₹{card['pricePerKg']:g}/kg")


__all__ = [
    "trust", "receipt", "notify_request",
    "BOT_ID", "GROUP", "bootstrap", "join_default_rooms", "open_deal", "escalate", "claim_ticket",
    "resolve_ticket", "deal_card", "post_deal_card", "log_event", "listing_card", "new_id",
]
