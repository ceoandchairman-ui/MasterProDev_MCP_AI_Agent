"""make_engine: SQLAlchemy gets an explicit psycopg2 driver, but libpq (psycopg2.connect) must get a plain postgresql:// DSN."""

import sys
import types

import pytest

from mpd_assistant.core import db


@pytest.mark.parametrize("given", ["postgresql://u:p@h:5432/d", "postgres://u:p@h:5432/d", "postgresql+asyncpg://u:p@h:5432/d"])
def test_engine_gets_explicit_driver_and_connect_gets_plain_dsn(monkeypatch, given):
    captured = {}
    connects = []

    class FakeOperationalError(Exception):
        pass

    fake = types.SimpleNamespace(OperationalError=FakeOperationalError, connect=lambda dsn, **kw: connects.append(dsn) or object())
    monkeypatch.setitem(sys.modules, "psycopg2", fake)
    monkeypatch.setattr(db, "create_engine", lambda url, **kw: captured.update(url=url, creator=kw["creator"]) or object())

    db.make_engine(given)
    captured["creator"]()

    assert captured["url"] == "postgresql+psycopg2://u:p@h:5432/d"
    assert connects == ["postgresql://u:p@h:5432/d"]
