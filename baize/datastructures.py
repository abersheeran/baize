import asyncio
import typing
from cgi import parse_header
from collections import namedtuple
from itertools import chain
from tempfile import SpooledTemporaryFile
from urllib.parse import SplitResult, parse_qsl, urlencode, urlsplit

from .typing import Environ, Scope

__all__ = [
    "Address",
    "MediaType",
    "ContentType",
    "URL",
    "ImmutableMultiDict",
    "MultiDict",
    "QueryParams",
    "UploadFile",
    "FormData",
    "Headers",
    "MutableHeaders",
]


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
                path = environ.get("SCRIPT_NAME", "") + environ.get("PATH_INFO", "")
                query_string = environ.get("QUERY_STRING", "").encode("ascii")
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
    def username(self) -> typing.Union[None, str]:
        return self.components.username

    @property
    def password(self) -> typing.Union[None, str]:
        return self.components.password

    @property
    def hostname(self) -> typing.Union[None, str]:
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
        params = MultiDict(parse_qsl(self.query, keep_blank_values=True))
        params.update({str(key): str(value) for key, value in kwargs.items()})
        query = urlencode(params.multi_items())
        return self.replace(query=query)

    def replace_query_params(self, **kwargs: typing.Any) -> "URL":
        query = urlencode([(str(key), str(value)) for key, value in kwargs.items()])
        return self.replace(query=query)

    def remove_query_params(
        self, keys: typing.Union[str, typing.Sequence[str]]
    ) -> "URL":
        if isinstance(keys, str):
            keys = [keys]
        params = MultiDict(parse_qsl(self.query, keep_blank_values=True))
        for key in keys:
            params.pop(key, None)
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


class ImmutableMultiDict(typing.Mapping):
    __slots__ = ("_dict", "_list")

    def __init__(
        self,
        *args: typing.Union[
            "ImmutableMultiDict",
            typing.Mapping,
            typing.List[typing.Tuple[typing.Any, typing.Any]],
        ],
        **kwargs: typing.Any,
    ) -> None:
        assert len(args) < 2, "Too many arguments."

        if args:
            value = args[0]
        else:
            value = []

        if kwargs:
            value = (
                ImmutableMultiDict(value).multi_items()
                + ImmutableMultiDict(kwargs).multi_items()
            )

        if not value:
            _items = []  # type: typing.List[typing.Tuple[typing.Any, typing.Any]]
        elif hasattr(value, "multi_items"):
            value = typing.cast(ImmutableMultiDict, value)
            _items = list(value.multi_items())
        elif hasattr(value, "items"):
            value = typing.cast(typing.Mapping, value)
            _items = list(value.items())
        else:
            value = typing.cast(
                typing.List[typing.Tuple[typing.Any, typing.Any]], value
            )
            _items = list(value)

        self._dict = {k: v for k, v in _items}
        self._list = _items

    def getlist(self, key: typing.Any) -> typing.List[str]:
        return [item_value for item_key, item_value in self._list if item_key == key]

    def keys(self) -> typing.KeysView:
        return self._dict.keys()

    def values(self) -> typing.ValuesView:
        return self._dict.values()

    def items(self) -> typing.ItemsView:
        return self._dict.items()

    def multi_items(self) -> typing.List[typing.Tuple[str, str]]:
        return list(self._list)

    def get(self, key: typing.Any, default: typing.Any = None) -> typing.Any:
        if key in self._dict:
            return self._dict[key]
        return default

    def __getitem__(self, key: typing.Any) -> str:
        return self._dict[key]

    def __contains__(self, key: typing.Any) -> bool:
        return key in self._dict

    def __iter__(self) -> typing.Iterator[typing.Any]:
        return iter(self.keys())

    def __len__(self) -> int:
        return len(self._dict)

    def __eq__(self, other: typing.Any) -> bool:
        if not isinstance(other, self.__class__):
            return False
        return sorted(self._list) == sorted(other._list)

    def __repr__(self) -> str:
        class_name = self.__class__.__name__
        items = self.multi_items()
        return f"{class_name}({items!r})"


class MultiDict(ImmutableMultiDict):
    __slots__ = ("_dict", "_list")

    def __setitem__(self, key: typing.Any, value: typing.Any) -> None:
        self.setlist(key, [value])

    def __delitem__(self, key: typing.Any) -> None:
        self._list = [(k, v) for k, v in self._list if k != key]
        del self._dict[key]

    def pop(self, key: typing.Any, default: typing.Any = None) -> typing.Any:
        self._list = [(k, v) for k, v in self._list if k != key]
        return self._dict.pop(key, default)

    def popitem(self) -> typing.Tuple:
        key, value = self._dict.popitem()
        self._list = [(k, v) for k, v in self._list if k != key]
        return key, value

    def poplist(self, key: typing.Any) -> typing.List:
        values = [v for k, v in self._list if k == key]
        self.pop(key)
        return values

    def clear(self) -> None:
        self._dict.clear()
        self._list.clear()

    def setdefault(self, key: typing.Any, default: typing.Any = None) -> typing.Any:
        if key not in self:
            self._dict[key] = default
            self._list.append((key, default))

        return self[key]

    def setlist(self, key: typing.Any, values: typing.List) -> None:
        if not values:
            self.pop(key, None)
        else:
            existing_items = [(k, v) for (k, v) in self._list if k != key]
            self._list = existing_items + [(key, value) for value in values]
            self._dict[key] = values[-1]

    def append(self, key: typing.Any, value: typing.Any) -> None:
        self._list.append((key, value))
        self._dict[key] = value

    def update(
        self,
        *args: typing.Union[
            "MultiDict",
            typing.Mapping,
            typing.List[typing.Tuple[typing.Any, typing.Any]],
        ],
        **kwargs: typing.Any,
    ) -> None:
        value = MultiDict(*args, **kwargs)
        existing_items = [(k, v) for (k, v) in self._list if k not in value.keys()]
        self._list = existing_items + value.multi_items()
        self._dict.update(value)


class QueryParams(ImmutableMultiDict):
    """
    An immutable multidict.
    """

    __slots__ = ("_dict", "_list")

    def __init__(
        self,
        *args: typing.Union[
            ImmutableMultiDict,
            typing.Mapping,
            typing.List[typing.Tuple[typing.Any, typing.Any]],
            str,
            bytes,
        ],
        **kwargs: typing.Any,
    ) -> None:
        assert len(args) < 2, "Too many arguments."

        value = args[0] if args else []

        if isinstance(value, str):
            super().__init__(parse_qsl(value, keep_blank_values=True), **kwargs)
        elif isinstance(value, bytes):
            super().__init__(
                parse_qsl(value.decode("latin-1"), keep_blank_values=True), **kwargs
            )
        else:
            super().__init__(*args, **kwargs)  # type: ignore
        self._list = [(str(k), str(v)) for k, v in self._list]
        self._dict = {str(k): str(v) for k, v in self._dict.items()}

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


class FormData(ImmutableMultiDict):
    """
    An immutable multidict, containing both file uploads and text input.
    """

    __slots__ = ("_dict", "_list")

    def __init__(
        self,
        *args: typing.Union[
            "FormData",
            typing.Mapping[str, typing.Union[str, UploadFile]],
            typing.List[typing.Tuple[str, typing.Union[str, UploadFile]]],
        ],
        **kwargs: typing.Union[str, UploadFile],
    ) -> None:
        super().__init__(*args, **kwargs)

    def close(self) -> None:
        for key, value in self.multi_items():
            if isinstance(value, UploadFile):
                value.close()

    async def aclose(self) -> None:
        for key, value in self.multi_items():
            if isinstance(value, UploadFile):
                await value.aclose()


class Headers(typing.Mapping[str, str]):
    """
    An immutable, case-insensitive multidict.
    """

    __slots__ = ("raw",)

    def __init__(
        self,
        headers: typing.Mapping[str, str] = None,
        raw: typing.List[typing.Tuple[str, str]] = None,
        scope: Scope = None,
        environ: Environ = None,
    ) -> None:
        self.raw: typing.List[typing.Tuple[str, str]] = []
        if headers is not None:
            self.raw = [(key.lower(), value) for key, value in headers.items()]
        elif raw is not None:
            self.raw = raw
        elif scope is not None:
            self.raw = [
                (key.lower().decode("latin-1"), value.decode("latin-1"))
                for key, value in scope["headers"]
            ]
        elif environ is not None:
            self.raw = [
                (key.lower().replace("_", "-"), value)
                for key, value in chain(
                    (
                        (key[5:], value)
                        for key, value in environ.items()
                        if key.startswith("HTTP_")
                    ),
                    (
                        (key, value)
                        for key, value in environ.items()
                        if key in ("CONTENT_TYPE", "CONTENT_LENGTH")
                    ),
                )
            ]

    def keys(self) -> typing.List[str]:  # type: ignore
        return [key for key, _ in self.raw]

    def values(self) -> typing.List[str]:  # type: ignore
        return [value for _, value in self.raw]

    def items(self) -> typing.List[typing.Tuple[str, str]]:  # type: ignore
        return [(key, value) for key, value in self.raw]

    def get(self, key: str, default: typing.Any = None) -> typing.Any:
        try:
            return self[key]
        except KeyError:
            return default

    def getlist(self, key: str) -> typing.List[str]:
        return [
            item_value for item_key, item_value in self.raw if item_key == key.lower()
        ]

    def mutablecopy(self) -> "MutableHeaders":
        return MutableHeaders(raw=self.raw[:])

    def __getitem__(self, key: str) -> str:
        get_header_key = key.lower()
        for header_key, header_value in self.raw:
            if header_key == get_header_key:
                return header_value
        raise KeyError(key)

    def __contains__(self, key: typing.Any) -> bool:
        get_header_key = key.lower()
        for header_key, header_value in self.raw:
            if header_key == get_header_key:
                return True
        return False

    def __iter__(self) -> typing.Iterator[typing.Any]:
        return iter(self.keys())

    def __len__(self) -> int:
        return len(self.raw)

    def __eq__(self, other: typing.Any) -> bool:
        if not isinstance(other, Headers):
            return False
        return sorted(self.raw) == sorted(other.raw)

    def __repr__(self) -> str:
        class_name = self.__class__.__name__
        as_dict = dict(self.items())
        if len(as_dict) == len(self):
            return f"{class_name}({as_dict!r})"
        return f"{class_name}(raw={self.raw!r})"


class MutableHeaders(Headers):
    __slots__ = ("raw",)

    def __setitem__(self, key: str, value: str) -> None:
        """
        Set the header `key` to `value`, removing any duplicate entries.
        Retains insertion order.
        """
        set_key = key.lower()
        set_value = value

        found_indexes = []
        for idx, (item_key, item_value) in enumerate(self.raw):
            if item_key == set_key:
                found_indexes.append(idx)

        for idx in reversed(found_indexes[1:]):
            del self.raw[idx]

        if found_indexes:
            idx = found_indexes[0]
            self.raw[idx] = (set_key, set_value)
        else:
            self.raw.append((set_key, set_value))

    def __delitem__(self, key: str) -> None:
        """
        Remove the header `key`.
        """
        del_key = key.lower()

        pop_indexes = []
        for idx, (item_key, item_value) in enumerate(self.raw):
            if item_key == del_key:
                pop_indexes.append(idx)

        for idx in reversed(pop_indexes):
            del self.raw[idx]

    def setdefault(self, key: str, value: str) -> str:
        """
        If the header `key` does not exist, then set it to `value`.
        Returns the header value.
        """
        set_key = key.lower()
        set_value = value

        for idx, (item_key, item_value) in enumerate(self.raw):
            if item_key == set_key:
                return item_value
        self.raw.append((set_key, set_value))
        return value

    def update(self, other: dict) -> None:
        for key, val in other.items():
            self[key] = val

    def append(self, key: str, value: str) -> None:
        """
        Append a header, preserving any duplicate entries.
        """
        self.raw.append((key.lower(), value))

    def add_vary_header(self, vary: str) -> None:
        existing = self.get("vary")
        if existing is not None:
            vary = ", ".join([existing, vary])
        self["vary"] = vary
