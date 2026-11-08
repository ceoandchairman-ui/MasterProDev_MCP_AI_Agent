"""Staff review of held-back quotes: the only way a needs_approval quote becomes payable."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session as DbSession

from mpd_assistant.api import app as app_module
from mpd_assistant.business.admin import AdminService
from mpd_assistant.business.escalations import EscalationService, InMemoryEscalations
from mpd_assistant.business.quote_review import QuoteReview
from mpd_assistant.business.quote_store import MemoryQuoteRepository, SqlQuoteRepository
from mpd_assistant.business.quoting import CatalogItem, build_quote
from mpd_assistant.core import config, crypto
from mpd_assistant.core.models import Base, Lead, Tenant, User

CATALOG = {"dev-hour": CatalogItem("dev-hour", "Development hour", "hour", 15000)}


def big_quote():
    return build_quote(CATALOG, [{"sku": "dev-hour", "quantity": 200}])  # 3,000,000 cents before tax: needs a human


def small_quote():
    return build_quote(CATALOG, [{"sku": "dev-hour", "quantity": 10}])


async def test_approving_a_held_back_quote_makes_it_payable_once():
    repo, notices, audits = MemoryQuoteRepository(), [], []
    stored = repo.save("u1", big_quote())
    assert stored.status == "needs_approval"
    review = QuoteReview(repo, audit=lambda *a: audits.append(a), on_decision=lambda q, ok: _record(notices, q, ok))
    assert [q.ref for q in review.pending()] == [stored.ref]
    assert await review.decide(stored.ref, True, "ann") == "approved"
    assert repo.get(stored.id).status == "approved" and review.pending() == []
    assert notices == [(stored.ref, True)] and audits[0][:3] == ("ann", "quote_approved", stored.ref)
    assert await review.decide(stored.ref, True) == "not_pending"  # a decision cannot be repeated or flipped
    assert await review.decide(stored.ref, False) == "not_pending"


async def _record(notices, quote, approved):
    notices.append((quote.ref, approved))


async def test_rejecting_keeps_the_quote_unpayable():
    from mpd_assistant.business.quote_store import PAYABLE

    repo = MemoryQuoteRepository()
    stored = repo.save("u1", big_quote())
    assert await QuoteReview(repo).decide(stored.ref, False) == "rejected"
    assert repo.get(stored.id).status == "rejected" and "rejected" not in PAYABLE


async def test_unknown_short_and_ordinary_quotes_are_not_decidable():
    repo = MemoryQuoteRepository()
    ordinary = repo.save("u1", small_quote())
    review = QuoteReview(repo)
    assert ordinary.status == "draft"
    assert await review.decide(ordinary.ref, True) == "not_pending"
    assert await review.decide("ZZZZZZZZ", True) == "not_found"
    assert await review.decide("abc", True) == "not_found"  # too short to be a reference


async def test_a_failing_notice_does_not_undo_the_decision():
    repo = MemoryQuoteRepository()
    stored = repo.save("u1", big_quote())

    async def boom(quote, approved):
        raise RuntimeError("smtp down")

    assert await QuoteReview(repo, on_decision=boom).decide(stored.ref, True) == "approved"
    assert repo.get(stored.id).status == "approved"


def test_sql_repository_finds_by_reference_and_lists_by_status(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'q.db'}")
    Base.metadata.create_all(engine)
    with DbSession(engine) as s:
        tenant = Tenant(name="t")
        s.add(tenant)
        s.flush()
        user = User(tenant_id=tenant.id, name_enc="n", email_enc="e", email_index="i", phone_enc="p", phone_index="p")
        s.add(user)
        s.flush()
        s.commit()
        tenant_id, user_id = tenant.id, user.id
    repo = SqlQuoteRepository(engine, tenant_id)
    with DbSession(engine) as s:
        s.add(Lead(tenant_id=tenant_id, user_id=user_id, stage="qualified"))
        s.commit()
    held, normal = repo.save(user_id, big_quote()), repo.save(user_id, small_quote())
    assert [q.ref for q in repo.list_by_status("needs_approval")] == [held.ref]
    assert repo.find_by_ref(held.ref).user_id == user_id and repo.find_by_ref(held.ref.lower()).id == held.id
    assert repo.find_by_ref("short") is None and repo.find_by_ref("00000000") is None
    repo.set_status(normal.id, "paid")
    assert repo.list_by_status("paid")[0].ref == normal.ref


def test_admin_overview_and_routes_need_the_staff_token(monkeypatch):
    for k, v in {
        "SECRET_KEY": "x" * 16, "DATABASE_URL": "postgresql://u:p@127.0.0.1:1/d", "REDIS_URL": "redis://127.0.0.1:1",
        "DATA_ENCRYPTION_KEY": crypto.generate_key(), "BLIND_INDEX_KEY": crypto.generate_key(), "METRICS_TOKEN": "m",
        "ENV": "development", "ADMIN_TOKEN": "staff-secret",
    }.items():
        monkeypatch.setenv(k, v)
    config.get_settings.cache_clear()
    services = app_module.build_services()
    # the factory's in-memory quote repository is shared with the review service
    stored = services.admin.quotes._quotes.save("u1", big_quote())
    from mpd_assistant.api.main import create_app

    client = TestClient(create_app(services))
    auth = {"Authorization": "Bearer staff-secret"}
    assert client.get("/v2/admin/quotes").status_code == 401
    assert client.get("/v2/admin/overview", headers=auth).json()["quotes_awaiting_review"] == 1
    listing = client.get("/v2/admin/quotes", headers=auth).json()["quotes"]
    assert listing[0]["reference"] == stored.ref and listing[0]["lines"][0]["name"] == "Development hour"
    assert "email" not in str(listing).lower()
    assert client.post(f"/v2/admin/quotes/{stored.ref}/approve", headers=auth).json() == {"status": "approved"}
    assert client.post(f"/v2/admin/quotes/{stored.ref}/approve", headers=auth).status_code == 409
    assert client.post("/v2/admin/quotes/NOSUCHQT/reject", headers=auth).status_code == 404
    assert client.get("/v2/admin/overview", headers=auth).json()["quotes_awaiting_review"] == 0
    config.get_settings.cache_clear()


def test_admin_service_without_review_reports_nothing():
    admin = AdminService(EscalationService(repo=InMemoryEscalations()), InMemoryEscalations())
    assert admin.pending_quotes() == [] and admin.overview()["quotes_awaiting_review"] == 0


async def test_admin_service_decide_without_review_is_not_found():
    admin = AdminService(EscalationService(repo=InMemoryEscalations()), InMemoryEscalations())
    assert await admin.decide_quote("ABCDEF12", True) == "not_found"


@pytest.mark.parametrize("lang", ["en", "fr"])
def test_decision_templates_exist_in_both_languages(lang):
    from mpd_assistant.responses.engine import render

    for name in ("quote_approved", "quote_declined", "quote_approved_subject", "quote_declined_subject"):
        assert render(name, lang, {"quote": "ABCD1234"})
    assert "ABCD1234" in render("quote_approved", lang, {"quote": "ABCD1234"})
