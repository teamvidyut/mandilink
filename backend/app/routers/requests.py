"""Buyer requests ("Wanted" board).

A buyer posts what they need; Mandi Mitra pings matching farmers through
Nexconn direct messages in each farmer's own language. A farmer answers with
one of their listings, which opens a normal deal room (Nexconn group channel).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session, col, select

from .. import mandi
from ..db import get_session
from ..lang import CROP_DISPLAY, crop_name
from ..models import BuyRequest, Listing, User
from ..security import current_user
from ..services import log_event, notify_request, open_deal, same_world, trust, trust_many, world_filter

router = APIRouter(prefix="/api/requests", tags=["requests"])


class RequestIn(BaseModel):
    crop: str
    quantity_kg: float = Field(gt=0, le=1_000_000)
    target_price_per_kg: float | None = Field(default=None, gt=0, le=100_000)
    district: str = Field(default="", max_length=40)
    note: str = Field(default="", max_length=300)


class RespondIn(BaseModel):
    listing_id: int


async def request_out(session: Session, r: BuyRequest, viewer: User, trusts: dict[str, dict] | None = None) -> dict:
    buyer = session.get(User, r.buyer_id)
    info = await mandi.get_price(r.crop)
    mine = []
    if viewer.role == "farmer":
        mine = [
            {"id": li.id, "quantityKg": li.quantity_kg, "pricePerKg": li.price_per_kg, "variety": li.variety}
            for li in session.exec(
                select(Listing).where(Listing.seller_id == viewer.id, Listing.crop == r.crop, Listing.status == "active")
            ).all()
        ]
    return {
        "id": r.id,
        "crop": r.crop,
        "cropNames": {lg: crop_name(r.crop, lg) for lg in ("en", "hi", "bn")},
        "quantityKg": r.quantity_kg,
        "targetPricePerKg": r.target_price_per_kg,
        "district": r.district,
        "note": r.note,
        "status": r.status,
        "notified": r.notified,
        "createdAt": int(r.created_at.timestamp() * 1000),
        "buyer": {"id": buyer.id, "name": buyer.name, "district": buyer.district, "trust": (trusts or {}).get(buyer.id) or trust(session, buyer.id)}
        if buyer else None,
        "mandi": info.to_dict() if info else None,
        "myMatchingListings": mine,
    }


@router.get("")
async def list_requests(mine: bool = False, user: User = Depends(current_user), session: Session = Depends(get_session)):
    q = select(BuyRequest)
    q = q.where(BuyRequest.buyer_id == user.id) if mine else q.where(
        BuyRequest.status == "open", world_filter(BuyRequest.buyer_id, user.id))
    rows = session.exec(q.order_by(col(BuyRequest.created_at).desc()).limit(50)).all()
    buyers = list({r.buyer_id for r in rows})
    if buyers:
        session.exec(select(User).where(col(User.id).in_(buyers))).all()
    trusts = trust_many(session, buyers)
    return [await request_out(session, r, user, trusts) for r in rows]


@router.post("")
async def create_request(body: RequestIn, user: User = Depends(current_user), session: Session = Depends(get_session)):
    if user.role != "buyer":
        raise HTTPException(403, "Only buyer accounts can post requirements")
    if body.crop not in CROP_DISPLAY:
        raise HTTPException(422, "Choose a crop from the list")
    req = BuyRequest(buyer_id=user.id, crop=body.crop, quantity_kg=body.quantity_kg,
                     target_price_per_kg=body.target_price_per_kg, district=body.district.strip() or user.district,
                     note=body.note.strip())
    session.add(req)
    session.commit()
    session.refresh(req)
    req.notified = await notify_request(session, req, user)
    session.add(req)
    session.commit()
    log_event(session, user.id, "request_posted")
    return await request_out(session, req, user)


@router.post("/{request_id}/respond")
async def respond(request_id: int, body: RespondIn, user: User = Depends(current_user),
                  session: Session = Depends(get_session)):
    """Farmer offers one of their listings: opens a deal room with the buyer."""
    req = session.get(BuyRequest, request_id)
    if not req or req.status != "open" or not same_world(user.id, req.buyer_id):
        raise HTTPException(404, "This request is closed")
    li = session.get(Listing, body.listing_id)
    if not li or li.seller_id != user.id or li.status != "active":
        raise HTTPException(404, "Listing not found")
    if li.crop != req.crop:
        raise HTTPException(422, "That listing is for a different crop")
    buyer = session.get(User, req.buyer_id)
    if not buyer:
        raise HTTPException(404, "Buyer not found")
    info = await mandi.get_price(li.crop)
    deal = await open_deal(session, buyer, li, info.to_dict() if info else None)
    log_event(session, user.id, "request_answered", deal.id)
    return {"dealId": deal.id}


@router.post("/{request_id}/close")
async def close(request_id: int, user: User = Depends(current_user), session: Session = Depends(get_session)):
    req = session.get(BuyRequest, request_id)
    if not req or req.buyer_id != user.id:
        raise HTTPException(404, "Request not found")
    req.status = "closed"
    session.add(req)
    session.commit()
    return await request_out(session, req, user)
