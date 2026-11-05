import asyncio
import hashlib
import os
import sys
import tempfile
from pathlib import Path

DB = Path(tempfile.mkdtemp()) / "test.db"
os.environ["DATABASE_URL"] = f"sqlite:///{DB}"
os.environ["NEXCONN_APP_KEY"] = ""
os.environ["NEXCONN_APP_SECRET"] = ""
os.environ["LLM_PROVIDER"] = "none"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import seed  # noqa: E402
from app.main import app  # noqa: E402
from app.nexconn import sign  # noqa: E402


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        asyncio.run(seed.main())
        yield c


def login(client, phone, pin="1234"):
    r = client.post("/api/auth/login", json={"phone": phone, "pin": pin})
    assert r.status_code == 200, r.text
    data = r.json()
    return {"Authorization": f"Bearer {data['session']}"}, data


def test_signature_matches_official_sdk_algorithm():
    assert sign("secret", "123", "456") == hashlib.sha1(b"secret123456").hexdigest()


def test_health_demo_mode(client):
    assert client.get("/api/health").json()["demoMode"] is True


def test_register_and_duplicate(client):
    body = {"name": "Test Farmer", "phone": "98765 43210", "pin": "4321", "role": "farmer", "language": "bn",
            "district": "Purba Medinipur"}
    r = client.post("/api/auth/register", json=body)
    assert r.status_code == 200, r.text
    assert r.json()["nexconn"]["token"].startswith("demo-")
    assert client.post("/api/auth/register", json=body).status_code == 409
    assert client.post("/api/auth/login", json={"phone": "9876543210", "pin": "0000"}).status_code == 401


def test_listings_have_mandi_band(client):
    h, _ = login(client, "9000000002")
    rows = client.get("/api/listings", headers=h).json()
    assert len(rows) >= 5
    potato = next(r for r in rows if r["crop"] == "potato")
    assert potato["mandi"]["source"] == "reference" and potato["fairness"] in ("low", "fair", "high")


def test_buyer_cannot_list(client):
    h, _ = login(client, "9000000002")
    r = client.post("/api/listings", headers=h, json={"crop": "onion", "quantity_kg": 10, "price_per_kg": 20})
    assert r.status_code == 403


def test_full_deal_flow(client):
    hb, _ = login(client, "9000000002")
    hf, _ = login(client, "9000000001")
    potato = next(r for r in client.get("/api/listings", headers=hb).json() if r["crop"] == "potato")
    deal_id = client.post(f"/api/listings/{potato['id']}/enquire", headers=hb).json()["dealId"]
    hist = client.get("/api/dev/history", headers=hb, params={"channel_type": 3, "channel_id": deal_id}).json()
    assert [m["messageType"] for m in hist][:2] == ["ML:Listing", "ML:Notice"]

    convs = client.get("/api/conversations", headers=hf).json()
    assert any(c["channelId"] == deal_id for c in convs)

    card = client.post(f"/api/deals/{deal_id}/propose", headers=hb, json={"quantity_kg": 500, "price_per_kg": 13.5}).json()
    assert card["status"] == "proposed" and card["buyerAccepted"] and not card["sellerAccepted"]
    card = client.post(f"/api/deals/{deal_id}/accept", headers=hf).json()
    assert card["status"] == "agreed" and card["totalRs"] == 6750
    after = next(r for r in client.get("/api/listings", headers=hb).json() if r["id"] == potato["id"])
    assert after["quantityKg"] == 2000


def test_assistant_price_reply_in_bengali(client):
    hf, _ = login(client, "9000000001")
    r = client.post("/api/chat/after-send", headers=hf,
                    json={"channel_type": 1, "channel_id": "mandi-mitra", "text": "আলুর দাম কত?"}).json()
    assert r["replied"] and r["intent"] == "price"
    hist = client.get("/api/dev/history", headers=hf, params={"channel_type": 1, "channel_id": "mandi-mitra"}).json()
    assert "আলু" in hist[-1]["content"]["text"]


def test_escalation_reaches_agent(client):
    hb, _ = login(client, "9000000003")
    r = client.post("/api/chat/after-send", headers=hb,
                    json={"channel_type": 1, "channel_id": "mandi-mitra", "text": "मुझे एजेंट से बात करनी है, पैसे नहीं मिले"}).json()
    assert r["escalated"] and r["ticketId"]
    ha, _ = login(client, "9000000000", "2468")
    tickets = client.get("/api/support/tickets", headers=ha).json()
    t = next(t for t in tickets if t["id"] == r["ticketId"])
    assert t["priority"] == "high" and t["status"] == "open"
    claimed = client.post(f"/api/support/tickets/{t['id']}/claim", headers=ha).json()
    assert claimed["status"] == "assigned"
    hist = client.get("/api/dev/history", headers=ha, params={"channel_type": 3, "channel_id": t["channelId"]}).json()
    assert hist[-1]["content"]["kind"] == "agent_joined"
    assert client.post(f"/api/support/tickets/{t['id']}/resolve", headers=ha).json()["status"] == "resolved"


def test_translation_phrasebook_and_same_language(client):
    h, _ = login(client, "9000000002")
    r = client.post("/api/translate", headers=h, json={"text": "দাম কত?", "target": "en"}).json()
    assert r["translated"] and r["text"] == "What is the price?"
    same = client.post("/api/translate", headers=h, json={"text": "hello there", "target": "en"}).json()
    assert same["engine"] == "same"


def test_same_translation_saved_twice_does_not_fail(client):
    # Two viewers translating the same message at the same moment both write the cache row.
    from sqlmodel import Session
    from app.db import engine
    from app.translate import translate

    from app.models import TranslationCache

    class MissesCache(Session):
        """A session that, like a request racing another one, did not see the cached row."""

        def get(self, entity, *args, **kwargs):
            return None if entity is TranslationCache else super().get(entity, *args, **kwargs)

    async def both():
        with Session(engine) as a, MissesCache(engine) as b:
            first = await translate(a, "Okay, I agree", "bn")  # writes the cache row
            second = await translate(b, "Okay, I agree", "bn")  # misses it, writes again
            return first, second

    first, second = asyncio.run(both())
    assert first.text == second.text == "ঠিক আছে, আমি রাজি"
    assert second.engine == "phrasebook"  # it really went past the cache


def test_metrics_counts(client):
    m = client.get("/api/metrics").json()
    # Only the real (non-demo) user registered in test_register counts; demo activity is excluded.
    assert m["farmers"] == 1 and m["buyers"] == 0 and m["dealsAgreed"] == 0 and len(m["series"]) == 14


def test_non_member_blocked(client):
    h, _ = login(client, "9000000004")
    r = client.post("/api/chat/after-send", headers=h, json={"channel_type": 3, "channel_id": "deal_1_u_demo_buyer", "text": "hi"})
    assert r.status_code == 403


def test_plain_help_escalates_and_group_bot_has_variants(client):
    from app.agent import _rules
    assert _rules("help", False)["intent"] == "escalate"
    assert _rules("I was cheated by a buyer", False)["intent"] == "escalate"
    hb, _ = login(client, "9000000002")
    deal = next(c for c in client.get("/api/conversations", headers=hb).json() if c["kind"] == "deal")
    r = client.post("/api/chat/ask-ai", headers=hb, json={"channel_id": deal["channelId"]}).json()
    assert r["replied"]
    hist = client.get("/api/dev/history", headers=hb, params={"channel_type": 3, "channel_id": deal["channelId"]}).json()
    bot = [m for m in hist if m["senderUserId"] == "mandi-mitra" and m["messageType"] == "RC:TxtMsg"][-1]
    import json
    variants = json.loads(bot["content"]["extra"])["variants"]
    assert set(variants) == {"en", "hi", "bn"} and "₹" in variants["bn"]


# ----------------------------------------------------------------- v2 features
def _agreed_deal(client):
    hb, _ = login(client, "9000000002")
    hf, _ = login(client, "9000000001")
    rice = next(r for r in client.get("/api/listings", headers=hb).json() if r["crop"] == "rice")
    deal_id = client.post(f"/api/listings/{rice['id']}/enquire", headers=hb).json()["dealId"]
    client.post(f"/api/deals/{deal_id}/propose", headers=hb, json={"quantity_kg": 100, "price_per_kg": 35})
    client.post(f"/api/deals/{deal_id}/accept", headers=hf)
    return hb, hf, deal_id


def test_search_sort_and_ticker(client):
    h, _ = login(client, "9000000002")
    bn = client.get("/api/listings", headers=h, params={"q": "আলু"}).json()
    assert bn and all(r["crop"] == "potato" for r in bn)
    assert client.get("/api/listings", headers=h, params={"q": "Nadia"}).json()
    prices = [r["pricePerKg"] for r in client.get("/api/listings", headers=h, params={"sort": "price_asc"}).json()]
    assert prices == sorted(prices)
    ticker = client.get("/api/prices").json()
    assert len(ticker) == 12 and {"names", "modal_per_kg"} <= set(ticker[0])


def test_receipt_delivery_review_and_trust(client):
    hb, hf, deal_id = _agreed_deal(client)
    rc = client.get(f"/api/deals/{deal_id}/receipt", headers=hb).json()
    assert rc["receiptNo"].startswith("ML-") and rc["totalRs"] == 3500 and rc["seller"]["name"]
    assert "phone" not in str(rc)
    assert client.post(f"/api/deals/{deal_id}/delivered", headers=hf).status_code == 403  # seller cannot
    done = client.post(f"/api/deals/{deal_id}/delivered", headers=hb).json()
    assert done["status"] == "completed"
    r = client.post(f"/api/deals/{deal_id}/review", headers=hb, json={"stars": 5, "comment": "Good rice"}).json()
    assert r["trust"]["rating"] == 5.0 and r["trust"]["deals"] >= 1
    assert client.get(f"/api/deals/{deal_id}/review", headers=hb).json()["stars"] == 5
    seller = next(x for x in client.get("/api/listings", headers=hb).json() if x["crop"] == "rice")["seller"]
    assert seller["trust"]["badge"] in ("trusted", "top")


def test_smart_replies_carry_fair_price_and_translate(client):
    hb, _ = login(client, "9000000002")
    hf, _ = login(client, "9000000001")
    cauli = next(r for r in client.get("/api/listings", headers=hb).json() if r["crop"] == "cauliflower")
    deal_id = client.post(f"/api/listings/{cauli['id']}/enquire", headers=hb).json()["dealId"]
    s = client.get("/api/chat/suggestions", headers=hb, params={"channel_id": deal_id}).json()
    counter = next(x for x in s["replies"] if x.startswith("Can you do"))
    assert f"₹{s['fairPrice']:g}/kg" in counter and s["fairPrice"] <= cauli["pricePerKg"]
    sf = client.get("/api/chat/suggestions", headers=hf, params={"channel_id": deal_id}).json()
    assert any("দাম" in x for x in sf["replies"])  # the farmer gets Bengali replies
    tr = client.post("/api/translate", headers=hf, json={"text": counter, "target": "bn"}).json()
    assert tr["translated"] and f"₹{s['fairPrice']:g}/kg" in tr["text"]


def test_buy_request_pings_farmers_and_opens_deal(client):
    hb, _ = login(client, "9000000003")
    hf, _ = login(client, "9000000004")
    assert client.post("/api/requests", headers=hf, json={"crop": "jute", "quantity_kg": 10}).status_code == 403
    req = client.post("/api/requests", headers=hb, json={"crop": "jute", "quantity_kg": 300, "target_price_per_kg": 50}).json()
    assert req["notified"] >= 1
    hist = client.get("/api/dev/history", headers=hf, params={"channel_type": 1, "channel_id": "mandi-mitra"}).json()
    assert "পাট" in hist[-1]["content"]["text"]  # pinged in Bengali
    seen = next(r for r in client.get("/api/requests", headers=hf).json() if r["id"] == req["id"])
    listing_id = seen["myMatchingListings"][0]["id"]
    deal_id = client.post(f"/api/requests/{req['id']}/respond", headers=hf, json={"listing_id": listing_id}).json()["dealId"]
    assert any(c["channelId"] == deal_id for c in client.get("/api/conversations", headers=hb).json())


def test_photo_upload_roundtrip(client):
    import base64
    hf, _ = login(client, "9000000001")
    png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")
    url = client.post("/api/photos", headers=hf, json={"data_url": "data:image/png;base64," + base64.b64encode(png).decode()}).json()["url"]
    got = client.get(url)
    assert got.status_code == 200 and got.content == png
    assert client.post("/api/photos", headers=hf, json={"data_url": "data:text/html;base64,PGI+"}).status_code == 422
    bad = client.post("/api/listings", headers=hf, json={"crop": "onion", "quantity_kg": 1, "price_per_kg": 1,
                                                         "photo_url": "javascript:alert(1)"})
    assert bad.status_code == 422


def test_agent_brief(client):
    hb, _ = login(client, "9000000002")
    deal = next(c for c in client.get("/api/conversations", headers=hb).json() if c["kind"] == "deal")
    t = client.post("/api/support/request", headers=hb, json={"channel_id": deal["channelId"], "reason": "Payment not received yet"}).json()
    ha, _ = login(client, "9000000000", "2468")
    b = client.get(f"/api/support/tickets/{t['ticketId']}/brief", headers=ha).json()
    assert b["category"] == "payment" and any("Mandi band" in f for f in b["facts"]) and b["suggestedAction"]
    assert client.get(f"/api/support/tickets/{t['ticketId']}/brief", headers=hb).status_code == 403
    client.post(f"/api/support/tickets/{t['ticketId']}/claim", headers=ha)
    s = client.get("/api/chat/suggestions", headers=ha, params={"channel_id": t["channelId"]}).json()
    assert len(s["replies"]) == 4


def test_v2_metrics_shape(client):
    m = client.get("/api/metrics").json()
    assert {"gmvRs", "kgTraded", "languages", "requests", "dealsCompleted"} <= set(m)
    assert m["gmvRs"] == 0  # demo deals never count as traction


def test_gemini_falls_back_when_model_retired(monkeypatch):
    import httpx
    from app import llm
    from app.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "llm_provider", "gemini")
    monkeypatch.setattr(s, "gemini_api_key", "test-key")
    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req.url.path)
        if s.gemini_model in req.url.path:
            return httpx.Response(404, json={"error": {"message": "model not found"}})
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "নমস্কার"}]}}]})

    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    out = asyncio.run(llm.complete("sys", "hello"))
    assert out == "নমস্কার"
    assert s.gemini_model in seen[0] and s.gemini_fallback_model in seen[1]


def test_gemini_falls_back_when_model_times_out(monkeypatch):
    import httpx
    from app import llm
    from app.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "llm_provider", "gemini")
    monkeypatch.setattr(s, "gemini_api_key", "test-key")

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.headers["x-goog-api-key"] == "test-key" and "key=" not in str(req.url)
        if s.gemini_model in req.url.path:
            raise httpx.ReadTimeout("overloaded", request=req)
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "ok"}]}}]})

    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    assert asyncio.run(llm.complete("sys", "hello")) == "ok"


def test_precomposed_bengali_ya_still_matches(client):
    """Keyboards may send য় as one code point (U+09DF) instead of য + ় (U+09AF U+09BC).
    Escalation, crop detection and the phrasebook must work with either spelling."""
    from app.agent import _rules
    from app.lang import find_crop, phrasebook
    not_paid = "টাকা দেয়নি"  # টাকা দেয়নি, precomposed য়
    onion = "পেঁয়াজ"  # পেঁয়াজ, precomposed য়
    assert "য়" in not_paid and "য়" in onion
    assert _rules(not_paid, True)["intent"] == "escalate"
    assert find_crop(onion + "ের দাম") == "onion"
    yes_agree = "ঠিক আছে, আমি রাজি"  # ঠিক আছে, আমি রাজি
    assert phrasebook(yes_agree, "bn", "en") == "Okay, I agree"

    hf, _ = login(client, "9000000004")
    ht, _ = login(client, "9000000003")
    brinjal = next(r for r in client.get("/api/listings", headers=ht).json() if r["crop"] == "brinjal")
    deal_id = client.post(f"/api/listings/{brinjal['id']}/enquire", headers=ht).json()["dealId"]
    r = client.post("/api/chat/after-send", headers=hf,
                    json={"channel_type": 3, "channel_id": deal_id, "text": "মাল পাঠিয়েছি, " + not_paid}).json()
    assert r.get("escalated") and r.get("ticketId")


def _wav(ms=1000, rate=16000):
    import io
    import wave
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(rate * ms / 1000))
    return buf.getvalue()


def test_voice_note_upload_playback_and_validation(client):
    import base64
    hf, _ = login(client, "9000000001")
    wav = _wav()
    r = client.post("/api/voice", headers=hf, json={"data_url": "data:audio/wav;base64," + base64.b64encode(wav).decode(),
                                                    "duration_ms": 1000, "lang": "bn"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["url"].startswith("/api/voice/") and body["transcript"] == "" and body["lang"] == "bn"
    got = client.get(body["url"])
    assert got.status_code == 200 and got.content == wav and got.headers["content-type"] == "audio/wav"
    bad = client.post("/api/voice", headers=hf, json={"data_url": "data:text/html;base64,PGI+", "duration_ms": 1000})
    assert bad.status_code == 422
    short = client.post("/api/voice", headers=hf, json={"data_url": "data:audio/wav;base64,AAAA", "duration_ms": 100})
    assert short.status_code == 422


def test_voice_note_transcript_with_gemini(client, monkeypatch):
    import base64
    import httpx
    from app.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "llm_provider", "gemini")
    monkeypatch.setattr(s, "gemini_api_key", "test-key")
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        import json as _json
        seen["body"] = _json.loads(req.content)
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "আলুর দাম কত?"}]}}]})

    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    hf, _ = login(client, "9000000001")
    r = client.post("/api/voice", headers=hf, json={"data_url": "data:audio/wav;base64," + base64.b64encode(_wav()).decode(),
                                                    "duration_ms": 1000}).json()
    assert r["transcript"] == "আলুর দাম কত?" and r["lang"] == "bn"
    part = seen["body"]["contents"][0]["parts"][1]["inline_data"]
    assert part["mime_type"] == "audio/wav" and base64.b64decode(part["data"]) == _wav()


def test_spoken_complaint_escalates(client):
    hb, _ = login(client, "9000000002")
    hf, _ = login(client, "9000000004")
    jute = next(r for r in client.get("/api/listings", headers=hb).json() if r["crop"] == "jute")
    deal_id = client.post(f"/api/listings/{jute['id']}/enquire", headers=hb).json()["dealId"]
    r = client.post("/api/chat/after-send", headers=hf, json={
        "channel_type": 3, "channel_id": deal_id, "message_type": "ML:Voice",
        "text": "টাকা দেয়নি"}).json()
    assert r.get("escalated") and r.get("ticketId")


def test_metrics_exclude_demo_listings_and_feedback(client):
    h, _ = login(client, "9000000002")
    client.post("/api/feedback", headers=h, json={"rating": 1, "comment": "demo"})
    m = client.get("/api/metrics").json()
    assert m["listings"] == 0 and m["feedbackCount"] == 0 and "voiceNotes" in m


def test_existing_nexconn_group_is_reused_and_namespace_applied(monkeypatch):
    from app import services
    from app.config import get_settings
    from app.nexconn import GROUP_EXISTS, NexconnClient, NexconnError

    c = NexconnClient()
    monkeypatch.setattr(c.s, "nexconn_app_key", "k")
    monkeypatch.setattr(c.s, "nexconn_app_secret", "s")
    calls = []

    async def fake_post(path, body):
        calls.append(path)
        if path.endswith("/create"):
            raise NexconnError(GROUP_EXISTS, "group already exists")
        return {"code": 0}

    monkeypatch.setattr(c, "_post", fake_post)
    asyncio.run(c.create_group("deal_9_u_x", "Deal", "mandi-mitra", ["u_a", "u_b"]))
    assert calls == ["/v4/group-channel/create", "/v4/group-channel/join"]

    async def other_error(path, body):
        raise NexconnError(401, "bad signature")

    monkeypatch.setattr(c, "_post", other_error)
    with pytest.raises(NexconnError):
        asyncio.run(c.create_group("deal_9_u_x", "Deal", "mandi-mitra", ["u_a"]))

    monkeypatch.setattr(get_settings(), "channel_namespace", "live")
    assert services.channel_id("deal_1_u_demo_buyer") == "deal_1_u_demo_buyer-live"
    monkeypatch.setattr(get_settings(), "channel_namespace", "")
    assert services.channel_id("room-veg-kolkata") == "room-veg-kolkata"


def _register(client, phone, role, name="Real User", lang="bn"):
    r = client.post("/api/auth/register", json={"name": name, "phone": phone, "pin": "5555", "role": role,
                                                "language": lang, "district": "Bankura"})
    if r.status_code == 409:
        return login(client, phone, "5555")
    assert r.status_code == 200, r.text
    d = r.json()
    return {"Authorization": f"Bearer {d['session']}"}, d


def test_demo_desk_only_sees_demo_tickets_and_private_desk_sees_all(client, monkeypatch):
    from sqlmodel import Session
    from app import services
    from app.config import get_settings
    from app.db import engine

    hr, real = _register(client, "9123400001", "buyer", "Real Buyer")
    real_ticket = client.post("/api/support/request", headers=hr, json={"reason": "My payment is stuck"}).json()["ticketId"]
    ha, _ = login(client, "9000000000", "2468")
    ids = [t["id"] for t in client.get("/api/support/tickets", headers=ha).json()]
    assert real_ticket not in ids and ids  # demo desk still has demo tickets
    assert client.post(f"/api/support/tickets/{real_ticket}/claim", headers=ha).status_code == 404
    assert client.get(f"/api/support/tickets/{real_ticket}/brief", headers=ha).status_code == 404
    pings = client.get("/api/dev/history", headers=ha, params={"channel_type": 1, "channel_id": "mandi-mitra"}).json()
    assert not any(str(real_ticket) in str(m["content"]) and "Real Buyer" in str(m["content"]) for m in pings)

    s = get_settings()
    monkeypatch.setattr(s, "support_agent_phone", "9876500000")
    monkeypatch.setattr(s, "support_agent_pin", "135790")
    with Session(engine) as session:
        asyncio.run(services.bootstrap(session))
    hp, _ = login(client, "9876500000", "135790")
    assert real_ticket in [t["id"] for t in client.get("/api/support/tickets", headers=hp).json()]
    assert client.post(f"/api/support/tickets/{real_ticket}/claim", headers=hp).json()["status"] == "assigned"
    assert client.get(f"/api/support/tickets/{real_ticket}/brief", headers=hp).status_code == 200
    assert login(client, "9000000000", "2468")  # demo desk PIN unchanged for judges


def test_short_private_agent_pin_is_ignored(monkeypatch):
    from sqlmodel import Session
    from app import services
    from app.config import get_settings
    from app.db import engine
    from app.models import User

    s = get_settings()
    monkeypatch.setattr(s, "support_agent_phone", "9876511111")
    monkeypatch.setattr(s, "support_agent_pin", "1234")
    with Session(engine) as session:
        asyncio.run(services.bootstrap(session))
        assert session.exec(__import__("sqlmodel").select(User).where(User.phone == "9876511111")).first() is None


def test_demo_and_real_users_never_meet(client):
    hrf, realf = _register(client, "9123400002", "farmer", "Real Farmer")
    li = client.post("/api/listings", headers=hrf, json={"crop": "onion", "quantity_kg": 100, "price_per_kg": 22}).json()
    hdb, _ = login(client, "9000000002")
    assert li["id"] not in [x["id"] for x in client.get("/api/listings", headers=hdb).json()]
    assert client.post(f"/api/listings/{li['id']}/enquire", headers=hdb).status_code == 404
    hrb, _ = _register(client, "9123400003", "buyer", "Real Buyer Two", "en")
    seen = client.get("/api/listings", headers=hrb).json()
    assert li["id"] in [x["id"] for x in seen] and not any(x["seller"]["id"].startswith("u_demo") for x in seen)
    deal = client.post(f"/api/listings/{li['id']}/enquire", headers=hrb).json()["dealId"]
    assert deal

    hdt, _ = login(client, "9000000003")
    req = client.post("/api/requests", headers=hdt, json={"crop": "onion", "quantity_kg": 50}).json()
    pings = client.get("/api/dev/history", headers=hrf, params={"channel_type": 1, "channel_id": "mandi-mitra"}).json()
    assert not any("Sunita" in str(m["content"]) for m in pings)  # demo request never pings a real farmer
    assert req["id"] not in [r["id"] for r in client.get("/api/requests", headers=hrf).json()]
    me = client.patch("/api/auth/me", headers=hdb, json={}).json()
    assert me["demo"] is True and client.patch("/api/auth/me", headers=hrb, json={}).json()["demo"] is False
