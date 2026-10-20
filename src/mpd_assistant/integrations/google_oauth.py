"""Per-user Google OAuth: authorization with a single-use state, encrypted refresh tokens, short-lived access tokens.

Credentials come from configuration. Without a client id the feature reports itself as not configured.
"""

import secrets
from datetime import UTC, datetime
from urllib.parse import urlencode

import httpx
from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import Session as DbSession

from mpd_assistant.core.crypto import FieldCipher
from mpd_assistant.core.kv import KeyValueStore
from mpd_assistant.core.models import OAuthToken

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
STATE_TTL_SECONDS = 600
ACCESS_CACHE_SECONDS = 50 * 60
PROVIDER = "google"
SCOPES = (
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/gmail.modify",
)


class NotConfigured(RuntimeError):
    pass


class OAuthError(RuntimeError):
    pass


class GoogleOAuth:
    def __init__(
        self,
        engine: Engine,
        kv: KeyValueStore,
        cipher: FieldCipher,
        client_id: str | None,
        client_secret: str | None,
        redirect_uri: str | None,
        http: httpx.AsyncClient | None = None,
    ):
        self._engine, self._kv, self._cipher = engine, kv, cipher
        self._client_id, self._client_secret, self._redirect = client_id, client_secret, redirect_uri
        self._http = http

    @property
    def configured(self) -> bool:
        return bool(self._client_id and self._client_secret and self._redirect)

    def _require(self) -> None:
        if not self.configured:
            raise NotConfigured("Google OAuth is not configured")

    def authorize_url(self, user_id: str) -> str:
        self._require()
        state = secrets.token_urlsafe(32)
        self._kv.set(f"oauth-state:{state}", {"user_id": user_id}, STATE_TTL_SECONDS)
        params = {
            "client_id": self._client_id,
            "redirect_uri": self._redirect,
            "response_type": "code",
            "scope": " ".join(SCOPES),
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
        return f"{AUTH_URL}?{urlencode(params)}"

    async def complete(self, state: str, code: str) -> str:
        """Consumes the state (single use), exchanges the code and stores the refresh token. Returns the user id."""
        self._require()
        bound = self._kv.get(f"oauth-state:{state}") if state else None
        if state:
            self._kv.delete(f"oauth-state:{state}")  # consumed whether or not the exchange succeeds
        if not bound or not code:
            raise OAuthError("Invalid or expired authorization")
        data = await self._post(
            {
                "code": code,
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "redirect_uri": self._redirect,
                "grant_type": "authorization_code",
            }
        )
        refresh = data.get("refresh_token")
        if not refresh:
            raise OAuthError("Google did not return a refresh token")
        self._save(bound["user_id"], refresh)
        self._kv.set(f"oauth-access:{PROVIDER}:{bound['user_id']}", self._cipher.encrypt(data["access_token"]), ACCESS_CACHE_SECONDS)
        return bound["user_id"]

    async def access_token(self, user_id: str) -> str | None:
        """Current access token for the user, refreshed when needed. None if the user never connected."""
        if not self.configured:
            return None
        cached = self._kv.get(f"oauth-access:{PROVIDER}:{user_id}")
        if cached:
            return self._cipher.decrypt(cached)
        refresh = self._load(user_id)
        if refresh is None:
            return None
        try:
            data = await self._post(
                {
                    "refresh_token": refresh,
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "grant_type": "refresh_token",
                }
            )
        except OAuthError:
            self.disconnect(user_id)  # revoked or expired grant: the user must connect again
            return None
        self._kv.set(f"oauth-access:{PROVIDER}:{user_id}", self._cipher.encrypt(data["access_token"]), ACCESS_CACHE_SECONDS)
        return data["access_token"]

    def disconnect(self, user_id: str) -> bool:
        with DbSession(self._engine) as db:
            removed = db.execute(delete(OAuthToken).where(OAuthToken.user_id == user_id, OAuthToken.provider == PROVIDER)).rowcount
            db.commit()
        self._kv.delete(f"oauth-access:{PROVIDER}:{user_id}")
        return bool(removed)

    def is_connected(self, user_id: str) -> bool:
        return self._load(user_id) is not None

    def _save(self, user_id: str, refresh: str) -> None:
        with DbSession(self._engine) as db:
            row = db.scalar(select(OAuthToken).where(OAuthToken.user_id == user_id, OAuthToken.provider == PROVIDER))
            if row is None:
                row = OAuthToken(user_id=user_id, provider=PROVIDER)
                db.add(row)
            row.refresh_enc = self._cipher.encrypt(refresh)
            row.scopes = " ".join(SCOPES)
            row.updated_at = datetime.now(UTC)
            db.commit()

    def _load(self, user_id: str) -> str | None:
        with DbSession(self._engine) as db:
            row = db.scalar(select(OAuthToken).where(OAuthToken.user_id == user_id, OAuthToken.provider == PROVIDER))
            return self._cipher.decrypt(row.refresh_enc) if row else None

    async def _post(self, form: dict) -> dict:
        try:
            if self._http is not None:
                resp = await self._http.post(TOKEN_URL, data=form, timeout=10.0)
            else:
                async with httpx.AsyncClient() as client:
                    resp = await client.post(TOKEN_URL, data=form, timeout=10.0)
        except httpx.HTTPError as exc:
            raise OAuthError(f"token endpoint unreachable: {type(exc).__name__}") from exc
        if resp.status_code != 200:
            raise OAuthError(f"token endpoint returned {resp.status_code}")  # body may echo secrets; never include it
        return resp.json()
