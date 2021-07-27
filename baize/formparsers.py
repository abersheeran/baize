import typing
from cgi import parse_header
from collections import deque
from enum import Enum

from .datastructures import ContentType, FormData, UploadFile

try:
    from multipart import MultipartParser
except ImportError:  # pragma: no cover

    class MultipartParser:  # type: ignore
        def __init__(self, *args, **kwargs) -> None:
            raise NotImplementedError(
                "The `python-multipart` library must be installed to use form parsing."
            )


class MultiPartMessage(Enum):
    PART_BEGIN = 1
    PART_DATA = 2
    PART_END = 3
    HEADER_FIELD = 4
    HEADER_VALUE = 5
    HEADER_END = 6
    HEADERS_FINISHED = 7
    END = 8


Stream = typing.TypeVar("Stream", typing.Iterable[bytes], typing.AsyncIterable[bytes])


def _user_safe_decode(src: typing.Union[bytes, bytearray], charset: str) -> str:
    try:
        return src.decode(charset)
    except (UnicodeDecodeError, LookupError):
        return src.decode("latin-1")


class BaseMultiPartParser(typing.Generic[Stream]):
    def __init__(self, content_type: ContentType, stream: Stream) -> None:
        self.charset = content_type.options.get("charset", "utf8")
        # Create a stream parser
        self.parser = MultipartParser(
            content_type.options.get("boundary"),
            {
                "on_part_begin": self.on_part_begin,
                "on_part_data": self.on_part_data,
                "on_part_end": self.on_part_end,
                "on_header_field": self.on_header_field,
                "on_header_value": self.on_header_value,
                "on_header_end": self.on_header_end,
                "on_headers_finished": self.on_headers_finished,
                "on_end": self.on_end,
            },
        )
        self.stream: Stream = stream
        self.messages: typing.Deque[typing.Tuple[MultiPartMessage, bytes]] = deque()

    def on_part_begin(self) -> None:
        message = (MultiPartMessage.PART_BEGIN, b"")
        self.messages.append(message)

    def on_part_data(self, data: bytes, start: int, end: int) -> None:
        message = (MultiPartMessage.PART_DATA, data[start:end])
        self.messages.append(message)

    def on_part_end(self) -> None:
        message = (MultiPartMessage.PART_END, b"")
        self.messages.append(message)

    def on_header_field(self, data: bytes, start: int, end: int) -> None:
        message = (MultiPartMessage.HEADER_FIELD, data[start:end])
        self.messages.append(message)

    def on_header_value(self, data: bytes, start: int, end: int) -> None:
        message = (MultiPartMessage.HEADER_VALUE, data[start:end])
        self.messages.append(message)

    def on_header_end(self) -> None:
        message = (MultiPartMessage.HEADER_END, b"")
        self.messages.append(message)

    def on_headers_finished(self) -> None:
        message = (MultiPartMessage.HEADERS_FINISHED, b"")
        self.messages.append(message)

    def on_end(self) -> None:
        message = (MultiPartMessage.END, b"")
        self.messages.append(message)


class MultiPartParser(BaseMultiPartParser[typing.Iterable[bytes]]):
    def parse(self) -> FormData:
        header_field = bytearray()
        header_value = bytearray()
        content_disposition = ""
        content_type = ""
        field_name = ""
        data = bytearray()
        file: typing.Optional[UploadFile] = None

        items: typing.List[typing.Tuple[str, typing.Union[str, UploadFile]]] = []

        # Feed the parser with data from the request.
        for chunk in self.stream:
            self.parser.write(chunk)
            while len(self.messages) > 0:
                message_type, message_bytes = self.messages.popleft()
                if message_type == MultiPartMessage.PART_BEGIN:
                    content_disposition = ""
                    content_type = ""
                    data = bytearray()
                elif message_type == MultiPartMessage.HEADER_FIELD:
                    header_field.extend(message_bytes)
                elif message_type == MultiPartMessage.HEADER_VALUE:
                    header_value.extend(message_bytes)
                elif message_type == MultiPartMessage.HEADER_END:
                    field = _user_safe_decode(header_field, self.charset).lower()
                    if field == "content-disposition":
                        content_disposition = _user_safe_decode(
                            header_value, self.charset
                        )
                    elif field == "content-type":
                        content_type = _user_safe_decode(header_value, self.charset)
                    header_field.clear()
                    header_value.clear()
                elif message_type == MultiPartMessage.HEADERS_FINISHED:
                    disposition, options = parse_header(content_disposition)
                    field_name = options["name"]
                    if "filename" in options:
                        filename = options["filename"]
                        file = UploadFile(filename=filename, content_type=content_type)
                    else:
                        file = None
                elif message_type == MultiPartMessage.PART_DATA:
                    if file is None:
                        data.extend(message_bytes)
                    else:
                        file.write(message_bytes)
                elif message_type == MultiPartMessage.PART_END:
                    if file is None:
                        items.append(
                            (field_name, _user_safe_decode(data, self.charset))
                        )
                    else:
                        file.seek(0)
                        items.append((field_name, file))
                elif message_type == MultiPartMessage.END:
                    pass

        self.parser.finalize()
        return FormData(items)


class AsyncMultiPartParser(BaseMultiPartParser[typing.AsyncIterable[bytes]]):
    async def parse(self) -> FormData:
        header_field = bytearray()
        header_value = bytearray()
        content_disposition = ""
        content_type = ""
        field_name = ""
        data = bytearray()
        file: typing.Optional[UploadFile] = None

        items: typing.List[typing.Tuple[str, typing.Union[str, UploadFile]]] = []

        # Feed the parser with data from the request.
        async for chunk in self.stream:
            self.parser.write(chunk)
            while len(self.messages) > 0:
                message_type, message_bytes = self.messages.popleft()
                if message_type == MultiPartMessage.PART_BEGIN:
                    content_disposition = ""
                    content_type = ""
                    data = bytearray()
                elif message_type == MultiPartMessage.HEADER_FIELD:
                    header_field.extend(message_bytes)
                elif message_type == MultiPartMessage.HEADER_VALUE:
                    header_value.extend(message_bytes)
                elif message_type == MultiPartMessage.HEADER_END:
                    field = _user_safe_decode(header_field, self.charset).lower()
                    if field == "content-disposition":
                        content_disposition = _user_safe_decode(
                            header_value, self.charset
                        )
                    elif field == "content-type":
                        content_type = _user_safe_decode(header_value, self.charset)
                    header_field.clear()
                    header_value.clear()
                elif message_type == MultiPartMessage.HEADERS_FINISHED:
                    disposition, options = parse_header(content_disposition)
                    field_name = options["name"]
                    if "filename" in options:
                        filename = options["filename"]
                        file = UploadFile(filename=filename, content_type=content_type)
                    else:
                        file = None
                elif message_type == MultiPartMessage.PART_DATA:
                    if file is None:
                        data.extend(message_bytes)
                    else:
                        await file.awrite(message_bytes)
                elif message_type == MultiPartMessage.PART_END:
                    if file is None:
                        items.append(
                            (field_name, _user_safe_decode(data, self.charset))
                        )
                    else:
                        await file.aseek(0)
                        items.append((field_name, file))
                elif message_type == MultiPartMessage.END:
                    pass

        self.parser.finalize()
        return FormData(items)
