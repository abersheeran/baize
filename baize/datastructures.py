import datetime
import os
import re
import string
import typing
from tempfile import SpooledTemporaryFile
from urllib.parse import SplitResult, parse_qsl, urlencode, urlsplit

from .concurrency import run_in_threadpool
from .typing import Environ, Final, Literal, Scope
from .utils import parse_header

__all__ = [
    "Address",
    "MediaType",
    "ContentType",
    "Cookie",
    "URL",
    "MultiMapping",
    "MutableMultiMapping",
    "QueryParams",
    "Headers",
    "MutableHeaders",
    "UploadFile",
    "FormData",
]


T = typing.TypeVar("T")  # Any type.
KT = typing.TypeVar("KT")  # Key type.
VT = typing.TypeVar("VT")  # Value type.


class Address(typing.NamedTuple):
    host: typing.Optional[str]
    port: typing.Optional[int]


class defaultdict(dict):
    def __init__(self, default_factory, *args, **kwargs) -> None:
        self.default_factory = default_factory
        super().__init__(*args, **kwargs)

    def __missing__(self, key):
        return self.default_factory(key)


class MediaType:
    __slots__ = ("main_type", "sub_type", "options")

    def __init__(self, media_type_raw_line: str) -> None:
        full_type, self.options = parse_header(media_type_raw_line)
        self.main_type, _, self.sub_type = full_type.partition("/")

    def __str__(self) -> str:
        return (
            self.main_type
            + (f"/{self.sub_type}" if self.sub_type else "")
            + "".join(f"; {k}={v}" for k, v in self.options.items())
        )

    def __repr__(self) -> str:
        return f"<{self.__class__.__qualname__}: {self}>"

    @property
    def is_all_types(self) -> bool:
        return self.main_type == "*" and self.sub_type == "*"

    def match(self, other: str) -> bool:
        if self.is_all_types:
            return True
        other_media_type = MediaType(other)
        return self.main_type == other_media_type.main_type and (
            self.sub_type in {"*", other_media_type.sub_type}
        )


class ContentType:
    __slots__ = ("type", "options")

    def __init__(self, content_type_raw_line: str) -> None:
        self.type, self.options = parse_header(content_type_raw_line)

    def __repr__(self) -> str:
        return f"<{self.__class__.__qualname__}: {self}>"

    def __str__(self) -> str:
        return self.type + "".join(f"; {k}={v}" for k, v in self.options.items())

    def __eq__(self, other: typing.Any) -> bool:
        if not isinstance(other, str):
            return NotImplemented
        return self.type == other


_cookie_legal_chars: Final[str] = (
    string.ascii_letters + string.digits + "!#$%&'*+-.^_`|~:"
)
_cookie_is_legal_key = re.compile("[%s]+" % re.escape(_cookie_legal_chars)).fullmatch
_cookie_translator: Final[typing.Dict[int, str]] = {
    **{
        n: "\\%03o" % n
        for n in set(range(256)) - set(map(ord, _cookie_legal_chars + " ()/<=>?@[]{}"))
    },
    ord('"'): '\\"',
    ord("\\"): "\\\\",
}


class Cookie:
    def __init__(
        self,
        name: str,
        value: str,
        expires: typing.Optional[datetime.datetime] = None,
        domain: typing.Optional[str] = None,
        path: typing.Optional[str] = None,
        httponly: bool = False,
        secure: bool = False,
        max_age: int = -1,
        samesite: Literal["strict", "lax", "none"] = "lax",
    ):
        self.name = name
        self.value = value
        self.expires = expires
        self.domain = domain
        self.path = path
        self.httponly = httponly
        self.secure = secure
        self.max_age = max_age
        self.samesite = samesite

    def _quote(self, value: str) -> str:
        r"""
        Quote a string for use in a cookie header.

        If the string does not need to be double-quoted, then just return the
        string.  Otherwise, surround the string in doublequotes and quote
        (with a \) special characters.
        """
        if _cookie_is_legal_key(value):
            return value
        else:
            return '"' + value.translate(_cookie_translator) + '"'

    def __str__(self) -> str:
        parts: typing.List[str] = []
        parts.append(f"{self._quote(self.name)}={self._quote(self.value)}")

        if self.expires:
            parts.append(
                "expires=" + self.expires.strftime("%a, %d %b %Y %H:%M:%S GMT")
            )

        if self.max_age > -1:
            parts.append(f"max-age={self.max_age}")

        if self.domain:
            parts.append(f"domain={self.domain}")

        if self.path:
            parts.append(f"path={self.path}")

        if self.httponly:
            parts.append("httponly")

        if self.secure or self.samesite in ("strict", "none"):
            parts.append("secure")

        parts.append(f"samesite={self.samesite}")

        return "; ".join(parts)

    def __bytes__(self) -> bytes:
        return str(self).encode("ascii")

    def __eq__(self, other: object) -> bool:
        if isinstance(other, str):
            return str(self) == other
        if isinstance(other, bytes):
            return bytes(self) == other
        if isinstance(other, Cookie):
            return str(self) == str(other)
        return NotImplemented

    def __repr__(self) -> str:
        return f"<Cookie {self.name}: {self.value}>"


class URL:
    __slots__ = ("_url", "_components")

    def __init__(
        self,
        url: str = "",
        *,
        scope: typing.Optional[Scope] = None,
        environ: typing.Optional[Environ] = None,
        **components: typing.Any,
    ) -> None:
        if components:
            assert not url, 'Cannot set both "url" and "**components".'
            url = URL("").replace(**components).components.geturl()
        elif scope is not None:
            scheme = scope.get("scheme", "http")
            server = scope.get("server", None)
            path = scope.get("root_path", "") + scope["path"]
            query_string = scope.get("query_string", b"")

            host_header = None
            for key, value in scope["headers"]:
                if key == b"host":
                    host_header = value.decode("latin-1")
                    break
            url = self._build_url(scheme, path, query_string, server, host_header)
        elif environ is not None:
            scheme = environ["wsgi.url_scheme"]
            server = (environ["SERVER_NAME"], int(environ["SERVER_PORT"]))
            path = (
                (environ.get("SCRIPT_NAME", "") + environ.get("PATH_INFO", ""))
                .encode("latin1")
                .decode("utf8")
            )
            query_string = environ.get("QUERY_STRING", "").encode("latin-1")
            host_header = environ.get("HTTP_HOST", None)
            url = self._build_url(scheme, path, query_string, server, host_header)

        self._url = url
        self._components = urlsplit(url)

    def _build_url(
        self,
        scheme: str,
        path: str,
        query_string: bytes = b"",
        server: typing.Optional[typing.Tuple[str, typing.Optional[int]]] = None,
        host_header: typing.Optional[str] = None,
    ) -> str:
        if host_header is not None:
            url = f"{scheme}://{host_header}{path}"
        elif server is None:
            url = path
        else:
            host, port = server
            default_port = {"http": 80, "https": 443, "ws": 80, "wss": 443}[scheme]
            if port == default_port or port is None:
                url = f"{scheme}://{host}{path}"
            else:
                url = f"{scheme}://{host}:{port}{path}"

        if query_string:
            url = f"{url}?{query_string.decode()}"

        return url

    @property
    def components(self) -> SplitResult:
        return self._components

    @property
    def scheme(self) -> str:
        return self.components.scheme

    @property
    def netloc(self) -> str:
        return self.components.netloc

    @property
    def path(self) -> str:
        return self.components.path

    @property
    def query(self) -> str:
        return self.components.query

    @property
    def fragment(self) -> str:
        return self.components.fragment

    @property
    def username(self) -> typing.Optional[str]:
        return self.components.username

    @property
    def password(self) -> typing.Optional[str]:
        return self.components.password

    @property
    def hostname(self) -> typing.Optional[str]:
        return self.components.hostname

    @property
    def port(self) -> typing.Optional[int]:
        return self.components.port

    def replace(self, **kwargs: typing.Any) -> "URL":
        if (
            "username" in kwargs
            or "password" in kwargs
            or "hostname" in kwargs
            or "port" in kwargs
        ):
            hostname = kwargs.pop("hostname", None)
            port = kwargs.pop("port", self.port)
            username = kwargs.pop("username", self.username)
            password = kwargs.pop("password", self.password)

            if hostname is None:
                netloc = self.netloc
                _, _, hostname = netloc.rpartition("@")

                if hostname[-1] != "]":
                    hostname = hostname.rsplit(":", 1)[0]

            netloc = hostname
            if port is not None:
                netloc += f":{port}"
            if username is not None:
                userpass = username
                if password is not None:
                    userpass += f":{password}"
                netloc = f"{userpass}@{netloc}"

            kwargs["netloc"] = netloc

        components = self.components._replace(**kwargs)
        return self.__class__(components.geturl())

    def include_query_params(self, **kwargs: typing.Any) -> "URL":
        params: MutableMultiMapping[str, str] = MutableMultiMapping(
            parse_qsl(self.query, keep_blank_values=True)
        )
        params.update({key: str(value) for key, value in kwargs.items()})
        query = urlencode(params.multi_items())
        return self.replace(query=query)

    def replace_query_params(self, **kwargs: typing.Any) -> "URL":
        query = urlencode([(key, str(value)) for key, value in kwargs.items()])
        return self.replace(query=query)

    def remove_query_params(self, *keys: str) -> "URL":
        params: MutableMultiMapping[str, str] = MutableMultiMapping(
            parse_qsl(self.query, keep_blank_values=True)
        )
        [params.pop(key, None) for key in keys]
        query = urlencode(params.multi_items())
        return self.replace(query=query)

    def __eq__(self, other: typing.Any) -> bool:
        return str(self) == str(other)

    def __str__(self) -> str:
        return self._url

    def __repr__(self) -> str:
        url = str(self)
        if self.password:
            url = str(self.replace(password="********"))
        return f"{self.__class__.__name__}({repr(url)})"


class MultiMapping(typing.Generic[KT, VT], typing.Mapping[KT, VT]):
    __slots__ = ("_dict", "_list")

    def __init__(
        self,
        raw: typing.Optional[
            typing.Union[
                typing.Mapping[KT, VT],
                typing.Iterable[typing.Tuple[KT, VT]],
            ]
        ] = None,
    ) -> None:
        _items: typing.List[typing.Tuple[KT, VT]]
        if raw is None:
            _items = []
        elif isinstance(raw, MultiMapping):
            _items = typing.cast(
                typing.List[typing.Tuple[KT, VT]], list(raw.multi_items())
            )
        elif isinstance(raw, typing.Mapping):
            _items = typing.cast(typing.List[typing.Tuple[KT, VT]], list(raw.items()))
        else:
            _items = list(raw)

        self._dict = dict(_items)
        self._list = _items

    def __getitem__(self, key: KT) -> VT:
        return self._dict[key]

    def __iter__(self) -> typing.Iterator[KT]:
        return iter(self._dict)

    def __len__(self) -> int:
        return len(self._dict)

    def getlist(self, key: KT) -> typing.List[VT]:
        return [item_value for item_key, item_value in self._list if item_key == key]

    def multi_items(self) -> typing.List[typing.Tuple[KT, VT]]:
        return list(self._list)

    def __eq__(self, other: typing.Any) -> bool:
        return isinstance(other, type(self)) and sorted(self._list) == sorted(
            other._list
        )

    def __repr__(self) -> str:
        class_name = self.__class__.__name__
        items = self.multi_items()
        return f"{class_name}({items!r})"


class MutableMultiMapping(
    typing.Generic[KT, VT], MultiMapping[KT, VT], typing.MutableMapping[KT, VT]
):
    __slots__ = MultiMapping.__slots__

    def __setitem__(self, key: KT, value: VT) -> None:
        indexes = tuple(index for index, kv in enumerate(self._list) if kv[0] == key)
        if indexes:
            frist_index = indexes[0]
            for index in reversed(indexes):
                if index == frist_index:
                    self._list[index] = (key, value)
                else:
                    del self._list[index]
        else:
            self._list.append((key, value))
        self._dict[key] = value

    def __delitem__(self, key: KT) -> None:
        _list = self._list[:]
        self._list.clear()
        self._list.extend((k, v) for k, v in _list if k != key)
        del self._dict[key]

    def setlist(self, key: KT, values: typing.Sequence[VT]) -> None:
        if values:
            self._list = [
                *((k, v) for k, v in self._list if k != key),
                *((key, value) for value in values),
            ]
            self._dict[key] = values[-1]
        elif key in self:
            del self[key]

    def poplist(self, key: KT) -> typing.List[VT]:
        values = [v for k, v in self._list if k == key]
        try:
            del self[key]
        except KeyError:
            pass
        return values

    def append(self, key: KT, value: VT) -> None:
        self._list.append((key, value))
        self._dict[key] = value


class QueryParams(MultiMapping[str, str]):
    """
    An immutable MutableMultiMapping.
    """

    __slots__ = ("_dict", "_list")

    def __init__(
        self,
        raw: typing.Optional[
            typing.Union[
                "MultiMapping[str, str]",
                typing.Mapping[str, str],
                typing.Iterable[typing.Tuple[str, str]],
                str,
                bytes,
            ]
        ] = None,
    ) -> None:
        if isinstance(raw, str):
            super().__init__(parse_qsl(raw, keep_blank_values=True))
        elif isinstance(raw, bytes):
            super().__init__(parse_qsl(raw.decode("latin-1"), keep_blank_values=True))
        else:
            super().__init__(raw)

    def __str__(self) -> str:
        return urlencode(self._list)

    def __repr__(self) -> str:
        class_name = self.__class__.__name__
        query_string = str(self)
        return f"{class_name}({query_string!r})"


class Headers(typing.Mapping[str, str]):
    __slots__ = ("_dict",)

    def __init__(
        self,
        headers: typing.Optional[
            typing.Union[
                typing.Mapping[str, str],
                typing.Iterable[typing.Tuple[str, str]],
            ]
        ] = None,
    ) -> None:
        store: typing.Dict[str, str] = {}
        items: typing.Iterable[typing.Tuple[str, str]]
        if isinstance(headers, typing.Mapping):
            items = typing.cast(
                typing.Iterable[typing.Tuple[str, str]], headers.items()
            )
        elif headers is None:
            items = ()
        else:
            items = headers
        for key, value in items:
            key = key.lower()
            if key in store:
                store[key] = f"{store[key]}, {value}"
            else:
                store[key] = value

        self._dict = store

    def __getitem__(self, key: str) -> str:
        return self._dict[key.lower()]

    def __iter__(self) -> typing.Iterator[str]:
        return self._dict.__iter__()

    def __len__(self) -> int:
        return self._dict.__len__()


class MutableHeaders(Headers, typing.MutableMapping[str, str]):
    __slots__ = Headers.__slots__

    def __setitem__(self, key: str, value: str) -> None:
        if "\n" in key or "\r" in key or "\0" in key:
            raise ValueError("Header names must not contain control characters.")
        if "\n" in value or "\r" in value or "\0" in value:
            raise ValueError("Header values must not contain control characters.")
        self._dict[key.lower()] = value

    def __delitem__(self, key: str) -> None:
        del self._dict[key.lower()]

    def append(self, key: str, value: str) -> None:
        if key in self:
            self[key] = f"{self[key]}, {value}"
        else:
            self[key] = value


class UploadFile:
    """
    An uploaded file included as part of the request data.
    """

    __slots__ = ("filename", "headers", "content_type", "file")

    spool_max_size = 1024 * 1024

    def __init__(self, filename: str, headers: Headers) -> None:
        self.filename = filename
        self.headers = headers
        self.content_type = headers.get("content-type", "")
        self.file = SpooledTemporaryFile(max_size=self.spool_max_size, mode="w+b")

    @property
    def in_memory(self) -> bool:
        rolled_to_disk = getattr(self.file, "_rolled", True)
        return not rolled_to_disk

    def write(self, data: bytes) -> None:
        self.file.write(data)

    async def awrite(self, data: bytes) -> None:
        if self.in_memory:
            self.write(data)
        else:
            await run_in_threadpool(self.write, data)

    def read(self, size: int = -1) -> bytes:
        return self.file.read(size)

    async def aread(self, size: int = -1) -> bytes:
        if self.in_memory:
            return self.read(size)
        return await run_in_threadpool(self.read, size)

    def seek(self, offset: int) -> None:
        self.file.seek(offset)

    async def aseek(self, offset: int) -> None:
        if self.in_memory:
            self.seek(offset)
        else:
            await run_in_threadpool(self.seek, offset)

    def close(self) -> None:
        self.file.close()

    async def aclose(self) -> None:
        if self.in_memory:
            self.close()
        else:
            await run_in_threadpool(self.close)

    def save(self, filepath: str) -> None:
        """
        Save file to disk.
        """
        # from shutil.COPY_BUFSIZE
        copy_bufsize = 1024 * 1024 if os.name == "nt" else 64 * 1024
        file_position = self.file.tell()
        self.file.seek(0, 0)
        try:
            with open(filepath, "wb+") as target_file:
                source_read = self.file.read
                target_write = target_file.write
                while True:
                    buf = source_read(copy_bufsize)
                    if not buf:
                        break
                    target_write(buf)
        finally:
            self.file.seek(file_position)

    async def asave(self, filepath: str) -> None:
        """
        Save file to disk, work in threading pool.
        """
        await run_in_threadpool(self.save, filepath)


class FormData(MultiMapping[str, typing.Union[str, UploadFile]]):
    """
    An immutable MultiMapping, containing both file uploads and text input.
    """

    __slots__ = MultiMapping.__slots__

    def close(self) -> None:
        for key, value in self.multi_items():
            if isinstance(value, UploadFile):
                value.close()

    async def aclose(self) -> None:
        for key, value in self.multi_items():
            if isinstance(value, UploadFile):
                await value.aclose()
