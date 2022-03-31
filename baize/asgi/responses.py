import abc
import asyncio
import json
import os
import stat
from mimetypes import guess_type
from random import choices as random_choices
from typing import (
    Any,
    AsyncIterable,
    Dict,
    Generic,
    Mapping,
    Optional,
    Sequence,
    Tuple,
    TypeVar,
    Union,
)

from baize.concurrency import run_in_threadpool
from baize.datastructures import URL
from baize.exceptions import MalformedRangeHeader, RangeNotSatisfiable
from baize.responses import (
    BaseResponse,
    FileResponseMixin,
    build_bytes_from_sse,
    iri_to_uri,
)
from baize.typing import Protocol, Receive, Scope, Send, ServerSentEvent

from .helper import send_http_body, send_http_start


class Response(BaseResponse):
    """
    The parent class of all responses, whose objects can be used directly as ASGI
    application.
    """

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        self.headers["content-length"] = "0"
        await send_http_start(send, self.status_code, self.list_headers(as_bytes=True))
        return await send_http_body(send)


_ContentType = TypeVar("_ContentType")


class SmallResponse(Response, abc.ABC, Generic[_ContentType]):
    """
    Abstract base class for small response objects.
    """

    media_type: str = ""
    charset = "utf-8"

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
    async def render(self, content: _ContentType) -> bytes:
        raise NotImplementedError

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        body = await self.render(self.content)
        if body and "content-length" not in self.headers:
            content_length = str(len(body))
            self.headers["content-length"] = content_length
        content_type = self.media_type
        if content_type and "content-type" not in self.headers:
            if content_type.startswith("text/"):
                content_type += "; charset=" + self.charset
            self.headers["content-type"] = content_type
        await send_http_start(send, self.status_code, self.list_headers(as_bytes=True))
        await send_http_body(send, body)


class PlainTextResponse(SmallResponse[Union[bytes, str]]):
    media_type = "text/plain"

    async def render(self, content: Union[bytes, str]) -> bytes:
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

    async def render(self, content: Any) -> bytes:
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
        iterable: AsyncIterable[bytes],
        status_code: int = 200,
        headers: Optional[Mapping[str, str]] = None,
        content_type: str = "application/octet-stream",
    ) -> None:
        self.iterable = iterable
        super().__init__(status_code, headers)
        self.headers["content-type"] = content_type

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await send_http_start(send, self.status_code, self.list_headers(as_bytes=True))
        async for chunk in self.iterable:
            await send_http_body(send, chunk, more_body=True)
        return await send_http_body(send)


class Sendfile(Protocol):
    async def __call__(
        self,
        file_descriptor: int,
        offset: Optional[int] = None,
        count: Optional[int] = None,
        more_body: bool = False,
    ) -> None:
        pass


if os.name == "nt":  # pragma: py-no-win32

    async def open_for_sendfile(
        path: Union[str, bytes, "os.PathLike[str]", "os.PathLike[bytes]"]
    ) -> int:
        return await run_in_threadpool(os.open, path, os.O_RDONLY | os.O_BINARY)

else:  # pragma: py-win32

    async def open_for_sendfile(
        path: Union[str, bytes, "os.PathLike[str]", "os.PathLike[bytes]"]
    ) -> int:
        return await run_in_threadpool(os.open, path, os.O_RDONLY)


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

    def create_send_or_zerocopy(self, scope: Scope, send: Send) -> Sendfile:
        """
        https://asgi.readthedocs.io/en/latest/extensions.html#zero-copy-send
        """
        if (
            "extensions" in scope
            and "http.response.zerocopysend" in scope["extensions"]
        ):  # pragma: no cover

            async def sendfile(
                file_descriptor: int,
                offset: Optional[int] = None,
                count: Optional[int] = None,
                more_body: bool = False,
            ) -> None:
                message = {
                    "type": "http.response.zerocopysend",
                    "file": file_descriptor,
                    "more_body": more_body,
                }
                if offset is not None:
                    message["offset"] = offset
                if count is not None:
                    message["count"] = count
                await send(message)

            return sendfile
        else:

            async def fake_sendfile(
                file_descriptor: int,
                offset: Optional[int] = None,
                count: Optional[int] = None,
                more_body: bool = False,
            ) -> None:
                if offset is not None:
                    await run_in_threadpool(
                        os.lseek, file_descriptor, offset, os.SEEK_SET
                    )

                here = 0
                should_stop = False
                if count is None:
                    length = self.chunk_size
                    while not should_stop:
                        data = await run_in_threadpool(os.read, file_descriptor, length)
                        if len(data) == length:
                            await send_http_body(send, data, more_body=True)
                        else:
                            await send_http_body(send, data, more_body=more_body)
                            should_stop = True
                else:
                    while not should_stop:
                        length = min(self.chunk_size, count - here)
                        should_stop = length == count - here
                        here += length
                        data = await run_in_threadpool(os.read, file_descriptor, length)
                        await send_http_body(
                            send, data, more_body=more_body if should_stop else True
                        )

            return fake_sendfile

    async def handle_all(
        self, send_header_only: bool, file_size: int, scope: Scope, send: Send
    ) -> None:
        self.headers["content-type"] = str(self.content_type)
        self.headers["content-length"] = str(file_size)
        await send_http_start(send, 200, self.list_headers(as_bytes=True))
        if send_header_only:
            return await send_http_body(send)

        sendfile = self.create_send_or_zerocopy(scope, send)
        file_descriptor = await open_for_sendfile(self.filepath)
        try:
            await sendfile(file_descriptor)
        finally:
            await run_in_threadpool(os.close, file_descriptor)

    async def handle_single_range(
        self,
        send_header_only: bool,
        file_size: int,
        scope: Scope,
        send: Send,
        start: int,
        end: int,
    ) -> None:
        self.headers["content-range"] = f"bytes {start}-{end-1}/{file_size}"
        self.headers["content-type"] = str(self.content_type)
        self.headers["content-length"] = str(end - start)
        await send_http_start(send, 206, self.list_headers(as_bytes=True))
        if send_header_only:
            return await send_http_body(send)

        sendfile = self.create_send_or_zerocopy(scope, send)
        file_descriptor = await open_for_sendfile(self.filepath)
        try:
            await sendfile(file_descriptor, start, end - start)
        finally:
            await run_in_threadpool(os.close, file_descriptor)

    async def handle_several_ranges(
        self,
        send_header_only: bool,
        file_size: int,
        scope: Scope,
        send: Send,
        ranges: Sequence[Tuple[int, int]],
    ) -> None:
        boundary = "".join(random_choices("abcdefghijklmnopqrstuvwxyz0123456789", k=13))
        self.headers["content-type"] = f"multipart/byteranges; boundary={boundary}"
        content_length, generate_headers = self.generate_multipart(
            ranges, boundary, file_size, self.content_type
        )
        self.headers["content-length"] = str(content_length)
        await send_http_start(send, 206, self.list_headers(as_bytes=True))
        if send_header_only:
            return await send_http_body(send)
        sendfile = self.create_send_or_zerocopy(scope, send)
        file_descriptor = await open_for_sendfile(self.filepath)
        try:
            for start, end in ranges:
                await send_http_body(send, generate_headers(start, end), more_body=True)
                await sendfile(file_descriptor, start, end - start, True)
                await send_http_body(send, b"\n", more_body=True)
            return await send_http_body(send, f"--{boundary}--\n".encode("ascii"))
        finally:
            await run_in_threadpool(os.close, file_descriptor)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        send_header_only = scope["method"] == "HEAD"

        stat_result = self.stat_result
        file_size = stat_result.st_size

        http_range, http_if_range = "", ""
        for key, value in scope["headers"]:
            if key == b"range":
                http_range = value.decode("latin-1")
            elif key == b"if-range":
                http_if_range = value.decode("latin-1")

        if http_range == "" or (
            http_if_range != "" and not self.judge_if_range(http_if_range, stat_result)
        ):
            return await self.handle_all(send_header_only, file_size, scope, send)

        try:
            ranges = self.parse_range(http_range, file_size)
        except (MalformedRangeHeader, RangeNotSatisfiable) as exception:
            await send_http_start(
                send,
                exception.status_code,
                [
                    (k.encode("latin-1"), v.encode("latin-1"))
                    for k, v in (exception.headers or {}).items()
                ],
            )
            return await send_http_body(
                send,
                b"" if exception.content is None else exception.content.encode("utf8"),
            )

        if len(ranges) == 1:
            start, end = ranges[0]
            return await self.handle_single_range(
                send_header_only, file_size, scope, send, start, end
            )
        else:
            return await self.handle_several_ranges(
                send_header_only, file_size, scope, send, ranges
            )


class SendEventResponse(Response):
    """
    Server-sent events response.

    :param ping_interval: This determines the time interval (in seconds) between sending ping messages.
    """

    required_headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "Content-Type": "text/event-stream",
    }

    def __init__(
        self,
        iterable: AsyncIterable[ServerSentEvent],
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
        self.client_closed = False
        self.charset = charset

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": self.status_code,
                "headers": self.list_headers(as_bytes=True),
            }
        )

        done, pending = await asyncio.wait(
            (
                asyncio.ensure_future(self.keep_alive(send)),
                asyncio.ensure_future(self.send_event(send)),
                asyncio.ensure_future(self.wait_close(receive)),
            ),
            return_when=asyncio.FIRST_COMPLETED,
        )
        [task.cancel() for task in pending]
        [task.result() for task in done]
        return await send_http_body(send)

    async def send_event(self, send: Send) -> None:
        async for chunk in self.iterable:
            body = build_bytes_from_sse(chunk, self.charset)
            await send_http_body(send, body, more_body=True)

    async def keep_alive(self, send: Send) -> None:
        while not self.client_closed:
            await asyncio.sleep(self.ping_interval)
            ping = b": ping\n\n"
            await send_http_body(send, ping, more_body=True)

    async def wait_close(self, receive: Receive) -> None:
        while not self.client_closed:
            message = await receive()
            self.client_closed = message["type"] == "http.disconnect"
