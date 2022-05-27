import asyncio
import json
from typing import Any, AsyncIterator, Dict, Iterator, Mapping
from urllib.parse import parse_qsl

from baize.datastructures import (
    URL,
    Address,
    FormData,
    Headers,
    QueryParams,
    UploadFile,
)
from baize.exceptions import MalformedJSON, MalformedMultipart, UnsupportedMediaType
from baize.multipart_helper import parse_async_stream as parse_multipart
from baize.requests import MoreInfoFromHeaderMixin
from baize.typing import Receive, Scope, Send
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
            try:
                return json.loads(
                    data.decode(self.content_type.options.get("charset", "utf8"))
                )
            except json.JSONDecodeError as exc:
                raise MalformedJSON(str(exc)) from None

        raise UnsupportedMediaType("application/json")

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
            if "boundary" not in self.content_type.options:
                raise MalformedMultipart("Missing boundary in header content-type")
            boundary = self.content_type.options["boundary"].encode("latin-1")
            return FormData(
                await parse_multipart(
                    self.stream(), boundary, charset, file_factory=UploadFile
                )
            )
        if self.content_type == "application/x-www-form-urlencoded":
            body = (await self.body).decode(
                encoding=self.content_type.options.get("charset", "latin-1")
            )
            return FormData(parse_qsl(body, keep_blank_values=True))

        raise UnsupportedMediaType(
            "multipart/form-data, application/x-www-form-urlencoded"
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
