"""Thin, provider-agnostic LLM wrapper (Gemini or any OpenAI-compatible API).

Every caller must handle `None` (no provider / provider failure) with a
deterministic fallback, so the live demo never breaks because of an AI outage.
"""
from __future__ import annotations

import base64
import json
import logging
import re
from typing import Any

import httpx

from .config import get_settings

log = logging.getLogger("mandilink.llm")


def enabled() -> bool:
    s = get_settings()
    if s.llm_provider == "gemini":
        return bool(s.gemini_api_key)
    if s.llm_provider == "openai":
        return bool(s.openai_api_key)
    return False


async def complete(system: str, user: str, *, json_mode: bool = False, temperature: float = 0.3) -> str | None:
    s = get_settings()
    if not enabled():
        return None
    try:
        async with httpx.AsyncClient(timeout=s.llm_timeout_seconds) as client:
            if s.llm_provider == "gemini":
                body: dict[str, Any] = {
                    "systemInstruction": {"parts": [{"text": system}]},
                    "contents": [{"role": "user", "parts": [{"text": user}]}],
                    "generationConfig": {"temperature": temperature},
                }
                if json_mode:
                    body["generationConfig"]["responseMimeType"] = "application/json"
                return await _gemini(client, body, s.llm_timeout_seconds)

            body = {
                "model": s.openai_model,
                "temperature": temperature,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            }
            if json_mode:
                body["response_format"] = {"type": "json_object"}
            r = await client.post(
                s.openai_base_url.rstrip("/") + "/chat/completions",
                headers={"Authorization": f"Bearer {s.openai_api_key}"},
                json=body,
            )
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as exc:  # noqa: BLE001 - any provider failure falls back
        log.warning("LLM call failed: %s %s", type(exc).__name__, exc)
        return None


async def _gemini(client: httpx.AsyncClient, body: dict[str, Any], budget: float) -> str | None:
    """POST generateContent, trying the main then the fallback model on timeout,
    network error, 404 (retired), 429 (rate limit) or 5xx (outage)."""
    s = get_settings()
    models = [m for m in dict.fromkeys([s.gemini_model, s.gemini_fallback_model]) if m]
    # Split the time budget so a slow first model still leaves time for the fallback.
    per_model = budget / len(models)
    for i, model in enumerate(models):
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        has_next = i + 1 < len(models)
        try:
            # Header auth works for both classic (AIza…) and new (AQ.…) API keys.
            r = await client.post(url, headers={"x-goog-api-key": s.gemini_api_key}, json=body, timeout=per_model)
        except httpx.TransportError as exc:  # timeout or network error
            if has_next:
                log.warning("Gemini %s failed (%s), trying %s", model, type(exc).__name__, models[i + 1])
                continue
            raise
        if r.status_code in (404, 429) or r.status_code >= 500:
            if has_next:
                log.warning("Gemini %s returned %s, trying %s", model, r.status_code, models[i + 1])
                continue
        r.raise_for_status()
        parts = r.json()["candidates"][0]["content"]["parts"]
        return "".join(p.get("text", "") for p in parts).strip()
    return None


TRANSCRIBE_PROMPT = (
    "Transcribe this short voice message from an Indian farm marketplace chat. It is in Bengali, Hindi "
    "or English (possibly mixed). Write exactly what is said, in the script of the spoken language "
    "(Bengali script for Bengali, Devanagari for Hindi). Keep numbers as digits and units (kg, quintal, ₹). "
    "Output ONLY the transcript. If there is no speech, output nothing."
)


async def transcribe(audio: bytes, mime: str, lang_hint: str | None = None) -> str | None:
    """Speech-to-text for voice notes. Gemini only (audio input); None when unavailable."""
    s = get_settings()
    if s.llm_provider != "gemini" or not s.gemini_api_key:
        return None
    hint = {"bn": "Bengali", "hi": "Hindi", "en": "English"}.get(lang_hint or "", "")
    body: dict[str, Any] = {
        "contents": [{"role": "user", "parts": [
            {"text": TRANSCRIBE_PROMPT + (f" The speaker usually writes in {hint}." if hint else "")},
            {"inline_data": {"mime_type": mime, "data": base64.b64encode(audio).decode()}},
        ]}],
        "generationConfig": {"temperature": 0},
    }
    try:
        async with httpx.AsyncClient() as client:
            out = await _gemini(client, body, max(s.llm_timeout_seconds, 30.0))
        return (out or "").strip().strip('"') or None
    except Exception as exc:  # noqa: BLE001 - a failed transcript must not lose the voice note
        log.warning("Transcription failed: %s %s", type(exc).__name__, exc)
        return None


async def complete_json(system: str, user: str) -> dict[str, Any] | None:
    raw = await complete(system, user, json_mode=True, temperature=0.1)
    if not raw:
        return None
    match = re.search(r"\{.*\}", raw, re.S)
    try:
        return json.loads(match.group(0) if match else raw)
    except (json.JSONDecodeError, AttributeError):
        log.warning("LLM returned non-JSON: %s", raw[:200])
        return None
