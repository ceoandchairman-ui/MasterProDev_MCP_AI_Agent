"""OTP delivery. Real email/SMS providers are not chosen yet, so production fails loudly rather than silently."""

import logging

logger = logging.getLogger(__name__)


class ConsoleSender:
    """Development only: logs the code. Never constructed when ENV is production."""

    def __init__(self, channel: str):
        self._channel = channel

    def send(self, target: str, code: str) -> None:
        logger.warning("DEV %s OTP for %s: %s", self._channel, target, code)


class UnconfiguredSender:
    def __init__(self, channel: str):
        self._channel = channel

    def send(self, target: str, code: str) -> None:
        raise RuntimeError(f"No {self._channel} provider is configured")
