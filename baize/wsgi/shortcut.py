import functools
from typing import Callable, Iterable

from baize.typing import Environ, StartResponse, WSGIApp

from .requests import Request
from .responses import Response

ViewType = Callable[[Request], Response]


def request_response(view: ViewType) -> WSGIApp:
    """
    This can turn a callable object into a WSGI application.

    ```python
    @request_response
    def f(request: Request) -> Response:
        ...
    ```
    """

    @functools.wraps(view)
    def wsgi(environ: Environ, start_response: StartResponse) -> Iterable[bytes]:
        request = Request(environ)
        response = view(request)
        yield from response(environ, start_response)

    return wsgi


def decorator(
    handler: Callable[[Request, ViewType], Response],
) -> Callable[[ViewType], ViewType]:
    """
    This can turn a callable object into a decorator for view.

    ```python
    @decorator
    def m(request: Request, next_call: Callable[[Request], Response]) -> Response:
        ...
        response = next_call(request)
        ...
        return response

    @request_response
    @m
    def v(request: Request) -> Response:
        ...
    ```
    """

    @functools.wraps(handler)
    def d(next_call: ViewType) -> ViewType:
        """
        This is the actual decorator.
        """

        @functools.wraps(next_call)
        def view(request: Request) -> Response:
            return handler(request, next_call)

        return view

    return d
