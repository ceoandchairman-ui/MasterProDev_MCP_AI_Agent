"""New API (v2). Built by a factory so tests and the deployment inject their own services."""

import asyncio
import hmac
import json
import re
from dataclasses import dataclass

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware

from mpd_assistant.channels.gateway import ChannelGateway
from mpd_assistant.channels.inbound import empty_twiml, parse_twilio_form, twiml_reply, validate_twilio_signature
from mpd_assistant.core.kv import KeyValueStore
from mpd_assistant.graph.service import ChatService
from mpd_assistant.identity.abuse import AbuseBlocked
from mpd_assistant.identity.normalize import InvalidIdentifier
from mpd_assistant.identity.otp import OtpError
from mpd_assistant.identity.service import IdentityService
from mpd_assistant.integrations.google_oauth import GoogleOAuth, NotConfigured, OAuthError
from mpd_assistant.observability.metrics import REGISTRY
from mpd_assistant.responses.engine import render
from mpd_assistant.sessions.service import SessionService

MAX_MESSAGE_CHARS = 4000


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
        response.headers.setdefault("Cache-Control", "no-store")
        return response


KEEPALIVE_SECONDS = 5
GUEST_DAILY_MESSAGES = 30
VERIFIED_DAILY_MESSAGES = 300


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _sentences(text: str) -> list:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p for p in parts if p] or [text]


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)
    session_id: str | None = None


class ChatOut(BaseModel):
    reply: str
    session_id: str
    escalated: bool = False
    reference: str | None = None


class StartIn(BaseModel):
    session_id: str
    name: str = Field(max_length=120)
    email: str = Field(max_length=254)
    phone: str = Field(max_length=32)


class ConsentIn(BaseModel):
    session_id: str = Field(max_length=64)
    enabled: bool


class RevokeIn(BaseModel):
    session_id: str = Field(max_length=64)
    target_id: str | None = Field(default=None, max_length=64)


class StatusIn(BaseModel):
    session_id: str = Field(max_length=64)


class VerifyIn(BaseModel):
    session_id: str
    email_code: str = Field(max_length=12)
    phone_code: str = Field(max_length=12)


@dataclass
class Services:
    chat: ChatService
    sessions: SessionService
    identity: IdentityService
    metrics_token: str | None = None
    gateway: ChannelGateway | None = None
    google: GoogleOAuth | None = None
    kv: KeyValueStore | None = None
    turns: object | None = None
    users: object | None = None
    memory_store: object | None = None
    twilio_auth_token: str | None = None
    public_url: str | None = None  # externally visible base URL; Twilio signs the exact URL it called


def create_app(services: Services) -> FastAPI:
    app = FastAPI(title="MPD Assistant API", docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/metrics", include_in_schema=False)
    async def metrics(request: Request):
        token = services.metrics_token
        supplied = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
        if not token or not hmac.compare_digest(supplied.encode(), token.encode()):
            raise HTTPException(status_code=401, detail="Unauthorized")
        return Response(generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)

    @app.post("/v2/channels/twilio", include_in_schema=False)
    async def twilio_inbound(request: Request):
        if services.gateway is None or not services.twilio_auth_token or not services.public_url:
            raise HTTPException(status_code=404, detail="Not found")
        form = {k: str(v) for k, v in (await request.form()).items()}
        url = services.public_url.rstrip("/") + "/v2/channels/twilio"
        if not validate_twilio_signature(services.twilio_auth_token, url, form, request.headers.get("x-twilio-signature")):
            raise HTTPException(status_code=403, detail="Invalid signature")
        inbound = parse_twilio_form(form)
        reply = await services.gateway.handle(inbound) if inbound else None
        return Response(twiml_reply(reply) if reply else empty_twiml(), media_type="application/xml")

    async def _run_chat(body: ChatIn) -> ChatOut:
        session = services.sessions.resume(body.session_id) if body.session_id else None
        if session is None:
            session = services.sessions.create()
        if services.kv is not None:
            limit = VERIFIED_DAILY_MESSAGES if session.verified else GUEST_DAILY_MESSAGES
            if services.kv.incr(f"quota:{session.id}", 86400) > limit:
                return ChatOut(reply=render("rate_limited", "en"), session_id=session.id)
        result = await services.chat.chat(
            session.thread_id, body.message, verified=session.verified, user_id=session.user_id, session_row=session.id
        )
        if services.turns is not None:
            services.turns.record(session.id, result.safe_user_text, result.reply, result.intent, result.agent, result.mode)
        return ChatOut(reply=result.reply, session_id=session.id, escalated=result.escalated, reference=result.reference)

    @app.post("/v2/chat", response_model=ChatOut)
    async def chat(body: ChatIn):
        return await _run_chat(body)

    @app.post("/v2/chat/stream")
    async def chat_stream(body: ChatIn):
        """Server-sent events: an immediate 'thinking' event, keepalives while the assistant works, then the reply in
        sentence-sized chunks. The reply is produced whole and then split, so this is progressive display, not
        token-level streaming."""
        task = asyncio.create_task(_run_chat(body))

        async def events():
            yield _sse({"type": "thinking"})
            try:
                while not task.done():
                    await asyncio.wait({task}, timeout=KEEPALIVE_SECONDS)
                    if not task.done():
                        yield ": keepalive\n\n"
                out = task.result()
            except Exception:
                yield _sse({"type": "error", "text": render("temporary_error", "en")})
                return
            for piece in _sentences(out.reply):
                yield _sse({"type": "chunk", "text": piece})
            yield _sse({"type": "done", "session_id": out.session_id, "escalated": out.escalated, "reference": out.reference})

        return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    def _verified_session(session_id: str):
        session = services.sessions.resume(session_id) if session_id else None
        if session is None or not session.verified or not session.user_id:
            raise HTTPException(status_code=403, detail="Verify your email and phone first")
        return session

    def _google():
        if services.google is None or not services.google.configured:
            raise HTTPException(status_code=503, detail="Google integration is not configured")
        return services.google

    @app.get("/v2/integrations/google/status")
    async def google_status(session_id: str):
        session = _verified_session(session_id)
        return {"connected": bool(services.google and services.google.is_connected(session.user_id))}

    @app.get("/v2/integrations/google/start")
    async def google_start(session_id: str):
        session = _verified_session(session_id)
        try:
            return {"url": _google().authorize_url(session.user_id)}
        except NotConfigured as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get("/v2/integrations/google/callback")
    async def google_callback(state: str = "", code: str = ""):
        try:
            await _google().complete(state, code)
        except (OAuthError, NotConfigured):
            raise HTTPException(status_code=400, detail="Google connection failed; please try again") from None
        return {"status": "connected"}

    @app.post("/v2/integrations/google/disconnect")
    async def google_disconnect(body: StatusIn):
        session = _verified_session(body.session_id)
        removed = _google().disconnect(session.user_id)
        return {"status": "disconnected" if removed else "not_connected"}

    @app.get("/v2/account/sessions")
    async def account_sessions(session_id: str):
        session = _verified_session(session_id)
        rows = services.sessions.list_active(session.user_id)
        return {
            "sessions": [
                {"id": s.id[-6:], "current": s.id == session.id, "created_at": s.created_at, "last_seen": s.last_seen} for s in rows
            ]
        }

    @app.post("/v2/account/sessions/revoke")
    async def account_revoke(body: RevokeIn):
        """Sign out one device (by the short id shown in the list) or, without a target, every other device."""
        session = _verified_session(body.session_id)
        if body.target_id is None:
            return {"revoked": services.sessions.revoke_others(session.user_id, session.id)}
        for s in services.sessions.list_active(session.user_id):
            if s.id.endswith(body.target_id) and s.id != session.id:
                services.sessions.revoke(s.id)
                return {"revoked": 1}
        raise HTTPException(status_code=404, detail="Session not found")

    @app.post("/v2/memory/consent")
    async def memory_consent(body: ConsentIn):
        session = _verified_session(body.session_id)
        if services.users is None:
            raise HTTPException(status_code=503, detail="Memory is not available")
        services.users.set_memory_consent(session.user_id, body.enabled)
        if not body.enabled and services.memory_store is not None:
            services.memory_store.delete_all(session.user_id)  # withdrawing consent also forgets what was stored
        return {"memory": "on" if body.enabled else "off"}

    @app.get("/v2/memory")
    async def memory_list(session_id: str):
        session = _verified_session(session_id)
        items = services.memory_store.export(session.user_id) if services.memory_store is not None else []
        return {"memories": [{"id": m["id"], "kind": m["kind"], "text": m["text"]} for m in items if m.get("valid_to") is None]}

    @app.post("/v2/memory/forget")
    async def memory_forget(body: StatusIn):
        session = _verified_session(body.session_id)
        removed = services.memory_store.delete_all(session.user_id) if services.memory_store is not None else 0
        return {"forgotten": removed}

    @app.post("/v2/identity/start", status_code=202)
    async def identity_start(body: StartIn, request: Request):
        if services.sessions.resume(body.session_id) is None:
            raise HTTPException(status_code=401, detail="Unknown or expired session")
        try:
            await services.identity.start(
                body.session_id, body.name, body.email, body.phone, client_ip=request.client.host if request.client else None
            )
        except InvalidIdentifier as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except AbuseBlocked as exc:
            raise HTTPException(status_code=429, detail="Too many attempts. Please try again later.") from exc
        except OtpError as exc:
            raise HTTPException(status_code=429, detail=str(exc)) from exc
        return {"status": "codes_sent"}

    @app.post("/v2/identity/verify")
    async def identity_verify(body: VerifyIn):
        if services.sessions.resume(body.session_id) is None:
            raise HTTPException(status_code=401, detail="Unknown or expired session")
        user = services.identity.verify(body.session_id, body.email_code, body.phone_code)
        if user is None:
            raise HTTPException(status_code=400, detail="Verification failed")
        services.sessions.upgrade_to_verified(body.session_id, user.id)
        return {"status": "verified"}

    return app
