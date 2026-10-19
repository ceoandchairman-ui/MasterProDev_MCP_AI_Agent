"""Twilio Voice channel: speech recognition and speech synthesis are done by Twilio (<Gather input="speech"> and
<Say>); this module turns each recognized utterance into one assistant turn and answers with TwiML.

The caller's phone number maps to their verified account exactly as for SMS, so a known caller can book or pay
without re-identifying; an unknown caller is a visitor and gets the same gating as in chat.
"""

from typing import Mapping, Optional
from xml.sax.saxutils import escape, quoteattr

from mpd_assistant.channels.gateway import ChannelGateway
from mpd_assistant.channels.inbound import InboundMessage, parse_twilio_form
from mpd_assistant.core.kv import KeyValueStore
from mpd_assistant.messaging.models import Channel
from mpd_assistant.responses.engine import render
from mpd_assistant.routing.router import detect_language

MAX_TURNS_PER_CALL = 30
MAX_SILENT_PROMPTS = 2
MAX_CALLS_PER_HOUR = 6
CALL_STATE_TTL = 2 * 3600
SPEECH_LANGUAGE = {"en": "en-CA", "fr": "fr-CA"}
MIN_CONFIDENCE = 0.35
_HEADER = '<?xml version="1.0" encoding="UTF-8"?>'


def _say(text: str, language: str) -> str:
    return f"<Say language={quoteattr(SPEECH_LANGUAGE.get(language, 'en-CA'))}>{escape(text)}</Say>"


def gather(prompt: str, action_url: str, language: str = "en") -> str:
    """Speak the prompt, then listen; the recognized text is posted to action_url."""
    lang = SPEECH_LANGUAGE.get(language, "en-CA")
    return (
        f"{_HEADER}<Response><Gather input=\"speech\" language={quoteattr(lang)} speechTimeout=\"auto\" "
        f"action={quoteattr(action_url)} method=\"POST\">{_say(prompt, language)}</Gather>"
        f"<Redirect method=\"POST\">{escape(action_url)}</Redirect></Response>"
    )


def hangup(text: str, language: str = "en") -> str:
    return f"{_HEADER}<Response>{_say(text, language)}<Hangup/></Response>"


class VoiceGateway:
    def __init__(self, gateway: ChannelGateway, kv: KeyValueStore, action_url: str):
        self._gateway, self._kv, self._action = gateway, kv, action_url

    def _state(self, call_sid: str) -> dict:
        return self._kv.get(f"call:{call_sid}") or {"turns": 0, "silent": 0, "lang": "en"}

    def _save(self, call_sid: str, state: dict) -> None:
        self._kv.set(f"call:{call_sid}", state, CALL_STATE_TTL)

    async def handle(self, form: Mapping[str, str]) -> str:
        """One webhook call from Twilio. Always returns valid TwiML."""
        call_sid = form.get("CallSid", "")
        sender = form.get("From", "")
        parsed = parse_twilio_form({"From": sender, "Body": "x"})
        if not call_sid or parsed is None:
            return hangup(render("temporary_error", "en"))

        if self._kv.get(f"call:{call_sid}") is None:  # first request of this call
            if self._kv.incr(f"callrate:{sender}", 3600) > MAX_CALLS_PER_HOUR:
                return hangup(render("rate_limited", "en"))
            self._save(call_sid, self._state(call_sid))
            return gather(render("voice_welcome", "en"), self._action, "en")
        state = self._state(call_sid)

        speech = (form.get("SpeechResult") or "").strip()
        confidence = _float(form.get("Confidence"))
        if not speech or (confidence is not None and confidence < MIN_CONFIDENCE):
            state["silent"] += 1
            self._save(call_sid, state)
            if state["silent"] > MAX_SILENT_PROMPTS:
                return hangup(render("voice_goodbye", state["lang"]), state["lang"])
            return gather("Sorry, I didn't catch that. Could you say it again?" if state["lang"] == "en" else "Désolé, je n'ai pas compris. Pouvez-vous répéter ?", self._action, state["lang"])

        state["silent"] = 0
        state["turns"] += 1
        state["lang"] = detect_language(speech)
        self._save(call_sid, state)
        if state["turns"] > MAX_TURNS_PER_CALL:
            return hangup(render("voice_goodbye", state["lang"]), state["lang"])

        reply = await self._gateway.handle(InboundMessage(Channel.VOICE, parsed.sender, speech[:1000], call_sid))
        if not reply:
            return gather(render("voice_welcome", state["lang"]), self._action, state["lang"])
        return gather(reply, self._action, state["lang"])


def _float(value: Optional[str]) -> Optional[float]:
    try:
        return float(value) if value not in (None, "") else None
    except ValueError:
        return None


__all__ = ["VoiceGateway", "gather", "hangup"]
