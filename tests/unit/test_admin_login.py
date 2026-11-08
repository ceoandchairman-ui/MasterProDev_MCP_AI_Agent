import bcrypt

from mcp_host import auth
from mcp_host.config import settings


def test_plaintext_admin_credentials(monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_EMAIL", "Admin@Example.com")
    monkeypatch.setattr(settings, "ADMIN_PASSWORD", "correct horse")
    assert auth.verify_admin_credentials("admin@example.com", "correct horse")
    assert not auth.verify_admin_credentials("admin@example.com", "wrong")
    assert not auth.verify_admin_credentials("other@example.com", "correct horse")


def test_hashed_admin_password(monkeypatch):
    hashed = bcrypt.hashpw(b"s3cret", bcrypt.gensalt()).decode()
    monkeypatch.setattr(settings, "ADMIN_EMAIL", "a@b.co")
    monkeypatch.setattr(settings, "ADMIN_PASSWORD", hashed)
    assert auth.verify_admin_credentials("a@b.co", "s3cret")
    assert not auth.verify_admin_credentials("a@b.co", "nope")
