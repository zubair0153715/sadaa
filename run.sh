#!/bin/bash
# Sadaa — start the agency server locally.
cd "$(dirname "$0")"
exec ~/workspace/.venv-fc/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
