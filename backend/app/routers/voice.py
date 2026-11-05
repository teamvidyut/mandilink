"""Voice messages.

The browser records a short clip (16 kHz mono WAV), uploads it here, and gets
back a URL plus an AI transcript. It then sends a Nexconn custom message
(ML:Voice) with {url, durationMs, transcript, lang} through the Chat SDK. Each
reader sees the transcript translated into their own language, and the
transcript drives Mandi Mitra and support escalation exactly like typed text.
"""
from __future__ import annotations

import base64
import binascii
import re

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlmodel import Session

from .. import llm
from ..db import get_session
from ..lang import detect_language, nfc
from ..models import User, VoiceNote
from ..security import current_user
from ..services import log_event, new_id

router = APIRouter(prefix="/api/voice", tags=["voice"])

_DATA_URL = re.compile(r"^data:(audio/(?:wav|x-wav|webm|ogg|mpeg|mp4|aac))(?:;[^,]*)?;base64,(.+)$", re.S)
MAX_VOICE_BYTES = 2_500_000  # ~75 s of 16 kHz mono PCM
MAX_VOICE_MS = 61_000


class VoiceIn(BaseModel):
    data_url: str = Field(max_length=3_500_000)
    duration_ms: int = Field(ge=300, le=MAX_VOICE_MS)
    lang: str | None = Field(default=None, pattern=r"^(en|hi|bn)$")


@router.post("")
async def upload_voice(body: VoiceIn, user: User = Depends(current_user), session: Session = Depends(get_session)):
    m = _DATA_URL.match(body.data_url)
    if not m:
        raise HTTPException(422, "Upload a WAV, WebM, OGG, MP3 or AAC recording")
    try:
        data = base64.b64decode(m.group(2), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(422, "Recording is corrupted") from exc
    if len(data) > MAX_VOICE_BYTES:
        raise HTTPException(413, "Voice message is too long")
    mime = "audio/wav" if m.group(1) == "audio/x-wav" else m.group(1)
    transcript = nfc(await llm.transcribe(data, mime, body.lang or user.language) or "")
    lang = detect_language(transcript) if transcript else (body.lang or user.language)
    if transcript and lang == "en" and (body.lang or user.language) != "en" and not transcript.isascii():
        lang = body.lang or user.language
    note = VoiceNote(id=new_id("vn"), owner_id=user.id, mime=mime, data=data, duration_ms=body.duration_ms,
                     transcript=transcript[:2000], lang=lang)
    session.add(note)
    session.commit()
    log_event(session, user.id, "voice_note")
    return {"url": f"/api/voice/{note.id}", "transcript": note.transcript, "lang": note.lang,
            "durationMs": note.duration_ms}


@router.get("/{voice_id}")
def get_voice(voice_id: str, session: Session = Depends(get_session)):
    note = session.get(VoiceNote, voice_id)
    if not note:
        raise HTTPException(404, "Voice message not found")
    return Response(note.data, media_type=note.mime, headers={"Cache-Control": "public, max-age=31536000, immutable"})
