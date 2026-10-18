"""New API (v2). Built by a factory so tests and the deployment inject their own services."""

from dataclasses import dataclass

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware

from mpd_assistant.graph.service import ChatService
from mpd_assistant.identity.normalize import InvalidIdentifier
from mpd_assistant.identity.otp import OtpError
from mpd_assistant.identity.service import IdentityService
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


class VerifyIn(BaseModel):
    session_id: str
    email_code: str = Field(max_length=12)
    phone_code: str = Field(max_length=12)


@dataclass
class Services:
    chat: ChatService
    sessions: SessionService
    identity: IdentityService


def create_app(services: Services) -> FastAPI:
    app = FastAPI(title="MPD Assistant API", docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.post("/v2/chat", response_model=ChatOut)
    async def chat(body: ChatIn):
        session = services.sessions.resume(body.session_id) if body.session_id else None
        if session is None:
            session = services.sessions.create()
        result = await services.chat.chat(session.thread_id, body.message, verified=session.verified, user_id=session.user_id)
        return ChatOut(reply=result.reply, session_id=session.id, escalated=result.escalated, reference=result.reference)

    @app.post("/v2/identity/start", status_code=202)
    async def identity_start(body: StartIn):
        if services.sessions.resume(body.session_id) is None:
            raise HTTPException(status_code=401, detail="Unknown or expired session")
        try:
            services.identity.start(body.session_id, body.name, body.email, body.phone)
        except InvalidIdentifier as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
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
