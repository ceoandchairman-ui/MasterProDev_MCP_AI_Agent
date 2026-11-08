import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import MemorySaver

from mpd_assistant.api.main import GUEST_DAILY_MESSAGES, Services, create_app
from mpd_assistant.core import crypto
from mpd_assistant.core.flags import bucket, enabled_for
from mpd_assistant.core.kv import MemoryKV
from mpd_assistant.graph.builder import build_graph
from mpd_assistant.graph.service import ChatService
from mpd_assistant.identity.abuse import AbuseBlocked, SmsAbuseGuard
from mpd_assistant.identity.otp import OtpService
from mpd_assistant.identity.service import IdentityService, MemoryUserRepository
from mpd_assistant.privacy.vault import MemoryVaultStore, PiiVault
from mpd_assistant.sessions.service import MemorySessionRepository, SessionService


def test_only_allowed_countries_get_codes():
    guard = SmsAbuseGuard(MemoryKV(), countries={"CA", "US"})
    guard.check("+14169671111", "1.1.1.1")
    with pytest.raises(AbuseBlocked) as exc:
        guard.check("+61412345678", "1.1.1.1")
    assert exc.value.reason == "country_not_allowed"


def test_per_number_and_per_ip_limits():
    guard = SmsAbuseGuard(MemoryKV(), per_number=2, per_ip=3, daily_cap=50)
    guard.check("+14169671111", "9.9.9.9")
    guard.check("+14169671111", "9.9.9.9")
    with pytest.raises(AbuseBlocked) as exc:
        guard.check("+14169671111", "9.9.9.9")
    assert exc.value.reason == "too_many_codes_for_number"
    guard.check("+14165550100", "9.9.9.9")
    with pytest.raises(AbuseBlocked) as exc:
        guard.check("+14165550101", "9.9.9.9")
    assert exc.value.reason == "too_many_requests_from_address"


def test_daily_cap_stops_pumping():
    guard = SmsAbuseGuard(MemoryKV(), per_number=99, per_ip=99, daily_cap=2)
    guard.check("+14169671111", None)
    guard.check("+14165550100", None)
    with pytest.raises(AbuseBlocked) as exc:
        guard.check("+14165550101", None)
    assert exc.value.reason == "daily_send_cap_reached"


async def test_identity_start_refuses_blocked_country_before_sending():
    sent = []

    class Capture:
        def send(self, target, code):
            sent.append(target)

    cipher = crypto.FieldCipher(crypto.generate_key())
    identity = IdentityService(
        cipher, crypto.generate_key(), MemoryUserRepository(), OtpService("e"), OtpService("s"),
        Capture(), Capture(), abuse=SmsAbuseGuard(MemoryKV(), countries={"CA"}),
    )
    with pytest.raises(AbuseBlocked):
        await identity.start("s1", "Ann", "ann@example.com", "+61 2 1234 5678")
    assert sent == []


def test_guest_daily_quota_is_enforced_per_session():
    kv = MemoryKV()
    cipher = crypto.FieldCipher(crypto.generate_key())
    vault = PiiVault(cipher, MemoryVaultStore())
    chat = ChatService(build_graph({}, checkpointer=MemorySaver()), vault)
    identity = IdentityService(cipher, crypto.generate_key(), MemoryUserRepository(), OtpService("e"), OtpService("s"), None, None)
    client = TestClient(create_app(Services(chat, SessionService(MemorySessionRepository()), identity, kv=kv)))
    sid = None
    replies = []
    for _ in range(GUEST_DAILY_MESSAGES + 1):
        body = {"message": "hello"}
        if sid:
            body["session_id"] = sid
        r = client.post("/v2/chat", json=body).json()
        sid = r["session_id"]
        replies.append(r["reply"])
    assert replies[0].startswith("Hello") and "quickly" in replies[-1]


def test_rollout_buckets_are_stable_and_roughly_proportional():
    assert bucket("user-1") == bucket("user-1")
    hits = sum(enabled_for(f"k{i}", 25) for i in range(2000))
    assert 380 < hits < 620
    assert enabled_for("anyone", 0) is False and enabled_for("anyone", 100) is True
