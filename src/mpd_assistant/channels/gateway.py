"""ChannelGateway: one conversation pipeline for every channel, with cross-channel identity by phone."""

from typing import Optional, Protocol

from mpd_assistant.channels.inbound import InboundMessage, format_for_channel
from mpd_assistant.core.crypto import blind_index
from mpd_assistant.core.kv import KeyValueStore
from mpd_assistant.graph.service import ChatService
from mpd_assistant.messaging.models import Channel
from mpd_assistant.messaging.service import NotificationService, classify_keyword
from mpd_assistant.responses.engine import render
from mpd_assistant.sessions.service import SessionService

SESSION_MAP_TTL = 24 * 3600
MAX_INBOUND_PER_MINUTE = 20


class PhoneDirectory(Protocol):
    def find_by_phone_index(self, index: str): ...


class ChannelGateway:
    def __init__(
        self,
        chat: ChatService,
        sessions: SessionService,
        users: PhoneDirectory,
        notifications: NotificationService,
        kv: KeyValueStore,
        blind_key: str,
    ):
        self._chat, self._sessions, self._users = chat, sessions, users
        self._notifications, self._kv, self._key = notifications, kv, blind_key

    def _session_for(self, inbound: InboundMessage):
        index = blind_index(self._key, inbound.sender)
        user = self._users.find_by_phone_index(index)
        map_key = f"chan:{inbound.channel.value}:{index}"
        session_id = self._kv.get(map_key)
        session = self._sessions.resume(session_id) if session_id else None
        if session is None:
            session = self._sessions.create(user.id if user else None, verified=user is not None)
        elif user and not session.verified:
            session = self._sessions.upgrade_to_verified(session.id, user.id) or session
        self._kv.set(map_key, session.id, SESSION_MAP_TTL)
        return session

    async def handle(self, inbound: InboundMessage) -> Optional[str]:
        """Returns the reply text for the channel, or None when no reply should be sent."""
        action = classify_keyword(inbound.text)
        if action == "opt_out":
            self._notifications.record_opt_out(inbound.channel, inbound.sender)
            return render("opt_out_confirmed", "en")
        if action == "opt_in":
            self._notifications.clear_opt_out(inbound.channel, inbound.sender)
            return None

        if self._kv.incr(f"inrate:{inbound.channel.value}:{inbound.sender}", 60) > MAX_INBOUND_PER_MINUTE:
            return render("rate_limited", "en")

        session = self._session_for(inbound)
        result = await self._chat.chat(
            session.thread_id, inbound.text, verified=session.verified, user_id=session.user_id, session_row=session.id
        )
        return format_for_channel(result.reply, inbound.channel)


__all__ = ["Channel", "ChannelGateway"]
