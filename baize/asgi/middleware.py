import asyncio
import functools
from typing import (
    Any,
    AsyncGenerator,
    AsyncIterator,
    Awaitable,
    Callable,
    MutableMapping,
)

from ..datastructures import Headers
from ..typing import ASGIApp, Scope, Receive, Send, Message
from .requests import Request
from .responses import Response, StreamingResponse


class PipeStream(AsyncIterator[bytes]):
    def __init__(self) -> None:
        self._queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=1)
        self._pushed_eof = False

    async def push(self, chunk: bytes) -> None:
        if self._pushed_eof:
            raise RuntimeError("Cannot push chunk after push EOF.")  # pragma: no cover
        await self._queue.put(chunk)

    async def push_eof(self) -> None:
        self._pushed_eof = True

    async def __anext__(self) -> bytes:
        if self._pushed_eof and self._queue.empty():
            raise StopAsyncIteration
        return await self._queue.get()


class NextRequest(Request, MutableMapping[str, Any]):
    def __setitem__(self, name: str, value: Any) -> None:
        self._scope[name] = value

    def __delitem__(self, name: str) -> None:
        del self._scope[name]

    def stream(self) -> AsyncIterator[bytes]:
        raise RuntimeError("Cannot read request body in middleware.")


class NextResponse(StreamingResponse):
    """
    This is a response object for middleware.
    """

    async def render_stream(self) -> AsyncGenerator[bytes, None]:
        async for chunk in self.iterable:
            yield chunk

    @classmethod
    async def from_app(cls, app: ASGIApp, request: NextRequest) -> "NextResponse":
        """
        This is a helper method to convert a ASGI application into a NextResponse object.
        """
        status_code = 200
        headers = Headers()
        body = PipeStream()

        async def send(message: Message) -> None:
            nonlocal status_code
            nonlocal headers
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = Headers(
                    [
                        (k.decode("latin-1"), v.decode("latin-1"))
                        for k, v in message.get("headers", [])
                    ]
                )
            elif message["type"] == "http.response.body":
                await body.push(message.get("body", b""))
                if not message.get("more_body", False):
                    await body.push_eof()

        await app(request, request._receive, send)
        return NextResponse(body, status_code, headers)


def middleware(
    handler: Callable[
        [NextRequest, Callable[[NextRequest], Awaitable[NextResponse]]],
        Awaitable[Response],
    ],
) -> Callable[[ASGIApp], ASGIApp]:
    """
    This can turn a callable object into a middleware for ASGI application.

    ```python
    @middleware
    async def m(
        request: NextRequest, next_call: Callable[[NextRequest], Awaitable[NextResponse]]
    ) -> Response:
        ...
        response = await next_call(request)
        ...
        return response

    @m
    @request_response
    async def v(request: Request) -> Response:
        ...

    # OR

    @m
    async def asgi(scope: Scope, receive: Receive, send: Send) -> None:
        ...
    ```
    """

    @functools.wraps(handler)
    def d(app: ASGIApp) -> ASGIApp:
        """
        This is the actual middleware.
        """

        @functools.wraps(app)
        async def asgi(scope: Scope, receive: Receive, send: Send) -> None:
            request = NextRequest(scope, receive, send)

            async def next_call(request: NextRequest) -> NextResponse:
                return await NextResponse.from_app(app, request)

            response = await handler(request, next_call)
            await response(scope, receive, send)

        return asgi

    return d
