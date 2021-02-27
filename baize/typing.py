import sys
from types import TracebackType
from typing import (
    Any,
    Awaitable,
    Callable,
    Dict,
    Iterable,
    List,
    MutableMapping,
    Optional,
    Tuple,
    Type,
    Union,
)

if sys.version_info[:2] < (3, 8):
    from typing_extensions import Final, Literal, TypedDict, final
else:
    from typing import Final, Literal, TypedDict, final

__all__ = [
    "Scope",
    "Message",
    "Receive",
    "Send",
    "ASGIApp",
    "ExcInfo",
    "Environ",
    "StartResponse",
    "WSGIApp",
] + [
    # built-in types
    "TypedDict",
    "Literal",
    "Final",
    "final",
]

# ASGI
Scope = MutableMapping[str, Any]

Message = MutableMapping[str, Any]

Receive = Callable[[], Awaitable[Message]]

Send = Callable[[Message], Awaitable[None]]

ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

# WSGI: view PEP3333
ExcInfo = Tuple[Type[BaseException], BaseException, Optional[TracebackType]]

Environ = MutableMapping[str, Any]

StartResponse = Callable[[str, Iterable[Tuple[str, str]], Optional[ExcInfo]], None]

WSGIApp = Callable[[Environ, StartResponse], Iterable[bytes]]

# JSONable
# See mypy issue https://github.com/python/mypy/issues/731
JSONable = Union[str, bytes, int, float, bool, None, Dict[str, "JSONable"], List["JSONable"]]  # type: ignore

# Server-sent Event
# https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events
ServerSentEvent = TypedDict(
    "ServerSentEvent", {"event": str, "data": str, "id": str, "retry": int}, total=False
)
