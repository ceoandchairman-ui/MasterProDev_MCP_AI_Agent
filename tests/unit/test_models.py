import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from mpd_assistant.core import crypto
from mpd_assistant.core.models import Base, Lead, Session, Tenant, Turn, User


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with DbSession(engine) as s:
        yield s


def _user(tenant, key, email="ann@example.com"):
    cipher = crypto.FieldCipher(key)
    return User(
        tenant_id=tenant.id,
        name_enc=cipher.encrypt("Ann"),
        email_enc=cipher.encrypt(email),
        email_index=crypto.blind_index(key, email),
        phone_enc=cipher.encrypt("+14169671111"),
        phone_index=crypto.blind_index(key, "+14169671111"),
    )


def test_email_unique_per_tenant_via_blind_index(db):
    key = crypto.generate_key()
    t = Tenant(name="mpd")
    db.add(t)
    db.flush()
    db.add(_user(t, key))
    db.flush()
    db.add(_user(t, key))
    with pytest.raises(IntegrityError):
        db.flush()


def test_no_plaintext_contact_details_in_row(db):
    key = crypto.generate_key()
    t = Tenant(name="mpd")
    db.add(t)
    db.flush()
    u = _user(t, key)
    db.add(u)
    db.flush()
    stored = " ".join([u.name_enc, u.email_enc, u.email_index, u.phone_enc, u.phone_index])
    assert "ann@example.com" not in stored and "+1416" not in stored


def test_session_turn_and_lead_defaults(db):
    key = crypto.generate_key()
    t = Tenant(name="mpd")
    db.add(t)
    db.flush()
    u = _user(t, key)
    db.add(u)
    db.flush()
    s = Session(tenant_id=t.id, user_id=u.id)
    db.add(s)
    db.flush()
    db.add(Turn(session_id=s.id, user_text="hi", reply_text="hello"))
    db.add(Lead(tenant_id=t.id, user_id=u.id))
    db.flush()
    assert s.verified is False and s.turns[0].cache_hit is False
