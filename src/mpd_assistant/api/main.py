"""New API (v2). Built by a factory so tests and the deployment inject their own services."""

import asyncio
import base64
import hmac
import json
import re
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware

from mpd_assistant.business.payments import InvalidSignature
from mpd_assistant.business.people import MergeError
from mpd_assistant.channels.email_inbound import valid_token
from mpd_assistant.channels.gateway import ChannelGateway
from mpd_assistant.channels.inbound import empty_twiml, parse_twilio_form, twiml_reply, validate_twilio_signature
from mpd_assistant.core.kv import KeyValueStore
from mpd_assistant.core.resilience import infrastructure_failure
from mpd_assistant.graph.service import ChatService
from mpd_assistant.identity.abuse import AbuseBlocked
from mpd_assistant.identity.normalize import InvalidIdentifier
from mpd_assistant.identity.otp import OtpError
from mpd_assistant.identity.service import IdentityService
from mpd_assistant.integrations.google_oauth import GoogleOAuth, NotConfigured, OAuthError
from mpd_assistant.multimodal.uploads import UploadRejected
from mpd_assistant.multimodal.voice import MAX_AUDIO_BYTES, VoiceError
from mpd_assistant.observability.metrics import DEGRADED, PAYMENTS, REGISTRY, UPLOADS
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


ADMIN_UI_DIR = Path(__file__).parent / "static" / "admin"
ADMIN_UI_ASSETS = {"admin.js": "text/javascript", "admin.css": "text/css"}  # a fixed list, so no path can reach anything else
ADMIN_UI_HEADERS = {
    "Content-Security-Policy": "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
    "Cache-Control": "no-store",
}

MAX_UPLOADS_PER_HOUR = 20
MAX_VOICE_PER_HOUR = 60
EDGE_LIMITED_PREFIXES = ("/v2/chat", "/v2/voice", "/v2/upload", "/v2/identity", "/v2/session", "/v2/account")
EDGE_REQUESTS_PER_MINUTE = 120


def client_ip(request: Request, trusted_hops: int = 1) -> str:
    """The caller's address behind `trusted_hops` proxies. X-Forwarded-For is read from the right, because each
    trusted proxy appends the address it saw; entries further left are whatever the client chose to send."""
    forwarded = [p.strip() for p in request.headers.get("x-forwarded-for", "").split(",") if p.strip()]
    if trusted_hops > 0 and len(forwarded) >= trusted_hops:
        return forwarded[-trusted_hops]
    return request.client.host if request.client else "unknown"


class EdgeRateLimitMiddleware(BaseHTTPMiddleware):
    """Per-IP request ceiling in front of the chat and account routes. Provider webhooks are authenticated by signature
    or secret and are not limited here."""

    def __init__(self, app, kv: KeyValueStore, per_minute: int, trusted_hops: int):
        super().__init__(app)
        self._kv, self._limit, self._hops = kv, per_minute, trusted_hops

    async def dispatch(self, request: Request, call_next):
        if request.url.path.startswith(EDGE_LIMITED_PREFIXES) and request.method != "OPTIONS":
            if await run_in_threadpool(self._kv.incr, f"edge:{client_ip(request, self._hops)}", 60) > self._limit:
                return Response("Too many requests", status_code=429, headers={"Retry-After": "60"})
        return await call_next(request)


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


class CodeIn(BaseModel):
    session_id: str = Field(max_length=64)
    code: str = Field(max_length=12)


class NameIn(BaseModel):
    session_id: str = Field(max_length=64)
    name: str = Field(max_length=120)


class ContactIn(BaseModel):
    session_id: str = Field(max_length=64)
    kind: Literal["email", "phone"]
    value: str = Field(max_length=254)


class DeleteIn(BaseModel):
    session_id: str = Field(max_length=64)
    confirm: str = Field(max_length=10)


class MergeIn(BaseModel):
    primary_id: str = Field(max_length=64)
    duplicate_id: str = Field(max_length=64)
    confirm: Literal["MERGE"]


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
    account: object | None = None
    dsr: object | None = None
    twilio_auth_token: str | None = None
    public_url: str | None = None  # externally visible base URL; Twilio signs the exact URL it called
    payments: object | None = None
    uploads: object | None = None
    speech_to_text: object | None = None
    text_to_speech: object | None = None
    voice: object | None = None
    cors_origins: tuple = ()
    trusted_proxy_hops: int = 1
    edge_requests_per_minute: int = EDGE_REQUESTS_PER_MINUTE
    email_inbound: object | None = None
    email_inbound_token: str | None = None
    admin: object | None = None
    admin_token: str | None = None
    threadpool_size: int = 64
    entities: object | None = None
    delivery: object | None = None


def create_app(services: Services) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app):
        import anyio

        anyio.to_thread.current_default_thread_limiter().total_tokens = max(8, services.threadpool_size)
        yield

    app = FastAPI(title="MPD Assistant API", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.add_middleware(SecurityHeadersMiddleware)
    if services.kv is not None and services.edge_requests_per_minute > 0:
        app.add_middleware(EdgeRateLimitMiddleware, kv=services.kv, per_minute=services.edge_requests_per_minute, trusted_hops=services.trusted_proxy_hops)
    origins = [o for o in services.cors_origins if o and o != "*"]  # never a wildcard
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_methods=["GET", "POST", "DELETE", "PATCH"],
            allow_headers=["Content-Type"],
            allow_credentials=False,
            max_age=600,
        )

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

    @app.post("/v2/channels/twilio/status", include_in_schema=False)
    async def twilio_status(request: Request):
        """Twilio delivery receipts for messages we sent. Signed like the inbound webhook."""
        if services.delivery is None or not services.twilio_auth_token or not services.public_url:
            raise HTTPException(status_code=404, detail="Not found")
        form = {k: str(v) for k, v in (await request.form()).items()}
        url = services.public_url.rstrip("/") + "/v2/channels/twilio/status"
        if not validate_twilio_signature(services.twilio_auth_token, url, form, request.headers.get("x-twilio-signature")):
            raise HTTPException(status_code=403, detail="Invalid signature")
        return {"status": services.delivery.twilio_status(form)}

    @app.post("/v2/webhooks/sendgrid/{token}", include_in_schema=False)
    async def sendgrid_events(token: str, request: Request):
        """SendGrid event webhook. The secret in the URL is the only authentication, so a wrong token looks like a missing page."""
        if services.delivery is None or not valid_token(token, services.email_inbound_token):
            raise HTTPException(status_code=404, detail="Not found")
        try:
            events = await request.json()
        except ValueError:
            return {"handled": 0}  # a malformed batch would only be retried forever
        return {"handled": services.delivery.sendgrid_events(events) if isinstance(events, list) else 0}

    @app.post("/v2/channels/voice", include_in_schema=False)
    async def twilio_voice(request: Request):
        if services.voice is None or not services.twilio_auth_token or not services.public_url:
            raise HTTPException(status_code=404, detail="Not found")
        form = {k: str(v) for k, v in (await request.form()).items()}
        url = services.public_url.rstrip("/") + "/v2/channels/voice"
        if not validate_twilio_signature(services.twilio_auth_token, url, form, request.headers.get("x-twilio-signature")):
            raise HTTPException(status_code=403, detail="Invalid signature")
        return Response(await services.voice.handle(form), media_type="application/xml")

    def _staff() -> object:
        """Staff endpoints use a bearer token until staff accounts with MFA exist (S0.7)."""
        if services.admin is None:
            raise HTTPException(status_code=404, detail="Not found")
        return services.admin

    def _check_staff(request: Request) -> None:
        supplied = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
        if not services.admin_token or not hmac.compare_digest(supplied.encode(), services.admin_token.encode()):
            raise HTTPException(status_code=401, detail="Unauthorized")

    @app.get("/admin", include_in_schema=False)
    async def admin_console():
        """The staff console page. It holds no data: every call it makes needs the staff token."""
        if services.admin is None:
            raise HTTPException(status_code=404, detail="Not found")
        return FileResponse(ADMIN_UI_DIR / "index.html", media_type="text/html", headers=ADMIN_UI_HEADERS)

    @app.get("/admin/{asset}", include_in_schema=False)
    async def admin_asset(asset: str):
        media = ADMIN_UI_ASSETS.get(asset)
        if services.admin is None or media is None:
            raise HTTPException(status_code=404, detail="Not found")
        return FileResponse(ADMIN_UI_DIR / asset, media_type=media, headers=ADMIN_UI_HEADERS)

    @app.get("/v2/admin/overview", include_in_schema=False)
    def admin_overview(request: Request):
        _check_staff(request)
        return _staff().overview()

    @app.get("/v2/admin/escalations", include_in_schema=False)
    def admin_escalations(request: Request):
        _check_staff(request)
        return {"escalations": [e.__dict__ for e in _staff().list_open()]}

    @app.get("/v2/admin/escalations/{reference}", include_in_schema=False)
    def admin_escalation(reference: str, request: Request):
        _check_staff(request)
        view = _staff().get(reference)
        if view is None:
            raise HTTPException(status_code=404, detail="Not found")
        return view.__dict__

    def _people():
        directory = _staff().people
        if directory is None:
            raise HTTPException(status_code=404, detail="Not found")
        return directory

    @app.get("/v2/admin/people", include_in_schema=False)
    def admin_find_person(request: Request, email: str | None = None, phone: str | None = None):
        _check_staff(request)
        try:
            person = _people().lookup(email=email, phone=phone)
        except InvalidIdentifier as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if person is None:
            raise HTTPException(status_code=404, detail="Not found")
        return person.__dict__

    @app.get("/v2/admin/people/duplicates", include_in_schema=False)
    def admin_duplicates(request: Request):
        _check_staff(request)
        return {"groups": _people().duplicates()}

    @app.post("/v2/admin/people/merge", include_in_schema=False)
    def admin_merge(body: MergeIn, request: Request):
        _check_staff(request)
        try:
            report = _people().merge(body.primary_id, body.duplicate_id)
        except MergeError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"status": "merged", "moved": report.moved}

    @app.post("/v2/admin/cache/purge/{layer}", include_in_schema=False)
    async def admin_purge_cache(layer: str, request: Request):
        _check_staff(request)
        removed = await _staff().purge_cache(layer)
        if removed is None:
            raise HTTPException(status_code=404, detail=f"Unknown cache layer. Available: {', '.join(_staff().cache_layers)}")
        return {"layer": layer, "removed": removed}

    @app.get("/v2/admin/undelivered", include_in_schema=False)
    def admin_undelivered(request: Request):
        _check_staff(request)
        return {"messages": _staff().undelivered()}

    @app.get("/v2/admin/quotes", include_in_schema=False)
    def admin_quotes(request: Request):
        _check_staff(request)
        return {"quotes": _staff().pending_quotes()}

    @app.post("/v2/admin/quotes/{reference}/{decision}", include_in_schema=False)
    async def admin_decide_quote(reference: str, decision: Literal["approve", "reject"], request: Request):
        _check_staff(request)
        outcome = await _staff().decide_quote(reference, decision == "approve")
        if outcome in ("not_found", "not_pending"):
            raise HTTPException(status_code=404 if outcome == "not_found" else 409, detail="Quote not found" if outcome == "not_found" else "Quote is not waiting for review")
        return {"status": outcome}

    @app.get("/v2/admin/patterns", include_in_schema=False)
    def admin_patterns(request: Request):
        _check_staff(request)
        return {"patterns": _staff().pending_patterns()}

    @app.post("/v2/admin/patterns/{pattern_id}/{decision}", include_in_schema=False)
    def admin_review_pattern(pattern_id: str, decision: Literal["approve", "reject"], request: Request):
        _check_staff(request)
        if not _staff().review_pattern(pattern_id, decision == "approve"):
            raise HTTPException(status_code=404, detail="Not found or already reviewed")
        return {"status": "approved" if decision == "approve" else "rejected"}

    @app.post("/v2/admin/escalations/{reference}/resolve", include_in_schema=False)
    def admin_resolve(reference: str, request: Request):
        _check_staff(request)
        if not _staff().resolve(reference):
            raise HTTPException(status_code=404, detail="Not found or already resolved")
        return {"status": "resolved"}

    @app.post("/v2/channels/email/{token}", include_in_schema=False)
    async def email_inbound(token: str, request: Request):
        """SendGrid Inbound Parse. The secret in the URL is the only authentication, so a wrong token looks like a missing page."""
        gateway = services.email_inbound
        if gateway is None or not valid_token(token, services.email_inbound_token):
            raise HTTPException(status_code=404, detail="Not found")
        form = {k: str(v) for k, v in (await request.form()).items() if isinstance(v, str)}
        status = await gateway.handle(form)
        return {"status": status}  # always 200 once authenticated: a retry would only duplicate work

    @app.post("/v2/webhooks/stripe", include_in_schema=False)
    async def stripe_webhook(request: Request):
        """Stripe-signed. This is the only place a quote becomes 'paid'."""
        if services.payments is None or not services.payments.configured:
            raise HTTPException(status_code=404, detail="Not found")
        payload = await request.body()
        try:
            outcome = await services.payments.handle_webhook(payload, request.headers.get("stripe-signature", ""))
        except InvalidSignature:
            PAYMENTS.labels("invalid_signature").inc()
            raise HTTPException(status_code=400, detail="Invalid signature") from None
        PAYMENTS.labels(outcome.status).inc()
        return {"status": outcome.status}

    async def _run_chat(body: ChatIn) -> ChatOut:
        try:
            return await _run_chat_inner(body)
        except HTTPException:
            raise
        except Exception as exc:
            dependency = infrastructure_failure(exc)
            if dependency is None:
                raise
            DEGRADED.labels(dependency).inc()
            raise HTTPException(status_code=503, detail=render("temporary_error", "en"), headers={"Retry-After": "5"}) from None

    async def _run_chat_inner(body: ChatIn) -> ChatOut:
        session = await run_in_threadpool(services.sessions.resume, body.session_id) if body.session_id else None
        if session is None:
            session = await run_in_threadpool(services.sessions.create)
        if services.kv is not None:
            limit = VERIFIED_DAILY_MESSAGES if session.verified else GUEST_DAILY_MESSAGES
            if await run_in_threadpool(services.kv.incr, f"quota:{session.id}", 86400) > limit:
                return ChatOut(reply=render("rate_limited", "en"), session_id=session.id)
        result = await services.chat.chat(
            session.thread_id, body.message, verified=session.verified, user_id=session.user_id, session_row=session.id
        )
        if services.turns is not None and result.safe_user_text:
            try:
                await run_in_threadpool(services.turns.record, session.id, result.safe_user_text, result.reply, result.intent, result.agent, result.mode)
            except Exception as exc:
                # A lost history row is better than a failed reply; it shows up in the metric and the log.
                DEGRADED.labels(infrastructure_failure(exc) or "turn_record").inc()
        return ChatOut(reply=result.reply, session_id=session.id, escalated=result.escalated, reference=result.reference)

    @app.post("/v2/session", status_code=201)
    def new_session():
        """A visitor session without sending a message, so the widget can run sign-in before the first question."""
        session = services.sessions.create()
        return {"session_id": session.id, "verified": False}

    @app.get("/v2/session/{session_id}")
    def session_status(session_id: str):
        session = services.sessions.resume(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Unknown or expired session")
        return {"session_id": session.id, "verified": session.verified}

    @app.post("/v2/session/{session_id}/end")
    async def end_session(session_id: str):
        """The user closed the conversation: keep a short episode (with consent) and clear working state."""
        session = services.sessions.resume(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Unknown or expired session")
        await services.chat.end_conversation(session.thread_id, session.user_id, "closed")
        return {"status": "ended"}

    @app.post("/v2/upload", status_code=201)
    async def upload(session_id: str = Form(max_length=64), file: UploadFile = File(...)):
        """A file the user wants to talk about. Verified users only; the text is kept for this conversation, not forever."""
        if services.uploads is None:
            raise HTTPException(status_code=503, detail="Uploads are not available")
        session = await run_in_threadpool(_verified_session, session_id)
        if services.kv is not None and await run_in_threadpool(services.kv.incr, f"uploadrate:{session.id}", 3600) > MAX_UPLOADS_PER_HOUR:
            raise HTTPException(status_code=429, detail="Too many uploads. Please try again later.")
        data = await file.read(services.uploads.max_bytes + 1)
        try:
            result = await services.uploads.accept(session.thread_id, session.id, file.filename or "file", data)
        except UploadRejected as exc:
            UPLOADS.labels("unknown", exc.reason).inc()
            raise HTTPException(status_code=422, detail=render("upload_rejected", "en", {"limit": "10 MB"})) from exc
        UPLOADS.labels(result.kind, "accepted").inc()
        if services.entities is not None:
            services.entities.remember(session.thread_id, "document", result.id, result.kind)  # so "that file" resolves later
        return {"id": result.id, "kind": result.kind, "note": result.note}

    @app.delete("/v2/upload/{upload_id}")
    def delete_upload(upload_id: str, session_id: str):
        if services.uploads is None:
            raise HTTPException(status_code=503, detail="Uploads are not available")
        session = _verified_session(session_id)
        return {"removed": services.uploads.remove(session.thread_id, upload_id)}

    @app.post("/v2/voice")
    async def voice(request: Request, session_id: str = Form(max_length=64), audio: UploadFile = File(...), speak: bool = Form(False)):
        """Speech in, text reply out (and spoken reply when asked). Audio is transcribed and discarded, never stored."""
        if services.speech_to_text is None:
            raise HTTPException(status_code=503, detail=render("voice_unavailable", "en"))
        session = await run_in_threadpool(services.sessions.resume, session_id)
        if session is None:
            raise HTTPException(status_code=401, detail="Unknown or expired session")
        if services.kv is not None and await run_in_threadpool(services.kv.incr, f"voicerate:{session.id}", 3600) > (MAX_VOICE_PER_HOUR if session.verified else MAX_VOICE_PER_HOUR // 3):
            raise HTTPException(status_code=429, detail=render("rate_limited", "en"))
        data = await audio.read(MAX_AUDIO_BYTES + 1)
        try:
            transcript = await services.speech_to_text.transcribe(data, audio.content_type or "")
        except VoiceError as exc:
            raise HTTPException(status_code=422, detail=render("voice_unavailable", "en")) from exc
        if not transcript:
            raise HTTPException(status_code=422, detail=render("voice_unavailable", "en"))
        out = await _run_chat(ChatIn(message=transcript[:MAX_MESSAGE_CHARS], session_id=session.id))
        payload = {"transcript": transcript, "reply": out.reply, "session_id": out.session_id, "escalated": out.escalated, "reference": out.reference}
        if speak and services.text_to_speech is not None:
            try:
                payload["audio_base64"] = base64.b64encode(await services.text_to_speech.speak(out.reply)).decode()
            except VoiceError:
                pass  # the text reply still goes out
        return payload

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
    def google_status(session_id: str):
        session = _verified_session(session_id)
        return {"connected": bool(services.google and services.google.is_connected(session.user_id))}

    @app.get("/v2/integrations/google/start")
    def google_start(session_id: str):
        session = _verified_session(session_id)
        if services.account is not None:
            _recent(session)
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
    def google_disconnect(body: StatusIn):
        session = _verified_session(body.session_id)
        removed = _google().disconnect(session.user_id)
        return {"status": "disconnected" if removed else "not_connected"}

    def _account():
        if services.account is None:
            raise HTTPException(status_code=503, detail="Account management is not available")
        return services.account

    def _recent(session):
        """Sensitive actions need a verification code entered in the last 15 minutes."""
        if not _account().has_recent(session.id):
            raise HTTPException(status_code=403, detail="step_up_required")

    @app.post("/v2/account/stepup/start", status_code=202)
    async def stepup_start(body: StatusIn):
        session = _verified_session(body.session_id)
        try:
            await _account().stepup_start(session.user_id)
        except OtpError as exc:
            raise HTTPException(status_code=429, detail=str(exc)) from exc
        return {"status": "code_sent"}

    @app.post("/v2/account/stepup/verify")
    def stepup_verify(body: CodeIn):
        session = _verified_session(body.session_id)
        if not _account().stepup_verify(session.id, session.user_id, body.code):
            raise HTTPException(status_code=400, detail="Verification failed")
        return {"status": "verified"}

    @app.patch("/v2/account/profile")
    def update_profile(body: NameIn):
        session = _verified_session(body.session_id)
        try:
            _account().update_name(session.user_id, body.name)
        except InvalidIdentifier as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"status": "updated"}

    @app.post("/v2/account/contact/start", status_code=202)
    async def contact_start(body: ContactIn):
        session = _verified_session(body.session_id)
        _recent(session)
        try:
            await _account().contact_start(session.user_id, body.kind, body.value)
        except InvalidIdentifier as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except OtpError as exc:
            raise HTTPException(status_code=429, detail=str(exc)) from exc
        return {"status": "code_sent"}

    @app.post("/v2/account/contact/verify")
    async def contact_verify(body: CodeIn):
        session = _verified_session(body.session_id)
        _recent(session)
        if not await _account().contact_verify(session.user_id, body.code):
            raise HTTPException(status_code=400, detail="Verification failed")
        return {"status": "updated"}

    @app.get("/v2/account/export")
    def account_export(session_id: str):
        session = _verified_session(session_id)
        _recent(session)
        if services.dsr is None:
            raise HTTPException(status_code=503, detail="Export is not available")
        return services.dsr.export(session.user_id)

    @app.post("/v2/account/delete")
    def account_delete(body: DeleteIn):
        session = _verified_session(body.session_id)
        _recent(session)
        if body.confirm != "DELETE":
            raise HTTPException(status_code=422, detail='Type "DELETE" to confirm')
        if services.dsr is None:
            raise HTTPException(status_code=503, detail="Deletion is not available")
        services.sessions.revoke_all_for_user(session.user_id)
        report = services.dsr.erase(session.user_id)
        return {"status": "deleted" if report.complete else "partial"}

    @app.get("/v2/account/sessions")
    def account_sessions(session_id: str):
        session = _verified_session(session_id)
        rows = services.sessions.list_active(session.user_id)
        return {
            "sessions": [
                {"id": s.id[-6:], "current": s.id == session.id, "created_at": s.created_at, "last_seen": s.last_seen} for s in rows
            ]
        }

    @app.post("/v2/account/sessions/revoke")
    def account_revoke(body: RevokeIn):
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
    def memory_consent(body: ConsentIn):
        session = _verified_session(body.session_id)
        if services.users is None:
            raise HTTPException(status_code=503, detail="Memory is not available")
        services.users.set_memory_consent(session.user_id, body.enabled)
        if not body.enabled and services.memory_store is not None:
            services.memory_store.delete_all(session.user_id)  # withdrawing consent also forgets what was stored
        return {"memory": "on" if body.enabled else "off"}

    @app.get("/v2/memory")
    def memory_list(session_id: str):
        session = _verified_session(session_id)
        items = services.memory_store.export(session.user_id) if services.memory_store is not None else []
        return {"memories": [{"id": m["id"], "kind": m["kind"], "text": m["text"]} for m in items if m.get("valid_to") is None]}

    @app.post("/v2/memory/forget")
    def memory_forget(body: StatusIn):
        session = _verified_session(body.session_id)
        removed = services.memory_store.delete_all(session.user_id) if services.memory_store is not None else 0
        return {"forgotten": removed}

    @app.post("/v2/identity/start", status_code=202)
    async def identity_start(body: StartIn, request: Request):
        if services.sessions.resume(body.session_id) is None:
            raise HTTPException(status_code=401, detail="Unknown or expired session")
        try:
            await services.identity.start(
                body.session_id, body.name, body.email, body.phone, client_ip=client_ip(request, services.trusted_proxy_hops)
            )
        except InvalidIdentifier as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except AbuseBlocked as exc:
            raise HTTPException(status_code=429, detail="Too many attempts. Please try again later.") from exc
        except OtpError as exc:
            raise HTTPException(status_code=429, detail=str(exc)) from exc
        return {"status": "codes_sent"}

    @app.post("/v2/identity/verify")
    def identity_verify(body: VerifyIn):
        if services.sessions.resume(body.session_id) is None:
            raise HTTPException(status_code=401, detail="Unknown or expired session")
        user = services.identity.verify(body.session_id, body.email_code, body.phone_code)
        if user is None:
            raise HTTPException(status_code=400, detail="Verification failed")
        services.sessions.upgrade_to_verified(body.session_id, user.id)
        if services.account is not None:
            services.account.mark_recent(body.session_id)  # a fresh sign-in counts as a recent verification
        return {"status": "verified"}

    return app
