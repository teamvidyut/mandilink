from __future__ import annotations

import base64
import binascii
import re

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlmodel import Session, col, select

from .. import mandi
from ..db import get_session
from ..lang import CROP_DISPLAY, CROPS, crop_name
from ..models import Deal, Listing, Photo, Review, User
from ..nexconn import MSG_NOTICE, nexconn
from ..security import current_user
from ..services import BOT_ID, deal_card, log_event, new_id, now, open_deal, post_deal_card, receipt, trust

router = APIRouter(prefix="/api", tags=["market"])


class ListingIn(BaseModel):
    crop: str
    variety: str = Field(default="", max_length=40)
    quantity_kg: float = Field(gt=0, le=1_000_000)
    price_per_kg: float = Field(gt=0, le=100_000)
    district: str = Field(default="", max_length=40)
    grade: str = Field(default="A", pattern=r"^(A|B|C)$")
    description: str = Field(default="", max_length=400)
    photo_url: str = Field(default="", max_length=500, pattern=r"^(/api/photos/[A-Za-z0-9_]+|https://\S+)?$")


async def listing_out(session: Session, li: Listing) -> dict:
    seller = session.get(User, li.seller_id)
    info = await mandi.get_price(li.crop)
    return {
        "id": li.id,
        "crop": li.crop,
        "cropNames": {lg: crop_name(li.crop, lg) for lg in ("en", "hi", "bn")},
        "variety": li.variety,
        "quantityKg": li.quantity_kg,
        "pricePerKg": li.price_per_kg,
        "district": li.district,
        "grade": li.grade,
        "description": li.description,
        "photoUrl": li.photo_url,
        "status": li.status,
        "createdAt": int(li.created_at.timestamp() * 1000),
        "seller": {"id": seller.id, "name": seller.name, "district": seller.district, "language": seller.language,
                   "trust": trust(session, seller.id)}
        if seller else None,
        "mandi": info.to_dict() if info else None,
        "fairness": mandi.fairness(li.price_per_kg, info) if info else None,
    }


@router.get("/crops")
def crops():
    return [{"key": k, "names": v} for k, v in CROP_DISPLAY.items()]


@router.get("/prices")
async def all_prices():
    """Market ticker: today's band for every crop (live Agmarknet or labelled estimate)."""
    out = []
    for key in CROP_DISPLAY:
        info = await mandi.get_price(key)
        if info:
            out.append({**info.to_dict(), "names": CROP_DISPLAY[key]})
    return out


@router.get("/prices/{crop}")
async def price(crop: str):
    info = await mandi.get_price(crop)
    if not info:
        raise HTTPException(404, "Unknown crop")
    return info.to_dict()


@router.get("/listings")
async def listings(
    crop: str | None = None,
    mine: bool = False,
    search: str = Query(default="", alias="q", max_length=60),
    sort: str = Query(default="new", pattern=r"^(new|price_asc|price_desc|qty|fair)$"),
    limit: int = Query(default=40, le=100),
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    q = select(Listing)
    if mine:
        q = q.where(Listing.seller_id == user.id)
    else:
        q = q.where(Listing.status == "active")
    if crop:
        q = q.where(Listing.crop == crop)
    order = {
        "price_asc": col(Listing.price_per_kg).asc(),
        "price_desc": col(Listing.price_per_kg).desc(),
        "qty": col(Listing.quantity_kg).desc(),
    }.get(sort, col(Listing.created_at).desc())
    rows = list(session.exec(q.order_by(order).limit(200 if search else limit)).all())
    if search:
        rows = [li for li in rows if _matches(session, li, search)][:limit]
    out = [await listing_out(session, li) for li in rows]
    if sort == "fair":
        rank = {"low": 0, "fair": 1, "high": 2}
        out.sort(key=lambda r: rank.get(r["fairness"], 3))
    return out


def _matches(session: Session, li: Listing, q: str) -> bool:
    """Search across crop names in all languages + aliases, variety, district, seller."""
    needle = q.strip().lower()
    seller = session.get(User, li.seller_id)
    hay = [li.variety, li.district, li.description, seller.name if seller else ""]
    hay += list(CROP_DISPLAY.get(li.crop, {}).values())
    hay += [n for names in CROPS.get(li.crop, {}).values() for n in names]
    return any(needle in (h or "").lower() for h in hay)


@router.post("/listings")
async def create_listing(body: ListingIn, user: User = Depends(current_user), session: Session = Depends(get_session)):
    if user.role != "farmer":
        raise HTTPException(403, "Only farmer accounts can list produce")
    if body.crop not in CROP_DISPLAY:
        raise HTTPException(422, "Choose a crop from the list")
    li = Listing(seller_id=user.id, district=body.district or user.district,
                 **body.model_dump(exclude={"district"}))
    session.add(li)
    session.commit()
    session.refresh(li)
    log_event(session, user.id, "listing_created")
    return await listing_out(session, li)


@router.patch("/listings/{listing_id}")
async def update_listing(listing_id: int, status: str = Query(pattern=r"^(active|paused|sold)$"),
                         user: User = Depends(current_user), session: Session = Depends(get_session)):
    li = session.get(Listing, listing_id)
    if not li or li.seller_id != user.id:
        raise HTTPException(404, "Listing not found")
    li.status = status
    session.add(li)
    session.commit()
    return await listing_out(session, li)


@router.post("/listings/{listing_id}/enquire")
async def enquire(listing_id: int, user: User = Depends(current_user), session: Session = Depends(get_session)):
    li = session.get(Listing, listing_id)
    if not li or li.status != "active":
        raise HTTPException(404, "This listing is no longer available")
    if li.seller_id == user.id:
        raise HTTPException(400, "This is your own listing")
    info = await mandi.get_price(li.crop)
    deal = await open_deal(session, user, li, info.to_dict() if info else None)
    return {"dealId": deal.id}


# ------------------------------------------------------------------ deals
class ProposalIn(BaseModel):
    quantity_kg: float = Field(gt=0)
    price_per_kg: float = Field(gt=0)


def _deal_for(session: Session, deal_id: str, user: User) -> tuple[Deal, Listing]:
    deal = session.get(Deal, deal_id)
    if not deal or user.id not in (deal.buyer_id, deal.seller_id):
        raise HTTPException(404, "Deal not found")
    listing = session.get(Listing, deal.listing_id)
    assert listing is not None
    return deal, listing


@router.get("/deals/{deal_id}")
def get_deal(deal_id: str, user: User = Depends(current_user), session: Session = Depends(get_session)):
    deal, listing = _deal_for(session, deal_id, user)
    return deal_card(deal, listing)


@router.post("/deals/{deal_id}/propose")
async def propose(deal_id: str, body: ProposalIn, user: User = Depends(current_user),
                  session: Session = Depends(get_session)):
    deal, listing = _deal_for(session, deal_id, user)
    if deal.status == "agreed":
        raise HTTPException(409, "This deal is already agreed")
    if body.quantity_kg > listing.quantity_kg:
        raise HTTPException(422, f"Only {listing.quantity_kg:g} kg available")
    deal.proposed_qty_kg = body.quantity_kg
    deal.proposed_price_per_kg = body.price_per_kg
    deal.proposed_by = user.id
    deal.status = "proposed"
    deal.buyer_accepted = user.id == deal.buyer_id
    deal.seller_accepted = user.id == deal.seller_id
    deal.updated_at = now()
    session.add(deal)
    session.commit()
    await post_deal_card(deal, listing)
    log_event(session, user.id, "deal_proposed", deal.id)
    return deal_card(deal, listing)


@router.post("/deals/{deal_id}/accept")
async def accept(deal_id: str, user: User = Depends(current_user), session: Session = Depends(get_session)):
    deal, listing = _deal_for(session, deal_id, user)
    if deal.status != "proposed":
        raise HTTPException(409, "There is no open offer to accept")
    if user.id == deal.buyer_id:
        deal.buyer_accepted = True
    else:
        deal.seller_accepted = True
    if deal.buyer_accepted and deal.seller_accepted:
        deal.status = "agreed"
        deal.agreed_at = now()
        listing.quantity_kg = max(0.0, listing.quantity_kg - (deal.proposed_qty_kg or 0))
        if listing.quantity_kg == 0:
            listing.status = "sold"
        session.add(listing)
        log_event(session, deal.buyer_id, "deal_agreed", deal.id)
    deal.updated_at = now()
    session.add(deal)
    session.commit()
    await post_deal_card(deal, listing)
    return deal_card(deal, listing)


@router.post("/deals/{deal_id}/decline")
async def decline(deal_id: str, user: User = Depends(current_user), session: Session = Depends(get_session)):
    deal, listing = _deal_for(session, deal_id, user)
    if deal.status != "proposed":
        raise HTTPException(409, "There is no open offer")
    deal.status = "negotiating"
    deal.buyer_accepted = deal.seller_accepted = False
    deal.updated_at = now()
    session.add(deal)
    session.commit()
    await post_deal_card(deal, listing)
    return deal_card(deal, listing)


@router.get("/deals/{deal_id}/receipt")
def deal_receipt(deal_id: str, user: User = Depends(current_user), session: Session = Depends(get_session)):
    deal, listing = _deal_for(session, deal_id, user)
    if deal.status not in ("agreed", "completed"):
        raise HTTPException(409, "A receipt is available once both sides agree")
    return receipt(session, deal, listing)


@router.post("/deals/{deal_id}/delivered")
async def delivered(deal_id: str, user: User = Depends(current_user), session: Session = Depends(get_session)):
    """Buyer confirms the goods arrived: closes the deal lifecycle."""
    deal, listing = _deal_for(session, deal_id, user)
    if user.id != deal.buyer_id:
        raise HTTPException(403, "Only the buyer can confirm delivery")
    if deal.status != "agreed":
        raise HTTPException(409, "Only an agreed deal can be marked delivered")
    deal.status = "completed"
    deal.updated_at = now()
    session.add(deal)
    session.commit()
    await nexconn.send_group(BOT_ID, deal.id, MSG_NOTICE, {"kind": "delivered", "buyer": user.name},
                             push_content="Delivery confirmed")
    await post_deal_card(deal, listing)
    log_event(session, user.id, "deal_completed", deal.id)
    return deal_card(deal, listing)


class ReviewIn(BaseModel):
    stars: int = Field(ge=1, le=5)
    comment: str = Field(default="", max_length=300)


@router.post("/deals/{deal_id}/review")
def review(deal_id: str, body: ReviewIn, user: User = Depends(current_user), session: Session = Depends(get_session)):
    deal, _ = _deal_for(session, deal_id, user)
    if deal.status not in ("agreed", "completed"):
        raise HTTPException(409, "You can rate after the deal is agreed")
    other = deal.seller_id if user.id == deal.buyer_id else deal.buyer_id
    row = session.get(Review, (deal.id, user.id))
    if row:
        row.stars, row.comment = body.stars, body.comment.strip()
    else:
        row = Review(deal_id=deal.id, from_user=user.id, to_user=other, stars=body.stars, comment=body.comment.strip())
    session.add(row)
    session.commit()
    log_event(session, user.id, "review", deal.id)
    return {"ok": True, "trust": trust(session, other)}


@router.get("/deals/{deal_id}/review")
def my_review(deal_id: str, user: User = Depends(current_user), session: Session = Depends(get_session)):
    deal, _ = _deal_for(session, deal_id, user)
    row = session.get(Review, (deal.id, user.id))
    return {"stars": row.stars, "comment": row.comment} if row else None


@router.get("/users/{user_id}/trust")
def user_trust(user_id: str, _: User = Depends(current_user), session: Session = Depends(get_session)):
    if not session.get(User, user_id):
        raise HTTPException(404, "User not found")
    return trust(session, user_id)


# ------------------------------------------------------------------ photos
_DATA_URL = re.compile(r"^data:(image/(?:jpeg|png|webp));base64,(.+)$", re.S)
MAX_PHOTO_BYTES = 600_000


class PhotoIn(BaseModel):
    data_url: str = Field(max_length=900_000)


@router.post("/photos")
def upload_photo(body: PhotoIn, user: User = Depends(current_user), session: Session = Depends(get_session)):
    m = _DATA_URL.match(body.data_url)
    if not m:
        raise HTTPException(422, "Upload a JPEG, PNG or WebP image")
    try:
        data = base64.b64decode(m.group(2), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(422, "Image data is corrupted") from exc
    if len(data) > MAX_PHOTO_BYTES:
        raise HTTPException(413, "Photo is too large")
    photo = Photo(id=new_id("ph"), owner_id=user.id, mime=m.group(1), data=data)
    session.add(photo)
    session.commit()
    return {"url": f"/api/photos/{photo.id}"}


@router.get("/photos/{photo_id}")
def get_photo(photo_id: str, session: Session = Depends(get_session)):
    photo = session.get(Photo, photo_id)
    if not photo:
        raise HTTPException(404, "Photo not found")
    return Response(photo.data, media_type=photo.mime, headers={"Cache-Control": "public, max-age=31536000, immutable"})
