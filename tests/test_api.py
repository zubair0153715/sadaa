# -*- coding: utf-8 -*-
"""API tests: agents CRUD, full call lifecycle, leads, tickets, campaigns."""
from datetime import date, timedelta

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_pages_load():
    assert client.get("/").status_code == 200
    assert b"Sadaa" in client.get("/").content
    assert client.get("/call").status_code == 200
    assert b"Call now" in client.get("/call").content
    assert client.get("/static/voice.js").status_code == 200
    assert client.get("/static/app.js").status_code == 200


def test_health_and_ai_status():
    assert client.get("/api/health").json()["ok"] is True
    assert "ai_available" in client.get("/api/ai-status").json()


def test_agents_seed_five():
    d = client.get("/api/agents").json()
    assert d["ok"] is True
    ids = {a["id"] for a in d["agents"]}
    assert ids == {"receptionist", "sales", "booker", "support", "payments"}


def test_agent_crud():
    body = {"name": "Test Agent", "role": "Tester", "persona": "test",
            "greeting": "Hi", "system_prompt": "Be helpful.", "tools": []}
    created = client.post("/api/agents", json=body).json()
    assert created["ok"] is True
    aid = created["agent"]["id"]
    assert client.get("/api/agents/" + aid).json()["agent"]["name"] == "Test Agent"
    body["name"] = "Test Agent 2"
    assert client.put("/api/agents/" + aid, json=body).json()["agent"]["name"] == "Test Agent 2"
    assert client.delete("/api/agents/" + aid).json()["ok"] is True


def _book_a_call():
    start = client.post("/api/calls/start", json={
        "agent_id": "booker", "direction": "inbound", "contact_name": "API User"}).json()
    assert start["ok"] is True and start["state"] == "RINGING"
    call_id = start["call_id"]
    # turn while ringing must fail
    bad = client.post("/api/calls/%s/turn" % call_id, json={"text": "hello"})
    assert bad.status_code == 400
    assert client.post("/api/calls/%s/state" % call_id, json={"state": "ACTIVE"}).json()["ok"] is True
    return call_id


def test_call_lifecycle_booking():
    call_id = _book_a_call()
    r1 = client.post("/api/calls/%s/turn" % call_id, json={"text": "I want to book an appointment"}).json()
    assert "day" in r1["reply"].lower()
    r2 = client.post("/api/calls/%s/turn" % call_id, json={"text": "tomorrow"}).json()
    assert "time" in r2["reply"].lower()
    r3 = client.post("/api/calls/%s/turn" % call_id, json={"text": "11am"}).json()
    assert "name" in r3["reply"].lower()
    r4 = client.post("/api/calls/%s/turn" % call_id, json={"text": "API User"}).json()
    assert r4["tool_calls"] and r4["tool_calls"][0]["ok"] is True
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    appts = client.get("/api/appointments?date=" + tomorrow).json()["appointments"]
    assert any(a["name"] == "API User" for a in appts)
    end = client.post("/api/calls/%s/end" % call_id, json={"outcome": "resolved", "csat": 5}).json()
    assert end["ok"] is True and end["duration_sec"] >= 0
    detail = client.get("/api/calls/" + call_id).json()["call"]
    assert detail["state"] == "ENDED"
    assert detail["outcome"] == "resolved"
    assert len(detail["turns"]) >= 8  # caller + agent + tool turns


def test_call_history_and_analytics():
    call_id = _book_a_call()
    client.post("/api/calls/%s/end" % call_id, json={"outcome": "resolved", "csat": 4})
    calls = client.get("/api/calls").json()["calls"]
    assert len(calls) >= 1
    a = client.get("/api/analytics").json()
    assert a["total_calls"] >= 1
    assert a["resolution_rate"] >= 0
    assert a["avg_csat"] is not None


def test_supervisor_flow():
    call_id = _book_a_call()
    assert client.post("/api/calls/%s/supervise" % call_id,
                       json={"action": "whisper", "message": "Offer a discount"}).json()["ok"] is True
    assert client.post("/api/calls/%s/supervise" % call_id,
                       json={"action": "barge"}).json()["ok"] is True
    # agent is silent while barged in
    r = client.post("/api/calls/%s/turn" % call_id, json={"text": "hello"}).json()
    assert r["mode"] == "supervisor"
    assert client.post("/api/calls/%s/supervisor-say" % call_id,
                       json={"text": "Hello, this is the supervisor speaking."}).json()["ok"] is True
    assert client.post("/api/calls/%s/supervise" % call_id,
                       json={"action": "resume"}).json()["ok"] is True
    r = client.post("/api/calls/%s/turn" % call_id, json={"text": "goodbye"}).json()
    assert r.get("reply")
    client.post("/api/calls/%s/end" % call_id, json={"outcome": "resolved", "csat": 5})


def test_leads_and_tickets():
    lead = client.post("/api/leads", json={
        "name": "API Lead", "phone": "03001234567", "interest": "inbound support"}).json()
    assert lead["ok"] is True
    leads = client.get("/api/leads").json()["leads"]
    assert any(l["name"] == "API Lead" for l in leads)
    tick = client.post("/api/tickets", json={
        "subject": "API ticket", "caller_name": "API Lead"}).json()
    assert tick["ok"] is True and tick["ticket_ref"].startswith("TKT-")
    assert client.patch("/api/tickets/%d" % tick["ticket_id"],
                        json={"status": "closed"}).json()["ok"] is True
    tickets = client.get("/api/tickets?status=closed").json()["tickets"]
    assert any(t["id"] == tick["ticket_id"] for t in tickets)


def test_slots_seeded():
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    d = client.get("/api/slots?date=" + tomorrow).json()
    assert d["ok"] is True
    assert len(d["slots"]) == 9  # 09:00..17:00
    assert all(s["status"] == "free" for s in d["slots"])


def test_campaign_flow():
    created = client.post("/api/campaigns", json={
        "name": "Test campaign", "agent_id": "sales",
        "contacts": [{"ref": "SIM-001", "name": "Demo One"},
                     {"ref": "SIM-002", "name": "Demo Two"}]}).json()
    assert created["ok"] is True
    camp_id = created["campaign_id"]
    assert client.post("/api/campaigns/%d/start" % camp_id).json()["ok"] is True
    nxt = client.get("/api/campaigns/%d/next" % camp_id).json()
    assert nxt["done"] is False and nxt["contact"]["name"] == "Demo One"
    nxt2 = client.get("/api/campaigns/%d/next" % camp_id).json()
    assert nxt2["contact"]["name"] == "Demo Two"
    nxt3 = client.get("/api/campaigns/%d/next" % camp_id).json()
    assert nxt3["done"] is True


def test_unknown_agent_404():
    assert client.get("/api/agents/nope").status_code == 404
    assert client.post("/api/calls/start", json={"agent_id": "nope"}).status_code == 404
    assert client.get("/api/calls/nope").status_code == 404
