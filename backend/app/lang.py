"""Language helpers: script detection, crop glossary, offline phrasebook."""
from __future__ import annotations

import re
import unicodedata


def nfc(text: str) -> str:
    """One canonical spelling for Indic text. Keyboards differ: Bengali য় can arrive as
    one code point (U+09DF) or as য + ়; Hindi ड़/ज़ likewise. NFC folds both into the
    decomposed form, so rules, crop names and the phrasebook match whatever was typed."""
    return unicodedata.normalize("NFC", text or "")


def rx(pattern: str, flags: int = 0) -> re.Pattern[str]:
    """re.compile on the canonical form of the pattern (see nfc)."""
    return re.compile(nfc(pattern), flags)

LANG_NAMES = {"en": "English", "hi": "Hindi", "bn": "Bengali"}

_BENGALI = re.compile(r"[ঀ-৿]")
_DEVANAGARI = re.compile(r"[ऀ-ॿ]")


def detect_language(text: str) -> str:
    bn = len(_BENGALI.findall(text))
    hi = len(_DEVANAGARI.findall(text))
    if bn == 0 and hi == 0:
        return "en"
    return "bn" if bn >= hi else "hi"


# crop key -> names per language (+ common romanised aliases used by farmers)
CROPS: dict[str, dict[str, list[str]]] = {
    "potato": {"en": ["potato", "aloo", "alu"], "hi": ["आलू"], "bn": ["আলু"]},
    "onion": {"en": ["onion", "pyaz", "pyaj", "peyaj"], "hi": ["प्याज"], "bn": ["পেঁয়াজ", "পিঁয়াজ"]},
    "tomato": {"en": ["tomato", "tamatar"], "hi": ["टमाटर"], "bn": ["টমেটো"]},
    "rice": {"en": ["rice", "paddy", "dhan", "chawal"], "hi": ["चावल", "धान"], "bn": ["চাল", "ধান"]},
    "wheat": {"en": ["wheat", "gehu", "gehun"], "hi": ["गेहूं", "गेहूँ"], "bn": ["গম"]},
    "jute": {"en": ["jute", "paat", "pat"], "hi": ["जूट", "पटसन"], "bn": ["পাট"]},
    "mustard": {"en": ["mustard", "sarson", "sorse"], "hi": ["सरसों"], "bn": ["সরিষা", "সর্ষে"]},
    "cauliflower": {"en": ["cauliflower", "gobi", "phulkopi"], "hi": ["गोभी", "फूलगोभी"], "bn": ["ফুলকপি"]},
    "brinjal": {"en": ["brinjal", "eggplant", "baingan", "begun"], "hi": ["बैंगन"], "bn": ["বেগুন"]},
    "banana": {"en": ["banana", "kela", "kola"], "hi": ["केला"], "bn": ["কলা"]},
    "mango": {"en": ["mango", "aam"], "hi": ["आम"], "bn": ["আম"]},
    "green chilli": {"en": ["chilli", "chili", "mirchi", "lanka"], "hi": ["मिर्च"], "bn": ["লঙ্কা", "মরিচ"]},
}

CROP_DISPLAY = {
    "potato": {"en": "Potato", "hi": "आलू", "bn": "আলু"},
    "onion": {"en": "Onion", "hi": "प्याज", "bn": "পেঁয়াজ"},
    "tomato": {"en": "Tomato", "hi": "टमाटर", "bn": "টমেটো"},
    "rice": {"en": "Rice", "hi": "चावल", "bn": "চাল"},
    "wheat": {"en": "Wheat", "hi": "गेहूं", "bn": "গম"},
    "jute": {"en": "Jute", "hi": "जूट", "bn": "পাট"},
    "mustard": {"en": "Mustard", "hi": "सरसों", "bn": "সরিষা"},
    "cauliflower": {"en": "Cauliflower", "hi": "फूलगोभी", "bn": "ফুলকপি"},
    "brinjal": {"en": "Brinjal", "hi": "बैंगन", "bn": "বেগুন"},
    "banana": {"en": "Banana", "hi": "केला", "bn": "কলা"},
    "mango": {"en": "Mango", "hi": "आम", "bn": "আম"},
    "green chilli": {"en": "Green chilli", "hi": "हरी मिर्च", "bn": "কাঁচা লঙ্কা"},
}


def find_crop(text: str) -> str | None:
    text = nfc(text)
    low = text.lower()
    for key, names in CROPS.items():
        for lang_names in names.values():
            for n in lang_names:
                if (n.isascii() and re.search(rf"\b{re.escape(n)}\b", low)) or (not n.isascii() and nfc(n) in text):
                    return key
    return None


def crop_name(key: str, lang: str) -> str:
    return CROP_DISPLAY.get(key, {}).get(lang) or key.title()


_DIGITS = {
    "bn": str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789"),
    "hi": str.maketrans("०१२३४५६७८९", "0123456789"),
}


def normalise_digits(text: str) -> str:
    text = nfc(text)
    for table in _DIGITS.values():
        text = text.translate(table)
    return text


# Offline phrasebook: used when no LLM is configured, so the most common
# marketplace lines still translate during a demo.
PHRASES: list[dict[str, str]] = [
    {"en": "Hello", "hi": "नमस्ते", "bn": "নমস্কার"},
    {"en": "Hi", "hi": "नमस्ते", "bn": "নমস্কার"},
    {"en": "Thank you", "hi": "धन्यवाद", "bn": "ধন্যবাদ"},
    {"en": "Yes", "hi": "हाँ", "bn": "হ্যাঁ"},
    {"en": "No", "hi": "नहीं", "bn": "না"},
    {"en": "Okay", "hi": "ठीक है", "bn": "ঠিক আছে"},
    {"en": "Ok", "hi": "ठीक है", "bn": "ঠিক আছে"},
    {"en": "What is the price?", "hi": "कीमत क्या है?", "bn": "দাম কত?"},
    {"en": "How much quantity do you have?", "hi": "आपके पास कितनी मात्रा है?", "bn": "আপনার কাছে কত পরিমাণ আছে?"},
    {"en": "Can you reduce the price?", "hi": "क्या आप कीमत कम कर सकते हैं?", "bn": "দাম কি একটু কমানো যাবে?"},
    {"en": "The price is final", "hi": "कीमत अंतिम है", "bn": "দাম চূড়ান্ত"},
    {"en": "When can you deliver?", "hi": "आप कब डिलीवर कर सकते हैं?", "bn": "কবে ডেলিভারি দিতে পারবেন?"},
    {"en": "I can deliver tomorrow", "hi": "मैं कल डिलीवर कर सकता हूँ", "bn": "আমি কাল ডেলিভারি দিতে পারব"},
    {"en": "Please send a photo", "hi": "कृपया एक फोटो भेजें", "bn": "দয়া করে একটা ছবি পাঠান"},
    {"en": "Deal done", "hi": "सौदा पक्का", "bn": "চুক্তি পাকা"},
    {"en": "Is the quality good?", "hi": "क्या गुणवत्ता अच्छी है?", "bn": "মান কি ভালো?"},
    {"en": "The quality is very good", "hi": "गुणवत्ता बहुत अच्छी है", "bn": "মান খুব ভালো"},
    {"en": "I am interested", "hi": "मुझे रुचि है", "bn": "আমি আগ্রহী"},
    {"en": "Payment on delivery", "hi": "डिलीवरी पर भुगतान", "bn": "ডেলিভারির সময় পেমেন্ট"},
    {"en": "Okay, I agree", "hi": "ठीक है, मैं सहमत हूँ", "bn": "ঠিক আছে, আমি রাজি"},
    {"en": "Goods received, thank you", "hi": "माल मिल गया, धन्यवाद", "bn": "মাল পেয়েছি, ধন্যবাদ"},
    {"en": "Where should I deliver?", "hi": "मैं कहाँ डिलीवर करूँ?", "bn": "কোথায় ডেলিভারি দেব?"},
    {"en": "Hello, I am here to help you.", "hi": "नमस्ते, मैं आपकी मदद के लिए यहाँ हूँ।", "bn": "নমস্কার, আমি আপনাকে সাহায্য করতে এসেছি।"},
    {"en": "Please tell me what happened.", "hi": "कृपया बताइए क्या हुआ।", "bn": "দয়া করে বলুন কী হয়েছে।"},
    {"en": "I am talking to the other party now.", "hi": "मैं अभी दूसरे पक्ष से बात कर रहा हूँ।", "bn": "আমি এখন অন্য পক্ষের সঙ্গে কথা বলছি।"},
    {"en": "Your issue is resolved. Thank you for your patience.", "hi": "आपकी समस्या हल हो गई है। धैर्य के लिए धन्यवाद।", "bn": "আপনার সমস্যার সমাধান হয়েছে। ধৈর্যের জন্য ধন্যবাদ।"},
    # Number-aware templates: {n} matches any number and is carried across.
    {"en": "Can you do ₹{n}/kg?", "hi": "क्या ₹{n}/kg में देंगे?", "bn": "₹{n}/kg-তে দেবেন?"},
    {"en": "My best price is ₹{n}/kg", "hi": "मेरा आख़िरी भाव ₹{n}/kg है", "bn": "আমার শেষ দাম ₹{n}/kg"},
    {"en": "I need {n} kg", "hi": "मुझे {n} किलो चाहिए", "bn": "আমার {n} কেজি লাগবে"},
    {"en": "I have {n} kg ready", "hi": "मेरे पास {n} किलो तैयार है", "bn": "আমার কাছে {n} কেজি তৈরি আছে"},
]

# Smart replies offered in deal rooms / support chats, keyed by situation.
# Every line is in PHRASES above, so it translates for the other side even
# with no AI provider configured.
SMART = {
    "buyer_negotiating": ["Is the quality good?", "Can you do ₹{fair}/kg?", "When can you deliver?", "Please send a photo"],
    "seller_negotiating": ["The quality is very good", "My best price is ₹{floor}/kg", "I can deliver tomorrow", "Payment on delivery"],
    "buyer_proposed": ["When can you deliver?", "Payment on delivery", "Thank you"],
    "seller_proposed": ["Okay, I agree", "My best price is ₹{floor}/kg", "I can deliver tomorrow"],
    "buyer_agreed": ["When can you deliver?", "Payment on delivery", "Goods received, thank you"],
    "seller_agreed": ["Where should I deliver?", "I can deliver tomorrow", "Payment on delivery"],
    "buyer_completed": ["Thank you"],
    "seller_completed": ["Thank you"],
    "agent": ["Hello, I am here to help you.", "Please tell me what happened.", "I am talking to the other party now.",
              "Your issue is resolved. Thank you for your patience."],
}


def localise(phrase_en: str, lang: str, **nums: float) -> str:
    """English smart-reply template -> the user's language, numbers filled in."""
    names = re.findall(r"\{(\w+)\}", phrase_en)
    generic = re.sub(r"\{\w+\}", "{n}", phrase_en)
    row = next((r for r in PHRASES if r["en"] == generic), None)
    out = (row or {}).get(lang) or generic
    for name in names:
        out = out.replace("{n}", f"{nums.get(name, 0):g}", 1)
    return out


def _norm(s: str) -> str:
    return re.sub(r"[\s।?!,]+|\.(?!\d)", " ", s.strip().lower()).strip()


_NUM = r"(\d+(?:\.\d+)?)"


def _template_re(src: str) -> re.Pattern[str]:
    parts = [re.escape(x) for x in _norm(nfc(src)).split("{n}")]
    return re.compile("^" + _NUM.join(parts) + "$")


def phrasebook(text: str, source: str, target: str) -> str | None:
    key = _norm(normalise_digits(text))
    for row in PHRASES:
        src, dst = row.get(source, ""), row.get(target)
        if not src or not dst:
            continue
        if "{n}" not in src:
            if _norm(nfc(src)) == key:
                return dst
            continue
        m = _template_re(src).match(key)
        if m:
            out = dst
            for n in m.groups():
                out = out.replace("{n}", n, 1)
            return out
    return None
