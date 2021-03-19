import functools
import json
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor
from concurrent.futures import wait as wait
from http import HTTPStatus
from itertools import chain
from queue import Queue
from typing import (
    Any,
    Callable,
    Dict,
    Generator,
    Generic,
    Iterable,
    Iterator,
    Mapping,
    MutableSequence,
    Optional,
    Sequence,
    Tuple,
    TypeVar,
    Union,
)
from urllib.parse import parse_qsl, quote_plus

from .datastructures import URL, Address, FormData, Headers, QueryParams, defaultdict
from .exceptions import HTTPException
from .formparsers import MultiPartParser
from .requests import MoreInfoFromHeaderMixin
from .responses import BaseFileResponse, BaseResponse
from .routing import BaseHosts, BaseRouter
from .typing import Environ, JSONable, ServerSentEvent, StartResponse, WSGIApp
from .utils import cached_property

StatusStringMapping = defaultdict(
    lambda status: f"{status} Custom status code",
    {int(status): f"{status} {status.phrase}" for status in HTTPStatus},
)


class HTTPConnection(Mapping, MoreInfoFromHeaderMixin):
    def __init__(self, environ: Environ) -> None:
        self._environ = environ
        self._stream_consumed = False

    def __getitem__(self, key: str) -> str:
        return self._environ[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._environ)

    def __len__(self) -> int:
        return len(self._environ)

    @cached_property
    def client(self) -> Address:
        if self.get("REMOTE_ADDR") and self.get("REMOTE_PORT"):
            return Address(self["REMOTE_ADDR"], int(self["REMOTE_PORT"]))
        return Address(host=None, port=None)

    @cached_property
    def url(self) -> URL:
        return URL(environ=self._environ)

    @cached_property
    def path_params(self) -> Dict[str, Any]:
        return self.get("PATH_PARAMS", {})

    @cached_property
    def query_params(self) -> QueryParams:
        return QueryParams(self["QUERY_STRING"])

    @cached_property
    def headers(self) -> Headers:
        return Headers(environ=self._environ)


class Request(HTTPConnection):
    @cached_property
    def method(self) -> str:
        return self["REQUEST_METHOD"]

    def stream(self) -> Generator[bytes, None, None]:
        if "body" in self.__dict__:
            yield self.body
            return

        if self._stream_consumed:
            raise RuntimeError("Stream consumed")

        self._stream_consumed = True
        body = self._environ["wsgi.input"]
        while True:
            chunk = body.read(4096)
            if not chunk:
                return
            yield chunk

    @cached_property
    def body(self) -> bytes:
        chunks = []
        for chunk in self.stream():
            chunks.append(chunk)
        return b"".join(chunks)

    @cached_property
    def json(self) -> Any:
        if self.content_type == "application/json":
            return json.loads(
                self.body.decode(self.content_type.options.get("charset", "utf8"))
            )

        raise HTTPException(415, {"Accpet": "application/json"})

    @cached_property
    def form(self) -> FormData:
        if self.content_type == "multipart/form-data":
            return MultiPartParser(self.content_type, self.stream()).parse()
        if self.content_type == "application/x-www-form-urlencoded":
            data = self.body.decode(
                encoding=self.content_type.options.get("charset", "latin-1")
            )
            # this is type check error in mypy
            return FormData(parse_qsl(data, keep_blank_values=True))  # type: ignore

        raise HTTPException(
            415, {"Accpet": "multipart/form-data, application/x-www-form-urlencoded"}
        )

    def close(self) -> None:
        if "form" in self.__dict__:
            self.form.close()


class Response(BaseResponse):
    def __call__(
        self, environ: Environ, start_response: StartResponse
    ) -> Iterable[bytes]:
        start_response(StatusStringMapping[self.status_code], self.raw_headers, None)
        return (b"",)


ResponseContent = TypeVar("ResponseContent")


class SmallResponse(Generic[ResponseContent], Response):
    media_type: str = ""
    charset: str = "utf-8"

    def __init__(
        self,
        content: ResponseContent,
        status_code: int = 200,
        headers: Mapping[str, str] = None,
    ) -> None:
        super().__init__(status_code, headers)
        self.body = self.render(content)
        self.generate_more_headers()

    def render(self, content: ResponseContent) -> bytes:
        raise NotImplementedError

    def generate_more_headers(self) -> None:
        body = getattr(self, "body", b"")
        if body and not any(k == "content-length" for k, _ in self.raw_headers):
            content_length = str(len(body))
            self.raw_headers.append(("content-length", content_length))

        content_type = self.media_type
        if content_type and not any(k == "content-type" for k, _ in self.raw_headers):
            if content_type.startswith("text/"):
                content_type += "; charset=" + self.charset
            self.raw_headers.append(("content-type", content_type))

    def __call__(
        self, environ: Environ, start_response: StartResponse
    ) -> Iterable[bytes]:
        start_response(StatusStringMapping[self.status_code], self.raw_headers, None)
        yield self.body


class PlainTextResponse(SmallResponse[Union[bytes, str]]):
    media_type = "text/plain"

    def __init__(
        self,
        content: Union[bytes, str],
        status_code: int = 200,
        headers: Mapping[str, str] = None,
        media_type: str = "",
    ) -> None:
        self.media_type = media_type or self.media_type
        super().__init__(content, status_code, headers)

    def render(self, content: Union[bytes, str]) -> bytes:
        return content if isinstance(content, bytes) else content.encode(self.charset)


class HTMLResponse(PlainTextResponse):
    media_type = "text/html"


class JSONResponse(SmallResponse[JSONable]):
    media_type = "application/json"

    def __init__(
        self,
        content: JSONable,
        status_code: int = 200,
        headers: Mapping[str, str] = None,
        *,
        ensure_ascii: bool = False,
        allow_nan: bool = False,
        indent: Union[int, str] = None,
        separators: Optional[Tuple[str, str]] = (",", ":"),
        default: Callable[[Any], Any] = None,
        **kwargs: Any,
    ) -> None:
        self.json_kwargs = {
            "ensure_ascii": ensure_ascii,
            "allow_nan": allow_nan,
            "indent": indent,
            "separators": separators,
            "default": default,
            **kwargs,
        }
        super().__init__(content, status_code=status_code, headers=headers)

    def render(self, content: JSONable) -> bytes:
        # This is mypy error
        return json.dumps(content, **self.json_kwargs).encode("utf-8")  # type: ignore


class RedirectResponse(Response):
    def __init__(
        self,
        url: Union[str, URL],
        status_code: int = 307,
        headers: Mapping[str, str] = None,
    ) -> None:
        super().__init__(status_code=status_code, headers=headers)
        self.raw_headers.append(
            ("location", quote_plus(str(url), safe=":/%#?&=@[]!$&'()*+,;"))
        )


class StreamResponse(Response):
    def __init__(
        self,
        generator: Generator[bytes, None, None],
        status_code: int = 200,
        headers: Mapping[str, str] = None,
        content_type: str = "application/octet-stream",
    ) -> None:
        self.generator = generator
        super().__init__(status_code, headers)
        self.raw_headers.append(("content-type", content_type))
        self.raw_headers.append(("transfer-encoding", "chunked"))

    def __call__(
        self, environ: Environ, start_response: StartResponse
    ) -> Iterable[bytes]:
        start_response(StatusStringMapping[self.status_code], self.raw_headers, None)
        for chunk in self.generator:
            yield chunk


class FileResponse(BaseFileResponse, Response):
    def handle_all(
        self,
        send_header_only: bool,
        file_size: int,
        headers: MutableSequence[Tuple[str, str]],
        start_response: StartResponse,
    ) -> Generator[bytes, None, None]:
        headers.append(("content-type", str(self.media_type)))
        headers.append(("content-length", str(file_size)))
        start_response(
            StatusStringMapping[200], list(chain(self.raw_headers, headers)), None
        )

        if send_header_only:
            yield b""
            return

        with open(self.filepath, "rb") as file:
            for _ in range(0, file_size, 4096):
                yield file.read(4096)

    def handle_single_range(
        self,
        send_header_only: bool,
        file_size: int,
        headers: MutableSequence[Tuple[str, str]],
        start_response: StartResponse,
        start: int,
        end: int,
    ) -> Generator[bytes, None, None]:
        headers.append(("content-range", f"bytes {start}-{end-1}/{file_size}"))
        headers.append(("content-type", str(self.media_type)))
        headers.append(("content-length", str(end - start)))
        start_response(
            StatusStringMapping[206], list(chain(self.raw_headers, headers)), None
        )
        if send_header_only:
            yield b""
            return

        with open(self.filepath, "rb") as file:
            file.seek(start)
            for here in range(start, end, 4096):
                yield file.read(min(4096, end - here))
            return

    def handle_several_ranges(
        self,
        send_header_only: bool,
        file_size: int,
        headers: MutableSequence[Tuple[str, str]],
        start_response: StartResponse,
        ranges: Sequence[Tuple[int, int]],
    ) -> Generator[bytes, None, None]:
        headers.append(("content-type", "multipart/byteranges; boundary=3d6b6a416f9b5"))
        content_length = (
            18
            + len(ranges) * (57 + len(self.media_type) + len(str(file_size)))
            + sum(len(str(start)) + len(str(end - 1)) for start, end in ranges)
        ) + sum(end - start for start, end in ranges)
        headers.append(("content-length", str(content_length)))

        start_response(
            StatusStringMapping[206], list(chain(self.raw_headers, headers)), None
        )
        if send_header_only:
            yield b""
            return

        with open(self.filepath, "rb") as file:
            for start, end in ranges:
                file.seek(start)
                yield b"--3d6b6a416f9b5\n"
                yield f"Content-Type: {self.media_type}\n".encode("latin-1")
                yield f"Content-Range: bytes {start}-{end-1}/{file_size}\n".encode(
                    "latin-1"
                )
                yield b"\n"
                for here in range(start, end, 4096):
                    yield file.read(min(4096, end - here))
                yield b"\n"
            yield b"--3d6b6a416f9b5--\n"

    def __call__(
        self, environ: Environ, start_response: StartResponse
    ) -> Iterable[bytes]:
        send_header_only = environ["REQUEST_METHOD"] == "HEAD"

        stat_result = self.stat_result
        file_size = stat_result.st_size
        headers = self.generate_required_header(stat_result)

        if "HTTP_RANGE" not in environ or (
            "HTTP_IF_RANGE" in environ
            and not self.judge_if_range(environ["HTTP_IF_RANGE"], stat_result)
        ):
            yield from self.handle_all(
                send_header_only, file_size, headers, start_response
            )
            return

        try:
            ranges = self.parse_range(environ["HTTP_RANGE"], file_size)
        except HTTPException as exception:
            start_response(
                StatusStringMapping[exception.status_code],
                [(k, v) for k, v in (exception.headers or {}).items()],
                None,
            )
            yield b""
            return

        if len(ranges) == 1:
            start, end = ranges[0]
            yield from self.handle_single_range(
                send_header_only, file_size, headers, start_response, start, end
            )
        else:
            yield from self.handle_several_ranges(
                send_header_only, file_size, headers, start_response, ranges
            )


class SendEventResponse(Response):
    """
    Server-sent events
    """

    thread_pool = ThreadPoolExecutor(max_workers=10)

    required_headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "Content-Type": "text/event-stream",
    }

    def __init__(
        self,
        generator: Generator[ServerSentEvent, None, None],
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
        self.generator = generator
        self.ping_interval = ping_interval
        self.charset = charset
        self.queue: Queue = Queue(13)
        self.has_more_data = True

    def __call__(
        self, environ: Environ, start_response: StartResponse
    ) -> Iterable[bytes]:
        start_response(StatusStringMapping[self.status_code], self.raw_headers, None)

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
            if not future.done():
                future.cancel()

    def send_event(self) -> None:
        for chunk in self.generator:
            if "data" in chunk:
                data = (
                    f"data: {_}".encode(self.charset)
                    for _ in chunk.pop("data").splitlines()
                )
            event = b"\n".join(
                chain(
                    (f"{k}: {v}".encode(self.charset) for k, v in chunk.items()),
                    data,
                    (b"", b""),  # for generate b"\n\n"
                )
            )
            self.queue.put(event)

        self.has_more_data = False

    def keep_alive(self) -> None:
        while self.has_more_data:
            time.sleep(self.ping_interval)
            self.queue.put(b": ping\n\n")


def request_response(view: Callable[[Request], Response]) -> WSGIApp:
    @functools.wraps(view)
    def wsgi(environ: Environ, start_response: StartResponse) -> Iterable[bytes]:
        request = Request(environ)
        response = view(request)
        return response(environ, start_response)

    return wsgi


class Router(BaseRouter[WSGIApp]):
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


class Hosts(BaseHosts[WSGIApp]):
    def __call__(
        self, environ: Environ, start_response: StartResponse
    ) -> Iterable[bytes]:
        host = environ.get("HTTP_HOST", "")
        for host_pattern, endpoint in self._host_array:
            if host_pattern.fullmatch(host) is None:
                continue
            return endpoint(environ, start_response)

        return PlainTextResponse(b"Invalid host", 404)(environ, start_response)
