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
    Final,
    Literal,
    Protocol,
    TypedDict,
    final,
    runtime_checkable,
)

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
    # built-in types
    "TypedDict",
    "Literal",
    "Final",
    "final",
    "Protocol",
    "runtime_checkable",
]

# ASGI
Scope = MutableMapping[str, Any]

Message = MutableMapping[str, Any]

Receive = Callable[[], Awaitable[Message]]

Send = Callable[[Message], Awaitable[None]]


class ASGIApp(Protocol):
    def __call__(
        self, scope: Scope, receive: Receive, send: Send
    ) -> Awaitable[None]: ...


# WSGI: view PEP3333
Environ = MutableMapping[str, Any]

ExcInfo = Tuple[Type[BaseException], BaseException, Optional[TracebackType]]


class StartResponse(Protocol):
    def __call__(
        self,
        status: str,
        response_headers: List[Tuple[str, str]],
        exc_info: Optional[ExcInfo] = None,
    ) -> Any: ...


class WSGIApp(Protocol):
    def __call__(
        self, environ: Environ, start_response: StartResponse
    ) -> Iterable[bytes]: ...


# Server-sent Event
# https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events
ServerSentEvent = TypedDict(
    "ServerSentEvent", {"event": str, "data": str, "id": str, "retry": int}, total=False
)
