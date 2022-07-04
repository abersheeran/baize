import re
from typing import List, Optional, Tuple, Union, cast

from .datastructures import Headers
from .exceptions import MalformedMultipart
from .typing import Final
from .utils import parse_header

__all__ = [
    "Event",
    "Preamble",
    "Field",
    "File",
    "Data",
    "Epilogue",
    "NeedData",
    "NEED_DATA",
    "MultipartDecoder",
    "safe_decode",
]


class Event:
    __slots__ = ()


class Preamble(Event):
    __slots__ = ("data",)

    def __init__(self, data: bytes) -> None:
        self.data = data

    def __eq__(self, obj: object) -> bool:
        return isinstance(obj, self.__class__) and self.data == obj.data


class Field(Event):
    __slots__ = ("name", "headers")

    def __init__(self, name: str, headers: Headers) -> None:
        self.name = name
        self.headers = headers

    def __eq__(self, obj: object) -> bool:
        return (
            isinstance(obj, self.__class__)
            and self.name == obj.name
            and self.headers == obj.headers
        )


class File(Event):
    __slots__ = ("name", "filename", "headers")

    def __init__(self, name: str, filename: str, headers: Headers) -> None:
        self.name = name
        self.filename = filename
        self.headers = headers

    def __eq__(self, obj: object) -> bool:
        return (
            isinstance(obj, self.__class__)
            and self.name == obj.name
            and self.filename == obj.filename
            and self.headers == obj.headers
        )


class Data(Event):
    __slots__ = ("data", "more_data")

    def __init__(self, data: bytes, more_data: bool) -> None:
        self.data = data
        self.more_data = more_data

    def __eq__(self, obj: object) -> bool:
        return (
            isinstance(obj, self.__class__)
            and self.data == obj.data
            and self.more_data == obj.more_data
        )


class Epilogue(Event):
    __slots__ = ("data",)

    def __init__(self, data: bytes) -> None:
        self.data = data

    def __eq__(self, obj: object) -> bool:
        return isinstance(obj, self.__class__) and self.data == obj.data


class NeedData(Event):
    __slots__ = ()


NEED_DATA: Final = NeedData()


class State:
    PREAMBLE: Final = object()
    PART: Final = object()
    DATA: Final = object()
    EPILOGUE: Final = object()
    COMPLETE: Final = object()


# Multipart line breaks MUST be CRLF (\r\n) by RFC-7578, except that
# many implementations break this and either use CR or LF alone.
LINE_BREAK: Final = b"(?:\r\n|\n|\r)"
BLANK_LINE_RE: Final = re.compile(b"(?:\r\n\r\n|\r\r|\n\n)", re.MULTILINE)
LINE_BREAK_RE: Final = re.compile(LINE_BREAK, re.MULTILINE)
# Header values can be continued via a space or tab after the linebreak, as
# per RFC2231
HEADER_CONTINUATION_RE: Final = re.compile(b"%s[ \t]" % LINE_BREAK, re.MULTILINE)


class MultipartDecoder:
    """Decodes a multipart message as bytes into Python events.
    The part data is returned as available to allow the caller to save
    the data from memory to disk, if desired.
    """

    def __init__(self, boundary: bytes, charset: str) -> None:
        self.buffer = bytearray()
        self.complete = False
        self.state = State.PREAMBLE
        self.boundary = boundary
        self.charset = charset

        # Note in the below \h i.e. horizontal whitespace is used
        # as [^\S\n\r] as \h isn't supported in python.

        # The preamble must end with a boundary where the boundary is
        # prefixed by a line break, RFC2046. Except that many
        # implementations including Werkzeug's tests omit the line
        # break prefix. In addition the first boundary could be the
        # epilogue boundary (for empty form-data) hence the matching
        # group to understand if it is an epilogue boundary.
        self.preamble_re = re.compile(
            rb"%s?--%s(--[^\S\n\r]*%s?|[^\S\n\r]*%s)"
            % (LINE_BREAK, re.escape(boundary), LINE_BREAK, LINE_BREAK),
            re.MULTILINE,
        )
        # A boundary must include a line break prefix and suffix, and
        # may include trailing whitespace. In addition the boundary
        # could be the epilogue boundary hence the matching group to
        # understand if it is an epilogue boundary.
        self.boundary_re = re.compile(
            rb"%s--%s(--[^\S\n\r]*%s?|[^\S\n\r]*%s)"
            % (LINE_BREAK, re.escape(boundary), LINE_BREAK, LINE_BREAK),
            re.MULTILINE,
        )

    def last_newline(self) -> int:
        try:
            last_nl = self.buffer.rindex(b"\n")
        except ValueError:
            last_nl = len(self.buffer)
        try:
            last_cr = self.buffer.rindex(b"\r")
        except ValueError:
            last_cr = len(self.buffer)

        return min(last_nl, last_cr)

    def receive_data(self, data: Optional[bytes]) -> None:
        if data is None:
            self.complete = True
        else:
            self.buffer.extend(data)

    def next_event(self) -> Event:
        event: Event = NEED_DATA

        if self.state == State.PREAMBLE:
            match = self.preamble_re.search(self.buffer)
            if match is not None:
                if match.group(1).startswith(b"--"):
                    self.state = State.EPILOGUE
                else:
                    self.state = State.PART
                data = bytes(self.buffer[: match.start()])
                del self.buffer[: match.end()]
                event = Preamble(data=data)

        elif self.state == State.PART:
            match = BLANK_LINE_RE.search(self.buffer)
            if match is not None:
                headers = self._parse_headers(self.buffer[: match.start()])
                del self.buffer[: match.end()]

                if "content-disposition" not in headers:  # pragma: no cover
                    raise MalformedMultipart("Missing Content-Disposition header")

                disposition, extra = parse_header(headers["content-disposition"])
                name = cast(str, extra.get("name"))
                filename = extra.get("filename")
                if filename is not None:
                    event = File(filename=filename, headers=headers, name=name)
                else:
                    event = Field(headers=headers, name=name)
                self.state = State.DATA

        elif self.state == State.DATA:
            if self.buffer.find(b"--" + self.boundary) == -1:
                # No complete boundary in the buffer, but there may be
                # a partial boundary at the end. As the boundary
                # starts with either a nl or cr find the earliest and
                # return up to that as data.
                data_length = del_index = self.last_newline()
                more_data = True
            else:
                match = self.boundary_re.search(self.buffer)
                if match is not None:
                    if match.group(1).startswith(b"--"):
                        self.state = State.EPILOGUE
                    else:
                        self.state = State.PART
                    data_length = match.start()
                    del_index = match.end()
                else:
                    data_length = del_index = self.last_newline()
                more_data = match is None

            data = bytes(self.buffer[:data_length])
            del self.buffer[:del_index]
            if data or not more_data:
                event = Data(data=data, more_data=more_data)

        elif self.state == State.EPILOGUE and self.complete:
            event = Epilogue(data=bytes(self.buffer))
            del self.buffer[:]
            self.state = State.COMPLETE

        if self.complete and isinstance(event, NeedData):  # pragma: no cover
            raise MalformedMultipart(
                f"Invalid form-data cannot parse beyond {self.state}"
            )

        return event

    def _parse_headers(self, data: bytes) -> Headers:
        headers: List[Tuple[str, str]] = []
        # Merge the continued headers into one line
        data = HEADER_CONTINUATION_RE.sub(b" ", data)
        # Now there is one header per line
        for line in data.splitlines():
            line = line.strip()
            if line != b"":
                name, value = safe_decode(line, self.charset).split(":", 1)
                headers.append((name.strip(), value.strip()))
        return Headers(headers)


def safe_decode(src: Union[bytes, bytearray], charset: str) -> str:
    try:
        return src.decode(charset)
    except (UnicodeDecodeError, LookupError):
        return src.decode("latin-1")
