# -*- coding: utf-8 -*-
"""Engine tests: intent routing, slot machine, tools, state machine."""
import json

from app import db, engine
from app.api import _agent_out


def _agent(agent_id):
    conn = db.connect()
    try:
        row = conn.execute("SELECT * FROM agents WHERE id=?", (agent_id,)).fetchone()
        return _agent_out(row)
    finally:
        conn.close()


def _call(agent_id="booker", contact_name="Test Caller"):
    conn = db.connect()
    try:
        conn.execute(
            "INSERT INTO calls (id, agent_id, direction, contact_name, state, started_at) "
            "VALUES (?,?,?,?,?,?)",
            ("testcall1", agent_id, "inbound", contact_name, "ACTIVE", engine.now_iso()))
        conn.commit()
        return db.row_to_dict(conn.execute(
            "SELECT * FROM calls WHERE id='testcall1'").fetchone())
    finally:
        conn.close()


def _turn(call, agent, text):
    conn = db.connect()
    try:
        call = db.row_to_dict(conn.execute(
            "SELECT * FROM calls WHERE id=?", (call["id"],)).fetchone())
        res = engine.handle_turn(conn, call, agent, text)
        conn.commit()
        return res
    finally:
        conn.close()


# ---------------------------------------------------------------- parsing

def test_parse_date_tomorrow():
    from datetime import date, timedelta
    assert engine.parse_date("tomorrow") == (date.today() + timedelta(days=1)).isoformat()


def test_parse_date_weekday():
    assert engine.parse_date("next monday") is not None


def test_parse_time_variants():
    assert engine.parse_time("10am") == "10:00"
    assert engine.parse_time("2 pm") == "14:00"
    assert engine.parse_time("10:30") == "10:30"
    assert engine.parse_time("14:00") == "14:00"


# ---------------------------------------------------------------- intents

def test_receptionist_routes_booking():
    agent = _agent("receptionist")
    intent = engine.match_intent(agent, "I want to book an appointment")
    assert intent is not None and intent["name"] == "route_booking"


def test_receptionist_routes_support_and_payment():
    agent = _agent("receptionist")
    assert engine.match_intent(agent, "my internet is not working")["name"] == "route_support"
    assert engine.match_intent(agent, "I want to pay my bill")["name"] == "route_payment"


def test_support_faq_hours():
    agent = _agent("support")
    assert engine.match_intent(agent, "what are your opening hours")["name"] == "faq_hours"


def test_no_intent_for_gibberish():
    agent = _agent("booker")
    assert engine.match_intent(agent, "purple elephant banana") is None


# ---------------------------------------------------------------- slot machine

def test_booking_flow_end_to_end():
    agent = _agent("booker")
    call = _call("booker")
    r1 = _turn(call, agent, "I want to book an appointment")
    assert "day" in r1["reply"].lower()
    r2 = _turn(call, agent, "tomorrow")
    assert "time" in r2["reply"].lower()
    r3 = _turn(call, agent, "10am")
    assert "name" in r3["reply"].lower()
    r4 = _turn(call, agent, "Test User")
    assert r4["tool_calls"] and r4["tool_calls"][0]["ok"] is True
    assert "booked" in r4["reply"].lower()
    conn = db.connect()
    try:
        appt = conn.execute(
            "SELECT * FROM appointments WHERE name='Test User'").fetchone()
        assert appt is not None and appt["status"] == "booked"
    finally:
        conn.close()


def test_booking_bad_date_reprompts():
    agent = _agent("booker")
    call = _call("booker")
    _turn(call, agent, "book an appointment")
    r = _turn(call, agent, "sometime whenever")
    assert "didn't catch" in r["reply"]


def test_double_booking_rejected():
    agent = _agent("booker")
    call = _call("booker")
    _turn(call, agent, "book an appointment")
    _turn(call, agent, "tomorrow")
    _turn(call, agent, "10am")
    _turn(call, agent, "First User")
    # second caller, same slot (reload the call row each turn, like the API does)
    c2 = {"id": "testcall2"}
    conn = db.connect()
    try:
        conn.execute(
            "INSERT INTO calls (id, agent_id, direction, contact_name, state, started_at) "
            "VALUES ('testcall2','booker','inbound','Second','ACTIVE',?)", (engine.now_iso(),))
        conn.commit()
    finally:
        conn.close()
    _turn(c2, agent, "book an appointment")
    _turn(c2, agent, "tomorrow")
    _turn(c2, agent, "10am")
    r = _turn(c2, agent, "Second User")
    assert r["tool_calls"] and r["tool_calls"][0]["ok"] is False
    assert "already taken" in r["reply"]


def test_cancel_frees_slot():
    agent = _agent("booker")
    call = _call("booker")
    _turn(call, agent, "book an appointment")
    _turn(call, agent, "tomorrow")
    _turn(call, agent, "11am")
    _turn(call, agent, "Cancel Me")
    r = _turn(call, agent, "cancel my appointment")
    r = _turn(call, agent, "Cancel Me")
    r = _turn(call, agent, "tomorrow")
    assert r["tool_calls"] and r["tool_calls"][0]["ok"] is True
    conn = db.connect()
    try:
        appt = conn.execute(
            "SELECT * FROM appointments WHERE name='Cancel Me'").fetchone()
        assert appt["status"] == "cancelled"
    finally:
        conn.close()


def test_support_ticket_flow():
    agent = _agent("support")
    call = _call("support")
    r1 = _turn(call, agent, "I want to raise a ticket")
    assert "problem" in r1["reply"].lower()
    r2 = _turn(call, agent, "my dashboard won't load")
    assert "name" in r2["reply"].lower()
    r3 = _turn(call, agent, "Ticket User")
    assert r3["tool_calls"] and r3["tool_calls"][0]["ok"] is True
    assert "TKT-" in r3["reply"]


def test_payment_balance_demo_account():
    agent = _agent("payments")
    call = _call("payments")
    _turn(call, agent, "how much do I owe")
    r = _turn(call, agent, "ACC-1001")
    assert r["tool_calls"] and r["tool_calls"][0]["ok"] is True
    assert "12500" in r["reply"]


def test_sales_lead_capture():
    agent = _agent("sales")
    call = _call("sales")
    _turn(call, agent, "I'm looking for a call centre team")
    _turn(call, agent, "inbound support")
    _turn(call, agent, "Lead Person")
    r = _turn(call, agent, "0300 1234567")
    assert r["tool_calls"] and r["tool_calls"][0]["ok"] is True
    conn = db.connect()
    try:
        lead = conn.execute("SELECT * FROM leads WHERE name='Lead Person'").fetchone()
        assert lead is not None
    finally:
        conn.close()


def test_fallback_is_polite():
    agent = _agent("booker")
    call = _call("booker")
    r = _turn(call, agent, "purple elephant banana")
    assert "didn't quite catch" in r["reply"]


def test_goodbye_ends_call_flag():
    agent = _agent("receptionist")
    call = _call("receptionist")
    r = _turn(call, agent, "goodbye, that's all")
    assert r["end_call"] is True


# ---------------------------------------------------------------- state machine

def test_state_machine_valid_path():
    conn = db.connect()
    try:
        call = _call("booker")
        call = db.row_to_dict(conn.execute("SELECT * FROM calls WHERE id='testcall1'").fetchone())
        # fresh call is ACTIVE in the fixture; test transitions on a new row
        conn.execute(
            "INSERT INTO calls (id, agent_id, direction, state, started_at) "
            "VALUES ('sm1','booker','inbound','QUEUED',?)", (engine.now_iso(),))
        conn.commit()
        c = db.row_to_dict(conn.execute("SELECT * FROM calls WHERE id='sm1'").fetchone())
        ok, _ = engine.transition(conn, c, "RINGING")
        assert ok
        c = db.row_to_dict(conn.execute("SELECT * FROM calls WHERE id='sm1'").fetchone())
        ok, _ = engine.transition(conn, c, "ACTIVE")
        assert ok
        c = db.row_to_dict(conn.execute("SELECT * FROM calls WHERE id='sm1'").fetchone())
        ok, _ = engine.transition(conn, c, "HOLD")
        assert ok
        c = db.row_to_dict(conn.execute("SELECT * FROM calls WHERE id='sm1'").fetchone())
        ok, _ = engine.transition(conn, c, "ACTIVE")
        assert ok
        c = db.row_to_dict(conn.execute("SELECT * FROM calls WHERE id='sm1'").fetchone())
        ok, _ = engine.transition(conn, c, "ENDED")
        assert ok
    finally:
        conn.close()


def test_state_machine_invalid():
    conn = db.connect()
    try:
        conn.execute(
            "INSERT INTO calls (id, agent_id, direction, state, started_at) "
            "VALUES ('sm2','booker','inbound','QUEUED',?)", (engine.now_iso(),))
        conn.commit()
        c = db.row_to_dict(conn.execute("SELECT * FROM calls WHERE id='sm2'").fetchone())
        ok, msg = engine.transition(conn, c, "ACTIVE")
        assert ok is False
        assert "Cannot move" in msg
    finally:
        conn.close()


def test_supervisor_barge_in_silences_agent():
    agent = _agent("booker")
    call = _call("booker")
    conn = db.connect()
    try:
        conn.execute("UPDATE calls SET supervisor_active=1 WHERE id='testcall1'")
        conn.commit()
        c = db.row_to_dict(conn.execute("SELECT * FROM calls WHERE id='testcall1'").fetchone())
        res = engine.handle_turn(conn, c, agent, "hello")
        assert res["mode"] == "supervisor"
        assert res["reply"] is None
    finally:
        conn.close()
