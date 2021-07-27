import abc
import asyncio
import functools
import json
from enum import Enum
from io import FileIO
from random import choices as random_choices
from typing import (
    Any,
    AsyncIterable,
    AsyncIterator,
    Awaitable,
    Callable,
    Dict,
    Generic,
    Iterable,
    Iterator,
    Mapping,
    Sequence,
    Tuple,
    TypeVar,
    Union,
)
from typing import cast as typing_cast
from urllib.parse import parse_qsl, quote

from .concurrency import run_in_threadpool
from .datastructures import URL, Address, FormData, Headers, QueryParams
from .exceptions import HTTPException
from .formparsers import AsyncMultiPartParser
from .requests import MoreInfoFromHeaderMixin
from .responses import BaseFileResponse, BaseResponse, build_bytes_from_sse
from .routing import BaseHosts, BaseRouter, BaseSubpaths
from .typing import ASGIApp, Message, Receive, Scope, Send, ServerSentEvent
from .utils import cached_property


async def send_http_start(
    send: Send, status_code: int, headers: Iterable[Tuple[bytes, bytes]] = None
) -> None:
    """
    helper function for send http.response.start

    https://asgi.readthedocs.io/en/latest/specs/www.html#response-start-send-event
    """
    message = {"type": "http.response.start", "status": status_code}
    if headers is not None:
        message["headers"] = headers
    await send(message)


async def send_http_body(
    send: Send, body: bytes = b"", *, more_body: bool = False
) -> None:
    """
    helper function for send http.response.body

    https://asgi.readthedocs.io/en/latest/specs/www.html#response-body-send-event
    """
    await send({"type": "http.response.body", "body": body, "more_body": more_body})


class ClientDisconnect(Exception):
    """
    HTTP connection disconnected.
    """


async def empty_receive() -> Message:
    raise NotImplementedError("Receive channel has not been made available")


async def empty_send(message: Message) -> None:
    raise NotImplementedError("Send channel has not been made available")


class HTTPConnection(Mapping[str, Any], MoreInfoFromHeaderMixin):
    """
    A base class for incoming HTTP connections.

    It is a valid Mapping type that allows you to directly
    access the values in any ASGI `scope` dictionary.
    """

    def __init__(
        self, scope: Scope, receive: Receive = empty_receive, send: Send = empty_send
    ) -> None:
        self._scope = scope
        self._send = send
        self._receive = receive

    def __getitem__(self, key: str) -> Any:
        return self._scope[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._scope)

    def __len__(self) -> int:
        return len(self._scope)

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, self.__class__):
            return NotImplemented
        return (
            self._scope == other._scope
            and self._send == other._send
            and self._receive == other._receive
        )

    @cached_property
    def client(self) -> Address:
        """
        Client's IP and Port.

        Note that this depends on the "client" value given by
        the ASGI Server, and is not necessarily accurate.
        """
        host, port = self.get("client") or (None, None)
        return Address(host=host, port=port)

    @cached_property
    def url(self) -> URL:
        """
        The full URL of this request.
        """
        return URL(scope=self._scope)

    @cached_property
    def path_params(self) -> Dict[str, Any]:
        """
        The path parameters parsed by the framework.
        """
        return self.get("path_params", {})

    @cached_property
    def query_params(self) -> QueryParams:
        """
        Query parameter. It is a multi-value mapping.
        """
        return QueryParams(self["query_string"])

    @cached_property
    def headers(self) -> Headers:
        """
        A read-only case-independent mapping.

        Note that in its internal storage, all keys are in lower case.
        """
        return Headers(
            (key.decode("latin-1"), value.decode("latin-1"))
            for key, value in self._scope["headers"]
        )


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
        """
        HTTP method. Uppercase string.
        """
        return self._scope["method"]

    async def stream(self) -> AsyncIterator[bytes]:
        """
        Streaming read request body. e.g. `async for chunk in request.stream(): ...`

        If you access `.stream()` then the byte chunks are provided
        without storing the entire body to memory. Any subsequent
        calls to `.body`, `.form`, or `.json` will raise an error.
        """
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
        """
        Read all the contents of the request body into the memory and return it.
        """
        return b"".join([chunk async for chunk in self.stream()])

    @cached_property
    async def json(self) -> Any:
        """
        Call `await self.body` and use `json.loads` parse it.

        If `content_type` is not equal to `application/json`,
        an HTTPExcption exception will be thrown.
        """
        if self.content_type == "application/json":
            data = await self.body
            return json.loads(
                data.decode(self.content_type.options.get("charset", "utf8"))
            )

        raise HTTPException(415, {"Accpet": "application/json"})

    @cached_property
    async def form(self) -> FormData:
        """
        Parse the data in the form format and return it as a multi-value mapping.

        If `content_type` is equal to `multipart/form-data`, it will directly
        perform streaming analysis, and subsequent calls to `self.body`
        or `self.json` will raise errors.

        If `content_type` is not equal to `multipart/form-data` or
        `application/x-www-form-urlencoded`, an HTTPExcption exception will be thrown.
        """
        if self.content_type == "multipart/form-data":
            return await AsyncMultiPartParser(self.content_type, self.stream()).parse()
        if self.content_type == "application/x-www-form-urlencoded":
            data = (await self.body).decode(
                encoding=self.content_type.options.get("charset", "latin-1")
            )
            return FormData(parse_qsl(data, keep_blank_values=True))

        raise HTTPException(
            415, {"Accpet": "multipart/form-data, application/x-www-form-urlencoded"}
        )

    async def close(self) -> None:
        """
        Close all temporary files in the `self.form`.

        This can always be called, regardless of whether you use form or not.
        """
        if "form" in self.__dict__ and self.__dict__["form"].done():
            await (await self.form).aclose()

    async def is_disconnected(self) -> bool:
        """
        The method used to determine whether the connection is interrupted.
        """
        if not self._is_disconnected:
            try:
                message = await asyncio.wait_for(self._receive(), timeout=0.0000001)
                self._is_disconnected = message.get("type") == "http.disconnect"
            except asyncio.TimeoutError:
                pass
        return self._is_disconnected


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
        headers: Mapping[str, str] = None,
        media_type: str = None,
        charset: str = None,
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

    async def render(self, content: Any) -> bytes:
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
        iterable: AsyncIterable[bytes],
        status_code: int = 200,
        headers: Mapping[str, str] = None,
        content_type: str = "application/octet-stream",
    ) -> None:
        self.iterable = iterable
        super().__init__(status_code, headers)
        self.headers["content-type"] = content_type
        self.headers["transfer-encoding"] = "chunked"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await send_http_start(send, self.status_code, self.list_headers(as_bytes=True))
        async for chunk in self.iterable:
            await send_http_body(send, chunk, more_body=True)
        return await send_http_body(send)


class FileResponse(BaseFileResponse, Response):
    """
    File response.

    It will automatically determine whether to send only headers
    and the range of files that need to be sent.
    """

    async def handle_all(
        self,
        send_header_only: bool,
        file_size: int,
        send: Send,
    ) -> None:
        self.headers["content-type"] = str(self.content_type)
        self.headers["content-length"] = str(file_size)
        await send_http_start(send, 200, self.list_headers(as_bytes=True))
        if send_header_only:
            return await send_http_body(send)

        file = typing_cast(FileIO, await run_in_threadpool(open, self.filepath, "rb"))
        try:
            for _ in range(0, file_size, self.chunk_size):
                await send_http_body(
                    send,
                    await run_in_threadpool(file.read, self.chunk_size),
                    more_body=True,
                )
            return await send_http_body(send)
        finally:
            await run_in_threadpool(file.close)

    async def handle_single_range(
        self,
        send_header_only: bool,
        file_size: int,
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

        file = typing_cast(FileIO, await run_in_threadpool(open, self.filepath, "rb"))
        try:
            await run_in_threadpool(file.seek, start)
            for here in range(start, end, self.chunk_size):
                await send_http_body(
                    send,
                    await run_in_threadpool(
                        file.read, min(self.chunk_size, end - here)
                    ),
                    more_body=True,
                )
            return await send_http_body(send)
        finally:
            await run_in_threadpool(file.close)

    async def handle_several_ranges(
        self,
        send_header_only: bool,
        file_size: int,
        send: Send,
        ranges: Sequence[Tuple[int, int]],
    ) -> None:
        boundary = "".join(random_choices("abcdefghijklmnopqrstuvwxyz0123456789", k=13))
        self.headers["content-type"] = f"multipart/byteranges; boundary={boundary}"
        content_length, generate_headers = self.generate_multipart(
            ranges, boundary, file_size
        )
        self.headers["content-length"] = str(content_length)
        await send_http_start(send, 206, self.list_headers(as_bytes=True))
        if send_header_only:
            return await send_http_body(send)

        file = typing_cast(FileIO, await run_in_threadpool(open, self.filepath, "rb"))
        try:
            for start, end in ranges:
                await send_http_body(send, generate_headers(start, end), more_body=True)
                await run_in_threadpool(file.seek, start)
                for here in range(start, end, self.chunk_size):
                    await send_http_body(
                        send,
                        await run_in_threadpool(
                            file.read, min(self.chunk_size, end - here)
                        ),
                        more_body=True,
                    )
                await send_http_body(send, b"\n", more_body=True)
            return await send_http_body(send, f"--{boundary}--\n".encode("ascii"))
        finally:
            await run_in_threadpool(file.close)

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
            return await self.handle_all(send_header_only, file_size, send)

        try:
            ranges = self.parse_range(http_range, file_size)
        except HTTPException as exception:
            await send_http_start(
                send,
                exception.status_code,
                [
                    (k.encode("latin-1"), v.encode("latin-1"))
                    for k, v in (exception.headers or {}).items()
                ],
            )
            return await send_http_body(send, exception.content or b"")

        if len(ranges) == 1:
            start, end = ranges[0]
            return await self.handle_single_range(
                send_header_only, file_size, send, start, end
            )
        else:
            return await self.handle_several_ranges(
                send_header_only, file_size, send, ranges
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
        """
        Accept websocket connection.
        """
        if self.client_state == WebSocketState.CONNECTING:
            # If we haven't yet seen the 'connect' message, then wait for it first.
            await self.receive()
        await self.send({"type": "websocket.accept", "subprotocol": subprotocol})

    def _raise_on_disconnect(self, message: Message) -> None:
        if message["type"] == "websocket.disconnect":
            raise WebSocketDisconnect(message["code"])

    async def receive_text(self) -> str:
        """
        Receive a WebSocket text frame and return.
        """
        assert self.application_state == WebSocketState.CONNECTED
        message = await self.receive()
        self._raise_on_disconnect(message)
        return message["text"]

    async def receive_bytes(self) -> bytes:
        """
        Receive a WebSocket binary frame and return.
        """
        assert self.application_state == WebSocketState.CONNECTED
        message = await self.receive()
        self._raise_on_disconnect(message)
        return message["bytes"]

    async def iter_text(self) -> AsyncIterator[str]:
        """
        Keep receiving text frames until the WebSocket connection is disconnected.
        """
        try:
            while True:
                yield await self.receive_text()
        except WebSocketDisconnect:
            pass

    async def iter_bytes(self) -> AsyncIterator[bytes]:
        """
        Keep receiving binary frames until the WebSocket connection is disconnected.
        """
        try:
            while True:
                yield await self.receive_bytes()
        except WebSocketDisconnect:
            pass

    async def send_text(self, data: str) -> None:
        """
        Send a WebSocket text frame.
        """
        await self.send({"type": "websocket.send", "text": data})

    async def send_bytes(self, data: bytes) -> None:
        """
        Send a WebSocket binary frame.
        """
        await self.send({"type": "websocket.send", "bytes": data})

    async def close(self, code: int = 1000) -> None:
        """
        Close WebSocket connection. It can be called multiple times.
        """
        if self.application_state != WebSocketState.DISCONNECTED:
            await self.send({"type": "websocket.close", "code": code})


def request_response(view: Callable[[Request], Awaitable[Response]]) -> ASGIApp:
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
        request = Request(scope, receive, send)
        resposne = await view(request)
        return await resposne(scope, receive, send)

    return asgi


class Router(BaseRouter[ASGIApp]):
    """
    A router to assign different paths to different ASGI applications.

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
    """

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


class Subpaths(BaseSubpaths[ASGIApp]):
    """
    A router allocates different prefix requests to different ASGI applications.

    NOTE: This will change the values of `scope["root_path"]` and `scope["path"]`.

    ```python
    applications = Subpaths(
        ("/static", static_files),
        ("/api", api_app),
        ("", default_app),
    )
    ```
    """

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope["path"]
        for prefix, endpoint in self._route_array:
            if not path.startswith(prefix):
                continue
            scope["root_path"] = scope.get("root_path", "") + prefix
            scope["path"] = path[len(prefix) :]
            return await endpoint(scope, receive, send)

        return await PlainTextResponse(b"", 404)(scope, receive, send)


class Hosts(BaseHosts[ASGIApp]):
    r"""
    A router that distributes requests to different ASGI applications based on Host.

    ```python
    applications = Hosts(
        (r"static\.example\.com", static_files),
        (r"api\.example\.com", api_app),
        (r"(www\.)?example\.com", default_app),
    )
    ```
    """

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
