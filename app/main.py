# -*- coding: utf-8 -*-
"""Sadaa — Call Centre Agency with voice AI agents.

Run:  uvicorn app.main:app --host 127.0.0.1 --port 8000
Then open http://127.0.0.1:8000

Voice calls in the browser are free (Web Speech API, no key, no card).
Real PSTN phone numbers need Twilio (the owner's account + credits) —
Sadaa never fakes a phone call.
"""
import os

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import db
from .api import router

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


def create_app():
    app = FastAPI(title="Sadaa — Call Centre Agency", version="1.0.0")
    db.init_db()
    app.include_router(router)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/")
    def index():
        return FileResponse(os.path.join(STATIC_DIR, "index.html"))

    @app.get("/call")
    def call_page():
        """Public click-to-call page — a visitor taps Call now and speaks
        to a voice agent in the browser, free. No account, no number."""
        return FileResponse(os.path.join(STATIC_DIR, "call.html"))

    return app


app = create_app()
