"""Provider wrappers. Credentials and response bodies are never copied into errors or logs."""

from typing import Optional

import httpx

from mpd_assistant.messaging.models import Channel, SendResult

TWILIO_API = "https://api.twilio.com/2010-04-01"
SENDGRID_API = "https://api.sendgrid.com/v3/mail/send"


class TwilioProvider:
    """SMS and WhatsApp through the Twilio Messages REST API."""

    channels = frozenset({Channel.SMS, Channel.WHATSAPP})

    def __init__(
        self,
        account_sid: str,
        auth_token: str,
        sms_from: Optional[str] = None,
        whatsapp_from: Optional[str] = None,
        status_callback_url: Optional[str] = None,
        client: Optional[httpx.AsyncClient] = None,
        timeout: float = 10.0,
    ):
        self._sid, self._token = account_sid, auth_token
        self._sms_from, self._wa_from = sms_from, whatsapp_from
        self._callback = status_callback_url
        self._client = client
        self._timeout = timeout

    def _addresses(self, channel: Channel, to: str):
        if channel is Channel.WHATSAPP:
            return (f"whatsapp:{to}", f"whatsapp:{self._wa_from}") if self._wa_from else (None, None)
        return (to, self._sms_from) if self._sms_from else (None, None)

    async def send(self, channel: Channel, to: str, body: str, subject: Optional[str] = None) -> SendResult:
        to_addr, from_addr = self._addresses(channel, to)
        if not to_addr or not from_addr:
            return SendResult("failed", reason="channel_not_configured")
        data = {"To": to_addr, "From": from_addr, "Body": body}
        if self._callback:
            data["StatusCallback"] = self._callback
        url = f"{TWILIO_API}/Accounts/{self._sid}/Messages.json"
        try:
            if self._client:
                resp = await self._client.post(url, data=data, auth=(self._sid, self._token), timeout=self._timeout)
            else:
                async with httpx.AsyncClient() as client:
                    resp = await client.post(url, data=data, auth=(self._sid, self._token), timeout=self._timeout)
        except httpx.HTTPError as exc:
            return SendResult("failed", reason=f"network_{type(exc).__name__}")
        if resp.status_code in (200, 201):
            return SendResult("sent", provider_id=resp.json().get("sid"))
        try:
            code = resp.json().get("code")
        except ValueError:
            code = None
        return SendResult("failed", reason=f"twilio_{resp.status_code}_{code}" if code else f"twilio_{resp.status_code}")


class SendGridProvider:
    """Transactional email through the SendGrid v3 mail API."""

    channels = frozenset({Channel.EMAIL})

    def __init__(self, api_key: str, from_email: str, from_name: str = "MasterProDev", client: Optional[httpx.AsyncClient] = None, timeout: float = 10.0):
        self._key, self._from, self._name = api_key, from_email, from_name
        self._client = client
        self._timeout = timeout

    async def send(self, channel: Channel, to: str, body: str, subject: Optional[str] = None) -> SendResult:
        payload = {
            "personalizations": [{"to": [{"email": to}]}],
            "from": {"email": self._from, "name": self._name},
            "subject": subject or "Message from MasterProDev",
            "content": [{"type": "text/plain", "value": body}],
        }
        headers = {"Authorization": f"Bearer {self._key}"}
        try:
            if self._client:
                resp = await self._client.post(SENDGRID_API, json=payload, headers=headers, timeout=self._timeout)
            else:
                async with httpx.AsyncClient() as client:
                    resp = await client.post(SENDGRID_API, json=payload, headers=headers, timeout=self._timeout)
        except httpx.HTTPError as exc:
            return SendResult("failed", reason=f"network_{type(exc).__name__}")
        if resp.status_code == 202:
            return SendResult("sent", provider_id=resp.headers.get("x-message-id"))
        return SendResult("failed", reason=f"sendgrid_{resp.status_code}")
