# MandiLink

**Farmers and buyers chat, negotiate and close deals in their own language, with fair mandi prices on every screen.**

Built for the Nexconn Build Challenge 2026, **Marketplace & Support** track. All messaging runs on the **Nexconn Chat SDK** (`@nexconn/chat`) and the **Nexconn Server API**.

## The problem

A Bengali-speaking potato farmer in Hooghly and an English- or Hindi-speaking buyer in Kolkata or Asansol can't easily talk directly. Middlemen fill that gap and take a large share. Farmers also rarely know whether an offer is fair.

## What MandiLink does

| Feature | How it uses Nexconn |
|---|---|
| **Deal rooms**: buyer, seller and the AI assistant in one chat | Nexconn **group channel** per deal, created via `/v4/group-channel/create` |
| **Live translation**: everyone reads every message in their own language (বাংলা / हिन्दी / English), with the original one tap away | Text messages carry the sender's language in `extra`; each viewer's client translates on receipt |
| **Mandi rate band**: today's min / typical / max price with the asking or offer price pinned on it | Rendered inside a custom **`ML:Listing`** message card |
| **Offers and acceptance**: structured offer cards with Accept / Decline; the listing stock updates when both agree | Custom **`ML:Deal`** messages sent by the server |
| **Mandi Mitra AI assistant** (LangGraph): prices, finding produce, fair counter-offers, selling help | Bot is a real Nexconn user; replies via `/v4/direct-channel/message/send` and `/v4/group-channel/message/send` |
| **Human handoff**: "Get help", or keywords like *fraud* or *not paid*, open a ticket; the agent joins the same chat | Agent added with `/v4/group-channel/join`; agents get instant Nexconn DM alerts; **`ML:Notice`** system messages |
| **Voice typing and read-aloud**, for farmers who prefer speaking | Browser speech APIs on top of normal Nexconn text messages |
| **Mandi community rooms** (Potato · Hooghly, Paddy · Bengal, Vegetables · Kolkata) | Nexconn group channels; type `@mitra` to ask the AI |
| **Typing indicators, history, reconnect** | `ChannelHandler.onTypingStatusChanged`, `BaseChannel.createMessagesQuery`, `ConnectionStatusHandler` |
| **Impact page** at `/impact`: value traded, active users, languages, daily messages | Counts messages sent through the SDK |

### New in v2

| Feature | How it uses Nexconn |
|---|---|
| **Smart replies**: one-tap, context-aware replies in your language. In a deal room they carry the AI fair price ("Can you do ₹13.8/kg?"), and they translate for the other side even with no AI key | Sent as normal Nexconn text messages with `extra.lang` |
| **Deal lifecycle stepper**: Enquiry → Offer → Agreed → Delivered, with **Confirm goods received** for the buyer | `ML:Notice` (`delivered`) and updated `ML:Deal` cards posted by the server |
| **Deal receipt**: printable, shareable slip (Web Share / WhatsApp) with receipt number, parties and terms, no phone numbers | Built from the deal agreed inside the Nexconn group channel |
| **Ratings and trust badges**: rate each trade; sellers and buyers show ★ rating, completed deals and New / Trusted / Top rated | Rating card appears in the deal chat once both sides agree |
| **Buyer "Wanted" board**: buyers post a requirement; Mandi Mitra pings matching farmers **in each farmer's own language**; a farmer answers with one tap, which opens a deal room | Server sends `/v4/direct-channel/message/send` per language group; reply opens a group channel |
| **AI case brief for support agents**: category (payment, fraud, quality, delivery, price), deal facts, mandi band, both sides' trust and a suggested next step; plus agent quick replies | Agent joins the deal's group channel; quick replies are translated for the user |
| **Live mandi ticker, search and sort**: search in any script (আলু, आलू, aloo, potato), sort by price or best value | — |
| **Listing photos**: resized in the browser to ~100 KB (works on 2G), stored in the database so they survive redeploys | — |
| **AI suggested price** while listing, from today's mandi band | — |
| **Dark mode** (Light / Dark / Auto) and a redesigned, animated UI | — |
| **Voice messages with AI transcripts**: record in any language; Gemini writes down what was said and each reader sees it in their own language. A spoken question goes to Mandi Mitra, a spoken complaint opens a support ticket | Custom **`ML:Voice`** message sent through the Chat SDK; audio served by MandiLink |
| **Typing indicator in deal rooms** (group channels) | Silent custom **`ML:Typing`** message (not stored, not counted, no push), since the SDK's typing status is direct-chat only |
| **One-tap language switch** (বাংলা · हिन्दी · EN) on the Market, and protection against browser auto-translate garbling the page | — |

## Architecture

```
Browser (React + TS, PWA)                     FastAPI backend
├─ @nexconn/chat  ── WebSocket ──► Nexconn ◄── Server API (signed: App-Key/Nonce/Timestamp/Signature)
│   NCEngine, DirectChannel, GroupChannel,      ├─ issue access tokens (App Secret stays server-side)
│   MessageHandler, custom ML:* messages        ├─ create/join group channels, bot + system messages
└─ REST /api ────────────────────────────────► ├─ LangGraph agent "Mandi Mitra"
                                                ├─ translation (Gemini / OpenAI-compatible, cached)
                                                ├─ Agmarknet mandi prices (data.gov.in)
                                                └─ listings, deals, tickets, metrics (SQLite/Postgres)
```

Upgrading from v1 is safe: on start-up the backend adds any new database columns automatically.

Every component degrades safely. Without an AI key, the assistant answers from templates in all three languages, and translation falls back to a phrasebook. Without a data.gov.in key, prices come from labelled reference ranges.

---

## Run it locally (5 minutes)

Requirements: Python 3.11+ and Node 18.12+.

```bash
# 1. Backend
cd backend
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                   # then fill in keys (see below)
python -m app.seed                                     # demo accounts + listings
uvicorn app.main:app --reload --port 8000

# 2. Frontend (new terminal)
cd frontend
npm install
npm run dev                                            # http://localhost:5173
```

Or run it as **one server** (what judges will use): build the frontend once, then the backend serves everything at http://localhost:8000:

```bash
cd frontend && npm install && npm run build
cd ../backend && uvicorn app.main:app --port 8000
```

Open **two browser windows**, one normal and one incognito. On the welcome screen use **Try a demo account**: one window as *Farmer (বাংলা)*, the other as *Buyer (English)*. As the buyer, open *Potato* in the Market, then tap **Chat with seller**.

| Demo account | Mobile | PIN |
|---|---|---|
| Farmer, Bengali | 9000000001 | 1234 |
| Buyer, English | 9000000002 | 1234 |
| Trader, Hindi | 9000000003 | 1234 |
| Support agent | 9000000000 | 2468 |

> With no Nexconn keys in `.env`, the app runs in **demo mode**: a yellow banner shows, and chat goes through a local WebSocket stand-in. Use it only to try the UI. **Your submission must run with real Nexconn keys.**

### Go live on Nexconn

1. Sign up free at https://console.nexconn.ai and create an app (Free Chat Plan, no card needed).
2. Copy the **App Key**, **App Secret** and your data center's **API domain** into `backend/.env`:
   ```
   NEXCONN_APP_KEY=...
   NEXCONN_APP_SECRET=...
   NEXCONN_API_HOST=https://api.sg-light-api.com     # use the domain shown in your Console
   ```
3. Restart the backend. `/api/health` should show `"demoMode": false` and the yellow banner disappears.

### Turn on AI (recommended)

Get a free Gemini key at https://aistudio.google.com/apikey and set `LLM_PROVIDER=gemini` and `GEMINI_API_KEY=...`. The default model is `gemini-3.5-flash-lite` (free tier, translates a chat message in about 1.5 s), with automatic fallback to `gemini-flash-lite-latest` if it is slow, retired, rate-limited or down. Both new `AQ.…` and classic `AIza…` keys work. (`gemini-2.0-flash` was shut down on 1 June 2026.) This gives natural translation of any sentence and natural-sounding assistant replies. Any OpenAI-compatible API (OpenAI, Groq) also works with `LLM_PROVIDER=openai`.

### Live mandi prices (optional)

Register at https://data.gov.in, copy your API key and set `DATAGOV_API_KEY`.

### Tests

```bash
cd backend && python -m pytest -q      # 19 tests: auth, deals, AI, escalation, translation, metrics,
                                       # search, receipts, delivery, ratings, smart replies, buyer requests,
                                       # photo upload safety, agent brief
```

---

## Deploy (one URL for judges)

The backend serves the built frontend, so one web service is enough.

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/teamvidyut/mandilink)

**Render:** click the button above (or **New → Blueprint** and select this repo) (`render.yaml` is included). Fill in `NEXCONN_APP_KEY`, `NEXCONN_APP_SECRET`, `GEMINI_API_KEY`, and set **`DATABASE_URL`** to a free Postgres, such as Neon or Supabase. Render's free disk is wiped on every deploy, and you need your user data to survive for traction proof.

Manual alternative on any VM:
```bash
cd frontend && npm ci && npm run build
cd ../backend && pip install -r requirements.txt && python -m app.seed
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Voice input needs **HTTPS**, which Render provides, and works best in Chrome or Android.

## Security notes
- The App Secret and request signing live only on the server. The browser receives a per-user Nexconn access token.
- `.env` is git-ignored. Never commit keys, and never post your App Key or user IDs in public GitHub issues.
- Each user's PIN is hashed with PBKDF2. App sessions use JWT.

## Project layout
```
backend/app/
  nexconn.py     Nexconn Server API client (signing, failover, demo-mode shim)
  agent.py       LangGraph assistant: understand → tools → respond
  translate.py   per-viewer translation with cache
  mandi.py       Agmarknet prices + fairness verdict
  services.py    deals, escalation, bootstrap (bot, agent, rooms)
  lang.py        language detection, crop glossary, number-aware phrasebook, smart replies
  routers/       auth, market (listings, deals, receipts, ratings, photos), requests (Wanted board),
                 chat (smart replies), support (tickets, AI brief, metrics), dev (demo mode)
frontend/src/
  chat/transport.ts   NexconnTransport (Chat SDK) + DemoTransport
  screens/            Welcome, Market, Chats, ChatRoom, Support, Profile, Impact
  components/ui.tsx   RateBand, Ticker, Stepper, TrustBadge, Stars, Sheet, icons
  lib/photo.ts        in-browser photo resize
```
