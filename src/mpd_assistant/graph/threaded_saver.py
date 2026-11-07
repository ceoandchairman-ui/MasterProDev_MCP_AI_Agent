"""Gives a synchronous LangGraph checkpoint saver the async methods the graph calls (ainvoke/astream).

RedisSaver's async methods raise NotImplementedError; its synchronous ones work. Running those in a worker thread keeps the
event loop free and avoids binding an async Redis client to a loop before the server starts.
"""

import asyncio


def with_async_methods(saver_cls):
    class ThreadedSaver(saver_cls):
        async def aget_tuple(self, config):
            return await asyncio.to_thread(self.get_tuple, config)

        async def alist(self, config, *, filter=None, before=None, limit=None):
            items = await asyncio.to_thread(lambda: list(self.list(config, filter=filter, before=before, limit=limit)))
            for item in items:
                yield item

        async def aput(self, config, checkpoint, metadata, new_versions):
            return await asyncio.to_thread(self.put, config, checkpoint, metadata, new_versions)

        async def aput_writes(self, config, writes, task_id, task_path=""):
            await asyncio.to_thread(self.put_writes, config, writes, task_id, task_path)

        async def adelete_thread(self, thread_id):
            await asyncio.to_thread(self.delete_thread, thread_id)

    ThreadedSaver.__name__ = f"Threaded{saver_cls.__name__}"
    return ThreadedSaver
