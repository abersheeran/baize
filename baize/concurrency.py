import asyncio
import functools
from typing import Any, Callable, TypeVar

T = TypeVar("T")


async def run_in_threadpool(func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, functools.partial(func, *args, **kwargs))
