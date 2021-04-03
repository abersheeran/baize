import asyncio
import functools
import inspect
import typing

T = typing.TypeVar("T")


class cached_property(typing.Generic[T]):
    """
    A property that is only computed once per instance and then replaces
    itself with an ordinary attribute. Deleting the attribute resets the
    property.
    """

    def __init__(self, func: typing.Callable[..., T]) -> None:
        self.func = func
        functools.update_wrapper(self, func)

    def __get__(self, obj: typing.Any, cls: typing.Any) -> T:
        if obj is None:
            value = self
        else:
            result = self.func(obj)
            if inspect.isawaitable(result):
                result = asyncio.ensure_future(result)
            value = obj.__dict__[self.func.__name__] = result
        return value
