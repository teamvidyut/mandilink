"""Mandi Mitra — the MandiLink AI assistant, built as a LangGraph state machine.

    understand ──► route ──► price_tool ─────┐
                      ├────► listings_tool ──┤
                      ├────► negotiate_tool ─┼──► respond ──► END
                      ├────► escalate ───────┤
                      └────► (no tool) ──────┘

* `understand` extracts intent/crop/quantity/price. Fast multilingual rules run
  first; the LLM (if configured) refines ambiguous messages.
* Tools are deterministic (DB + mandi prices), so facts never come from the LLM.
* `respond` lets the LLM phrase the answer in the user's language; templates
  are the fallback, so the bot always answers even with no AI provider.
* Escalation is decided by rules (dispute / fraud / "talk to a human") or the
  LLM, and the caller opens a human-support ticket.
"""
from __future__ import annotations

import re
from typing import Any, Literal, Optional, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from sqlmodel import Session, select

from . import llm, mandi
from .lang import LANG_NAMES, crop_name, detect_language, find_crop, nfc, normalise_digits, rx
from .models import Deal, Listing, User

Intent = Literal["price", "find_listings", "sell_help", "negotiate", "escalate", "greeting", "other"]


class AgentState(TypedDict, total=False):
    text: str
    lang: str
    user_id: str
    role: str
    district: str
    deal_id: Optional[str]
    intent: Intent
    crop: Optional[str]
    quantity_kg: Optional[float]
    price_per_kg: Optional[float]
    facts: dict[str, Any]
    reply: str
    escalate: bool
    escalate_reason: str
    priority: str


# --------------------------------------------------------------------------- rules
_ESCALATE = rx(
    r"^\s*help\s*[.!]?\s*$"
    r"|\b(human|person|agent|support|complain\w*|fraud\w*|cheat\w*|scam\w*|dispute\w*|refund\w*|not paid|police|helpline)\b"
    r"|মানুষ|অভিযোগ|প্রতারণা|ঠকিয়েছে|টাকা দেয়নি|সাহায্য চাই|এজেন্ট"
    r"|इंसान|शिकायत|धोखा|ठगी|पैसे नहीं|एजेंट|मदद चाहिए",
    re.I,
)
_HIGH = rx(r"fraud|cheat|scam|police|not paid|unpaid|প্রতারণা|ঠকিয়েছে|টাকা দেয়নি|धोखा|ठगी|पैसे नहीं", re.I)
_PRICE = rx(r"\b(price|rate|bhav|bhaav|daam|dam|mandi|cost|worth)\b|দাম|দর|ভাও|भाव|दाम|कीमत|रेट", re.I)
_FIND = rx(r"\b(buy|find|need|want|looking|available|supplier|sellers?)\b|কিনতে|চাই|পাওয়া|खरीद|चाहिए|मिलेगा", re.I)
_SELL = rx(r"\b(sell|list|post|upload)\b|বিক্রি|বেচ|बेच|बिक्री", re.I)
_NEGOTIATE = rx(r"\b(offer|counter|negotiat|fair|discount|reduce|kom|kam)\b|কমানো|ন্যায্য|অফার|कम|मोलभाव|उचित", re.I)
_GREET = rx(r"^\s*(hi|hello|hey|namaste|namaskar|নমস্কার|হ্যালো|नमस्ते|हैलो)\b", re.I)
_QTY = rx(r"(\d+(?:\.\d+)?)\s*(kg|kilo|quintal|qtl|ton|tonne|কেজি|কুইন্টাল|किलो|क्विंटल|टन)", re.I)
_RS = rx(r"(?:₹|rs\.?|inr|টাকা|रुपये|रु)\s*(\d+(?:\.\d+)?)|(\d+(?:\.\d+)?)\s*(?:₹|rs|টাকা|रुपये|रु)", re.I)


def _rules(text: str, in_deal: bool) -> dict[str, Any]:
    t = normalise_digits(text)
    out: dict[str, Any] = {"crop": find_crop(t)}
    if m := _QTY.search(t):
        n, unit = float(m.group(1)), m.group(2).lower()
        mult = 100 if unit in ("quintal", "qtl", "কুইন্টাল", "क्विंटल") else 1000 if unit in ("ton", "tonne", "टन") else 1
        out["quantity_kg"] = n * mult
    if m := _RS.search(t):
        out["price_per_kg"] = float(m.group(1) or m.group(2))
    if _ESCALATE.search(t):
        out["intent"] = "escalate"
    elif in_deal and _NEGOTIATE.search(t):
        out["intent"] = "negotiate"
    elif _PRICE.search(t):
        out["intent"] = "price"
    elif _SELL.search(t):
        out["intent"] = "sell_help"
    elif _FIND.search(t) and out["crop"]:
        out["intent"] = "find_listings"
    elif _GREET.search(t):
        out["intent"] = "greeting"
    elif in_deal:
        out["intent"] = "negotiate"
    elif out["crop"]:
        out["intent"] = "price"
    else:
        out["intent"] = "other"
    return out


_UNDERSTAND_SYS = (
    "You classify messages sent to an agricultural marketplace assistant in India. Messages may be in "
    "English, Hindi, Bengali or romanised Hindi/Bengali. Return JSON with keys: intent (one of price, "
    "find_listings, sell_help, negotiate, escalate, greeting, other), crop (English singular noun or null), "
    "quantity_kg (number or null), price_per_kg (number or null), escalate_reason (string, empty unless "
    "intent is escalate). Use escalate for disputes, fraud, payment problems, or requests for a human."
)


# --------------------------------------------------------------------------- nodes
async def understand(state: AgentState) -> AgentState:
    text = state["text"]
    lang = state.get("lang") or detect_language(text)
    parsed = _rules(text, bool(state.get("deal_id")))
    if llm.enabled() and parsed["intent"] in ("other", "greeting") and len(text) > 12:
        got = await llm.complete_json(_UNDERSTAND_SYS, text)
        if got and got.get("intent") in Intent.__args__:  # type: ignore[attr-defined]
            parsed["intent"] = got["intent"]
            parsed["crop"] = parsed["crop"] or (got.get("crop") or "").lower() or None
            parsed["quantity_kg"] = parsed.get("quantity_kg") or got.get("quantity_kg")
            parsed["price_per_kg"] = parsed.get("price_per_kg") or got.get("price_per_kg")
            if got.get("escalate_reason"):
                parsed["escalate_reason"] = got["escalate_reason"]
    return {
        "lang": lang,
        "intent": parsed["intent"],
        "crop": parsed.get("crop"),
        "quantity_kg": parsed.get("quantity_kg"),
        "price_per_kg": parsed.get("price_per_kg"),
        "escalate_reason": parsed.get("escalate_reason", ""),
        "facts": {},
        "escalate": False,
    }


def route(state: AgentState) -> str:
    return {
        "price": "price_tool",
        "find_listings": "listings_tool",
        "negotiate": "negotiate_tool",
        "escalate": "escalate",
    }.get(state["intent"], "respond")


async def price_tool(state: AgentState) -> AgentState:
    crop = state.get("crop")
    if not crop:
        return {"facts": {"need_crop": True}}
    info = await mandi.get_price(crop)
    return {"facts": {"price": info.to_dict() if info else None}}


def _session(config: RunnableConfig) -> Session:
    return config["configurable"]["session"]


async def listings_tool(state: AgentState, config: RunnableConfig) -> AgentState:
    s = _session(config)
    from .services import world_filter  # local import: services imports this module's callers

    q = select(Listing).where(Listing.status == "active", world_filter(Listing.seller_id, state.get("user_id") or ""))
    if state.get("crop"):
        q = q.where(Listing.crop == state["crop"])
    rows = s.exec(q.order_by(Listing.price_per_kg).limit(3)).all()  # type: ignore[arg-type]
    items = []
    for li in rows:
        seller = s.get(User, li.seller_id)
        items.append(
            {
                "id": li.id,
                "crop": li.crop,
                "qty": li.quantity_kg,
                "price": li.price_per_kg,
                "district": li.district,
                "seller": seller.name if seller else "",
            }
        )
    info = await mandi.get_price(state["crop"]) if state.get("crop") else None
    return {"facts": {"listings": items, "price": info.to_dict() if info else None}}


async def negotiate_tool(state: AgentState, config: RunnableConfig) -> AgentState:
    s = _session(config)
    deal = s.get(Deal, state["deal_id"]) if state.get("deal_id") else None
    listing = s.get(Listing, deal.listing_id) if deal else None
    if not listing:
        return {"facts": {}}
    info = await mandi.get_price(listing.crop)
    facts: dict[str, Any] = {
        "listing": {"crop": listing.crop, "qty": listing.quantity_kg, "price": listing.price_per_kg},
        "price": info.to_dict() if info else None,
    }
    if info:
        ask = listing.price_per_kg
        # A fair landing zone: between the mandi modal price and the ask, never below mandi min.
        fair = round(max(info.min_per_kg, (ask + info.modal_per_kg) / 2), 1)
        facts["fair_price"] = fair
        facts["fairness"] = mandi.fairness(ask, info)
    return {"facts": facts}


async def escalate(state: AgentState) -> AgentState:
    pri = "high" if _HIGH.search(state["text"]) else "normal"
    return {"escalate": True, "priority": pri, "escalate_reason": state.get("escalate_reason") or state["text"][:140]}


# ----------------------------------------------------------------------- respond
T = {
    "greeting": {
        "en": "Namaste! I'm Mandi Mitra 🌾. Ask me today's mandi price (e.g. \"potato price\"), find produce to buy, or get help listing your crop.",
        "hi": "नमस्ते! मैं मंडी मित्र हूँ 🌾। मुझसे आज का मंडी भाव पूछें (जैसे \"आलू का भाव\"), खरीदने के लिए फसल खोजें, या अपनी फसल बेचने में मदद लें।",
        "bn": "নমস্কার! আমি মান্ডি মিত্র 🌾। আজকের মান্ডি দর জিজ্ঞেস করুন (যেমন \"আলুর দাম\"), কেনার জন্য ফসল খুঁজুন, বা ফসল বিক্রির জন্য সাহায্য নিন।",
    },
    "need_crop": {
        "en": "Which crop? For example: potato, onion, rice, jute.",
        "hi": "कौन सी फसल? जैसे: आलू, प्याज, चावल, जूट।",
        "bn": "কোন ফসল? যেমন: আলু, পেঁয়াজ, চাল, পাট।",
    },
    "sell_help": {
        "en": "To sell: tap “+ Sell” on the Market tab, choose the crop, quantity and your price. I'll show buyers the fair mandi band so they trust your price.",
        "hi": "बेचने के लिए: मार्केट टैब पर “+ बेचें” दबाएँ, फसल, मात्रा और अपना भाव चुनें। मैं खरीदारों को मंडी का उचित भाव दिखाऊँगा ताकि वे आपकी कीमत पर भरोसा करें।",
        "bn": "বিক্রি করতে: মার্কেট ট্যাবে “+ বিক্রি” চাপুন, ফসল, পরিমাণ আর আপনার দাম দিন। ক্রেতাদের আমি ন্যায্য মান্ডি দর দেখাব, যাতে তারা আপনার দামে ভরসা পায়।",
    },
    "escalate": {
        "en": "I'm connecting you to a MandiLink support agent now. They'll join this chat shortly 🙏",
        "hi": "मैं आपको अभी MandiLink सहायता एजेंट से जोड़ रहा हूँ। वे जल्द ही इस चैट में आएँगे 🙏",
        "bn": "আমি আপনাকে এখনই MandiLink সাপোর্ট এজেন্টের সঙ্গে যুক্ত করছি। তিনি শিগগিরই এই চ্যাটে আসবেন 🙏",
    },
    "other": {
        "en": "I can help with mandi prices, finding produce, listing your crop, and fair negotiation. Type “help” to talk to a person.",
        "hi": "मैं मंडी भाव, फसल खोजने, अपनी फसल लिस्ट करने और उचित मोलभाव में मदद कर सकता हूँ। किसी व्यक्ति से बात करने के लिए “मदद चाहिए” लिखें।",
        "bn": "আমি মান্ডি দর, ফসল খোঁজা, ফসল তালিকাভুক্ত করা আর ন্যায্য দরদামে সাহায্য করতে পারি। মানুষের সঙ্গে কথা বলতে “সাহায্য চাই” লিখুন।",
    },
    "no_listings": {
        "en": "No active listings for that crop right now. I'll keep watching — try again soon or post what you need in a Mandi room.",
        "hi": "अभी उस फसल की कोई सक्रिय लिस्टिंग नहीं है। जल्द दोबारा देखें या मंडी रूम में अपनी ज़रूरत लिखें।",
        "bn": "এই ফসলের এখন কোনো সক্রিয় তালিকা নেই। একটু পরে আবার দেখুন, বা মান্ডি রুমে আপনার প্রয়োজন লিখুন।",
    },
}


def _template(state: AgentState) -> str:
    lang = state.get("lang", "en")
    if lang not in LANG_NAMES:
        lang = "en"
    intent = state["intent"]
    f = state.get("facts", {})
    if state.get("escalate"):
        return T["escalate"][lang]
    if f.get("need_crop"):
        return T["need_crop"][lang]
    price = mandi.PriceInfo(**f["price"]) if f.get("price") else None
    if intent == "price" and price:
        return "📊 " + price.describe(lang)
    if intent == "find_listings":
        items = f.get("listings") or []
        if not items:
            return T["no_listings"][lang]
        head = {"en": "Best offers right now:", "hi": "अभी के सबसे अच्छे ऑफर:", "bn": "এখনকার সেরা অফার:"}[lang]
        lines = [head]
        for it in items:
            lines.append(f"• {crop_name(it['crop'], lang)} — {it['qty']:g} kg @ ₹{it['price']:g}/kg · {it['district']} ({it['seller']})")
        if price:
            lines.append("📊 " + price.describe(lang))
        return "\n".join(lines)
    if intent == "negotiate" and f.get("fair_price"):
        li, fair = f["listing"], f["fair_price"]
        verdict = f.get("fairness", "fair")
        if lang == "bn":
            v = {"low": "বাজারের চেয়ে কম", "fair": "ন্যায্য", "high": "বাজারের চেয়ে বেশি"}[verdict]
            return f"🤝 চাওয়া দাম ₹{li['price']:g}/kg — {v}। দুই পক্ষের জন্য ন্যায্য দর প্রায় ₹{fair:g}/kg। {price.describe(lang) if price else ''}"
        if lang == "hi":
            v = {"low": "बाज़ार से कम", "fair": "उचित", "high": "बाज़ार से ज़्यादा"}[verdict]
            return f"🤝 माँगा गया भाव ₹{li['price']:g}/kg — {v}। दोनों के लिए उचित भाव लगभग ₹{fair:g}/kg। {price.describe(lang) if price else ''}"
        v = {"low": "below market", "fair": "fair", "high": "above market"}[verdict]
        return f"🤝 Asking price ₹{li['price']:g}/kg is {v}. A fair middle for both sides is about ₹{fair:g}/kg. {price.describe(lang) if price else ''}"
    if intent in T:
        return T[intent][lang]
    return T["other"][lang]


_RESPOND_SYS = (
    "You are Mandi Mitra, a warm, concise assistant inside MandiLink, a marketplace chat app connecting "
    "Indian farmers and buyers. Reply in {lang}. Use ONLY the facts provided; never invent prices, sellers or "
    "quantities. Keep replies under 70 words, plain text, at most one emoji. Prices are per kg in ₹. "
    "If facts say live=false, say the price is an estimate."
)


async def respond(state: AgentState) -> AgentState:
    draft = _template(state)
    if state.get("escalate") or not llm.enabled():
        return {"reply": draft}
    lang = LANG_NAMES.get(state.get("lang", "en"), "English")
    out = await llm.complete(
        _RESPOND_SYS.format(lang=lang),
        f"User role: {state.get('role')}\nUser message: {state['text']}\nIntent: {state['intent']}\n"
        f"Facts (JSON): {state.get('facts')}\nDraft answer (correct facts, rephrase naturally): {draft}",
        temperature=0.4,
    )
    return {"reply": out or draft}


def variants(state: AgentState) -> dict[str, str]:
    """The template answer in every app language. Used in shared rooms so each
    member reads the bot in their own language even without an LLM."""
    return {lg: _template({**state, "lang": lg}) for lg in LANG_NAMES}


def build_graph():
    g = StateGraph(AgentState)
    g.add_node("understand", understand)
    g.add_node("price_tool", price_tool)
    g.add_node("listings_tool", listings_tool)
    g.add_node("negotiate_tool", negotiate_tool)
    g.add_node("escalate", escalate)
    g.add_node("respond", respond)
    g.add_edge(START, "understand")
    g.add_conditional_edges("understand", route, ["price_tool", "listings_tool", "negotiate_tool", "escalate", "respond"])
    for n in ("price_tool", "listings_tool", "negotiate_tool", "escalate"):
        g.add_edge(n, "respond")
    g.add_edge("respond", END)
    return g.compile()


graph = build_graph()


async def run_agent(session: Session, user: User, text: str, deal_id: str | None = None) -> AgentState:
    text = nfc(text)
    # Native script wins; Latin-script input (English or romanised Bangla/Hindi)
    # is answered in the user's preferred language.
    detected = detect_language(text)
    lang = detected if detected != "en" else user.language
    state: AgentState = {
        "text": text,
        "lang": lang,
        "user_id": user.id,
        "role": user.role,
        "district": user.district,
        "deal_id": deal_id,
    }
    return await graph.ainvoke(state, config={"configurable": {"session": session}})
