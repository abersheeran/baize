import abc
import re
import uuid
from datetime import date
from decimal import Decimal
from typing import Any, Dict, Generic, List, Optional, Pattern, Sequence, Tuple, TypeVar

try:
    from mypy_extensions import mypyc_attr
except ImportError:  # pragma: no cover

    def mypyc_attr(*attrs, **kwattrs):  # type: ignore
        return lambda x: x


from .typing import ASGIApp, WSGIApp

T = TypeVar("T")


@mypyc_attr(allow_interpreted_subclasses=True)
class Convertor(Generic[T]):
    regex: str

    @abc.abstractmethod
    def to_python(self, value: str) -> T:
        raise NotImplementedError()

    @abc.abstractmethod
    def to_string(self, value: T) -> str:
        raise NotImplementedError()


@mypyc_attr(allow_interpreted_subclasses=True)
class StringConvertor(Convertor[str]):
    regex = "[^/]+"

    def to_python(self, value: str) -> str:
        return value

    def to_string(self, value: str) -> str:
        value = str(value)
        if not value:
            raise ValueError("Must not be empty")
        if "/" in value:
            raise ValueError("May not contain path separators")
        return value


@mypyc_attr(allow_interpreted_subclasses=True)
class IntegerConvertor(Convertor[int]):
    regex = "[0-9]+"

    def to_python(self, value: str) -> int:
        return int(value)

    def to_string(self, value: int) -> str:
        if value < 0:
            raise ValueError("Negative integers are not supported")
        return str(value)


@mypyc_attr(allow_interpreted_subclasses=True)
class DecimalConvertor(Convertor[Decimal]):
    regex = "[0-9]+(.[0-9]+)?"

    def to_python(self, value: str) -> Decimal:
        return Decimal(value)

    def to_string(self, value: Decimal) -> str:
        if value.is_nan():
            raise ValueError("NaN values are not supported")
        if value.is_infinite():
            raise ValueError("Infinite values are not supported")
        if Decimal("0.0") > value:
            raise ValueError("Negative decimal are not supported")
        return str(value).rstrip("0").rstrip(".")


@mypyc_attr(allow_interpreted_subclasses=True)
class UUIDConvertor(Convertor[uuid.UUID]):
    regex = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"

    def to_python(self, value: str) -> uuid.UUID:
        return uuid.UUID(value)

    def to_string(self, value: uuid.UUID) -> str:
        return str(value)


@mypyc_attr(allow_interpreted_subclasses=True)
class DateConvertor(Convertor[date]):
    regex = "[0-9]{4}-[0-9]{2}-[0-9]{2}"

    def to_python(self, value: str) -> date:
        return date(int(value[0:4]), int(value[5:7]), int(value[8:10]))

    def to_string(self, value: date) -> str:
        return value.isoformat()


@mypyc_attr(allow_interpreted_subclasses=True)
class AnyConvertor(Convertor[str]):
    regex = ".*"

    def to_python(self, value: str) -> str:
        return value

    def to_string(self, value: str) -> str:
        return value


CONVERTOR_TYPES: Dict[str, Convertor] = {
    "str": StringConvertor(),
    "int": IntegerConvertor(),
    "decimal": DecimalConvertor(),
    "uuid": UUIDConvertor(),
    "date": DateConvertor(),
    "any": AnyConvertor(),
}

# Match parameters in URL paths, eg. '{param}', and '{param:int}'
PARAM_REGEX = re.compile(r"{([^\d]\w*)(:\w+)?}")


def compile_path(path: str) -> Tuple[str, Dict[str, Convertor]]:
    """
    Given a path string, like: "/{username:str}", return a two-tuple
    of (format, {param_name:convertor}).

    format:     "/{username}"
    convertors: {"username": StringConvertor()}
    """
    path_format = ""
    idx = 0
    param_convertors = {}
    for match in PARAM_REGEX.finditer(path):
        param_name, convertor_type = match.groups("str")
        convertor_type = convertor_type.lstrip(":")
        if convertor_type not in CONVERTOR_TYPES:
            raise ValueError(f"Unknown path convertor '{convertor_type}'")
        convertor = CONVERTOR_TYPES[convertor_type]

        path_format += path[idx : match.start()]
        path_format += "{%s}" % param_name

        param_convertors[param_name] = convertor

        idx = match.end()

    path_format += path[idx:]

    return path_format, param_convertors


Interface = TypeVar("Interface", ASGIApp, WSGIApp)


@mypyc_attr(allow_interpreted_subclasses=True)
class Route(Generic[Interface]):
    def __init__(self, path: str, endpoint: Interface) -> None:
        self.path_format: str
        self.path_convertors: Dict[str, Convertor]
        self.path_format, self.path_convertors = compile_path(path)
        self.re_pattern = re.compile(
            self.path_format.format_map(
                {
                    name: f"(?P<{name}>{convertor.regex})"
                    for name, convertor in self.path_convertors.items()
                }
            )
        )
        self.endpoint: Interface = endpoint

    def matches(self, path: str) -> Tuple[bool, Dict[str, Any]]:
        match = self.re_pattern.fullmatch(path)
        if match is None:
            return False, {}
        return True, {
            name: self.path_convertors[name].to_python(value)
            for name, value in match.groupdict().items()
        }


@mypyc_attr(allow_interpreted_subclasses=True)
class BaseRouter(Generic[Interface]):
    def __init__(self, *routes: Tuple[str, Interface]) -> None:
        self._route_array: List[Route[Interface]] = [
            Route(path, endpoint) for path, endpoint in routes
        ]

    def search(self, path: str) -> Optional[Tuple[Route[Interface], Dict[str, Any]]]:
        for route in self._route_array:
            match_up, params = route.matches(path)
            if match_up:
                return route, params
        return None


@mypyc_attr(allow_interpreted_subclasses=True)
class BaseSubpaths(Generic[Interface]):
    def __init__(self, *routes: Tuple[str, Interface]) -> None:
        for prefix, _ in routes:
            if prefix == "":  # Allow use "" to set default app
                continue
            assert prefix.startswith("/"), "prefix must be starts with '/'"
            assert not prefix.endswith("/"), "prefix cannot be ends with '/'"
        self._route_array = [*routes]

    def search(self, path: str) -> Optional[Tuple[str, Interface]]:
        for prefix, endpoint in self._route_array:
            if path.startswith(prefix + "/") or path == prefix:
                return prefix, endpoint
        return None


@mypyc_attr(allow_interpreted_subclasses=True)
class BaseHosts(Generic[Interface]):
    def __init__(self, *hosts: Tuple[str, Interface]) -> None:
        self._host_array: Sequence[Tuple[Pattern, Interface]] = [
            (re.compile(host), endpoint) for host, endpoint in hosts
        ]

    def search(self, host: str) -> Optional[Interface]:
        for pattern, endpoint in self._host_array:
            if pattern.fullmatch(host) is not None:
                return endpoint
        return None
