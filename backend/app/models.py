"""Database models (SQLModel). Chat messages themselves live in Nexconn; we store
only marketplace data, deal state, support tickets and analytics events."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(SQLModel, table=True):
    id: str = Field(primary_key=True)  # also the Nexconn userId
    name: str
    phone: str = Field(index=True, unique=True)
    pin_hash: str
    role: str = Field(default="farmer")  # farmer | buyer | agent
    language: str = Field(default="en")  # en | hi | bn
    district: str = Field(default="")
    avatar_url: str = Field(default="")
    created_at: datetime = Field(default_factory=utcnow)
    last_seen_at: datetime = Field(default_factory=utcnow)


class Listing(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    seller_id: str = Field(index=True, foreign_key="user.id")
    crop: str
    variety: str = ""
    quantity_kg: float
    price_per_kg: float
    district: str = ""
    grade: str = "A"
    description: str = ""
    photo_url: str = ""
    status: str = Field(default="active")  # active | sold | paused
    created_at: datetime = Field(default_factory=utcnow)


class Deal(SQLModel, table=True):
    """A negotiation between one buyer and one seller over one listing.
    Each deal is a Nexconn group channel: buyer + seller + Mandi Assistant bot
    (+ a support agent when escalated)."""

    id: str = Field(primary_key=True)  # also the Nexconn group channelId
    listing_id: int = Field(foreign_key="listing.id", index=True)
    buyer_id: str = Field(foreign_key="user.id", index=True)
    seller_id: str = Field(foreign_key="user.id", index=True)
    status: str = Field(default="negotiating")  # negotiating | proposed | agreed | completed | cancelled
    proposed_qty_kg: Optional[float] = None
    proposed_price_per_kg: Optional[float] = None
    proposed_by: Optional[str] = None
    buyer_accepted: bool = False
    seller_accepted: bool = False
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    agreed_at: Optional[datetime] = None


class BuyRequest(SQLModel, table=True):
    """A buyer's posted requirement ("Wanted: 2 t potato in Hooghly"). Matching
    farmers get a Nexconn direct message from Mandi Mitra in their language."""

    id: Optional[int] = Field(default=None, primary_key=True)
    buyer_id: str = Field(foreign_key="user.id", index=True)
    crop: str = Field(index=True)
    quantity_kg: float
    target_price_per_kg: Optional[float] = None
    district: str = ""
    note: str = ""
    status: str = Field(default="open")  # open | closed
    notified: int = 0
    created_at: datetime = Field(default_factory=utcnow)


class Review(SQLModel, table=True):
    """Post-deal rating; builds each trader's trust score."""

    deal_id: str = Field(primary_key=True, foreign_key="deal.id")
    from_user: str = Field(primary_key=True, foreign_key="user.id")
    to_user: str = Field(foreign_key="user.id", index=True)
    stars: int
    comment: str = ""
    created_at: datetime = Field(default_factory=utcnow)


class Photo(SQLModel, table=True):
    """Listing photos, resized in the browser (~50-150 KB) and kept in the DB so
    they survive redeploys on hosts with ephemeral disks."""

    id: str = Field(primary_key=True)
    owner_id: str = Field(foreign_key="user.id", index=True)
    mime: str
    data: bytes
    created_at: datetime = Field(default_factory=utcnow)


class VoiceNote(SQLModel, table=True):
    """Voice message audio (16 kHz mono WAV from the browser) plus its AI transcript.
    The chat message itself is a Nexconn custom message (ML:Voice) pointing here."""

    id: str = Field(primary_key=True)
    owner_id: str = Field(foreign_key="user.id", index=True)
    mime: str
    data: bytes
    duration_ms: int = 0
    transcript: str = ""
    lang: str = ""
    created_at: datetime = Field(default_factory=utcnow)


class Room(SQLModel, table=True):
    """Public mandi community rooms (Nexconn group channels)."""

    id: str = Field(primary_key=True)
    name: str
    topic: str = ""
    emoji: str = "🌾"


class RoomMember(SQLModel, table=True):
    room_id: str = Field(primary_key=True, foreign_key="room.id")
    user_id: str = Field(primary_key=True, foreign_key="user.id")


class Ticket(SQLModel, table=True):
    """Human-support escalation. The ticket's channel is either the deal group
    (agent is added to it) or a dedicated support group channel."""

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: str = Field(foreign_key="user.id", index=True)
    channel_id: str  # Nexconn group channel the agent joins
    deal_id: Optional[str] = None
    reason: str = ""
    summary: str = ""
    priority: str = Field(default="normal")  # normal | high
    status: str = Field(default="open")  # open | assigned | resolved
    agent_id: Optional[str] = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class Feedback(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: str = Field(foreign_key="user.id")
    rating: int
    comment: str = ""
    created_at: datetime = Field(default_factory=utcnow)


class Event(SQLModel, table=True):
    """Lightweight analytics for the traction dashboard."""

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: str = Field(index=True)
    kind: str = Field(index=True)  # message_sent | translation | ai_reply | deal_agreed | login | ticket
    channel_id: str = ""
    created_at: datetime = Field(default_factory=utcnow, index=True)


class TranslationCache(SQLModel, table=True):
    key: str = Field(primary_key=True)  # sha1(target|text)
    target: str
    source_text: str
    translated: str
    detected: str = ""
    created_at: datetime = Field(default_factory=utcnow)


class DevGroupMember(SQLModel, table=True):
    """Group membership used ONLY in local demo mode (Nexconn tracks it for real)."""

    channel_id: str = Field(primary_key=True)
    user_id: str = Field(primary_key=True)


class DevMessage(SQLModel, table=True):
    """Message log used ONLY in local demo mode (no Nexconn credentials)."""

    id: str = Field(primary_key=True)
    channel_type: int
    channel_id: str = Field(index=True)
    sender_id: str
    message_type: str
    content_json: str
    sent_time: int = Field(index=True)
