import abc
import json
import os
import queue
import stat
from http import HTTPStatus
from mimetypes import guess_type
from queue import Queue
from random import choices as random_choices
from typing import (
    Any,
    Dict,
    Generator,
    Generic,
    Iterable,
    Mapping,
    Optional,
    Sequence,
    Tuple,
    TypeVar,
    Union,
)

from baize.concurrency import ThreadPoolExecutor
from baize.datastructures import URL, defaultdict
from baize.exceptions import MalformedRangeHeader, RangeNotSatisfiable
from baize.responses import (
    BaseResponse,
    FileResponseMixin,
    build_bytes_from_sse,
    iri_to_uri,
)
from baize.typing import Environ, ServerSentEvent, StartResponse

StatusStringMapping = defaultdict(
    lambda status: f"{status} Unknown Status Code",
    {int(status): f"{status} {status.phrase}" for status in HTTPStatus},
)


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
        headers: Optional[Mapping[str, str]] = None,
        media_type: Optional[str] = None,
        charset: Optional[str] = None,
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
        headers: Optional[Mapping[str, str]] = None,
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
        headers: Optional[Mapping[str, str]] = None,
    ) -> None:
        super().__init__(status_code=status_code, headers=headers)
        self.headers["location"] = iri_to_uri(str(url))


class StreamResponse(Response):
    def __init__(
        self,
        iterable: Iterable[bytes],
        status_code: int = 200,
        headers: Optional[Mapping[str, str]] = None,
        content_type: str = "application/octet-stream",
    ) -> None:
        self.iterable = iterable
        super().__init__(status_code, headers)
        self.headers["content-type"] = content_type

    def __call__(
        self, environ: Environ, start_response: StartResponse
    ) -> Iterable[bytes]:
        start_response(
            StatusStringMapping[self.status_code], self.list_headers(as_bytes=False)
        )
        yield from self.iterable


class FileResponse(Response, FileResponseMixin):
    """
    File response.

    It will automatically determine whether to send only headers
    and the range of files that need to be sent.
    """

    def __init__(
        self,
        filepath: str,
        headers: Optional[Mapping[str, str]] = None,
        content_type: Optional[str] = None,
        download_name: Optional[str] = None,
        stat_result: Optional[os.stat_result] = None,
        chunk_size: int = 4096 * 64,
    ) -> None:
        super().__init__(headers=headers)
        self.filepath = filepath
        self.content_type = (
            content_type
            or guess_type(download_name or os.path.basename(filepath))[0]
            or "application/octet-stream"
        )
        self.download_name = download_name
        self.stat_result = stat_result or os.stat(filepath)
        if stat.S_ISDIR(self.stat_result.st_mode):
            raise IsADirectoryError(f"{filepath} is a directory")
        self.chunk_size = chunk_size
        self.headers.update(
            self.generate_common_headers(
                self.filepath, self.content_type, self.download_name, self.stat_result
            )
        )

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
            ranges, boundary, file_size, self.content_type
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
        except (MalformedRangeHeader, RangeNotSatisfiable) as exception:
            start_response(
                StatusStringMapping[exception.status_code],
                [*(exception.headers or {}).items()],
            )
            yield b"" if exception.content is None else exception.content.encode("utf8")
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

    thread_pool = ThreadPoolExecutor(max_workers=10, thread_name_prefix="SendEvent_")

    required_headers = {
        "Cache-Control": "no-cache",
        # https://www.python.org/dev/peps/pep-3333/#other-http-features
        # WSGI application must not send connection header
        # "Connection": "keep-alive",
        "Content-Type": "text/event-stream",
    }

    def __init__(
        self,
        iterable: Iterable[ServerSentEvent],
        status_code: int = 200,
        headers: Optional[Mapping[str, str]] = None,
        *,
        ping_interval: float = 3,
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
        future = self.thread_pool.submit(self.send_event)

        try:
            while self.has_more_data or not self.queue.empty():
                try:
                    yield self.queue.get(timeout=self.ping_interval)
                except queue.Empty:
                    yield b": ping\n\n"
        finally:
            self.has_more_data = False
            future.cancel()

    def send_event(self) -> None:
        for chunk in self.iterable:
            self.queue.put(build_bytes_from_sse(chunk, self.charset))
        self.has_more_data = False
