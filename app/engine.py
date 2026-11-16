# -*- coding: utf-8 -*-
"""Sadaa — voice agent engine.

The conversation loop, borrowed (clean-room) from the pattern Pipecat and
LiveKit converge on: VAD/turn detection -> STT -> intent + tools -> TTS.
In Sadaa the browser does VAD/STT/TTS for free (Web Speech API); this
module is the middle of the pipeline: intent routing, a slot-filling state
machine, and tool calls against the app's own SQLite data.

Interruption: the browser cancels speechSynthesis the moment the caller
speaks (barge-in). Server-side, a turn arriving while the agent is
"speaking" simply starts a new turn — no partial state is kept, so a
barge-in can never corrupt a booking.

Call states: QUEUED -> RINGING -> ACTIVE -> HOLD <-> ACTIVE -> ENDED.
"""
import json
import re
from datetime import date, datetime, time as dtime, timedelta, timezone

from . import db

ALLOWED_TRANSITIONS = {
    "QUEUED": {"RINGING", "ENDED"},
    "RINGING": {"ACTIVE", "ENDED"},
    "ACTIVE": {"HOLD", "ENDED"},
    "HOLD": {"ACTIVE", "ENDED"},
    "ENDED": set(),
}

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday",
            "saturday", "sunday"]
MONTHS = {"jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3,
          "march": 3, "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6,
          "jul": 7, "july": 7, "aug": 8, "august": 8, "sep": 9,
          "september": 9, "oct": 10, "october": 10, "nov": 11,
          "november": 11, "dec": 12, "december": 12}


def now_iso():
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------- dates/times

def parse_date(text):
    """Parse 'tomorrow', 'monday', '12 Dec', '2026-11-20' -> ISO date or None."""
    t = text.lower()
    today = date.today()
    if "today" in t:
        return today.isoformat()
    if "tomorrow" in t:
        return (today + timedelta(days=1)).isoformat()
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", t)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
        except ValueError:
            return None
    m = re.search(r"(\d{1,2})(?:st|nd|rd|th)?\s+([a-z]+)", t)
    if m and m.group(2) in MONTHS:
        year = today.year
        try:
            d = date(year, MONTHS[m.group(2)], int(m.group(1)))
        except ValueError:
            return None
        if d < today:
            d = date(year + 1, MONTHS[m.group(2)], int(m.group(1)))
        return d.isoformat()
    for i, wd in enumerate(WEEKDAYS):
        if wd in t:
            delta = (i - today.weekday()) % 7 or 7
            return (today + timedelta(days=delta)).isoformat()
    return None


def parse_time(text):
    """Parse '10', '10am', '10:30', '2 pm', '14:00' -> 'HH:MM' or None."""
    t = text.lower().strip()
    m = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", t)
    if not m:
        return None
    hour = int(m.group(1))
    minute = int(m.group(2) or 0)
    ampm = m.group(3)
    if ampm == "pm" and hour < 12:
        hour += 12
    if ampm == "am" and hour == 12:
        hour = 0
    if hour > 23 or minute > 59:
        return None
    return "%02d:%02d" % (hour, minute)


def extract_slot(key, text):
    """Extract one slot value from free caller speech."""
    if key == "date":
        return parse_date(text)
    if key == "time":
        return parse_time(text)
    if key == "phone":
        m = re.search(r"(\+?\d[\d\s\-]{6,}\d)", text)
        return m.group(1).strip() if m else None
    if key == "email":
        m = re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", text)
        return m.group(0) if m else None
    if key == "ref":
        m = re.search(r"(acc[-\s]?\d+)", text, re.I)
        return m.group(1).upper().replace(" ", "") if m else None
    # name / message / subject / interest / pay_date: take the words as given,
    # stripping common filler.
    cleaned = re.sub(r"^(my name is|i am|i'm|it's|it is|my|the|a|an)\s+", "",
                     text.strip(), flags=re.I)
    cleaned = re.sub(r"\s*(please|thank you|thanks)\s*$", "", cleaned, flags=re.I)
    if key == "pay_date":
        return parse_date(text) or (cleaned or None)
    return cleaned or None


# ---------------------------------------------------------------- intents

def match_intent(agent, text):
    for intent in agent.get("intents", []):
        for pat in intent.get("patterns", []):
            if re.search(pat, text, re.I):
                return intent
    return None


def _ctx(call):
    try:
        return json.loads(call.get("context") or "{}")
    except (ValueError, TypeError):
        return {}


def _save_ctx(conn, call_id, ctx):
    conn.execute("UPDATE calls SET context=? WHERE id=?",
                 (json.dumps(ctx), call_id))


def _add_turn(conn, call_id, speaker, text):
    conn.execute("INSERT INTO turns (call_id, speaker, text, created_at) "
                 "VALUES (?,?,?,?)", (call_id, speaker, text, now_iso()))


# ---------------------------------------------------------------- tools

def run_tool(conn, call, tool_name, args):
    """Dispatch a tool call. Returns (ok, result_string)."""
    fn = TOOLS.get(tool_name)
    if fn is None:
        return False, "Sorry, that action isn't available right now."
    try:
        return fn(conn, call, args)
    except Exception as exc:  # tools must never crash a live call
        return False, "Sorry — something went wrong with that step (%s)." % exc


def _tool_book_slot(conn, call, args):
    d, t, name = args.get("date"), args.get("time"), args.get("name")
    if not (d and t and name):
        return False, "I still need the date, time and name to book."
    row = conn.execute("SELECT status FROM slots WHERE date=? AND time=?",
                       (d, t)).fetchone()
    if row is None:
        return False, ("Sorry, %s at %s is outside our hours — we're open "
                       "9 AM to 5 PM. Could you pick another time?" % (d, t))
    if row["status"] != "free":
        nxt = conn.execute(
            "SELECT time FROM slots WHERE date=? AND status='free' "
            "ORDER BY time LIMIT 1", (d,)).fetchone()
        alt = (" The nearest free slot that day is %s." % nxt["time"]) if nxt else ""
        return False, "Sorry, %s at %s is already taken.%s" % (d, t, alt)
    cur = conn.execute(
        "INSERT INTO appointments (date, time, name, service, call_id, created_at) "
        "VALUES (?,?,?,?,?,?)",
        (d, t, name, args.get("service", ""), call["id"], now_iso()))
    conn.execute("UPDATE slots SET status='booked', appointment_id=? "
                 "WHERE date=? AND time=?", (cur.lastrowid, d, t))
    return True, "Booked: %s at %s for %s." % (d, t, name)


def _tool_reschedule(conn, call, args):
    name, d, t = args.get("name"), args.get("date"), args.get("time")
    appt = conn.execute(
        "SELECT * FROM appointments WHERE name=? AND status='booked' "
        "ORDER BY date DESC LIMIT 1", (name,)).fetchone()
    if appt is None:
        return False, "I couldn't find a booking under %s." % name
    row = conn.execute("SELECT status FROM slots WHERE date=? AND time=?",
                       (d, t)).fetchone()
    if row is None or row["status"] != "free":
        return False, "Sorry, %s at %s isn't free. Could you pick another time?" % (d, t)
    conn.execute("UPDATE slots SET status='free', appointment_id=NULL "
                 "WHERE date=? AND time=?", (appt["date"], appt["time"]))
    conn.execute("UPDATE appointments SET date=?, time=? WHERE id=?",
                 (d, t, appt["id"]))
    conn.execute("UPDATE slots SET status='booked', appointment_id=? "
                 "WHERE date=? AND time=?", (appt["id"], d, t))
    return True, "Moved to %s at %s." % (d, t)


def _tool_cancel(conn, call, args):
    name, d = args.get("name"), args.get("date")
    appt = conn.execute(
        "SELECT * FROM appointments WHERE name=? AND status='booked' "
        "AND (? IS NULL OR date=?) ORDER BY date DESC LIMIT 1",
        (name, d, d)).fetchone()
    if appt is None:
        return False, "I couldn't find a booking under %s." % name
    conn.execute("UPDATE appointments SET status='cancelled' WHERE id=?",
                 (appt["id"],))
    conn.execute("UPDATE slots SET status='free', appointment_id=NULL "
                 "WHERE date=? AND time=?", (appt["date"], appt["time"]))
    return True, "Cancelled the appointment on %s." % appt["date"]


def _tool_create_ticket(conn, call, args):
    subject = args.get("subject") or "Support request"
    cur = conn.execute(
        "INSERT INTO tickets (subject, description, priority, caller_name, call_id, created_at) "
        "VALUES (?,?,?,?,?,?)",
        (subject, args.get("description", ""), args.get("priority", "normal"),
         args.get("name", call.get("contact_name", "")), call["id"], now_iso()))
    return True, "TKT-%04d" % cur.lastrowid


def _tool_capture_lead(conn, call, args):
    conn.execute(
        "INSERT INTO leads (name, phone, email, interest, source, notes, created_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (args.get("name", call.get("contact_name", "") or "Unknown caller"),
         args.get("phone", ""), args.get("email", ""),
         args.get("interest", args.get("message", "")), "call",
         args.get("message", ""), now_iso()))
    return True, "Lead saved."


def _tool_book_callback(conn, call, args):
    return _tool_capture_lead(conn, call, dict(args, interest="Callback requested: " + str(args.get("interest", ""))))


def _tool_lookup_faq(conn, call, args):
    q = (args.get("keywords") or args.get("question") or "").lower()
    words = [w for w in re.findall(r"[a-z]+", q) if len(w) > 2]
    best, best_score = None, 0
    for row in conn.execute("SELECT * FROM faqs").fetchall():
        hay = (row["question"] + " " + row["keywords"]).lower()
        score = sum(1 for w in words if w in hay)
        if score > best_score:
            best, best_score = row, score
    if best is None:
        return False, ("I don't have an answer for that in our knowledge base — "
                       "shall I open a ticket so a human can follow up?")
    return True, best["answer"]


def _tool_check_balance(conn, call, args):
    ref = (args.get("ref") or "").upper()
    row = conn.execute("SELECT * FROM accounts WHERE ref=?", (ref,)).fetchone()
    if row is None:
        return False, ("I couldn't find account %s. Could you check the "
                       "reference — it starts with ACC?" % ref)
    return True, ("Your outstanding balance on account %s is Rs %.0f, due on %s. "
                  "You can pay by bank transfer or JazzCash, or I can record a "
                  "payment date for you." % (ref, row["balance"], row["due_date"]))


def _tool_record_promise(conn, call, args):
    ref, pay_date = (args.get("ref") or "").upper(), args.get("pay_date")
    row = conn.execute("SELECT * FROM accounts WHERE ref=?", (ref,)).fetchone()
    if row is None:
        return False, "I couldn't find account %s — could you check the reference?" % ref
    conn.execute(
        "INSERT INTO leads (name, phone, email, interest, source, notes, created_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (row["name"], "", "", "Payment promise",
         "call", "Promised to pay account %s by %s." % (ref, pay_date), now_iso()))
    return True, "Promise recorded."


def _tool_transfer_human(conn, call, args):
    conn.execute("UPDATE calls SET handoff=1 WHERE id=?", (call["id"],))
    return True, "Transferring to a human agent."


TOOLS = {
    "book_slot": _tool_book_slot,
    "reschedule_booking": _tool_reschedule,
    "cancel_booking": _tool_cancel,
    "create_ticket": _tool_create_ticket,
    "capture_lead": _tool_capture_lead,
    "book_callback": _tool_book_callback,
    "lookup_faq": _tool_lookup_faq,
    "check_balance": _tool_check_balance,
    "record_promise": _tool_record_promise,
    "transfer_human": _tool_transfer_human,
}


# ---------------------------------------------------------------- turns

def transition(conn, call, new_state):
    if new_state not in ALLOWED_TRANSITIONS.get(call["state"], set()):
        return False, "Cannot move call from %s to %s." % (call["state"], new_state)
    conn.execute("UPDATE calls SET state=? WHERE id=?", (new_state, call["id"]))
    return True, new_state


def handle_turn(conn, call, agent, text, gemini=None):
    """Process one caller utterance. Returns a dict for the API.

    The reply is scripted intent + tool driven. If no intent matches and a
    Gemini brain is configured, the brain answers; otherwise a polite
    fallback asks the caller to rephrase.
    """
    _add_turn(conn, call["id"], "caller", text)
    ctx = _ctx(call)

    if call.get("supervisor_active"):
        # Supervisor has taken over (barge-in): the agent stays silent.
        return {"reply": None, "mode": "supervisor",
                "note": "Supervisor has taken over this call."}

    reply, end_call, tool_calls = None, False, []
    intent = None
    if ctx.get("intent"):
        intent = next((i for i in agent.get("intents", [])
                       if i["name"] == ctx["intent"]), None)

    if intent and intent.get("slots"):
        slots = ctx.setdefault("slots", {})
        missing = [s for s in intent["slots"] if s["key"] not in slots]
        if missing:
            slot = missing[0]
            value = extract_slot(slot["key"], text)
            if value:
                slots[slot["key"]] = value
                missing = missing[1:]
            else:
                reply = ("Sorry, I didn't catch that. " + slot["prompt"])
                _save_ctx(conn, call["id"], ctx)
                _add_turn(conn, call["id"], "agent", reply)
                return {"reply": reply, "end_call": False, "tool_calls": []}
            if missing:
                reply = missing[0]["prompt"]
                _save_ctx(conn, call["id"], ctx)
                _add_turn(conn, call["id"], "agent", reply)
                return {"reply": reply, "end_call": False, "tool_calls": []}
            # all slots filled -> run the tool
            ok, result = run_tool(conn, call, intent.get("tool", ""), slots)
            tool_calls.append({"tool": intent.get("tool", ""), "ok": ok,
                               "result": result})
            if ok:
                confirm = intent.get("confirm", "{tool_result}")
                reply = confirm.format(tool_result=result, **slots)
            else:
                # Never read out a success confirmation for a failed tool.
                reply = result
            end_call = bool(intent.get("end_call"))
            ctx = {}
            _save_ctx(conn, call["id"], ctx)
            _add_turn(conn, call["id"], "agent", reply)
            if tool_calls:
                _add_turn(conn, call["id"], "tool",
                          "%s -> %s" % (tool_calls[0]["tool"], result))
            return {"reply": reply, "end_call": end_call, "tool_calls": tool_calls}

    if intent is None:
        intent = match_intent(agent, text)

    if intent is not None:
        if intent.get("slots"):
            ctx = {"intent": intent["name"], "slots": {}}
            reply = intent["slots"][0]["prompt"]
            _save_ctx(conn, call["id"], ctx)
        elif intent.get("tool"):
            args = dict(intent.get("tool_args") or {})
            args.setdefault("question", text)
            ok, result = run_tool(conn, call, intent["tool"], args)
            tool_calls.append({"tool": intent["tool"], "ok": ok, "result": result})
            reply = (intent.get("confirm") or "{tool_result}").format(
                tool_result=result, **args)
            end_call = bool(intent.get("end_call"))
            if intent["tool"] == "transfer_human":
                conn.execute("UPDATE calls SET handoff=1 WHERE id=?", (call["id"],))
        else:
            reply = intent.get("reply", "")
            end_call = bool(intent.get("end_call"))
        _add_turn(conn, call["id"], "agent", reply)
        if tool_calls:
            _add_turn(conn, call["id"], "tool",
                      "%s -> %s" % (tool_calls[0]["tool"], tool_calls[0]["result"]))
        return {"reply": reply, "end_call": end_call, "tool_calls": tool_calls}

    # No scripted intent matched.
    if gemini is not None:
        reply = gemini.reply(agent, call, text)
        if reply:
            _add_turn(conn, call["id"], "agent", reply)
            return {"reply": reply, "end_call": False, "tool_calls": []}
    reply = ("I'm sorry, I didn't quite catch that. Could you say it in a "
             "different way — or say 'human' and I'll transfer you to a "
             "person on the team.")
    _add_turn(conn, call["id"], "agent", reply)
    return {"reply": reply, "end_call": False, "tool_calls": []}
