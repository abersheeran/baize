import asyncio
import functools
from concurrent.futures import ThreadPoolExecutor as _ThreadPoolExecutor
from contextvars import copy_context
from typing import Any, Callable, TypeVar, cast

__all__ = [
    "ThreadPoolExecutor",
    "run_in_threadpool",
]


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


async def run_in_threadpool(__fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """
    Asynchronously run function fn in a separate thread.
    Any *args and **kwargs supplied for this function are directly passed
    to fn. Also, the current :class:`contextvars.Context` is propogated,
    allowing context variables from the main thread to be accessed in the
    separate thread.

    https://github.com/python/cpython/blob/0f56263e62ba91d0baae40fb98947a3a98034a73/Lib/asyncio/threads.py
    """
    loop = asyncio.get_running_loop()
    ctx = copy_context()
    func_call = functools.partial(ctx.run, __fn, *args, **kwargs)
    return await loop.run_in_executor(None, cast(Callable[[], T], func_call))
