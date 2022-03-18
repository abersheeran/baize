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

    @typing.overload
    def __get__(self, obj: None, cls: type) -> "cached_property":
        ...

    @typing.overload
    def __get__(self, obj: object, cls: type) -> T:
        ...

    def __get__(self, obj, cls):
        if obj is None:
            value = self
        else:
            result = self.func(obj)
            if inspect.isawaitable(result):
                result = asyncio.ensure_future(result)
            value = obj.__dict__[self.func.__name__] = result
        return value


# ############################################################################
# ############################# COPY From stdlib #############################
# ############ Because https://peps.python.org/pep-0594/ #####################
# ############################################################################


def _parseparam(s: str) -> typing.Generator[str, None, None]:
    while s[:1] == ";":
        s = s[1:]
        end = s.find(";")
        while end > 0 and (s.count('"', 0, end) - s.count('\\"', 0, end)) % 2:
            end = s.find(";", end + 1)
        if end < 0:
            end = len(s)
        f = s[:end]
        yield f.strip()
        s = s[end:]


def parse_header(line: str) -> typing.Tuple[str, typing.Dict[str, str]]:
    """Parse a Content-type like header.

    Return the main content-type and a dictionary of options.

    """
    parts = _parseparam(";" + line)
    key = parts.__next__()
    pdict = {}
    for p in parts:
        i = p.find("=")
        if i >= 0:
            name = p[:i].strip().lower()
            value = p[i + 1 :].strip()
            if len(value) >= 2 and value[0] == value[-1] == '"':
                value = value[1:-1]
                value = value.replace("\\\\", "\\").replace('\\"', '"')
            pdict[name] = value
    return key, pdict
