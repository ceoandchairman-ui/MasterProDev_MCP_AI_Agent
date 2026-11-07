"""_checkpointer builds a RedisSaver directly: in current langgraph-checkpoint-redis, from_conn_string is a context manager."""

import contextlib
import sys
import types

import pytest

from mpd_assistant.api import app as app_module


def _install_fake_redis_saver(monkeypatch, setup_error=None):
    created = []

    class RedisSaver:
        def __init__(self, redis_url=None, **kwargs):
            self.redis_url, self.set_up = redis_url, False
            created.append(self)

        @classmethod
        @contextlib.contextmanager
        def from_conn_string(cls, redis_url=None, **kwargs):
            yield cls(redis_url=redis_url)

        def setup(self):
            if setup_error:
                raise setup_error
            self.set_up = True

    package = types.ModuleType("langgraph.checkpoint.redis")
    package.RedisSaver = RedisSaver
    monkeypatch.setitem(sys.modules, "langgraph.checkpoint.redis", package)
    return created


def test_a_ready_saver_is_returned_with_its_indexes_created(monkeypatch):
    created = _install_fake_redis_saver(monkeypatch)
    saver = app_module._checkpointer("redis://r:6379/0", production=True)
    assert saver is created[0] and saver.redis_url == "redis://r:6379/0" and saver.set_up


def test_production_fails_loudly_when_redis_stack_is_missing(monkeypatch):
    _install_fake_redis_saver(monkeypatch, setup_error=RuntimeError("RediSearch module missing"))
    with pytest.raises(RuntimeError):
        app_module._checkpointer("redis://r:6379/0", production=True)
    assert app_module._checkpointer("redis://r:6379/0", production=False) is not None  # development falls back to memory
