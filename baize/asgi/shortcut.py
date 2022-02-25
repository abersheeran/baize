import functools
from typing import Awaitable, Callable

from baize.typing import ASGIApp, Receive, Scope, Send

from .requests import Request
from .responses import Response
from .websocket import WebSocket, WebsocketDenialResponse

ViewType = Callable[[Request], Awaitable[Response]]
MiddlewareType = Callable[[Request, ViewType], Awaitable[Response]]


def request_response(view: ViewType) -> ASGIApp:
    """
    This can turn a callable object into a ASGI application.

    ```python
    @request_response
    async def f(request: Request) -> Response:
        ...
    ```
    """

    @functools.wraps(view)
    async def asgi(scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "websocket":
            return await WebsocketDenialResponse(Response(404))(scope, receive, send)
        else:
            request = Request(scope, receive, send)
            resposne = await view(request)
            return await resposne(scope, receive, send)

    return asgi


def websocket_session(view: Callable[[WebSocket], Awaitable[None]]) -> ASGIApp:
    """
    This can turn a callable object into a ASGI application.

    ```python
    @websocket_session
    async def f(websocket: WebSocket) -> None:
        ...
    ```
    """

    @functools.wraps(view)
    async def asgi(scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            await Response(404)(scope, receive, send)
        else:
            websocket = WebSocket(scope, receive, send)
            await view(websocket)

    return asgi


def middleware(handler: MiddlewareType) -> Callable[[ViewType], ViewType]:
    """
    This can turn a callable object into a middleware for view.

    ```python
    @middleware
    async def m(request: Request, next_call: Callable[[Request], Awaitable[Response]]) -> Response:
        ...
        response = await next_call(request)
        ...
        return response


    @request_response
    @m
    async def v(request: Request) -> Response:
        ...
    ```
    """

    @functools.wraps(handler)
    def decorator(next_call: ViewType) -> ViewType:
        """
        This is the actual decorator.
        """

        @functools.wraps(next_call)
        async def view(request: Request) -> Response:
            return await handler(request, next_call)

        return view

    return decorator
