import abc
import functools
import json
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor
from concurrent.futures import wait as wait
from http import HTTPStatus
from itertools import chain
from queue import Queue
from random import choices as random_choices
from typing import (
    Any,
    Callable,
    Dict,
    Generator,
    Generic,
    Iterable,
    Iterator,
    Mapping,
    Sequence,
    Tuple,
    TypeVar,
    Union,
)
from urllib.parse import parse_qsl, quote

from .datastructures import URL, Address, FormData, Headers, QueryParams, defaultdict
from .exceptions import HTTPException
from .formparsers import MultiPartParser
from .requests import MoreInfoFromHeaderMixin
from .responses import BaseFileResponse, BaseResponse, build_bytes_from_sse
from .routing import BaseHosts, BaseRouter, BaseSubpaths
from .typing import Environ, Final, ServerSentEvent, StartResponse, WSGIApp
from .utils import cached_property

StatusStringMapping: Final[defaultdict] = defaultdict(
    lambda status: f"{status} Unknown Status Code",
    {int(status): f"{status} {status.phrase}" for status in HTTPStatus},
)


class HTTPConnection(Mapping[str, Any], MoreInfoFromHeaderMixin):
    """
    A base class for incoming HTTP connections.

    It is a valid Mapping type that allows you to directly
    access the values in any WSGI `environ` dictionary.
    """

    def __init__(self, environ: Environ) -> None:
        self._environ = environ
        self._stream_consumed = False

    def __getitem__(self, key: str) -> Any:
        return self._environ[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._environ)

    def __len__(self) -> int:
        return len(self._environ)

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, self.__class__):
            return NotImplemented
        return self._environ == other._environ

    @cached_property
    def client(self) -> Address:
        """
        Client's IP and Port.

        Note that this depends on the `REMOTE_ADDR` and `REMOTE_PORT` values
        given by the WSGI Server, and is not necessarily accurate.
        """
        if self.get("REMOTE_ADDR") and self.get("REMOTE_PORT"):
            return Address(self["REMOTE_ADDR"], int(self["REMOTE_PORT"]))
        return Address(host=None, port=None)

    @cached_property
    def url(self) -> URL:
        """
        The full URL of this request.
        """
        return URL(environ=self._environ)

    @cached_property
    def path_params(self) -> Dict[str, Any]:
        """
        The path parameters parsed by the framework.
        """
        return self.get("PATH_PARAMS", {})

    @cached_property
    def query_params(self) -> QueryParams:
        """
        Query parameter. It is a multi-value mapping.
        """
        return QueryParams(self["QUERY_STRING"])

    @cached_property
    def headers(self) -> Headers:
        """
        A read-only case-independent mapping.

        Note that in its internal storage, all keys are in lower case.
        """
        return Headers(
            (key.lower().replace("_", "-"), value)
            for key, value in chain(
                (
                    (key[5:], value)
                    for key, value in self._environ.items()
                    if key.startswith("HTTP_")
                ),
                (
                    (key, value)
                    for key, value in self._environ.items()
                    if key in ("CONTENT_TYPE", "CONTENT_LENGTH")
                ),
            )
        )


class Request(HTTPConnection):
    @cached_property
    def method(self) -> str:
        """
        HTTP method. Uppercase string.
        """
        return self["REQUEST_METHOD"]

    def stream(self, chunk_size: int = 4096) -> Iterator[bytes]:
        """
        Streaming read request body. e.g. `for chunk in request.stream(): ...`

        If you access `.stream()` then the byte chunks are provided
        without storing the entire body to memory. Any subsequent
        calls to `.body`, `.form`, or `.json` will raise an error.
        """
        if "body" in self.__dict__:
            yield self.body
            return

        if self._stream_consumed:
            raise RuntimeError("Stream consumed")

        self._stream_consumed = True
        body = self._environ["wsgi.input"]
        while True:
            chunk = body.read(chunk_size)
            if not chunk:
                return
            yield chunk

    @cached_property
    def body(self) -> bytes:
        """
        Read all the contents of the request body into the memory and return it.
        """
        return b"".join([chunk for chunk in self.stream()])

    @cached_property
    def json(self) -> Any:
        """
        Call `self.body` and use `json.loads` parse it.

        If `content_type` is not equal to `application/json`,
        an HTTPExcption exception will be thrown.
        """
        if self.content_type == "application/json":
            return json.loads(
                self.body.decode(self.content_type.options.get("charset", "utf8"))
            )

        raise HTTPException(415, {"Accpet": "application/json"})

    @cached_property
    def form(self) -> FormData:
        """
        Parse the data in the form format and return it as a multi-value mapping.

        If `content_type` is equal to `multipart/form-data`, it will directly
        perform streaming analysis, and subsequent calls to `self.body`
        or `self.json` will raise errors.

        If `content_type` is not equal to `multipart/form-data` or
        `application/x-www-form-urlencoded`, an HTTPExcption exception will be thrown.
        """
        if self.content_type == "multipart/form-data":
            return MultiPartParser(self.content_type, self.stream()).parse()
        if self.content_type == "application/x-www-form-urlencoded":
            data = self.body.decode(
                encoding=self.content_type.options.get("charset", "latin-1")
            )
            return FormData(parse_qsl(data, keep_blank_values=True))

        raise HTTPException(
            415, {"Accpet": "multipart/form-data, application/x-www-form-urlencoded"}
        )

    def close(self) -> None:
        """
        Close all temporary files in the `self.form`.

        This can always be called, regardless of whether you use form or not.
        """
        if "form" in self.__dict__:
            self.form.close()


class Response(BaseResponse):
    """
    The parent class of all responses, whose objects can be used directly as WSGI
    application.
    """

    def __call__(
        self, environ: Environ, start_response: StartResponse
    ) -> Iterable[bytes]:
        self.headers["content-length"] = "0"
        start_response(
            StatusStringMapping[self.status_code], self.list_headers(as_bytes=False)
        )
        return (b"",)


_ContentType = TypeVar("_ContentType")


class SmallResponse(Response, abc.ABC, Generic[_ContentType]):
    """
    Abstract base class for small response objects.
    """

    media_type: str = ""
    charset: str = "utf-8"

    def __init__(
        self,
        content: _ContentType,
        status_code: int = 200,
        headers: Mapping[str, str] = None,
        media_type: str = None,
        charset: str = None,
    ) -> None:
        super().__init__(status_code, headers)
        self.content = content
        self.media_type = media_type or self.media_type
        self.charset = charset or self.charset

    @abc.abstractmethod
    def render(self, content: _ContentType) -> bytes:
        raise NotImplementedError

    def __call__(
        self, environ: Environ, start_response: StartResponse
    ) -> Iterable[bytes]:
        body = self.render(self.content)
        if body and "content-length" not in self.headers:
            content_length = str(len(body))
            self.headers["content-length"] = content_length
        content_type = self.media_type
        if content_type and "content-type" not in self.headers:
            if content_type.startswith("text/"):
                content_type += "; charset=" + self.charset
            self.headers["content-type"] = content_type
        start_response(
            StatusStringMapping[self.status_code], self.list_headers(as_bytes=False)
        )
        yield body


class PlainTextResponse(SmallResponse[Union[bytes, str]]):
    media_type = "text/plain"

    def render(self, content: Union[bytes, str]) -> bytes:
        return content if isinstance(content, bytes) else content.encode(self.charset)


class HTMLResponse(PlainTextResponse):
    media_type = "text/html"


class JSONResponse(SmallResponse[Any]):
    """
    `**kwargs` is used to accept all the parameters that `json.loads` can accept.
    """

    media_type = "application/json"

    def __init__(
        self,
        content: Any,
        status_code: int = 200,
        headers: Mapping[str, str] = None,
        **kwargs: Any,
    ) -> None:
        self.json_kwargs: Dict[str, Any] = {
            "ensure_ascii": False,
            "allow_nan": False,
            "indent": None,
            "separators": (",", ":"),
            "default": None,
        }
        self.json_kwargs.update(**kwargs)
        super().__init__(content, status_code=status_code, headers=headers)

    def render(self, content: Any) -> bytes:
        return json.dumps(content, **self.json_kwargs).encode(self.charset)


class RedirectResponse(Response):
    def __init__(
        self,
        url: Union[str, URL],
        status_code: int = 307,
        headers: Mapping[str, str] = None,
    ) -> None:
        super().__init__(status_code=status_code, headers=headers)
        self.headers["location"] = quote(str(url), safe="/#%[]=:;$&()+,!?*@'~")


class StreamResponse(Response):
    def __init__(
        self,
        iterable: Iterable[bytes],
        status_code: int = 200,
        headers: Mapping[str, str] = None,
        content_type: str = "application/octet-stream",
    ) -> None:
        self.iterable = iterable
        super().__init__(status_code, headers)
        self.headers["content-type"] = content_type
        self.headers["transfer-encoding"] = "chunked"

    def __call__(
        self, environ: Environ, start_response: StartResponse
    ) -> Iterable[bytes]:
        start_response(
            StatusStringMapping[self.status_code], self.list_headers(as_bytes=False)
        )
        for chunk in self.iterable:
            yield chunk


class FileResponse(BaseFileResponse, Response):
    """
    File response.

    It will automatically determine whether to send only headers
    and the range of files that need to be sent.
    """

    def handle_all(
        self,
        send_header_only: bool,
        file_size: int,
        start_response: StartResponse,
    ) -> Generator[bytes, None, None]:
        self.headers["content-type"] = str(self.content_type)
        self.headers["content-length"] = str(file_size)
        start_response(StatusStringMapping[200], self.list_headers(as_bytes=False))

        if send_header_only:
            yield b""
            return

        with open(self.filepath, "rb") as file:
            for _ in range(0, file_size, self.chunk_size):
                yield file.read(self.chunk_size)

    def handle_single_range(
        self,
        send_header_only: bool,
        file_size: int,
        start_response: StartResponse,
        start: int,
        end: int,
    ) -> Generator[bytes, None, None]:
        self.headers["content-range"] = f"bytes {start}-{end-1}/{file_size}"
        self.headers["content-type"] = str(self.content_type)
        self.headers["content-length"] = str(end - start)
        start_response(StatusStringMapping[206], self.list_headers(as_bytes=False))
        if send_header_only:
            yield b""
            return

        with open(self.filepath, "rb") as file:
            file.seek(start)
            for here in range(start, end, self.chunk_size):
                yield file.read(min(self.chunk_size, end - here))

    def handle_several_ranges(
        self,
        send_header_only: bool,
        file_size: int,
        start_response: StartResponse,
        ranges: Sequence[Tuple[int, int]],
    ) -> Generator[bytes, None, None]:
        boundary = "".join(random_choices("abcdefghijklmnopqrstuvwxyz0123456789", k=13))
        self.headers["content-type"] = f"multipart/byteranges; boundary={boundary}"
        content_length, generate_headers = self.generate_multipart(
            ranges, boundary, file_size
        )
        self.headers["content-length"] = str(content_length)

        start_response(StatusStringMapping[206], self.list_headers(as_bytes=False))
        if send_header_only:
            yield b""
            return

        with open(self.filepath, "rb") as file:
            for start, end in ranges:
                file.seek(start)
                yield generate_headers(start, end)
                for here in range(start, end, self.chunk_size):
                    yield file.read(min(self.chunk_size, end - here))
                yield b"\n"
            yield f"--{boundary}--\n".encode("ascii")

    def __call__(
        self, environ: Environ, start_response: StartResponse
    ) -> Iterable[bytes]:
        send_header_only = environ["REQUEST_METHOD"] == "HEAD"
        stat_result = self.stat_result
        file_size = stat_result.st_size

        if "HTTP_RANGE" not in environ or (
            "HTTP_IF_RANGE" in environ
            and not self.judge_if_range(environ["HTTP_IF_RANGE"], stat_result)
        ):
            yield from self.handle_all(send_header_only, file_size, start_response)
            return

        try:
            ranges = self.parse_range(environ["HTTP_RANGE"], file_size)
        except HTTPException as exception:
            start_response(
                StatusStringMapping[exception.status_code],
                [*(exception.headers or {}).items()],
            )
            yield b""
            return

        if len(ranges) == 1:
            start, end = ranges[0]
            yield from self.handle_single_range(
                send_header_only, file_size, start_response, start, end
            )
        else:
            yield from self.handle_several_ranges(
                send_header_only, file_size, start_response, ranges
            )


class SendEventResponse(Response):
    """
    Server-sent events response.

    :param ping_interval: This determines the time interval (in seconds) between sending ping messages.
    """

    thread_pool = ThreadPoolExecutor(max_workers=10)

    required_headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "Content-Type": "text/event-stream",
    }

    def __init__(
        self,
        iterable: Iterable[ServerSentEvent],
        status_code: int = 200,
        headers: Mapping[str, str] = None,
        *,
        ping_interval: int = 3,
        charset: str = "utf-8",
    ) -> None:
        if headers:
            headers = {**self.required_headers, **headers}
        else:
            headers = dict(self.required_headers)
        headers["Content-Type"] += f"; charset={charset}"
        super().__init__(status_code, headers)
        self.iterable = iterable
        self.ping_interval = ping_interval
        self.charset = charset
        self.queue: Queue = Queue(13)
        self.has_more_data = True

    def __call__(
        self, environ: Environ, start_response: StartResponse
    ) -> Iterable[bytes]:
        start_response(
            StatusStringMapping[self.status_code], self.list_headers(as_bytes=False)
        )

        future = self.thread_pool.submit(
            wait,
            (
                self.thread_pool.submit(self.send_event),
                self.thread_pool.submit(self.keep_alive),
            ),
            return_when=FIRST_COMPLETED,
        )

        try:
            while self.has_more_data or not self.queue.empty():
                yield self.queue.get()
        finally:
            self.has_more_data = False
            future.cancel()

    def send_event(self) -> None:
        for chunk in self.iterable:
            self.queue.put(build_bytes_from_sse(chunk, self.charset))
        self.has_more_data = False

    def keep_alive(self) -> None:
        while self.has_more_data:
            time.sleep(self.ping_interval)
            self.queue.put(b": ping\n\n")


def request_response(view: Callable[[Request], Response]) -> WSGIApp:
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
        return response(environ, start_response)

    return wsgi


class Router(BaseRouter[WSGIApp]):
    """
    A router to assign different paths to different WSGI applications.

    :param routes: A triple composed of path, endpoint, and name. The name is optional. \
        If the name is not given, the corresponding URL cannot be constructed through \
        build_url.

    ```python
    applications = Router(
        ("/static/{filepath:any}", static_files),
        ("/api/{_:any}", api_app),
        ("/about/{name}", about_page, "about"),
        ("/", homepage, "homepage"),
    )
    ```
    """

    def __call__(
        self, environ: Environ, start_response: StartResponse
    ) -> Iterable[bytes]:
        path = environ.get("PATH_INFO", "")
        for route in self._route_array:
            match_up, path_params = route.matches(path)
            if not match_up:
                continue
            environ["PATH_PARAMS"] = path_params
            environ["router"] = self
            return route.endpoint(environ, start_response)

        return PlainTextResponse(b"", 404)(environ, start_response)


class Subpaths(BaseSubpaths[WSGIApp]):
    """
    A router allocates different prefix requests to different WSGI applications.

    NOTE: This will change the values of `environ["SCRIPT_NAME"]` and `environ["PATH_INFO"]`.

    ```python
    applications = Subpaths(
        ("/static", static_files),
        ("/api", api_app),
        ("", default_app),
    )
    ```
    """

    def __call__(
        self, environ: Environ, start_response: StartResponse
    ) -> Iterable[bytes]:
        path = environ.get("PATH_INFO", "")
        for prefix, endpoint in self._route_array:
            if not path.startswith(prefix):
                continue
            environ["SCRIPT_NAME"] = environ.get("SCRIPT_NAME", "") + prefix
            environ["PATH_INFO"] = path[len(prefix) :]
            return endpoint(environ, start_response)

        return PlainTextResponse(b"", 404)(environ, start_response)


class Hosts(BaseHosts[WSGIApp]):
    r"""
    A router that distributes requests to different WSGI applications based on Host.

    ```python
    applications = Hosts(
        (r"static\.example\.com", static_files),
        (r"api\.example\.com", api_app),
        (r"(www\.)?example\.com", default_app),
    )
    ```
    """

    def __call__(
        self, environ: Environ, start_response: StartResponse
    ) -> Iterable[bytes]:
        host = environ.get("HTTP_HOST", "")
        for host_pattern, endpoint in self._host_array:
            if host_pattern.fullmatch(host) is None:
                continue
            return endpoint(environ, start_response)

        return PlainTextResponse(b"Invalid host", 404)(environ, start_response)
