import asyncio
import functools
import sys
from concurrent.futures import ThreadPoolExecutor as _ThreadPoolExecutor
from contextvars import copy_context
from typing import Any, Callable, TypeVar

__all__ = [
    "get_running_loop",
    "ThreadPoolExecutor",
    "run_in_threadpool",
]


if sys.version_info[:2] < (3, 7):

    def get_running_loop() -> asyncio.AbstractEventLoop:
        return asyncio.get_event_loop()

else:

    def get_running_loop() -> asyncio.AbstractEventLoop:
        return asyncio.get_running_loop()


T = TypeVar("T")


class ThreadPoolExecutor(_ThreadPoolExecutor):  # type: ignore
    """
    Thread pool with ContextVars

    - https://github.com/python/cpython/issues/78195
    """

    def submit(self, __fn, *args, **kwargs):
        return super().submit(
            functools.partial(copy_context().run, __fn), *args, **kwargs
        )


if sys.version_info[:2] < (3, 9):
    DEFAULT_EXECUTOR = ThreadPoolExecutor()

    async def run_in_threadpool(__fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        loop = get_running_loop()
        return await loop.run_in_executor(
            DEFAULT_EXECUTOR, functools.partial(__fn, *args, **kwargs)
        )

else:

    async def run_in_threadpool(__fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        return await asyncio.to_thread(__fn, *args, **kwargs)
