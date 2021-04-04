import sys
from types import TracebackType
from typing import (
    Any,
    Awaitable,
    Callable,
    Iterable,
    List,
    MutableMapping,
    Optional,
    Tuple,
    Type,
)

if sys.version_info[:2] < (3, 8):
    from typing_extensions import Final, Literal, Protocol, TypedDict, final
else:
    from typing import Final, Literal, Protocol, TypedDict, final

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
Environ = MutableMapping[str, Any]

ExcInfo = Tuple[Type[BaseException], BaseException, Optional[TracebackType]]


class StartResponse(Protocol):
    __slots__ = ()

    def __call__(
        self,
        status: str,
        response_headers: List[Tuple[str, str]],
        exc_info: ExcInfo = None,
    ) -> None:
        raise NotImplementedError


WSGIApp = Callable[[Environ, StartResponse], Iterable[bytes]]

# Server-sent Event
# https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events
ServerSentEvent = TypedDict(
    "ServerSentEvent", {"event": str, "data": str, "id": str, "retry": int}, total=False
)
