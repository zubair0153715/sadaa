# -*- coding: utf-8 -*-
"""Sadaa — REST API.

Agents, calls (with live voice turns), leads, tickets, appointments,
campaigns, analytics. All state lives in SQLite (app/db.py). No auth —
this is a local / single-agency deployment; put it behind your own
reverse proxy with auth before exposing it to the internet.
"""
import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import db, engine
from .gemini import GeminiBrain

router = APIRouter(prefix="/api")
BRAIN = GeminiBrain()


def _agent_out(row):
    a = db.row_to_dict(row)
    for key in ("tools", "intents", "sample_dialogue"):
        try:
            a[key] = json.loads(a.get(key) or "[]")
        except ValueError:
            a[key] = []
    a["voice"] = {"lang": a.pop("voice_lang"), "name": a.pop("voice_name"),
                  "rate": a.pop("voice_rate"), "pitch": a.pop("voice_pitch")}
    return a


def _get_agent(conn, agent_id):
    row = conn.execute("SELECT * FROM agents WHERE id=?", (agent_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Agent not found: %s" % agent_id)
    return _agent_out(row)


def _get_call(conn, call_id):
    row = conn.execute("SELECT * FROM calls WHERE id=?", (call_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Call not found: %s" % call_id)
    return db.row_to_dict(row)


def _turns(conn, call_id):
    return db.rows_to_dicts(conn.execute(
        "SELECT * FROM turns WHERE call_id=? ORDER BY id", (call_id,)).fetchall())


# ---------------------------------------------------------------- models

class AgentIn(BaseModel):
    id: str = ""
    name: str
    role: str = "Agent"
    persona: str = ""
    greeting: str = ""
    voice_lang: str = "en-US"
    voice_name: str = ""
    voice_rate: float = 1.0
    voice_pitch: float = 1.0
    system_prompt: str = ""
    tools: list = Field(default_factory=list)
    intents: list = Field(default_factory=list)
    sample_dialogue: list = Field(default_factory=list)


class CallStart(BaseModel):
    agent_id: str
    direction: str = "inbound"
    contact_name: str = ""
    contact_ref: str = ""


class TurnIn(BaseModel):
    text: str


class CallEnd(BaseModel):
    outcome: str = ""
    csat: int = 0


class StateIn(BaseModel):
    state: str


class SuperviseIn(BaseModel):
    action: str  # listen | whisper | barge | resume
    message: str = ""


class SupervisorSay(BaseModel):
    text: str


class LeadIn(BaseModel):
    name: str
    phone: str = ""
    email: str = ""
    interest: str = ""
    status: str = "new"
    notes: str = ""


class TicketIn(BaseModel):
    subject: str
    description: str = ""
    priority: str = "normal"
    caller_name: str = ""
    call_id: str = ""


class TicketPatch(BaseModel):
    status: str = ""


class CampaignIn(BaseModel):
    name: str
    agent_id: str
    contacts: list = Field(default_factory=list)  # [{ref, name}]


# ---------------------------------------------------------------- meta

@router.get("/health")
def health():
    return {"ok": True, "app": "sadaa", "ai_available": BRAIN.available}


@router.get("/ai-status")
def ai_status():
    return {"ai_available": BRAIN.available,
            "note": "Set GEMINI_API_KEY to enable the optional Gemini brain."}


# ---------------------------------------------------------------- agents

@router.get("/agents")
def list_agents():
    conn = db.connect()
    try:
        return {"ok": True, "agents": [_agent_out(r) for r in conn.execute(
            "SELECT * FROM agents ORDER BY name").fetchall()]}
    finally:
        conn.close()


@router.get("/agents/{agent_id}")
def get_agent(agent_id: str):
    conn = db.connect()
    try:
        return {"ok": True, "agent": _get_agent(conn, agent_id)}
    finally:
        conn.close()


@router.post("/agents")
def create_agent(body: AgentIn):
    agent_id = body.id or body.name.lower().replace(" ", "-")
    conn = db.connect()
    try:
        if conn.execute("SELECT 1 FROM agents WHERE id=?", (agent_id,)).fetchone():
            raise HTTPException(400, "Agent id already exists: %s" % agent_id)
        conn.execute(
            """INSERT INTO agents (id, name, role, persona, greeting, voice_lang,
                voice_name, voice_rate, voice_pitch, system_prompt, tools, intents,
                sample_dialogue, active, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (agent_id, body.name, body.role, body.persona, body.greeting,
             body.voice_lang, body.voice_name, body.voice_rate, body.voice_pitch,
             body.system_prompt, json.dumps(body.tools), json.dumps(body.intents),
             json.dumps(body.sample_dialogue), 1, engine.now_iso()))
        conn.commit()
        return {"ok": True, "agent": _get_agent(conn, agent_id)}
    finally:
        conn.close()


@router.put("/agents/{agent_id}")
def update_agent(agent_id: str, body: AgentIn):
    conn = db.connect()
    try:
        _get_agent(conn, agent_id)
        conn.execute(
            """UPDATE agents SET name=?, role=?, persona=?, greeting=?,
                voice_lang=?, voice_name=?, voice_rate=?, voice_pitch=?,
                system_prompt=?, tools=?, intents=?, sample_dialogue=?
               WHERE id=?""",
            (body.name, body.role, body.persona, body.greeting,
             body.voice_lang, body.voice_name, body.voice_rate, body.voice_pitch,
             body.system_prompt, json.dumps(body.tools), json.dumps(body.intents),
             json.dumps(body.sample_dialogue), agent_id))
        conn.commit()
        return {"ok": True, "agent": _get_agent(conn, agent_id)}
    finally:
        conn.close()


@router.delete("/agents/{agent_id}")
def delete_agent(agent_id: str):
    conn = db.connect()
    try:
        _get_agent(conn, agent_id)
        conn.execute("UPDATE agents SET active=0 WHERE id=?", (agent_id,))
        conn.commit()
        return {"ok": True, "deleted": agent_id}
    finally:
        conn.close()


# ---------------------------------------------------------------- calls

@router.post("/calls/start")
def start_call(body: CallStart):
    conn = db.connect()
    try:
        agent = _get_agent(conn, body.agent_id)
        call_id = uuid.uuid4().hex[:12]
        conn.execute(
            """INSERT INTO calls (id, agent_id, direction, contact_name,
                contact_ref, state, started_at) VALUES (?,?,?,?,?,?,?)""",
            (call_id, body.agent_id, body.direction, body.contact_name,
             body.contact_ref, "RINGING", engine.now_iso()))
        conn.commit()
        return {"ok": True, "call_id": call_id, "state": "RINGING",
                "greeting": agent["greeting"], "agent": agent}
    finally:
        conn.close()


@router.get("/calls")
def list_calls(limit: int = 50):
    conn = db.connect()
    try:
        calls = db.rows_to_dicts(conn.execute(
            "SELECT * FROM calls ORDER BY started_at DESC LIMIT ?", (limit,)).fetchall())
        return {"ok": True, "calls": calls}
    finally:
        conn.close()


@router.get("/calls/{call_id}")
def get_call(call_id: str):
    conn = db.connect()
    try:
        call = _get_call(conn, call_id)
        call["turns"] = _turns(conn, call_id)
        call["agent"] = _get_agent(conn, call["agent_id"])
        call["supervisor_events"] = db.rows_to_dicts(conn.execute(
            "SELECT * FROM supervisor_events WHERE call_id=? ORDER BY id",
            (call_id,)).fetchall())
        return {"ok": True, "call": call}
    finally:
        conn.close()


@router.post("/calls/{call_id}/turn")
def call_turn(call_id: str, body: TurnIn):
    conn = db.connect()
    try:
        call = _get_call(conn, call_id)
        if call["state"] != "ACTIVE":
            raise HTTPException(400, "Call is not active (state=%s)." % call["state"])
        agent = _get_agent(conn, call["agent_id"])
        brain = BRAIN if BRAIN.available else None
        result = engine.handle_turn(conn, call, agent, body.text, gemini=brain)
        conn.commit()
        call = _get_call(conn, call_id)
        result.update({"ok": True, "call_id": call_id, "state": call["state"]})
        return result
    finally:
        conn.close()


@router.post("/calls/{call_id}/state")
def call_state(call_id: str, body: StateIn):
    conn = db.connect()
    try:
        call = _get_call(conn, call_id)
        ok, msg = engine.transition(conn, call, body.state.upper())
        if not ok:
            raise HTTPException(400, msg)
        conn.commit()
        return {"ok": True, "state": body.state.upper()}
    finally:
        conn.close()


@router.post("/calls/{call_id}/end")
def end_call(call_id: str, body: CallEnd):
    conn = db.connect()
    try:
        call = _get_call(conn, call_id)
        if call["state"] != "ENDED":
            ok, msg = engine.transition(conn, call, "ENDED")
            if not ok:
                raise HTTPException(400, msg)
        started = datetime.fromisoformat(call["started_at"])
        ended = datetime.now(timezone.utc)
        duration = max(0, int((ended - started).total_seconds()))
        conn.execute(
            "UPDATE calls SET ended_at=?, duration_sec=?, outcome=?, csat=? WHERE id=?",
            (ended.isoformat(), duration, body.outcome,
             body.csat if body.csat else None, call_id))
        conn.commit()
        return {"ok": True, "call_id": call_id, "duration_sec": duration}
    finally:
        conn.close()


@router.post("/calls/{call_id}/supervise")
def supervise(call_id: str, body: SuperviseIn):
    conn = db.connect()
    try:
        call = _get_call(conn, call_id)
        action = body.action.lower()
        if action not in ("listen", "whisper", "barge", "resume"):
            raise HTTPException(400, "Unknown supervisor action: %s" % action)
        conn.execute(
            "INSERT INTO supervisor_events (call_id, action, message, created_at) "
            "VALUES (?,?,?,?)", (call_id, action, body.message, engine.now_iso()))
        if action == "barge":
            conn.execute("UPDATE calls SET supervisor_active=1 WHERE id=?", (call_id,))
        if action == "resume":
            conn.execute("UPDATE calls SET supervisor_active=0 WHERE id=?", (call_id,))
        conn.commit()
        return {"ok": True, "action": action}
    finally:
        conn.close()


@router.post("/calls/{call_id}/supervisor-say")
def supervisor_say(call_id: str, body: SupervisorSay):
    """Supervisor speaking as the agent while barged in."""
    conn = db.connect()
    try:
        call = _get_call(conn, call_id)
        if not call.get("supervisor_active"):
            raise HTTPException(400, "Supervisor has not barged in on this call.")
        engine._add_turn(conn, call_id, "agent", body.text)
        conn.execute(
            "INSERT INTO supervisor_events (call_id, action, message, created_at) "
            "VALUES (?,?,?,?)", (call_id, "say", body.text, engine.now_iso()))
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


# ---------------------------------------------------------------- leads/tickets

@router.get("/leads")
def list_leads(status: str = ""):
    conn = db.connect()
    try:
        q = "SELECT * FROM leads"
        args = []
        if status:
            q += " WHERE status=?"
            args.append(status)
        q += " ORDER BY created_at DESC LIMIT 200"
        return {"ok": True, "leads": db.rows_to_dicts(conn.execute(q, args).fetchall())}
    finally:
        conn.close()


@router.post("/leads")
def create_lead(body: LeadIn):
    conn = db.connect()
    try:
        cur = conn.execute(
            "INSERT INTO leads (name, phone, email, interest, source, status, notes, created_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (body.name, body.phone, body.email, body.interest, "manual",
             body.status, body.notes, engine.now_iso()))
        conn.commit()
        return {"ok": True, "lead_id": cur.lastrowid}
    finally:
        conn.close()


@router.get("/tickets")
def list_tickets(status: str = ""):
    conn = db.connect()
    try:
        q = "SELECT * FROM tickets"
        args = []
        if status:
            q += " WHERE status=?"
            args.append(status)
        q += " ORDER BY created_at DESC LIMIT 200"
        return {"ok": True, "tickets": db.rows_to_dicts(conn.execute(q, args).fetchall())}
    finally:
        conn.close()


@router.post("/tickets")
def create_ticket(body: TicketIn):
    conn = db.connect()
    try:
        cur = conn.execute(
            "INSERT INTO tickets (subject, description, priority, caller_name, call_id, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (body.subject, body.description, body.priority,
             body.caller_name, body.call_id, engine.now_iso()))
        conn.commit()
        return {"ok": True, "ticket_id": cur.lastrowid,
                "ticket_ref": "TKT-%04d" % cur.lastrowid}
    finally:
        conn.close()


@router.patch("/tickets/{ticket_id}")
def patch_ticket(ticket_id: int, body: TicketPatch):
    conn = db.connect()
    try:
        if body.status:
            conn.execute("UPDATE tickets SET status=? WHERE id=?",
                         (body.status, ticket_id))
            conn.commit()
        return {"ok": True}
    finally:
        conn.close()


# ---------------------------------------------------------------- diary

@router.get("/slots")
def list_slots(date: str):
    conn = db.connect()
    try:
        rows = conn.execute("SELECT * FROM slots WHERE date=? ORDER BY time",
                            (date,)).fetchall()
        return {"ok": True, "date": date,
                "slots": db.rows_to_dicts(rows)}
    finally:
        conn.close()


@router.get("/appointments")
def list_appointments(date: str = ""):
    conn = db.connect()
    try:
        q = "SELECT * FROM appointments"
        args = []
        if date:
            q += " WHERE date=?"
            args.append(date)
        q += " ORDER BY date, time LIMIT 200"
        return {"ok": True, "appointments": db.rows_to_dicts(conn.execute(q, args).fetchall())}
    finally:
        conn.close()


# ---------------------------------------------------------------- campaigns

@router.get("/campaigns")
def list_campaigns():
    conn = db.connect()
    try:
        camps = db.rows_to_dicts(conn.execute(
            "SELECT * FROM campaigns ORDER BY created_at DESC").fetchall())
        for c in camps:
            c["contacts"] = db.rows_to_dicts(conn.execute(
                "SELECT * FROM campaign_contacts WHERE campaign_id=? ORDER BY id",
                (c["id"],)).fetchall())
        return {"ok": True, "campaigns": camps}
    finally:
        conn.close()


@router.post("/campaigns")
def create_campaign(body: CampaignIn):
    conn = db.connect()
    try:
        _get_agent(conn, body.agent_id)
        cur = conn.execute(
            "INSERT INTO campaigns (name, agent_id, status, created_at) VALUES (?,?,?,?)",
            (body.name, body.agent_id, "draft", engine.now_iso()))
        camp_id = cur.lastrowid
        for c in body.contacts:
            conn.execute(
                "INSERT INTO campaign_contacts (campaign_id, ref, name) VALUES (?,?,?)",
                (camp_id, c.get("ref", ""), c.get("name", "Demo contact")))
        conn.commit()
        return {"ok": True, "campaign_id": camp_id}
    finally:
        conn.close()


@router.post("/campaigns/{campaign_id}/start")
def start_campaign(campaign_id: int):
    conn = db.connect()
    try:
        conn.execute("UPDATE campaigns SET status='active' WHERE id=?", (campaign_id,))
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


@router.get("/campaigns/{campaign_id}/next")
def next_contact(campaign_id: int):
    """Next pending contact for the dialer. Simulated dialling only — the
    ref is a demo label, never a real phone number."""
    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT * FROM campaign_contacts WHERE campaign_id=? AND status='pending' "
            "ORDER BY id LIMIT 1", (campaign_id,)).fetchone()
        if row is None:
            return {"ok": True, "done": True}
        conn.execute("UPDATE campaign_contacts SET status='dialling' WHERE id=?",
                     (row["id"],))
        conn.commit()
        return {"ok": True, "done": False, "contact": db.row_to_dict(row)}
    finally:
        conn.close()


@router.patch("/campaigns/{campaign_id}/contacts/{contact_id}")
def patch_contact(campaign_id: int, contact_id: int, body: dict):
    conn = db.connect()
    try:
        status = body.get("status", "")
        call_id = body.get("call_id", "")
        if status:
            conn.execute(
                "UPDATE campaign_contacts SET status=?, call_id=? WHERE id=? AND campaign_id=?",
                (status, call_id, contact_id, campaign_id))
            conn.commit()
        return {"ok": True}
    finally:
        conn.close()


# ---------------------------------------------------------------- analytics

@router.get("/analytics")
def analytics():
    conn = db.connect()
    try:
        total = conn.execute("SELECT COUNT(*) FROM calls").fetchone()[0]
        ended = conn.execute("SELECT COUNT(*) FROM calls WHERE state='ENDED'").fetchone()[0]
        resolved = conn.execute(
            "SELECT COUNT(*) FROM calls WHERE outcome='resolved'").fetchone()[0]
        avg_dur = conn.execute(
            "SELECT AVG(duration_sec) FROM calls WHERE state='ENDED'").fetchone()[0]
        csat = conn.execute(
            "SELECT AVG(csat) FROM calls WHERE csat IS NOT NULL").fetchone()[0]
        per_day = db.rows_to_dicts(conn.execute(
            "SELECT substr(started_at,1,10) AS day, COUNT(*) AS n FROM calls "
            "GROUP BY day ORDER BY day DESC LIMIT 7").fetchall())
        per_agent = db.rows_to_dicts(conn.execute(
            "SELECT agent_id, COUNT(*) AS n FROM calls GROUP BY agent_id").fetchall())
        return {"ok": True, "total_calls": total, "ended_calls": ended,
                "resolved": resolved,
                "resolution_rate": (resolved / ended) if ended else 0,
                "avg_duration_sec": round(avg_dur or 0, 1),
                "avg_csat": round(csat, 2) if csat else None,
                "calls_per_day": per_day, "calls_per_agent": per_agent,
                "open_tickets": conn.execute(
                    "SELECT COUNT(*) FROM tickets WHERE status='open'").fetchone()[0],
                "leads_new": conn.execute(
                    "SELECT COUNT(*) FROM leads WHERE status='new'").fetchone()[0]}
    finally:
        conn.close()
