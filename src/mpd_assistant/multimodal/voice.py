"""Speech to text and text to speech through OpenAI-compatible audio endpoints. Audio is never stored."""

from typing import Protocol

import httpx

MAX_AUDIO_BYTES = 10 * 1024 * 1024
AUDIO_TYPES = {"audio/webm", "audio/ogg", "audio/mpeg", "audio/mp4", "audio/wav", "audio/x-wav", "audio/m4a"}
MAX_SPEECH_CHARS = 1500


class VoiceError(RuntimeError):
    pass


class SpeechToText(Protocol):
    async def transcribe(self, audio: bytes, content_type: str, language: str | None = None) -> str: ...


class TextToSpeech(Protocol):
    async def speak(self, text: str, language: str = "en") -> bytes: ...


class OpenAICompatibleSTT:
    def __init__(self, base_url: str, api_key: str, model: str, client: httpx.AsyncClient | None = None, timeout: float = 60.0):
        self._url = base_url.rstrip("/") + "/audio/transcriptions"
        self._key, self._model, self._client, self._timeout = api_key, model, client, timeout

    async def transcribe(self, audio: bytes, content_type: str, language: str | None = None) -> str:
        if len(audio) > MAX_AUDIO_BYTES:
            raise VoiceError("Audio is too long")
        if content_type.split(";")[0].strip() not in AUDIO_TYPES:
            raise VoiceError("Unsupported audio type")
        data = {"model": self._model}
        if language:
            data["language"] = language
        files = {"file": ("audio", audio, content_type)}
        headers = {"Authorization": f"Bearer {self._key}"}
        try:
            if self._client:
                resp = await self._client.post(self._url, data=data, files=files, headers=headers, timeout=self._timeout)
            else:
                async with httpx.AsyncClient() as client:
                    resp = await client.post(self._url, data=data, files=files, headers=headers, timeout=self._timeout)
            resp.raise_for_status()
            return str(resp.json().get("text", "")).strip()[:4000]
        except (httpx.HTTPError, ValueError) as exc:
            raise VoiceError(f"Transcription failed: {type(exc).__name__}") from exc


class OpenAICompatibleTTS:
    def __init__(self, base_url: str, api_key: str, model: str, voices: dict | None = None, client: httpx.AsyncClient | None = None, timeout: float = 60.0):
        self._url = base_url.rstrip("/") + "/audio/speech"
        self._key, self._model, self._client, self._timeout = api_key, model, client, timeout
        self._voices = voices or {"en": "alloy", "fr": "alloy"}

    async def speak(self, text: str, language: str = "en") -> bytes:
        payload = {"model": self._model, "input": text[:MAX_SPEECH_CHARS], "voice": self._voices.get(language, "alloy"), "response_format": "mp3"}
        headers = {"Authorization": f"Bearer {self._key}"}
        try:
            if self._client:
                resp = await self._client.post(self._url, json=payload, headers=headers, timeout=self._timeout)
            else:
                async with httpx.AsyncClient() as client:
                    resp = await client.post(self._url, json=payload, headers=headers, timeout=self._timeout)
            resp.raise_for_status()
            return resp.content
        except httpx.HTTPError as exc:
            raise VoiceError(f"Speech synthesis failed: {type(exc).__name__}") from exc


__all__ = ["AUDIO_TYPES", "OpenAICompatibleSTT", "OpenAICompatibleTTS", "SpeechToText", "TextToSpeech", "VoiceError"]
