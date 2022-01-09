import json
from itertools import chain
from typing import Any, Dict, Iterator, List, Mapping, Optional, Tuple, Union
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
from baize.typing import Environ
from baize.utils import cached_property


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
            charset = self.content_type.options.get("charset", "utf8")
            parser = multipart.MultipartDecoder(
                self.content_type.options["boundary"].encode("latin-1"), charset
            )
            field_name = ""
            data = bytearray()
            file: Optional[UploadFile] = None

            items: List[Tuple[str, Union[str, UploadFile]]] = []

            for chunk in self.stream():
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
                            file.write(event.data)

                        if not event.more_data:
                            if file is None:
                                items.append(
                                    (field_name, multipart.safe_decode(data, charset))
                                )
                                data.clear()
                            else:
                                file.seek(0)
                                items.append((field_name, file))
                                file = None

            return FormData(items)
        if self.content_type == "application/x-www-form-urlencoded":
            body = self.body.decode(
                encoding=self.content_type.options.get("charset", "latin-1")
            )
            return FormData(parse_qsl(body, keep_blank_values=True))

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
