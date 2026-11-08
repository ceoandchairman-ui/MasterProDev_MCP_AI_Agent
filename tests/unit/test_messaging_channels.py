import base64
import hashlib
import hmac
import json

import httpx
import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import MemorySaver

from mpd_assistant.api.main import Services, create_app
from mpd_assistant.channels.gateway import ChannelGateway
from mpd_assistant.channels.inbound import (
    InboundMessage,
    format_for_channel,
    parse_twilio_form,
    twilio_signature,
    twiml_reply,
    validate_twilio_signature,
)
from mpd_assistant.core import crypto
from mpd_assistant.core.kv import MemoryKV
from mpd_assistant.graph.builder import build_graph
from mpd_assistant.graph.service import ChatService
from mpd_assistant.identity.otp import OtpService
from mpd_assistant.identity.service import IdentityService, MemoryUserRepository, VerifiedUser
from mpd_assistant.messaging.models import Channel, OutboundMessage, Purpose, SendResult, mask
from mpd_assistant.messaging.providers import SendGridProvider, TwilioProvider
from mpd_assistant.messaging.service import MessengerSender, NotificationService, classify_keyword
from mpd_assistant.privacy.vault import MemoryVaultStore, PiiVault
from mpd_assistant.sessions.service import MemorySessionRepository, SessionService


class FakeProvider:
    def __init__(self, channels=(Channel.SMS,), status="sent"):
        self.channels = frozenset(channels)
        self.sent = []
        self.status = status

    async def send(self, channel, to, body, subject=None):
        self.sent.append((channel, to, body, subject))
        return SendResult(self.status, provider_id=f"id{len(self.sent)}")


def sms(**kw):
    base = dict(channel=Channel.SMS, to="+14169671111", template="booking_confirmed", variables={"when": "Nov 2, 2pm"})
    base.update(kw)
    return OutboundMessage(**base)


# --- providers ----------------------------------------------------------------
async def test_twilio_sends_sms_and_whatsapp_with_basic_auth():
    seen = []

    def handler(request):
        seen.append((str(request.url), request.headers["authorization"], request.content.decode()))
        return httpx.Response(201, json={"sid": "SM123"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    tw = TwilioProvider("AC1", "tok", "+15550001111", "+15550002222", status_callback_url="https://x/cb", client=client)
    r = await tw.send(Channel.SMS, "+14169671111", "hello")
    w = await tw.send(Channel.WHATSAPP, "+14169671111", "hello")
    assert r.status == "sent" and r.provider_id == "SM123" and w.status == "sent"
    assert "Accounts/AC1/Messages.json" in seen[0][0] and seen[0][1].startswith("Basic ")
    assert "To=%2B14169671111" in seen[0][2] and "From=%2B15550001111" in seen[0][2]
    assert "whatsapp%3A%2B14169671111" in seen[1][2] and "whatsapp%3A%2B15550002222" in seen[1][2]


async def test_twilio_errors_never_leak_credentials_or_bodies():
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(400, json={"code": 21211, "message": "bad number +1416 secret-token"})))
    r = await TwilioProvider("AC1", "secret-token", "+1555", client=client).send(Channel.SMS, "+1416", "x")
    assert r.status == "failed" and r.reason == "twilio_400_21211" and "secret-token" not in r.reason


async def test_twilio_unconfigured_channel_and_network_error():
    assert (await TwilioProvider("AC", "t", sms_from="+1555").send(Channel.WHATSAPP, "+1416", "x")).reason == "channel_not_configured"

    def boom(request):
        raise httpx.ConnectError("down")

    client = httpx.AsyncClient(transport=httpx.MockTransport(boom))
    assert (await TwilioProvider("AC", "t", "+1555", client=client).send(Channel.SMS, "+1416", "x")).reason == "network_ConnectError"


async def test_sendgrid_payload_and_status():
    seen = {}

    def handler(request):
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(202, headers={"x-message-id": "m1"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    r = await SendGridProvider("SG.key", "no-reply@masterprodev.com", client=client).send(Channel.EMAIL, "ann@example.com", "body", "Subject")
    assert r.status == "sent" and r.provider_id == "m1" and seen["auth"] == "Bearer SG.key"
    assert seen["body"]["personalizations"][0]["to"][0]["email"] == "ann@example.com" and seen["body"]["subject"] == "Subject"


# --- notification policy ------------------------------------------------------------
async def test_renders_template_in_locale_and_sends():
    p = FakeProvider()
    svc = NotificationService([p], MemoryKV())
    assert (await svc.send(sms(locale="fr"))).status == "sent"
    assert "confirmé" in p.sent[0][2] and "Nov 2, 2pm" in p.sent[0][2]


async def test_idempotency_key_prevents_duplicate_sends():
    p = FakeProvider()
    svc = NotificationService([p], MemoryKV())
    assert (await svc.send(sms(idempotency_key="booking-1"))).status == "sent"
    assert (await svc.send(sms(idempotency_key="booking-1"))).status == "skipped"
    assert len(p.sent) == 1


async def test_marketing_needs_consent_and_respects_opt_out():
    p = FakeProvider()
    consented = {"u1"}
    svc = NotificationService([p], MemoryKV(), has_consent=lambda uid: uid in consented)
    marketing = sms(purpose=Purpose.MARKETING, user_id="u2")
    assert (await svc.send(marketing)).reason == "no_consent"
    ok = sms(purpose=Purpose.MARKETING, user_id="u1")
    assert (await svc.send(ok)).status == "sent"
    svc.record_opt_out(Channel.SMS, "+14169671111")
    assert (await svc.send(sms(purpose=Purpose.MARKETING, user_id="u1", template="quote_ready", variables={"link": "x"}))).reason == "opted_out"
    assert (await svc.send(sms())).status == "sent"  # transactional still allowed


async def test_per_target_rate_limit_and_daily_spend_cap():
    p = FakeProvider()
    svc = NotificationService([p], MemoryKV(), per_target_per_hour=2, daily_cap_per_channel=3)
    assert [(await svc.send(sms())).status for _ in range(3)] == ["sent", "sent", "blocked"]
    assert (await svc.send(sms(to="+14165550100"))).status == "sent"
    assert (await svc.send(sms(to="+14165550101"))).reason == "daily_cap"
    assert len(p.sent) == 3


async def test_no_provider_and_unknown_template():
    svc = NotificationService([FakeProvider()], MemoryKV())
    assert (await svc.send(sms(channel=Channel.EMAIL))).reason == "no_provider"
    assert (await svc.send(sms(template="nope"))).reason == "unknown_template"


async def test_email_gets_subject_from_template():
    p = FakeProvider((Channel.EMAIL,))
    svc = NotificationService([p], MemoryKV())
    await svc.send(OutboundMessage(Channel.EMAIL, "ann@example.com", "otp_code", "en", {"code": "123456"}))
    assert p.sent[0][3] == "Your verification code" and "123456" in p.sent[0][2]


async def test_messenger_sender_raises_when_delivery_fails():
    svc = NotificationService([FakeProvider(status="failed")], MemoryKV())
    with pytest.raises(RuntimeError):
        await MessengerSender(svc, Channel.SMS).send("+14169671111", "123456")


def test_keywords_and_masking():
    assert classify_keyword(" STOP ") == "opt_out" and classify_keyword("Unsubscribe") == "opt_out"
    assert classify_keyword("START") == "opt_in" and classify_keyword("hello") is None
    assert mask("+14169671111") == "***1111" and mask("ann@example.com") == "a***@example.com"


# --- inbound parsing and formatting ----------------------------------------------------
def test_twilio_signature_matches_reference_algorithm():
    url, token = "https://example.com/v2/channels/twilio", "12345"
    params = {"From": "+14169671111", "Body": "Hi", "MessageSid": "SM1"}
    payload = url + "".join(k + params[k] for k in sorted(params))
    expected = base64.b64encode(hmac.new(token.encode(), payload.encode(), hashlib.sha1).digest()).decode()
    assert twilio_signature(token, url, params) == expected
    assert validate_twilio_signature(token, url, params, expected)
    assert not validate_twilio_signature(token, url, {**params, "Body": "tampered"}, expected)
    assert not validate_twilio_signature(token, url, params, None)
    assert not validate_twilio_signature("", url, params, expected)


def test_parse_twilio_sms_whatsapp_and_garbage():
    sms_in = parse_twilio_form({"From": "+14169671111", "Body": " hi ", "MessageSid": "SM1"})
    assert sms_in == InboundMessage(Channel.SMS, "+14169671111", "hi", "SM1")
    wa = parse_twilio_form({"From": "whatsapp:+14169671111", "Body": "hello"})
    assert wa.channel is Channel.WHATSAPP and wa.sender == "+14169671111"
    for bad in ({"From": "", "Body": "x"}, {"From": "+14169671111", "Body": "  "}, {"From": "notaphone", "Body": "x"}):
        assert parse_twilio_form(bad) is None


def test_channel_formatting_and_twiml_escaping():
    assert format_for_channel("**Total**: `$5`\n# Title", Channel.SMS) == "Total: $5\nTitle"
    assert format_for_channel("**bold**", Channel.WEB) == "**bold**"
    assert len(format_for_channel("x" * 3000, Channel.SMS)) == 1000
    assert "<script>" not in twiml_reply("<script>alert(1)</script> & more")


# --- gateway: cross-channel identity ---------------------------------------------------------
def build_gateway(users=None):
    key = crypto.generate_key()
    cipher = crypto.FieldCipher(key)
    users = users or MemoryUserRepository()
    vault = PiiVault(cipher, MemoryVaultStore())
    chat = ChatService(build_graph({}, checkpointer=MemorySaver()), vault)
    sessions = SessionService(MemorySessionRepository())
    kv = MemoryKV()
    notifications = NotificationService([FakeProvider()], kv)
    return ChannelGateway(chat, sessions, users, notifications, kv, key), users, key, cipher, notifications


def add_user(users, key, cipher, phone="+14169671111", email="ann@example.com"):
    users.save(
        VerifiedUser("u1", cipher.encrypt("Ann"), cipher.encrypt(email), crypto.blind_index(key, email), cipher.encrypt(phone), crypto.blind_index(key, phone), None)
    )


async def test_unknown_sms_sender_is_a_visitor_and_gets_gated():
    gw, *_ = build_gateway()
    reply = await gw.handle(InboundMessage(Channel.SMS, "+14169671111", "I need a quote"))
    assert "verify" in reply.lower()


async def test_known_phone_is_recognized_across_channels():
    gw, users, key, cipher, _ = build_gateway()
    add_user(users, key, cipher)
    for channel in (Channel.SMS, Channel.WHATSAPP):
        reply = await gw.handle(InboundMessage(channel, "+14169671111", "I need a quote"))
        assert "verify" not in reply.lower()  # reaches the quote path (no LLM runners configured: safe template)


async def test_stop_opts_out_and_session_is_reused():
    gw, _, _, _, notifications = build_gateway()
    first = await gw.handle(InboundMessage(Channel.SMS, "+14169671111", "hello"))
    assert first.startswith("Hello")
    assert "unsubscribed" in (await gw.handle(InboundMessage(Channel.SMS, "+14169671111", "STOP"))).lower()
    assert notifications.is_opted_out(Channel.SMS, "+14169671111")
    assert await gw.handle(InboundMessage(Channel.SMS, "+14169671111", "START")) is None
    assert not notifications.is_opted_out(Channel.SMS, "+14169671111")


async def test_inbound_flood_is_rate_limited():
    gw, *_ = build_gateway()
    replies = [await gw.handle(InboundMessage(Channel.SMS, "+14165550100", "hello")) for _ in range(22)]
    assert "quickly" in replies[-1]


# --- webhook endpoint --------------------------------------------------------------------------
def webhook_client():
    gw, users, key, cipher, _ = build_gateway()
    identity = IdentityService(cipher, key, users, OtpService("e"), OtpService("s"), FakeSender(), FakeSender())
    app = create_app(
        Services(gw._chat, gw._sessions, identity, gateway=gw, twilio_auth_token="tok", public_url="https://api.example.com")
    )
    return TestClient(app)


class FakeSender:
    def send(self, target, code):
        return None


def signed(form):
    return {"X-Twilio-Signature": twilio_signature("tok", "https://api.example.com/v2/channels/twilio", form)}


def test_webhook_rejects_bad_signature_and_accepts_good_one():
    client = webhook_client()
    form = {"From": "+14169671111", "Body": "hello", "MessageSid": "SM1"}
    assert client.post("/v2/channels/twilio", data=form).status_code == 403
    assert client.post("/v2/channels/twilio", data=form, headers={"X-Twilio-Signature": "bogus"}).status_code == 403
    ok = client.post("/v2/channels/twilio", data=form, headers=signed(form))
    assert ok.status_code == 200 and ok.headers["content-type"].startswith("application/xml")
    assert "<Message>Hello!" in ok.text


def test_webhook_disabled_without_gateway():
    key = crypto.generate_key()
    gw, users, _, cipher, _ = build_gateway()
    identity = IdentityService(cipher, key, users, OtpService("e"), OtpService("s"), FakeSender(), FakeSender())
    client = TestClient(create_app(Services(gw._chat, gw._sessions, identity)))
    assert client.post("/v2/channels/twilio", data={"From": "+1", "Body": "x"}).status_code == 404


# --- booking confirmations ----------------------------------------------------------
async def test_booking_confirmation_goes_out_on_every_available_channel_once():
    from mpd_assistant.agents.factory import build_runners
    from mpd_assistant.core.llm.client import FakeLLM
    from mpd_assistant.messaging.confirmations import ConfirmationService
    from mpd_assistant.tools.executor import ToolExecutor
    from mpd_assistant.tools.registry import default_registry

    key = crypto.generate_key()
    cipher = crypto.FieldCipher(key)
    users = MemoryUserRepository()
    add_user(users, key, cipher)
    sms_p, mail_p = FakeProvider((Channel.SMS,)), FakeProvider((Channel.EMAIL,))
    notifications = NotificationService([sms_p, mail_p], MemoryKV())
    confirmations = ConfirmationService(notifications, users, cipher)

    plan = json.dumps({"steps": [{"tool": "create_calendar_event", "args": {"title": "Call", "start_time": "2026-11-02T14:00:00", "end_time": "2026-11-02T14:30:00"}}]})

    async def backend(tool, args):
        return {"status": "success"}

    registry = default_registry()
    vault = PiiVault(cipher, MemoryVaultStore())
    runners = build_runners(FakeLLM([plan]), None, ToolExecutor(registry, backend), registry, on_booked=confirmations.booking_confirmed)
    svc = ChatService(build_graph(runners, checkpointer=MemorySaver()), vault)

    await svc.chat("s1", "book a meeting for Nov 2", verified=True, user_id="u1")
    done = await svc.chat("s1", "yes", verified=True, user_id="u1")
    assert done.reply.startswith("Done")
    assert len(sms_p.sent) == 1 and len(mail_p.sent) == 1
    assert "2026-11-02 14:00" in sms_p.sent[0][2] and sms_p.sent[0][1] == "+14169671111"
    assert mail_p.sent[0][1] == "ann@example.com" and mail_p.sent[0][3] == "Your call is confirmed"


async def test_failed_confirmation_does_not_break_the_booking():
    from mpd_assistant.messaging.confirmations import ConfirmationService

    key = crypto.generate_key()
    cipher = crypto.FieldCipher(key)
    users = MemoryUserRepository()
    add_user(users, key, cipher)
    notifications = NotificationService([FakeProvider((Channel.SMS,), status="failed")], MemoryKV())
    await ConfirmationService(notifications, users, cipher).booking_confirmed({"user_id": "u1", "language": "en"}, {"start_time": "2026-11-02T14:00:00"})
