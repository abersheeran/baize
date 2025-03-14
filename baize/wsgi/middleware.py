import functools
from typing import Any, Callable, Generator, Iterable, Iterator, MutableMapping, Tuple

from ..datastructures import Headers
from ..typing import Environ, StartResponse, WSGIApp
from .requests import Request
from .responses import Response, StreamingResponse


class NextRequest(Request, MutableMapping[str, Any]):
    def __setitem__(self, name: str, value: Any) -> None:
        self._environ[name] = value

    def __delitem__(self, name: str) -> None:
        del self._environ[name]

    def stream(self, chunk_size: int = 4096 * 16) -> Iterator[bytes]:
        raise RuntimeError("Cannot read request body in middleware.")


def ensure_next(iterable: Iterable[bytes]) -> Iterable[bytes]:
    first_chunk = iterable.__iter__().__next__()

    def generator():
        yield first_chunk
        yield from iterable

    return generator()


class NextResponse(StreamingResponse):
    """
    This is a response object for middleware.
    """

    def render_stream(self) -> Generator[bytes, None, None]:
        yield from self.iterable

    @classmethod
    def from_app(cls, app: WSGIApp, request: NextRequest) -> "NextResponse":
        """
        This is a helper method to convert a WSGI application into a NextResponse object.
        """
        status_code = 200
        headers: Headers = Headers()

        def start_response(
            status: str, response_headers: Iterable[Tuple[str, str]], exc_info=None
        ) -> None:
            nonlocal status_code
            nonlocal headers
            status_code = int(status.split(" ")[0])
            headers = Headers(response_headers)

        body = ensure_next(app(request, start_response))
        return NextResponse(body, status_code, headers)


def middleware(
    handler: Callable[[NextRequest, Callable[[NextRequest], NextResponse]], Response],
) -> Callable[[WSGIApp], WSGIApp]:
    """
    This can turn a callable object into a middleware for WSGI application.

    ```python
    @middleware
    def m(request: NextRequest, next_call: Callable[[NextRequest], NextResponse]) -> Response:
        ...
        response = next_call(request)
        ...
        return response

    @m
    @request_response
    def v(request: Request) -> Response:
        ...

    # OR

    @m
    def wsgi(environ: Environ, start_response: StartResponse) -> Iterable[bytes]:
        ...
    ```
    """

    @functools.wraps(handler)
    def d(app: WSGIApp) -> WSGIApp:
        """
        This is the actual middleware.
        """

        @functools.wraps(app)
        def wsgi(environ: Environ, start_response: StartResponse) -> Iterable[bytes]:
            request = NextRequest(environ, start_response)

            def next_call(request: NextRequest) -> NextResponse:
                next_response = NextResponse.from_app(app, request)
                return next_response

            response = handler(request, next_call)
            yield from response(environ, start_response)

        return wsgi

    return d
