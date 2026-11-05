"""Mandi (wholesale market) price lookup.

Live data: data.gov.in Agmarknet "Variety-wise Daily Market Prices" API
(prices in ₹/quintal). Without an API key, or if the API is down, we fall back
to built-in reference ranges, which are clearly labelled as estimates in the UI.
"""
from __future__ import annotations

import logging
import time
from dataclasses import asdict, dataclass

import httpx

from .config import get_settings
from .lang import crop_name

log = logging.getLogger("mandilink.mandi")

# Indicative reference ranges (₹ per quintal). Used ONLY as a labelled fallback.
REFERENCE: dict[str, tuple[int, int, int]] = {
    "potato": (1100, 1600, 1350),
    "onion": (1800, 2800, 2300),
    "tomato": (1200, 2400, 1700),
    "rice": (2800, 3600, 3200),
    "wheat": (2300, 2700, 2450),
    "jute": (5000, 5800, 5400),
    "mustard": (5200, 6000, 5650),
    "cauliflower": (1000, 2000, 1500),
    "brinjal": (1200, 2200, 1700),
    "banana": (1500, 2500, 2000),
    "mango": (3000, 6000, 4500),
    "green chilli": (2500, 4500, 3500),
}

_COMMODITY = {
    "potato": "Potato",
    "onion": "Onion",
    "tomato": "Tomato",
    "rice": "Rice",
    "wheat": "Wheat",
    "jute": "Jute",
    "mustard": "Mustard",
    "cauliflower": "Cauliflower",
    "brinjal": "Brinjal",
    "banana": "Banana",
    "mango": "Mango",
    "green chilli": "Green Chilli",
}


@dataclass
class PriceInfo:
    crop: str
    min_per_kg: float
    max_per_kg: float
    modal_per_kg: float
    market: str
    date: str
    source: str  # "agmarknet" | "reference"
    live: bool

    def to_dict(self) -> dict:
        return asdict(self)

    def describe(self, lang: str) -> str:
        name = crop_name(self.crop, lang)
        rng = f"₹{self.min_per_kg:g}–₹{self.max_per_kg:g}/kg"
        modal = f"₹{self.modal_per_kg:g}/kg"
        if lang == "bn":
            src = "আজকের মান্ডি দর" if self.live else "আনুমানিক রেফারেন্স দর"
            return f"{name}: {src} {rng}, গড় {modal} ({self.market})"
        if lang == "hi":
            src = "आज का मंडी भाव" if self.live else "अनुमानित संदर्भ भाव"
            return f"{name}: {src} {rng}, औसत {modal} ({self.market})"
        src = "today's mandi rate" if self.live else "reference estimate"
        return f"{name}: {src} {rng}, typical {modal} ({self.market})"


_cache: dict[tuple[str, str], tuple[float, PriceInfo]] = {}
_TTL = 6 * 3600


def _q_to_kg(v: float) -> float:
    return round(v / 100.0, 1)


async def get_price(crop: str, state: str = "West Bengal") -> PriceInfo | None:
    crop = crop.lower()
    if crop not in REFERENCE:
        return None
    key = (crop, state)
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < _TTL:
        return hit[1]

    info = await _fetch_live(crop, state)
    if info is None:
        lo, hi, modal = REFERENCE[crop]
        info = PriceInfo(crop, _q_to_kg(lo), _q_to_kg(hi), _q_to_kg(modal), "Eastern India avg.", "", "reference", False)
    _cache[key] = (time.time(), info)
    return info


async def _fetch_live(crop: str, state: str) -> PriceInfo | None:
    s = get_settings()
    if not s.datagov_api_key:
        return None
    params = {
        "api-key": s.datagov_api_key,
        "format": "json",
        "limit": "50",
        "filters[commodity]": _COMMODITY[crop],
        "filters[state.keyword]": state,
    }
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(f"https://api.data.gov.in/resource/{s.datagov_resource_id}", params=params)
            r.raise_for_status()
            records = r.json().get("records", [])
    except Exception as exc:  # noqa: BLE001
        log.warning("Agmarknet fetch failed: %s", exc)
        return None
    rows = []
    for rec in records:
        try:
            rows.append(
                (
                    float(rec.get("min_price") or rec.get("Min_Price")),
                    float(rec.get("max_price") or rec.get("Max_Price")),
                    float(rec.get("modal_price") or rec.get("Modal_Price")),
                    rec.get("market") or rec.get("Market") or "",
                    rec.get("arrival_date") or rec.get("Arrival_Date") or "",
                )
            )
        except (TypeError, ValueError):
            continue
    if not rows:
        return None
    modal_sorted = sorted(r[2] for r in rows)
    median = modal_sorted[len(modal_sorted) // 2]
    return PriceInfo(
        crop=crop,
        min_per_kg=_q_to_kg(min(r[0] for r in rows)),
        max_per_kg=_q_to_kg(max(r[1] for r in rows)),
        modal_per_kg=_q_to_kg(median),
        market=f"{len(rows)} {state} mandis",
        date=rows[0][4],
        source="agmarknet",
        live=True,
    )


def fairness(price_per_kg: float, info: PriceInfo) -> str:
    """Return 'low' | 'fair' | 'high' for a listing price against the mandi band."""
    if price_per_kg < info.modal_per_kg * 0.85:
        return "low"
    if price_per_kg > info.modal_per_kg * 1.2:
        return "high"
    return "fair"
