import asyncio
import json
from enum import Enum
from typing import (
    Any,
    AsyncIterator,
    Dict,
    Iterator,
    List,
    Mapping,
    Optional,
    Tuple,
    Union,
)
from urllib.parse import parse_qsl

from baize import multipart
from baize.datastructures import (
    URL,
    Address,
    FormData,
    Headers,
    QueryParams,
    UploadFile,
)
from baize.exceptions import HTTPException
from baize.requests import MoreInfoFromHeaderMixin
from baize.typing import Message, Receive, Scope, Send
from baize.utils import cached_property

from .helper import empty_receive, empty_send


class ClientDisconnect(Exception):
    """
    HTTP connection disconnected.
    """


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
            charset = self.content_type.options.get("charset", "utf8")
            parser = multipart.MultipartDecoder(
                self.content_type.options["boundary"].encode("latin-1"), charset
            )
            field_name = ""
            data = bytearray()
            file: Optional[UploadFile] = None

            items: List[Tuple[str, Union[str, UploadFile]]] = []

            async for chunk in self.stream():
                parser.receive_data(chunk)
                while True:
                    event = parser.next_event()
                    if isinstance(event, (multipart.Epilogue, multipart.NeedData)):
                        break
                    elif isinstance(event, multipart.Field):
                        field_name = event.name
                    elif isinstance(event, multipart.File):
                        field_name = event.name
                        file = UploadFile(
                            event.filename, event.headers.get("content-type", "")
                        )
                    elif isinstance(event, multipart.Data):
                        if file is None:
                            data.extend(event.data)
                        else:
                            await file.awrite(event.data)

                        if not event.more_data:
                            if file is None:
                                items.append(
                                    (field_name, multipart.safe_decode(data, charset))
                                )
                                data.clear()
                            else:
                                await file.aseek(0)
                                items.append((field_name, file))
                                file = None

            return FormData(items)
        if self.content_type == "application/x-www-form-urlencoded":
            body = (await self.body).decode(
                encoding=self.content_type.options.get("charset", "latin-1")
            )
            return FormData(parse_qsl(body, keep_blank_values=True))

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
