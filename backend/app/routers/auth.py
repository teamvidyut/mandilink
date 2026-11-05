from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlmodel import Session, select

from ..config import get_settings
from ..db import get_session
from ..models import User
from ..nexconn import NexconnError, nexconn
from ..security import create_session_token, current_user, hash_pin, verify_pin
from ..services import is_demo_id, join_default_rooms, log_event, new_id, now

router = APIRouter(prefix="/api/auth", tags=["auth"])


class RegisterIn(BaseModel):
    name: str = Field(min_length=2, max_length=40)
    phone: str
    pin: str = Field(pattern=r"^\d{4,6}$")
    role: str = Field(pattern=r"^(farmer|buyer)$")
    language: str = Field(default="en", pattern=r"^(en|hi|bn)$")
    district: str = Field(default="", max_length=40)

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str) -> str:
        digits = re.sub(r"\D", "", v)[-10:]
        if len(digits) != 10:
            raise ValueError("Enter a 10-digit mobile number")
        return digits

    @field_validator("name", "district")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()


class LoginIn(BaseModel):
    phone: str
    pin: str


class ProfileIn(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=40)
    language: str | None = Field(default=None, pattern=r"^(en|hi|bn)$")
    district: str | None = Field(default=None, max_length=40)


def user_out(u: User) -> dict:
    return {"id": u.id, "name": u.name, "role": u.role, "language": u.language, "district": u.district,
            "phone": u.phone[-4:].rjust(10, "•"), "avatarUrl": u.avatar_url, "demo": is_demo_id(u.id)}


async def _session_payload(session: Session, user: User) -> dict:
    s = get_settings()
    try:
        token = await nexconn.issue_token(user.id, user.name, user.avatar_url)
    except NexconnError as exc:
        raise HTTPException(502, f"Chat service unavailable ({exc.code}). Please retry.") from exc
    user.last_seen_at = now()
    session.add(user)
    session.commit()
    log_event(session, user.id, "login")
    return {
        "session": create_session_token(user.id),
        "user": user_out(user),
        "nexconn": {"appKey": s.nexconn_app_key, "token": token, "demoMode": nexconn.demo_mode},
    }


@router.post("/register")
async def register(body: RegisterIn, session: Session = Depends(get_session)):
    if session.exec(select(User).where(User.phone == body.phone)).first():
        raise HTTPException(409, "This number is already registered. Please sign in.")
    user = User(id=new_id("u"), name=body.name, phone=body.phone, pin_hash=hash_pin(body.pin),
                role=body.role, language=body.language, district=body.district)
    session.add(user)
    session.commit()
    payload = await _session_payload(session, user)
    await join_default_rooms(session, user)
    return payload


@router.post("/login")
async def login(body: LoginIn, session: Session = Depends(get_session)):
    phone = re.sub(r"\D", "", body.phone)[-10:]
    user = session.exec(select(User).where(User.phone == phone)).first()
    if not user or not verify_pin(body.pin, user.pin_hash):
        raise HTTPException(401, "Wrong mobile number or PIN")
    payload = await _session_payload(session, user)
    if user.role in ("farmer", "buyer"):
        await join_default_rooms(session, user)
    return payload


@router.post("/refresh")
async def refresh(user: User = Depends(current_user), session: Session = Depends(get_session)):
    """Fresh Nexconn token for an existing app session (page reload)."""
    return await _session_payload(session, user)


@router.patch("/me")
async def update_me(body: ProfileIn, user: User = Depends(current_user), session: Session = Depends(get_session)):
    if body.name:
        user.name = body.name.strip()
    if body.language:
        user.language = body.language
    if body.district is not None:
        user.district = body.district.strip()
    session.add(user)
    session.commit()
    if body.name:
        try:
            await nexconn.update_user(user.id, user.name, user.avatar_url)
        except NexconnError:
            pass
    return user_out(user)
