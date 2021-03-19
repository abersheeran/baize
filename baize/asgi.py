import asyncio
import functools
import json
from enum import Enum
from itertools import chain
from typing import (
    Any,
    AsyncGenerator,
    AsyncIterator,
    Awaitable,
    Callable,
    Dict,
    Generic,
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

from .datastructures import URL, Address, FormData, Headers, QueryParams
from .exceptions import HTTPException
from .formparsers import AsyncMultiPartParser
from .requests import MoreInfoFromHeaderMixin
from .responses import BaseFileResponse, BaseResponse
from .routing import BaseHosts, BaseRouter
from .typing import ASGIApp, JSONable, Message, Receive, Scope, Send, ServerSentEvent
from .utils import cached_property


class ClientDisconnect(Exception):
    pass


async def empty_receive() -> Message:
    raise NotImplementedError("Receive channel has not been made available")


async def empty_send(message: Message) -> None:
    raise NotImplementedError("Send channel has not been made available")


class HTTPConnection(Mapping, MoreInfoFromHeaderMixin):
    """
    A base class for incoming HTTP connections, that is used to provide
    any functionality that is common to both `Request` and `WebSocket`.
    """

    def __init__(
        self, scope: Scope, receive: Receive = empty_receive, send: Send = empty_send
    ) -> None:
        self._scope = scope
        self._send = send
        self._receive = receive

    def __getitem__(self, key: str) -> str:
        return self._scope[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._scope)

    def __len__(self) -> int:
        return len(self._scope)

    @cached_property
    def client(self) -> Address:
        host, port = self.get("client") or (None, None)
        return Address(host=host, port=port)

    @cached_property
    def url(self) -> URL:
        return URL(scope=self._scope)

    @cached_property
    def path_params(self) -> Dict[str, Any]:
        return self.get("path_params", {})

    @cached_property
    def query_params(self) -> QueryParams:
        return QueryParams(self["query_string"])

    @cached_property
    def headers(self) -> Headers:
        return Headers(scope=self._scope)


class Request(HTTPConnection):
    def __init__(
        self, scope: Scope, receive: Receive = empty_receive, send: Send = empty_send
    ) -> None:
        assert scope["type"] == "http"
        super().__init__(scope, receive, send)
        self._stream_consumed = False
        self._is_disconnected = False

    @cached_property
    def method(self) -> str:
        return self._scope["method"]

    async def stream(self) -> AsyncGenerator[bytes, None]:
        if "body" in self.__dict__ and self.__dict__["body"].done():
            yield await self.body
            yield b""
            return

        if self._stream_consumed:
            raise RuntimeError("Stream consumed")

        self._stream_consumed = True
        while True:
            message = await self._receive()
            if message["type"] == "http.request":
                body = message.get("body", b"")
                if body:
                    yield body
                if not message.get("more_body", False):
                    break
            elif message["type"] == "http.disconnect":
                self._is_disconnected = True
                raise ClientDisconnect()
        yield b""

    @cached_property
    async def body(self) -> bytes:
        chunks = []
        async for chunk in self.stream():
            chunks.append(chunk)
        return b"".join(chunks)

    @cached_property
    async def json(self) -> Any:
        if self.content_type == "application/json":
            data = await self.body
            return json.loads(
                data.decode(self.content_type.options.get("charset", "utf8"))
            )

        raise HTTPException(415, {"Accpet": "application/json"})

    @cached_property
    async def form(self) -> FormData:
        if self.content_type == "multipart/form-data":
            return await AsyncMultiPartParser(self.content_type, self.stream()).parse()
        if self.content_type == "application/x-www-form-urlencoded":
            data = (await self.body).decode(
                encoding=self.content_type.options.get("charset", "latin-1")
            )
            # this is type check error in mypy
            return FormData(parse_qsl(data, keep_blank_values=True))  # type: ignore

        raise HTTPException(
            415, {"Accpet": "multipart/form-data, application/x-www-form-urlencoded"}
        )

    async def close(self) -> None:
        if "form" in self.__dict__ and self.__dict__["form"].done():
            await (await self.form).aclose()

    async def is_disconnected(self) -> bool:
        if not self._is_disconnected:
            try:
                message = await asyncio.wait_for(self._receive(), timeout=0.0000001)
            except asyncio.TimeoutError:
                message = {}

            self._is_disconnected = message.get("type") == "http.disconnect"

        return self._is_disconnected


class Response(BaseResponse):
    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": self.status_code,
                "headers": [
                    (k.encode("latin-1"), v.encode("latin-1"))
                    for k, v in self.raw_headers
                ],
            }
        )
        await send({"type": "http.response.body", "body": b""})


ResponseContent = TypeVar("ResponseContent")


class SmallResponse(Generic[ResponseContent], Response):
    media_type: str = ""
    charset = "utf-8"

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

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": self.status_code,
                "headers": [
                    (k.encode("latin-1"), v.encode("latin-1"))
                    for k, v in self.raw_headers
                ],
            }
        )
        await send({"type": "http.response.body", "body": self.body})


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
        self, url: Union[str, URL], status_code: int = 307, headers: dict = None
    ) -> None:
        super().__init__(status_code=status_code, headers=headers)
        self.raw_headers.append(
            ("location", quote_plus(str(url), safe=":/%#?&=@[]!$&'()*+,;"))
        )


class StreamResponse(Response):
    def __init__(
        self,
        generator: AsyncGenerator[bytes, None],
        status_code: int = 200,
        headers: Mapping[str, str] = None,
        content_type: str = "application/octet-stream",
    ) -> None:
        self.generator = generator
        super().__init__(status_code, headers)
        self.raw_headers.append(("content-type", content_type))
        self.raw_headers.append(("transfer-encoding", "chunked"))

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": self.status_code,
                "headers": [
                    (k.encode("latin-1"), v.encode("latin-1"))
                    for k, v in self.raw_headers
                ],
            }
        )
        async for chunk in self.generator:
            await send({"type": "http.response.body", "body": chunk, "more_body": True})

        await send({"type": "http.response.body", "body": b"", "more_body": False})


class FileResponse(BaseFileResponse, Response):
    async def handle_all(
        self,
        send_header_only: bool,
        file_size: int,
        headers: MutableSequence[Tuple[str, str]],
        loop: asyncio.AbstractEventLoop,
        send: Send,
    ) -> None:
        headers.append(("content-type", str(self.media_type)))
        headers.append(("content-length", str(file_size)))
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [
                    (k.encode("latin-1"), v.encode("latin-1"))
                    for k, v in chain(self.raw_headers, headers)
                ],
            }
        )
        if send_header_only:
            return await send({"type": "http.response.body", "body": b""})

        file = await loop.run_in_executor(None, open, self.filepath, "rb")
        try:
            for _ in range(0, file_size, 4096):
                await send(
                    {
                        "type": "http.response.body",
                        "body": await loop.run_in_executor(None, file.read, 4096),
                        "more_body": True,
                    }
                )
            await send({"type": "http.response.body", "body": b""})
        finally:
            await loop.run_in_executor(None, file.close)

    async def handle_single_range(
        self,
        send_header_only: bool,
        file_size: int,
        headers: MutableSequence[Tuple[str, str]],
        loop: asyncio.AbstractEventLoop,
        send: Send,
        start: int,
        end: int,
    ) -> None:
        headers.append(("content-range", f"bytes {start}-{end-1}/{file_size}"))
        headers.append(("content-type", str(self.media_type)))
        headers.append(("content-length", str(end - start)))
        await send(
            {
                "type": "http.response.start",
                "status": 206,
                "headers": [
                    (k.encode("latin-1"), v.encode("latin-1"))
                    for k, v in chain(self.raw_headers, headers)
                ],
            }
        )
        if send_header_only:
            return await send({"type": "http.response.body", "body": b""})

        file = await loop.run_in_executor(None, open, self.filepath, "rb")
        try:
            await loop.run_in_executor(None, file.seek, start)
            for here in range(start, end, 4096):
                await send(
                    {
                        "type": "http.response.body",
                        "body": await loop.run_in_executor(
                            None, file.read, min(4096, end - here)
                        ),
                        "more_body": True,
                    }
                )
            await send({"type": "http.response.body", "body": b""})
        finally:
            await loop.run_in_executor(None, file.close)

    async def handle_several_ranges(
        self,
        send_header_only: bool,
        file_size: int,
        headers: MutableSequence[Tuple[str, str]],
        loop: asyncio.AbstractEventLoop,
        send: Send,
        ranges: Sequence[Tuple[int, int]],
    ) -> None:
        headers.append(("content-type", "multipart/byteranges; boundary=3d6b6a416f9b5"))
        content_length = (
            18
            + len(ranges) * (57 + len(self.media_type) + len(str(file_size)))
            + sum(len(str(start)) + len(str(end - 1)) for start, end in ranges)
        ) + sum(end - start for start, end in ranges)
        headers.append(("content-length", str(content_length)))
        await send(
            {
                "type": "http.response.start",
                "status": 206,
                "headers": [
                    (k.encode("latin-1"), v.encode("latin-1"))
                    for k, v in chain(self.raw_headers, headers)
                ],
            }
        )
        if send_header_only:
            return await send({"type": "http.response.body", "body": b""})

        file = await loop.run_in_executor(None, open, self.filepath, "rb")
        try:
            for start, end in ranges:
                range_header = (
                    "--3d6b6a416f9b5\n"
                    f"Content-Type: {self.media_type}\n"
                    f"Content-Range: bytes {start}-{end-1}/{file_size}\n\n"
                ).encode("latin-1")
                await send(
                    {
                        "type": "http.response.body",
                        "body": range_header,
                        "more_body": True,
                    }
                )
                await loop.run_in_executor(None, file.seek, start)
                for here in range(start, end, 4096):
                    await send(
                        {
                            "type": "http.response.body",
                            "body": await loop.run_in_executor(
                                None, file.read, min(4096, end - here)
                            ),
                            "more_body": True,
                        }
                    )
                await send(
                    {"type": "http.response.body", "body": b"\n", "more_body": True}
                )
            await send(
                {
                    "type": "http.response.body",
                    "body": b"--3d6b6a416f9b5--\n",
                    "more_body": True,
                }
            )
            await send({"type": "http.response.body", "body": b""})
        finally:
            await loop.run_in_executor(None, file.close)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        send_header_only = scope["method"] == "HEAD"

        loop = asyncio.get_running_loop()
        stat_result = self.stat_result
        file_size = stat_result.st_size
        headers = self.generate_required_header(stat_result)

        http_range, http_if_range = "", ""
        for key, value in scope["headers"]:
            if key == b"range":
                http_range = value.decode("latin-1")
            elif key == b"if-range":
                http_if_range = value.decode("latin-1")

        if http_range == "" or (
            http_if_range != "" and not self.judge_if_range(http_if_range, stat_result)
        ):
            return await self.handle_all(
                send_header_only, file_size, headers, loop, send
            )

        try:
            ranges = self.parse_range(http_range, file_size)
        except HTTPException as exception:
            await send(
                {
                    "type": "http.response.start",
                    "status": exception.status_code,
                    "headers": [
                        (k.encode("latin-1"), v.encode("latin-1"))
                        for k, v in (exception.headers or {}).items()
                    ],
                }
            )
            return await send(
                {"type": "http.response.body", "body": exception.content or b""}
            )

        if len(ranges) == 1:
            start, end = ranges[0]
            return await self.handle_single_range(
                send_header_only, file_size, headers, loop, send, start, end
            )
        else:
            return await self.handle_several_ranges(
                send_header_only, file_size, headers, loop, send, ranges
            )


class SendEventResponse(Response):
    """
    Server-sent events
    """

    required_headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "Content-Type": "text/event-stream",
    }

    def __init__(
        self,
        generator: AsyncGenerator[ServerSentEvent, None],
        status_code: int = 200,
        headers: Mapping[str, str] = None,
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
        self.generator = generator
        self.ping_interval = ping_interval
        self.charset = charset

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": self.status_code,
                "headers": [
                    (k.encode("latin-1"), v.encode("latin-1"))
                    for k, v in self.raw_headers
                ],
            }
        )

        done, pending = await asyncio.wait(
            (self.keep_alive(send), self.send_event(send)),
            return_when=asyncio.FIRST_COMPLETED,
        )
        [task.cancel() for task in pending]
        [task.result() for task in done]
        await send({"type": "http.response.body", "body": b""})

    async def send_event(self, send: Send) -> None:
        async for chunk in self.generator:
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
            await send({"type": "http.response.body", "body": event, "more_body": True})

    async def keep_alive(self, send: Send) -> None:
        while True:
            await asyncio.sleep(self.ping_interval)
            await send(
                {
                    "type": "http.response.body",
                    "body": ": ping\n\n".encode(self.charset),
                    "more_body": True,
                }
            )


class WebSocketDisconnect(Exception):
    def __init__(self, code: int = 1000) -> None:
        self.code = code


class WebSocketState(Enum):
    CONNECTING = 0
    CONNECTED = 1
    DISCONNECTED = 2


class WebSocket(HTTPConnection):
    def __init__(self, scope: Scope, receive: Receive, send: Send) -> None:
        assert scope["type"] == "websocket"
        super().__init__(scope, receive, send)
        self.client_state = WebSocketState.CONNECTING
        self.application_state = WebSocketState.CONNECTING

    async def receive(self) -> Message:
        """
        Receive ASGI websocket messages, ensuring valid state transitions.
        """
        if self.client_state == WebSocketState.CONNECTING:
            message = await self._receive()
            message_type = message["type"]
            assert message_type == "websocket.connect"
            self.client_state = WebSocketState.CONNECTED
            return message
        elif self.client_state == WebSocketState.CONNECTED:
            message = await self._receive()
            message_type = message["type"]
            assert message_type in {"websocket.receive", "websocket.disconnect"}
            if message_type == "websocket.disconnect":
                self.client_state = WebSocketState.DISCONNECTED
            return message
        else:
            raise RuntimeError(
                'Cannot call "receive" once a disconnect message has been received.'
            )

    async def send(self, message: Message) -> None:
        """
        Send ASGI websocket messages, ensuring valid state transitions.
        """
        if self.application_state == WebSocketState.CONNECTING:
            message_type = message["type"]
            assert message_type in {"websocket.accept", "websocket.close"}
            if message_type == "websocket.close":
                self.application_state = WebSocketState.DISCONNECTED
            else:
                self.application_state = WebSocketState.CONNECTED
            await self._send(message)
        elif self.application_state == WebSocketState.CONNECTED:
            message_type = message["type"]
            assert message_type in {"websocket.send", "websocket.close"}
            if message_type == "websocket.close":
                self.application_state = WebSocketState.DISCONNECTED
            await self._send(message)
        else:
            raise RuntimeError('Cannot call "send" once a close message has been sent.')

    async def accept(self, subprotocol: str = None) -> None:
        if self.client_state == WebSocketState.CONNECTING:
            # If we haven't yet seen the 'connect' message, then wait for it first.
            await self.receive()
        await self.send({"type": "websocket.accept", "subprotocol": subprotocol})

    def _raise_on_disconnect(self, message: Message) -> None:
        if message["type"] == "websocket.disconnect":
            raise WebSocketDisconnect(message["code"])

    async def receive_text(self) -> str:
        assert self.application_state == WebSocketState.CONNECTED
        message = await self.receive()
        self._raise_on_disconnect(message)
        return message["text"]

    async def receive_bytes(self) -> bytes:
        assert self.application_state == WebSocketState.CONNECTED
        message = await self.receive()
        self._raise_on_disconnect(message)
        return message["bytes"]

    async def iter_text(self) -> AsyncIterator[str]:
        try:
            while True:
                yield await self.receive_text()
        except WebSocketDisconnect:
            pass

    async def iter_bytes(self) -> AsyncIterator[bytes]:
        try:
            while True:
                yield await self.receive_bytes()
        except WebSocketDisconnect:
            pass

    async def send_text(self, data: str) -> None:
        await self.send({"type": "websocket.send", "text": data})

    async def send_bytes(self, data: bytes) -> None:
        await self.send({"type": "websocket.send", "bytes": data})

    async def close(self, code: int = 1000) -> None:
        if self.application_state != WebSocketState.DISCONNECTED:
            await self.send({"type": "websocket.close", "code": code})


def request_response(view: Callable[[Request], Awaitable[Response]]) -> ASGIApp:
    @functools.wraps(view)
    async def asgi(scope: Scope, receive: Receive, send: Send) -> None:
        request = Request(scope, receive, send)
        resposne = await view(request)
        return await resposne(scope, receive, send)

    return asgi


class Router(BaseRouter[ASGIApp]):
    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope["path"]
        for route in self._route_array:
            match_up, path_params = route.matches(path)
            if not match_up:
                continue
            scope["path_params"] = path_params
            scope["router"] = self
            return await route.endpoint(scope, receive, send)

        return await PlainTextResponse(b"", 404)(scope, receive, send)


class Hosts(BaseHosts[ASGIApp]):
    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        host = ""
        for k, v in scope["headers"]:
            if k == b"host":
                host = v.decode("latin-1")
        for host_pattern, endpoint in self._host_array:
            if host_pattern.fullmatch(host) is None:
                continue
            return await endpoint(scope, receive, send)

        return await PlainTextResponse(b"Invalid host", 404)(scope, receive, send)
