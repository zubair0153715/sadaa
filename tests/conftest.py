import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

_db = os.path.join(tempfile.gettempdir(), "sadaa-test-%d.db" % os.getpid())
os.environ["SADAA_DB"] = _db

import pytest  # noqa: E402

from app import db  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    if os.path.exists(_db):
        os.remove(_db)
    db.init_db()
    yield
    if os.path.exists(_db):
        os.remove(_db)
