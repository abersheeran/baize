import asyncio
import typing
from cgi import parse_header
from collections import namedtuple
from tempfile import SpooledTemporaryFile
from urllib.parse import SplitResult, parse_qsl, urlencode, urlsplit

from .typing import Environ, Scope

__all__ = [
    "Address",
    "MediaType",
    "ContentType",
    "URL",
    "MultiMapping",
    "MutableMultiMapping",
    "QueryParams",
    "UploadFile",
    "FormData",
    "Headers",
    "MutableHeaders",
]


T = typing.TypeVar("T")  # Any type.
KT = typing.TypeVar("KT")  # Key type.
VT = typing.TypeVar("VT")  # Value type.


Address = namedtuple("Address", ["host", "port"])


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


class URL:
    __slots__ = ("_url", "_components")

    def __init__(
        self,
        url: str = "",
        *,
        scope: Scope = None,
        environ: Environ = None,
        **components: typing.Any,
    ) -> None:
        if scope is not None or environ is not None:
            assert not (url or components)
            if scope is not None:
                scheme = scope.get("scheme", "http")
                server = scope.get("server", None)
                path = scope.get("root_path", "") + scope["path"]
                query_string = scope.get("query_string", b"")

                host_header = None
                for key, value in scope["headers"]:
                    if key == b"host":
                        host_header = value.decode("latin-1")
                        break
            elif environ is not None:
                scheme = environ["wsgi.url_scheme"]
                server = (environ["SERVER_NAME"], environ["SERVER_PORT"])
                path = (
                    (environ.get("SCRIPT_NAME", "") + environ.get("PATH_INFO", ""))
                    .encode("latin1")
                    .decode("utf8")
                )
                query_string = environ.get("QUERY_STRING", "").encode("latin-1")
                host_header = environ.get("HTTP_HOST", None)

            if host_header is not None:
                url = f"{scheme}://{host_header}{path}"
            elif server is None:
                url = path
            else:
                host, port = server
                default_port = {"http": 80, "https": 443, "ws": 80, "wss": 443}[scheme]
                if port == default_port:
                    url = f"{scheme}://{host}{path}"
                else:
                    url = f"{scheme}://{host}:{port}{path}"

            if query_string:
                url += "?" + query_string.decode()
        elif components:
            assert not url, 'Cannot set both "url" and "**components".'
            url = URL("").replace(**components).components.geturl()

        self._url = url
        self._components = urlsplit(url)

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
            hostname = kwargs.pop("hostname", self.hostname)
            port = kwargs.pop("port", self.port)
            username = kwargs.pop("username", self.username)
            password = kwargs.pop("password", self.password)

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
        raw: typing.Union[
            typing.Mapping[KT, VT],
            typing.Iterable[typing.Tuple[KT, VT]],
        ] = None,
    ) -> None:
        if raw is None:
            _items = []
        elif isinstance(raw, MultiMapping):
            _items = list(raw.multi_items())
        elif isinstance(raw, typing.Mapping):
            _items = list(raw.items())
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

    def getlist(self, key: KT) -> typing.Sequence[VT]:
        return [item_value for item_key, item_value in self._list if item_key == key]

    def multi_items(self) -> typing.Sequence[typing.Tuple[KT, VT]]:
        return list(self._list)

    def __eq__(self, other: typing.Any) -> bool:
        if not isinstance(other, self.__class__):
            return False
        return sorted(self._list) == sorted(other._list)

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

    def poplist(self, key: KT) -> typing.Sequence[VT]:
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
        raw: typing.Union[
            "MultiMapping[str, str]",
            typing.Mapping[str, str],
            typing.Iterable[typing.Tuple[str, str]],
            str,
            bytes,
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


class UploadFile:
    """
    An uploaded file included as part of the request data.
    """

    __slots__ = ("filename", "content_type", "file")

    spool_max_size = 1024 * 1024

    def __init__(self, filename: str, content_type: str = "") -> None:
        self.filename = filename
        self.content_type = content_type
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
            await asyncio.get_event_loop().run_in_executor(None, self.write, data)

    def read(self, size: int = -1) -> bytes:
        return self.file.read(size)

    async def aread(self, size: int = -1) -> bytes:
        if self.in_memory:
            return self.read(size)
        return await asyncio.get_event_loop().run_in_executor(None, self.read, size)

    def seek(self, offset: int) -> None:
        self.file.seek(offset)

    async def aseek(self, offset: int) -> None:
        if self.in_memory:
            self.seek(offset)
        else:
            await asyncio.get_event_loop().run_in_executor(None, self.seek, offset)

    def close(self) -> None:
        self.file.close()

    async def aclose(self) -> None:
        if self.in_memory:
            self.close()
        else:
            await asyncio.get_event_loop().run_in_executor(None, self.close)


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


class Headers(typing.Mapping[str, str]):
    __slots__ = ("_dict",)

    def __init__(
        self,
        headers: typing.Union[
            typing.Mapping[str, str],
            typing.Iterable[typing.Tuple[str, str]],
        ] = None,
    ) -> None:
        store: typing.Dict[str, str] = {}
        items: typing.Iterable[typing.Tuple[str, str]]
        if isinstance(headers, typing.Mapping):
            items = headers.items()
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
        self._dict[key.lower()] = value

    def __delitem__(self, key: str) -> None:
        del self._dict[key.lower()]

    def append(self, key: str, value: str) -> None:
        key = key.lower()
        if key in self._dict:
            self._dict[key] = f"{self._dict[key]}, {value}"
        else:
            self._dict[key] = value
