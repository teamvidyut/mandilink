"""Per-viewer message translation with a DB cache.

Each receiver's client asks for the text in *their* language, so a Bengali
farmer, a Hindi trader and an English buyer can share one deal room.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from . import llm
from .lang import LANG_NAMES, detect_language, nfc, phrasebook
from .models import TranslationCache

SYSTEM = (
    "You translate short chat messages between farmers and buyers in an Indian agricultural "
    "marketplace. Translate faithfully into the target language, keep numbers, units (kg, quintal, "
    "₹) and names unchanged, keep the tone natural and polite, and use everyday words a farmer "
    "would use. Output ONLY the translation, no quotes or notes."
)


@dataclass
class Translation:
    text: str
    source: str
    target: str
    translated: bool
    engine: str  # same | cache | llm | phrasebook | none


def _key(text: str, target: str) -> str:
    return hashlib.sha1(f"{target}|{text}".encode()).hexdigest()


async def translate(session: Session, text: str, target: str, source_hint: str | None = None) -> Translation:
    text = nfc(text).strip()
    target = target if target in LANG_NAMES else "en"
    source = detect_language(text)
    if source == "en" and source_hint in LANG_NAMES and source_hint != "en":
        # Romanised Bengali/Hindi typed in Latin script ("dam koto?")
        source = source_hint
    if not text or source == target:
        return Translation(text, source, target, False, "same")

    cached = session.get(TranslationCache, _key(text, target))
    if cached:
        return Translation(cached.translated, cached.detected or source, target, True, "cache")

    out = await llm.complete(
        SYSTEM,
        f"Source language: {LANG_NAMES.get(source, 'auto')}\nTarget language: {LANG_NAMES[target]}\n\nMessage:\n{text}",
        temperature=0.2,
    )
    engine = "llm"
    if not out:
        out = phrasebook(text, source, target)
        engine = "phrasebook"
    if not out:
        return Translation(text, source, target, False, "none")

    # merge = insert or update: two viewers translating the same message at the
    # same moment must not collide on the cache key.
    session.merge(TranslationCache(key=_key(text, target), target=target, source_text=text, translated=out, detected=source))
    try:
        session.commit()
    except IntegrityError:  # the other request won the race; its row is just as good
        session.rollback()
    return Translation(out, source, target, True, engine)
