"""with_async_methods: a synchronous saver gets working async methods that run off the event loop."""

import threading

from mpd_assistant.graph.threaded_saver import with_async_methods


class SyncSaver:
    def __init__(self, redis_url=None):
        self.redis_url, self.calls, self.threads = redis_url, [], []

    def _note(self, name, *args):
        self.calls.append((name, args))
        self.threads.append(threading.current_thread())

    def get_tuple(self, config):
        self._note("get_tuple", config)
        return ("tuple", config)

    def list(self, config, *, filter=None, before=None, limit=None):
        self._note("list", config, filter, before, limit)
        return iter(["a", "b"])

    def put(self, config, checkpoint, metadata, new_versions):
        self._note("put", config, checkpoint, metadata, new_versions)
        return {"saved": True}

    def put_writes(self, config, writes, task_id, task_path=""):
        self._note("put_writes", config, writes, task_id, task_path)

    def delete_thread(self, thread_id):
        self._note("delete_thread", thread_id)


async def test_each_async_method_delegates_to_its_sync_twin_in_a_worker_thread():
    saver = with_async_methods(SyncSaver)(redis_url="redis://r/0")
    cfg = {"configurable": {"thread_id": "t"}}

    assert await saver.aget_tuple(cfg) == ("tuple", cfg)
    assert [x async for x in saver.alist(cfg, limit=2)] == ["a", "b"]
    assert await saver.aput(cfg, {"id": 1}, {"step": 0}, {}) == {"saved": True}
    await saver.aput_writes(cfg, [("ch", 1)], "task-1")
    await saver.adelete_thread("t")

    assert [name for name, _ in saver.calls] == ["get_tuple", "list", "put", "put_writes", "delete_thread"]
    assert all(t is not threading.main_thread() for t in saver.threads)
    assert saver.redis_url == "redis://r/0" and type(saver).__name__ == "ThreadedSyncSaver"
