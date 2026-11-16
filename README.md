# Sadaa (صدا) — Call Centre Agency with Voice AI Agents

A complete call-centre agency platform with professional voice AI agents —
end to end, free to run, no card, no paid service.

- **5 ready voice agents** — Ayesha (Receptionist), Bilal (Sales Qualifier),
  Sara (Appointment Booker), Omar (Support Agent), Hina (Payment Reminder)
- **Real voice calls in the browser** — mic → speech-to-text → agent brain →
  spoken reply, with interruption (barge-in) and turn-taking. Free via the
  Web Speech API; no API key needed.
- **Agency dashboard** — agent list + create/edit, live call board, inbound/
  outbound campaign dialler (simulated dialling), call history with full
  transcripts, call replay via TTS, analytics, CRM lead inbox, supervisor
  tools (listen / whisper / barge-in).
- **Backend** — FastAPI + SQLite, clean REST API for agents, calls, leads,
  tickets, campaigns and analytics.
- **Free inbound calling** — a visitor taps **Call now** on the public page
  (`/call`) and talks to an agent free; WhatsApp call button included.
  See [Free inbound calling](#free-inbound-calling) below.

## Quick start

```bash
git clone https://github.com/zubair0153715/sadaa
cd sadaa
pip install -r requirements.txt   # or use any venv with fastapi + uvicorn
./run.sh
# open http://127.0.0.1:8000
```

Requirements: Python 3.10+, FastAPI, uvicorn. Tests: `pytest tests/ -q`
(35 tests).

## How a call works

```
Caller speaks (mic)
  -> browser SpeechRecognition (free, on-device in Chrome/Edge)
  -> POST /api/calls/{id}/turn
  -> Sadaa engine: intent routing -> slot filling -> tool call
     (book a slot, open a ticket, capture a lead, check a balance…)
  -> reply text -> browser speechSynthesis (free, device voices)
Caller speaks over the agent -> speech is cancelled instantly (barge-in)
```

The engine is scripted intent + tools by default, so bookings, tickets and
payments stay deterministic. An optional Gemini brain (`GEMINI_API_KEY`
environment variable only — never in code) answers turns no scripted intent
matches. Scripted flows always win first.

## The five agents

| Agent | Role | What it does | Tools |
|---|---|---|---|
| **Ayesha** | Receptionist | Greets, routes, takes messages | capture_lead, transfer_human |
| **Bilal** | Sales Qualifier | Qualifies need / budget / timeline, books callbacks | capture_lead, book_callback |
| **Sara** | Appointment Booker | Books, reschedules, cancels — reads every booking back | book_slot, reschedule_booking, cancel_booking |
| **Omar** | Support Agent | Knowledge-base answers, opens tickets with a reference | lookup_faq, create_ticket, transfer_human |
| **Hina** | Payment Reminder | Polite overdue reminders, balance checks, payment promises | check_balance, record_promise, create_ticket |

Each agent has a persona, greeting, voice preference (browser voice name,
rate, pitch), system prompt, scripted intents and a sample dialogue — all
editable in the dashboard or via the API. Create your own agents the same way.

## API (all under `/api`)

| Endpoint | What it does |
|---|---|
| `GET/POST /agents`, `GET/PUT/DELETE /agents/{id}` | Manage voice agents |
| `POST /calls/start`, `POST /calls/{id}/turn`, `POST /calls/{id}/state`, `POST /calls/{id}/end` | Call lifecycle + voice turns |
| `POST /calls/{id}/supervise` (`listen`/`whisper`/`barge`/`resume`), `POST /calls/{id}/supervisor-say` | Supervisor tools |
| `GET /calls`, `GET /calls/{id}` | History + full transcript |
| `GET/POST /leads`, `GET/POST /tickets`, `PATCH /tickets/{id}` | CRM inbox + tickets |
| `GET /slots?date=`, `GET /appointments` | Live diary (next 7 days, 09:00–17:00) |
| `GET/POST /campaigns`, `POST /campaigns/{id}/start`, `GET /campaigns/{id}/next` | Campaign dialler |
| `GET /analytics` | Calls/day, avg duration, resolution rate, CSAT |

## Free inbound calling

**The honest physics first:** a real PSTN call to a Pakistani mobile or
landline (+92…) is never free — someone always pays for the number rental
plus per-minute termination. Anything that claims a free PSTN number is
either a trial, ad-supported, or a different kind of call. Sadaa gives you
the genuinely-free routes:

### 1. WebRTC click-to-call — works free today (recommended)
A visitor opens the public page and taps **Call now**. Their browser mic is
the phone line; the voice agent answers. No account, no number, no cost —
just internet + Chrome/Edge. This is the default inbound route in Sadaa:
the `/call` page.

### 2. WhatsApp call — free, internet only
Customers already call businesses free on WhatsApp. Sadaa's `/call` page has
a WhatsApp call button (wa.me link). WhatsApp Business voice calling via
Meta's API exists but needs business verification and is not a free
do-it-yourself PSTN replacement — the wa.me click-to-call path is the free
part, and it works today.

### 3. Free SIP address — free, internet only (setup needed)
Anyone with a SIP app (e.g. Linphone, free) can dial a SIP address such as
`sip:agent@sadaa.example` free over the internet — no PSTN, no per-minute
charge. A free SIP account is the owner's one-time signup (no card on the
free tiers that offer it); Sadaa's browser client can then answer SIP calls
via JsSIP. Exact provider + address + dial-in steps: see below once the
live SIP account is created.

### What is NOT free (do not be fooled)
- **Google Voice** — US-only, needs US verification; not usable from Pakistan.
- **Twilio trial** — $15 credit and a real number, but trial-limited
  (verified caller numbers only); real usage is paid.
- **TextNow / Fongo** — free US/CA numbers, ad-supported, with limits;
  not a Pakistan business number.
- **Any "free" PSTN number** — if it terminates to a real mobile/landline,
  someone is paying. If nobody is paying, it is not PSTN.

**To go live free:** (1) publish Sadaa's `/call` page and share the link —
works immediately; (2) add the WhatsApp button (already on the page);
(3) create a free SIP account and put the address on the page (owner's
signup step — see `docs/free-sip-setup.md` when added).

## Built on the shoulders of

Sadaa is original, clean-room code — no code copied from any of these
projects. It studies and borrows their *patterns*. Research verified
16 Nov 2026 (stars as fetched that day):

| Project | Stars | Licence | What Sadaa borrows |
|---|---|---|---|
| [Pipecat](https://github.com/pipecat-ai/pipecat) | 17,296 | BSD-2-Clause | The streaming frame pipeline (STT → LLM → TTS) with first-class interruption: a barge-in cancels the running turn. The cleanest, most permissively licensed architecture to mirror. |
| [LiveKit Agents](https://github.com/livekit/agents) | 15,249 | Apache-2.0* | The call-centre shape: a call is a session with a supervisor able to join, and adaptive interruption that distinguishes a real barge-in from a backchannel. Telephony via open-source SIP. |
| [Dograh](https://github.com/dograh-hq/dograh) | 6,156 | BSD-2-Clause | The *product* blueprint: agent builder + campaigns + QA + transcripts + human handoff in one self-hostable platform. Sadaa copies its feature checklist, not its Pipecat fork. |
| [OpenAI Realtime Agents](https://github.com/openai/openai-realtime-agents) | 7,018 | MIT | Two patterns: Chat-Supervisor (fast voice layer, slower model for hard tool work) and Sequential Handoffs (specialist agents handing the caller off). |
| [TEN Framework](https://github.com/TEN-framework/ten-framework) | 11,233 | Apache-2.0 + Agora conditions | The graph/node mental model only — its licence's non-compete clause rules it out as a base for a voice platform business. |
| [Vocode](https://github.com/vocodedev/vocode) | 3,808 | MIT | The pioneer of swappable transcriber/agent/synthesizer components. Dormant since Nov 2024 — read as reference, not a dependency. |
| [Bolna](https://github.com/bolna-ai/bolna) | 828 | MIT | JSON agent definitions and the telephony-first carrier set (Twilio/Plivo/Exotel/SIP). |

\* LiveKit's framework is Apache-2.0, but its turn-detection models are under
a separate LiveKit Model License — free only for use with LiveKit Agents.
Vapi, Retell AI and Bland are proprietary hosted platforms, not open source;
useful only as product benchmarks, never as lineage.

**The single pattern that matters most** (Pipecat + LiveKit converge on it):
a streaming cascaded pipeline — VAD → turn detection → streaming STT →
LLM (+ tools) → streaming TTS — where a user barge-in immediately cancels
TTS and the in-flight tool, and the agent resumes. Turn-end is predicted
from meaning, not a silence timeout, and interruption is a designed state
transition, not an error. That is what separates a production call centre
from a demo. Sadaa implements the same loop with free browser APIs:
the browser is the VAD/STT/TTS, the engine is the pipeline middle.

## Honest limits

- **Browser voice calls work free today.** Real phone numbers need Twilio
  (owner's account + credits) — the app says this in the UI and never
  fakes a PSTN call, a phone number, or a call record.
- **Campaign dialling is simulated** until Twilio is connected: contacts are
  demo labels (`SIM-001…`), not real numbers, and no real call is placed.
- **Call "recordings" are transcripts + TTS replay**, not stored audio.
- **Speech recognition needs Chrome/Edge** (Web Speech API). Other browsers
  get a text box; the agent still answers by voice.
- **Demo data is labelled demo** — sample accounts (`ACC-1001…`) and demo
  contacts exist only so the payment and dialler flows can be tried.
- **No auth on the API** — run it locally or behind your own reverse proxy
  with auth before exposing it to the internet.
- **No fake testimonials, clients or logos** anywhere in the app.

## Tests

```bash
pytest tests/ -q   # 35 tests: engine, API, agent configs — all passing
```

## Licence

MIT. Original code by Lapis for Zubair Ali / Sadaa Call Centre Agency.
