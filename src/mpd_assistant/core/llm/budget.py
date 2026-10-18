"""Daily token budgets: one per conversation and one global cap, both enforced before the model is called."""

from contextvars import ContextVar, Token
from datetime import UTC, datetime
from typing import Optional

from mpd_assistant.core.kv import KeyValueStore
from mpd_assistant.core.llm.client import LLMError
from mpd_assistant.observability.metrics import BUDGET_BLOCKS

_scope: ContextVar[Optional[str]] = ContextVar("token_budget_scope", default=None)


class BudgetExceeded(LLMError):
    def __init__(self, which: str):
        super().__init__(f"token budget exhausted: {which}")
        self.which = which


def set_scope(scope: Optional[str]) -> Token:
    return _scope.set(scope)


def reset_scope(marker: Token) -> None:
    _scope.reset(marker)


def current_scope() -> Optional[str]:
    return _scope.get()


class TokenBudget:
    """Counters live in the shared key-value store, so every replica spends from the same budget."""

    def __init__(self, kv: KeyValueStore, per_scope_daily: int, global_daily: int):
        self._kv, self._per_scope, self._global = kv, per_scope_daily, global_daily

    @staticmethod
    def _day() -> str:
        return datetime.now(UTC).strftime("%Y%m%d")

    def _used(self, key: str) -> int:
        return int(self._kv.get(key) or 0)

    def exhausted(self, scope: Optional[str]) -> Optional[str]:
        """Which budget is spent ('global' or 'session'), or None when there is room."""
        if self._global and self._used(f"tokens:global:{self._day()}") >= self._global:
            return "global"
        if scope and self._per_scope and self._used(f"tokens:{scope}:{self._day()}") >= self._per_scope:
            return "session"
        return None

    def check(self, scope: Optional[str]) -> None:
        which = self.exhausted(scope)
        if which:
            BUDGET_BLOCKS.labels(which).inc()
            raise BudgetExceeded(which)

    def record(self, scope: Optional[str], tokens: int) -> None:
        if tokens <= 0:
            return
        day = self._day()
        for key in ([f"tokens:{scope}:{day}"] if scope else []) + [f"tokens:global:{day}"]:
            self._kv.set(key, self._used(key) + tokens, 2 * 86400)
