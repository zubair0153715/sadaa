# -*- coding: utf-8 -*-
"""Sadaa — optional Gemini brain.

Off by default. Enabled only when the GEMINI_API_KEY environment variable
is set (the owner's own key, never in code or chat). When enabled, the
engine falls back to Gemini for turns no scripted intent matches; scripted
flows and tool calls always win first, so bookings, tickets and payments
stay deterministic.

Uses the plain Gemini REST endpoint via urllib — no extra dependency.
"""
import json
import os
import urllib.request

MODEL = "gemini-2.5-flash"
ENDPOINT = ("https://generativelanguage.googleapis.com/v1beta/models/%s:"
            "generateContent" % MODEL)


class GeminiBrain:
    def __init__(self, api_key=None):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY", "")

    @property
    def available(self):
        return bool(self.api_key)

    def reply(self, agent, call, text):
        if not self.available:
            return None
        prompt = (
            "%s\n\nYou are on a live phone call as %s, %s at Sadaa Call "
            "Centre Agency. The caller just said: \"%s\"\n"
            "Reply in one or two short spoken sentences, as the agent would "
            "say them aloud. Never invent bookings, balances or ticket "
            "numbers — if the caller asks for one of those, say you will "
            "check and ask for the details you need."
            % (agent.get("system_prompt", ""), agent.get("name", ""),
               agent.get("role", ""), text))
        body = json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode()
        req = urllib.request.Request(
            ENDPOINT + "?key=" + self.api_key, data=body,
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read().decode())
            parts = data["candidates"][0]["content"]["parts"]
            return "".join(p.get("text", "") for p in parts).strip() or None
        except Exception:
            return None
