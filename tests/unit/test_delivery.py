"""Delivery tracking: retries for transient failures, provider receipts, dead letters and the webhooks."""

from fastapi.testclient import TestClient

from mpd_assistant.api.main import Services, create_app
from mpd_assistant.channels.inbound import twilio_signature
from mpd_assistant.core.kv import MemoryKV
from mpd_assistant.messaging.delivery import DeliveryTracker, transient
from mpd_assistant.messaging.models import Channel, OutboundMessage, SendResult
from mpd_assistant.messaging.service import NotificationService


class Provider:
    channels = frozenset({Channel.SMS, Channel.EMAIL})

    def __init__(self, results):
        self.results, self.calls = list(results), 0

    async def send(self, channel, to, body, subject=None):
        self.calls += 1
        return self.results.pop(0) if self.results else SendResult("sent", provider_id=f"id{self.calls}")


def service(provider, tracker=None, delays=(0.5, 1.5)):
    slept = []

    async def sleep(seconds):
        slept.append(seconds)

    svc = NotificationService([provider], MemoryKV(), tracker=tracker, sleep=sleep, retry_delays=delays)
    return svc, slept


def message(**kw):
    return OutboundMessage(Channel.SMS, "+14165550123", "booking_confirmed", "en", {"when": "tomorrow"}, **kw)


def test_transient_reasons():
    for reason in ("network_ReadTimeout", "twilio_503", "twilio_503_30008", "twilio_429", "sendgrid_502"):
        assert transient(reason), reason
    for reason in ("twilio_400_21211", "twilio_401", "sendgrid_400", "unknown_template", "no_provider", ""):
        assert not transient(reason), reason


async def test_transient_failures_are_retried_with_growing_pauses():
    provider = Provider([SendResult("failed", reason="twilio_503"), SendResult("failed", reason="network_ReadTimeout")])
    svc, slept = service(provider)
    result = await svc.send(message())
    assert result.status == "sent" and provider.calls == 3 and slept == [0.5, 1.5]


async def test_retries_stop_after_the_last_delay_and_skip_permanent_failures():
    provider = Provider([SendResult("failed", reason="twilio_503")] * 5)
    svc, slept = service(provider)
    assert (await svc.send(message())).status == "failed" and provider.calls == 3 and slept == [0.5, 1.5]
    permanent = Provider([SendResult("failed", reason="twilio_400_21211")])
    svc, slept = service(permanent)
    assert (await svc.send(message())).status == "failed" and permanent.calls == 1 and slept == []


async def test_sent_messages_are_tracked_by_masked_target():
    kv = MemoryKV()
    tracker = DeliveryTracker(kv)
    svc, _ = service(Provider([SendResult("sent", provider_id="SM1")]), tracker)
    await svc.send(message())
    record = kv.get("deliv:SM1")
    assert record["template"] == "booking_confirmed" and "4165550123" not in str(record) and record["status"] == "sent"


def test_twilio_receipts_update_status_and_failures_become_dead_letters():
    kv = MemoryKV()
    tracker = DeliveryTracker(kv, clock=lambda: 1000.0)
    tracker.sent("SM1", Channel.SMS, "+14165550123", "booking_confirmed", "transactional")
    assert tracker.twilio_status({"MessageSid": "SM1", "MessageStatus": "queued"}) == "pending"
    assert tracker.twilio_status({"MessageSid": "SM1", "MessageStatus": "delivered"}) == "delivered" and kv.get("deliv:SM1")["status"] == "delivered"
    assert tracker.dead_letters() == []
    tracker.sent("SM2", Channel.SMS, "+14165550199", "otp", "transactional")
    assert tracker.twilio_status({"MessageSid": "SM2", "MessageStatus": "undelivered", "ErrorCode": "30003"}) == "failed"
    letters = tracker.dead_letters()
    assert len(letters) == 1 and letters[0]["code"] == "30003" and letters[0]["template"] == "otp" and "4165550199" not in str(letters)
    assert tracker.twilio_status({"MessageStatus": "sent"}) == "ignored" and tracker.twilio_status({}) == "ignored"


def test_sendgrid_batches_are_handled_and_junk_is_skipped():
    tracker = DeliveryTracker(MemoryKV(), clock=lambda: 5.0)
    tracker.sent("abc123", Channel.EMAIL, "ann@example.com", "payment_received", "transactional")
    handled = tracker.sendgrid_events([
        {"event": "delivered", "sg_message_id": "abc123.filter0001"},
        {"event": "bounce", "sg_message_id": "abc123.filter0002", "reason": "550 mailbox full"},
        {"event": "open", "sg_message_id": "abc123.f"},
        "junk", {"event": "delivered"},
    ])
    assert handled == 3  # delivered, bounce and open are understood; the junk entries are not
    letters = tracker.dead_letters()
    assert len(letters) == 1 and letters[0]["channel"] == "email" and "ann@example.com" not in str(letters)


def test_dead_letters_keep_only_the_newest_slots():
    tracker = DeliveryTracker(MemoryKV(), clock=iter(range(10_000)).__next__)
    for i in range(250):
        tracker.twilio_status({"MessageSid": f"SM{i}", "MessageStatus": "failed"})
    letters = tracker.dead_letters(limit=500)
    assert len(letters) == 200 and letters == sorted(letters, key=lambda x: x["at"], reverse=True)


# --- webhooks ------------------------------------------------------------------------------
def client(delivery):
    services = Services(chat=None, sessions=None, identity=None, delivery=delivery, twilio_auth_token="tok", public_url="https://api.example.com", email_inbound_token="secret", kv=None)
    return TestClient(create_app(services))


def test_twilio_status_webhook_requires_a_valid_signature():
    delivery = DeliveryTracker(MemoryKV())
    delivery.sent("SM9", Channel.SMS, "+14165550123", "otp", "transactional")
    c = client(delivery)
    form = {"MessageSid": "SM9", "MessageStatus": "failed", "ErrorCode": "30008"}
    url = "https://api.example.com/v2/channels/twilio/status"
    assert c.post("/v2/channels/twilio/status", data=form).status_code == 403
    assert c.post("/v2/channels/twilio/status", data=form, headers={"X-Twilio-Signature": "forged"}).status_code == 403
    ok = c.post("/v2/channels/twilio/status", data=form, headers={"X-Twilio-Signature": twilio_signature("tok", url, form)})
    assert ok.json() == {"status": "failed"} and delivery.dead_letters()[0]["code"] == "30008"


def test_sendgrid_webhook_hides_behind_its_token_and_survives_bad_bodies():
    delivery = DeliveryTracker(MemoryKV())
    c = client(delivery)
    batch = [{"event": "delivered", "sg_message_id": "zzz.1"}]
    assert c.post("/v2/webhooks/sendgrid/wrong", json=batch).status_code == 404
    assert c.post("/v2/webhooks/sendgrid/secret", json=batch).json() == {"handled": 1}
    assert c.post("/v2/webhooks/sendgrid/secret", content=b"not json").json() == {"handled": 0}
    assert c.post("/v2/webhooks/sendgrid/secret", json={"not": "a list"}).json() == {"handled": 0}


def test_admin_overview_counts_undelivered_messages():
    from mpd_assistant.business.admin import AdminService
    from mpd_assistant.business.escalations import EscalationService, InMemoryEscalations

    delivery = DeliveryTracker(MemoryKV())
    delivery.twilio_status({"MessageSid": "SM1", "MessageStatus": "failed"})
    admin = AdminService(EscalationService(repo=InMemoryEscalations()), InMemoryEscalations(), delivery=delivery)
    assert admin.overview()["undelivered_messages"] == 1 and len(admin.undelivered()) == 1
