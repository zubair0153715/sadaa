# Free inbound calling — setup guide

How a real person reaches a Sadaa voice agent **without anyone paying
for a phone call**. The physics first: a PSTN call to a Pakistani
mobile/landline (+92…) is never free — someone always pays for the number
plus per-minute termination. Every route below keeps the call on the
internet end-to-end (WebRTC / SIP / WhatsApp VoIP). The caller pays only
for their own internet/data.

Research verified 16–17 Nov 2026. Anything marked "owner's step" needs
Zubair's own account/signup — nothing here asks for a card.

## Door 1 — WebRTC "Call now" page (works today, $0)

**Status: already live in Sadaa.** The public page `/call` has a "Call now —
free" button. A visitor taps it, the browser asks for mic permission, and
they speak to a voice agent. No app, no account, no number, no cost.

How it works: the browser does speech recognition + speech synthesis
(Web Speech API, free, on-device in Chrome/Edge); Sadaa's API is the agent
brain. No server beyond Sadaa itself is needed for this door.

**To go live:** publish Sadaa (any free host that runs FastAPI, or the
local server) and share the `/call` link. Requires HTTPS in production —
browsers block mic access on plain HTTP.

## Door 2 — WhatsApp call button (works today, $0)

**Status: already on the `/call` page.** A wa.me link
(`https://wa.me/923116925020`) opens a WhatsApp chat with Sadaa's number;
the visitor taps the in-app call button for a free VoIP call. Works from
Pakistan right now with a normal Pakistani WhatsApp Business number.

**Upgrade path — WhatsApp Business Calling API (owner's steps):**
1. Set up a Meta Business Account + WhatsApp Business Account (WABA).
2. Register a **Cloud API number** — the WhatsApp Business *app* number
   and "coexistence" numbers do NOT support calling.
3. Switch calling on in the number's settings.
4. Note: BSP write-ups report a messaging-tier gate (~2,000
   business-initiated conversations/24h) before calling can be enabled —
   reported, not directly verified against Meta's page; check at setup.
5. Inbound (user-initiated) calls are **free for both sides** (Meta's
   pricing page). Outbound business-initiated calls are billed per minute;
   a +92 number is NOT on the outbound exclusion list.
6. Terminate inbound calls into Sadaa's agent via WebRTC (Graph API) or
   SIP — e.g. through LiveKit SIP.

## Door 3 — Free SIP address (owner's signup, $0)

For technical callers with a SIP app. Verified options:

### Linphone (recommended for SIP)
1. Install Linphone (free, Android/iOS/desktop).
2. Create account at `subscribe.linphone.org` — username + password + email
   verification. No card.
3. Your address is `username@linphone.org`. Anyone with a SIP app can dial
   `sip:username@linphone.org` free over the internet.
4. Publish the address on Sadaa's `/call` page (replace the placeholder
   in `app/static/call.html`, `id="sip-line"`).
5. To *answer* SIP calls with a voice agent, run a SIP client registered
   to that address on Sadaa's server (e.g. `linphone-cli` / `baresip` or a
   small PJSIP bot) and bridge it into the agent. Do this after Doors 1–2
   work; it is a nice-to-have, not the main path.
6. Caveats: not live-tested from a Pakistani network (no country
   restriction found in docs); a random customer will not have a SIP app,
   so this is a secondary door only.

### Alternatives (verified, with caveats)
- **OnSIP** — official free page still live (`user@company.onsip.com`, up
  to 100 users), but 2026 pricing trackers say the free plan was
  discontinued. Verify at signup: https://www.onsip.com/getonsip
- **Callcentric** — free SIP URI `1777XXXXXXX@in.callcentric.com`; a real
  diallable number costs from ~$2.95/mo.
- **sipgate** — dead end: free tier ended September 2026.

## The LiveKit upgrade path (optional, still $0)

If Sadaa wants true multi-party rooms and a path to PSTN later, the
recommended free platform is **LiveKit Cloud, Build plan ($0, no card)**:
5,000 WebRTC minutes/month + 1,000 agent-session minutes/month + 100
concurrent connections, hard cap (stops, never bills). Re-check the
pricing page before launching — figures come from Nov 2026 pricing
trackers citing LiveKit's page.

1. Create a free LiveKit Cloud account + project; note the API key/secret
   and `wss://<project>.livekit.cloud` URL.
2. Build a Sadaa voice agent with the open-source LiveKit Agents framework
   (Python/Node): STT → LLM → TTS. For $0 inference use free-tier keys
   Sadaa already has (Gemini); LiveKit's own ~$2.50/mo inference credit
   covers only ~50 min.
3. Add a public page with a "Call now — free" button using the
   `livekit-client` JS SDK: on tap, the page fetches a short-lived access
   token from Sadaa's backend (backend mints it with the LiveKit server
   SDK; the secret never reaches the browser), joins a room, and the agent
   joins the same room.
4. Keep one agent instance per caller room.

## What is NOT a free route (do not pursue)

| Option | Verdict |
|---|---|
| Google Voice | US-only, needs US number verification; Pakistan not covered even on paid Workspace (14 countries). |
| Twilio trial | $15 credit, but 10-min call cap, trial message on every call, only verified numbers can call; PK accounts gated on +1 numbers since Oct 2025. Testing only. |
| TextNow / Fongo | North-America-only registration; cannot sign up from Pakistan. |
| Any "free" PSTN number | If it reaches a real mobile/landline, someone pays. If nobody pays, it is not PSTN. |
