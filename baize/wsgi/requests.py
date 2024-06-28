import json
from typing import Any, Dict, Iterator, Mapping, Optional
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
from baize.multipart_helper import parse_stream as parse_multipart
from baize.requests import MoreInfoFromHeaderMixin
from baize.typing import Environ, StartResponse
from baize.utils import cached_property


class HTTPConnection(Mapping[str, Any], MoreInfoFromHeaderMixin):
    """
    A base class for incoming HTTP connections.

    It is a valid Mapping type that allows you to directly
    access the values in any WSGI `environ` dictionary.
    """

    def __init__(
        self, environ: Environ, start_response: Optional[StartResponse] = None
    ) -> None:
        self._environ = environ
        self._start_response = start_response

    def __getitem__(self, key: str) -> Any:
        return self._environ[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._environ)

    def __len__(self) -> int:
        return len(self._environ)

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, self.__class__):
            return NotImplemented
        return (
            self._environ == other._environ
            and self._start_response == other._start_response
        )

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
            (
                (key[5:] if key.startswith("HTTP_") else key).lower().replace("_", "-"),
                value,
            )
            for key, value in self._environ.items()
            if key.startswith("HTTP_") or key in ("CONTENT_TYPE", "CONTENT_LENGTH")
        )


class Request(HTTPConnection):
    def __init__(
        self, environ: Environ, start_response: Optional[StartResponse] = None
    ) -> None:
        super().__init__(environ, start_response)
        self._stream_consumed = False

    @property
    def method(self) -> str:
        """
        HTTP method. Uppercase string.
        """
        return self["REQUEST_METHOD"]

    def stream(self, chunk_size: int = 4096 * 16) -> Iterator[bytes]:
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
            try:
                return json.loads(
                    self.body.decode(self.content_type.options.get("charset", "utf8"))
                )
            except json.JSONDecodeError as exc:
                raise MalformedJSON(str(exc)) from None

        raise UnsupportedMediaType("application/json")

    def _parse_multipart(self, boundary: bytes, charset: str) -> FormData:
        return FormData(
            parse_multipart(self.stream(), boundary, charset, file_factory=UploadFile)
        )

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
            charset = self.content_type.options.get("charset", "utf8")
            if "boundary" not in self.content_type.options:
                raise MalformedMultipart("Missing boundary in header content-type")
            boundary = self.content_type.options["boundary"].encode("latin-1")
            return self._parse_multipart(boundary, charset)
        if self.content_type == "application/x-www-form-urlencoded":
            body = self.body.decode(
                encoding=self.content_type.options.get("charset", "latin-1")
            )
            return FormData(parse_qsl(body, keep_blank_values=True))

        raise UnsupportedMediaType(
            "multipart/form-data, application/x-www-form-urlencoded"
        )

    def close(self) -> None:
        """
        Close all temporary files in the `self.form`.

        This can always be called, regardless of whether you use form or not.
        """
        if "form" in self.__dict__:
            self.form.close()
