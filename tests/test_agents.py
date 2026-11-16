# -*- coding: utf-8 -*-
"""Agent config tests: the five ready agents are complete and consistent."""
from app import engine
from app.agents import AGENTS, DEMO_ACCOUNTS, FAQS

EXPECTED = {
    "receptionist": ("Ayesha", "Receptionist"),
    "sales": ("Bilal", "Sales Qualifier"),
    "booker": ("Sara", "Appointment Booker"),
    "support": ("Omar", "Support Agent"),
    "payments": ("Hina", "Payment Reminder"),
}


def test_five_agents_present():
    assert len(AGENTS) == 5
    assert {a["id"] for a in AGENTS} == set(EXPECTED)


def test_agent_fields_complete():
    for a in AGENTS:
        name, role = EXPECTED[a["id"]]
        assert a["name"] == name
        assert a["role"] == role
        assert a["persona"].strip()
        assert a["greeting"].strip()
        assert a["system_prompt"].strip()
        assert a["voice"]["lang"]
        assert 0.5 <= a["voice"].get("rate", 1.0) <= 2.0
        assert 0 <= a["voice"].get("pitch", 1.0) <= 2.0
        assert a["intents"], a["id"]
        assert a["sample_dialogue"], a["id"]
        for line in a["sample_dialogue"]:
            assert len(line) == 2 and line[0] and line[1]


def test_agent_tools_all_exist():
    for a in AGENTS:
        for tool in a["tools"]:
            assert tool in engine.TOOLS, "%s uses unknown tool %s" % (a["id"], tool)
        for intent in a["intents"]:
            if intent.get("tool"):
                assert intent["tool"] in engine.TOOLS, (
                    "%s intent %s uses unknown tool %s"
                    % (a["id"], intent["name"], intent["tool"]))
            assert intent.get("patterns"), "%s intent %s has no patterns" % (a["id"], intent["name"])


def test_every_agent_can_say_goodbye():
    for a in AGENTS:
        names = {i["name"] for i in a["intents"]}
        assert "goodbye" in names, a["id"]


def test_faqs_and_demo_accounts_seeded():
    assert len(FAQS) >= 5
    for q, ans, kw in FAQS:
        assert q.strip() and ans.strip()
    assert len(DEMO_ACCOUNTS) >= 2
    refs = [r for r, _, _, _ in DEMO_ACCOUNTS]
    assert all(r.startswith("ACC-") for r in refs)
