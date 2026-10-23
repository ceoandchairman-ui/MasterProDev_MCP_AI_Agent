"""Confirmation messages sent after an action succeeds. Contact details are read from the encrypted user record."""

import logging

from mpd_assistant.core.crypto import FieldCipher
from mpd_assistant.graph.state import AgentState
from mpd_assistant.messaging.models import Channel, OutboundMessage, Purpose
from mpd_assistant.messaging.service import NotificationService

logger = logging.getLogger(__name__)


class ConfirmationService:
    def __init__(self, notifications: NotificationService, users, cipher: FieldCipher):
        self._n, self._users, self._cipher = notifications, users, cipher

    async def payment_received(self, user_id: str, quote_ref: str, locale: str = "en") -> None:
        user = self._users.find_by_id(user_id)
        if user is None or not self._n.has_channel(Channel.EMAIL):
            return
        result = await self._n.send(
            OutboundMessage(
                Channel.EMAIL,
                self._cipher.decrypt(user.email_enc),
                "payment_received",
                locale,
                {"quote": quote_ref},
                Purpose.TRANSACTIONAL,
                f"payment:{quote_ref}",
                user.id,
            )
        )
        if result.status not in ("sent", "skipped"):
            logger.warning("payment receipt not delivered: %s", result.reason)

    async def quote_decided(self, user_id: str, quote_ref: str, approved: bool, locale: str = "en") -> None:
        user = self._users.find_by_id(user_id)
        if user is None or not self._n.has_channel(Channel.EMAIL):
            return
        name = "quote_approved" if approved else "quote_declined"
        result = await self._n.send(
            OutboundMessage(Channel.EMAIL, self._cipher.decrypt(user.email_enc), name, locale, {"quote": quote_ref}, Purpose.TRANSACTIONAL, f"{name}:{quote_ref}", user.id)
        )
        if result.status not in ("sent", "skipped"):
            logger.warning("quote decision notice not delivered: %s", result.reason)

    async def booking_confirmed(self, state: AgentState, args: dict) -> None:
        user = self._users.find_by_id(state.get("user_id") or "")
        if user is None:
            return
        when = str(args.get("start_time", ""))[:16].replace("T", " ")
        locale = state.get("language", "en")
        key = f"booking:{user.id}:{args.get('start_time', '')}"
        targets = ((Channel.SMS, self._cipher.decrypt(user.phone_enc)), (Channel.EMAIL, self._cipher.decrypt(user.email_enc)))
        for channel, to in targets:
            if not self._n.has_channel(channel):
                continue
            result = await self._n.send(
                OutboundMessage(channel, to, "booking_confirmed", locale, {"when": when}, Purpose.TRANSACTIONAL, f"{key}:{channel.value}", user.id)
            )
            if result.status not in ("sent", "skipped"):
                logger.warning("booking confirmation not delivered on %s: %s", channel.value, result.reason)
