import enum
import re
import typing
from cgi import parse_header
from typing import List, Optional, Tuple, cast

from .datastructures import ContentType, FormData, Headers, UploadFile

Stream = typing.TypeVar("Stream", typing.Iterable[bytes], typing.AsyncIterable[bytes])


def _user_safe_decode(src: typing.Union[bytes, bytearray], charset: str) -> str:
    try:
        return src.decode(charset)
    except (UnicodeDecodeError, LookupError):
        return src.decode("latin-1")


class BaseMultiPartParser(typing.Generic[Stream]):
    def __init__(self, content_type: ContentType, stream: Stream) -> None:
        self.charset = content_type.options.get("charset", "utf8")
        self.parser = MultipartDecoder(
            content_type.options["boundary"].encode("latin-1"), self.charset
        )
        self.stream: Stream = stream


class MultiPartParser(BaseMultiPartParser[typing.Iterable[bytes]]):
    def parse(self) -> FormData:
        field_name = ""
        data = bytearray()
        file: typing.Optional[UploadFile] = None

        items: typing.List[typing.Tuple[str, typing.Union[str, UploadFile]]] = []

        for chunk in self.stream:
            self.parser.receive_data(chunk)
            while True:
                event = self.parser.next_event()
                if isinstance(event, (Epilogue, NeedData)):
                    break
                elif isinstance(event, Field):
                    field_name = event.name
                elif isinstance(event, File):
                    field_name = event.name
                    file = UploadFile(
                        event.filename, event.headers.get("content-type", "")
                    )
                elif isinstance(event, Data):
                    if file is None:
                        data.extend(event.data)
                    else:
                        file.write(event.data)

                    if not event.more_data:
                        if file is None:
                            items.append(
                                (field_name, _user_safe_decode(data, self.charset))
                            )
                            data.clear()
                        else:
                            file.seek(0)
                            items.append((field_name, file))
                            file = None

        return FormData(items)


class AsyncMultiPartParser(BaseMultiPartParser[typing.AsyncIterable[bytes]]):
    async def parse(self) -> FormData:
        field_name = ""
        data = bytearray()
        file: typing.Optional[UploadFile] = None

        items: typing.List[typing.Tuple[str, typing.Union[str, UploadFile]]] = []

        async for chunk in self.stream:
            self.parser.receive_data(chunk)
            while True:
                event = self.parser.next_event()
                if isinstance(event, (Epilogue, NeedData)):
                    break
                elif isinstance(event, Field):
                    field_name = event.name
                elif isinstance(event, File):
                    field_name = event.name
                    file = UploadFile(
                        event.filename, event.headers.get("content-type", "")
                    )
                elif isinstance(event, Data):
                    if file is None:
                        data.extend(event.data)
                    else:
                        await file.awrite(event.data)

                    if not event.more_data:
                        if file is None:
                            items.append(
                                (field_name, _user_safe_decode(data, self.charset))
                            )
                            data.clear()
                        else:
                            await file.aseek(0)
                            items.append((field_name, file))
                            file = None

        return FormData(items)


class Event:
    def __eq__(self, obj: object) -> bool:
        return isinstance(obj, self.__class__) and self.__dict__ == obj.__dict__


class Preamble(Event):
    def __init__(self, data: bytes) -> None:
        self.data = data


class Field(Event):
    def __init__(self, name: str, headers: Headers) -> None:
        self.name = name
        self.headers = headers


class File(Event):
    def __init__(self, name: str, filename: str, headers: Headers) -> None:
        self.name = name
        self.filename = filename
        self.headers = headers


class Data(Event):
    def __init__(self, data: bytes, more_data: bool) -> None:
        self.data = data
        self.more_data = more_data


class Epilogue(Event):
    def __init__(self, data: bytes) -> None:
        self.data = data


class NeedData(Event):
    pass


NEED_DATA = NeedData()


class State(enum.Enum):
    PREAMBLE = enum.auto()
    PART = enum.auto()
    DATA = enum.auto()
    EPILOGUE = enum.auto()
    COMPLETE = enum.auto()


# Multipart line breaks MUST be CRLF (\r\n) by RFC-7578, except that
# many implementations break this and either use CR or LF alone.
LINE_BREAK = b"(?:\r\n|\n|\r)"
BLANK_LINE_RE = re.compile(b"(?:\r\n\r\n|\r\r|\n\n)", re.MULTILINE)
LINE_BREAK_RE = re.compile(LINE_BREAK, re.MULTILINE)
# Header values can be continued via a space or tab after the linebreak, as
# per RFC2231
HEADER_CONTINUATION_RE = re.compile(b"%s[ \t]" % LINE_BREAK, re.MULTILINE)


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
            br"%s?--%s(--[^\S\n\r]*%s?|[^\S\n\r]*%s)"
            % (LINE_BREAK, re.escape(boundary), LINE_BREAK, LINE_BREAK),
            re.MULTILINE,
        )
        # A boundary must include a line break prefix and suffix, and
        # may include trailing whitespace. In addition the boundary
        # could be the epilogue boundary hence the matching group to
        # understand if it is an epilogue boundary.
        self.boundary_re = re.compile(
            br"%s--%s(--[^\S\n\r]*%s?|[^\S\n\r]*%s)"
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
                    raise ValueError("Missing Content-Disposition header")

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
            raise ValueError(f"Invalid form-data cannot parse beyond {self.state}")

        return event

    def _parse_headers(self, data: bytes) -> Headers:
        headers: List[Tuple[str, str]] = []
        # Merge the continued headers into one line
        data = HEADER_CONTINUATION_RE.sub(b" ", data)
        # Now there is one header per line
        for line in data.splitlines():
            line = line.strip()
            if line != b"":
                name, value = _user_safe_decode(line, self.charset).split(":", 1)
                headers.append((name.strip(), value.strip()))
        return Headers(headers)
