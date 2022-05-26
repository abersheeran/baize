from typing import AsyncIterable, Iterable, List, Optional, Tuple, Type, TypeVar, Union

from .datastructures import UploadFile, UploadFileInterface
from .multipart import (
    Data,
    Epilogue,
    Field,
    File,
    MultipartDecoder,
    NeedData,
    safe_decode,
)

_UploadFile = TypeVar("_UploadFile", bound=UploadFileInterface)


async def parse_async_stream(
    stream: AsyncIterable[bytes],
    boundary: bytes,
    charset: str,
    *,
    file_factory: Type[_UploadFile] = UploadFile,  # type: ignore
    # the error is mypy bug, it doesn't understand the type of the bound
    # related link https://github.com/microsoft/pyright/discussions/3090
) -> List[Tuple[str, Union[str, _UploadFile]]]:
    """
    Parse an asynchronous stream in multipart format

    ```python
    for field_name, field_or_file in await parse_async_stream(stream, boundary, charset):
        print(field_name, field_or_file)
    ```
    """
    parser = MultipartDecoder(boundary, charset)
    field_name = ""
    data = bytearray()
    file: Optional[_UploadFile] = None

    items: List[Tuple[str, Union[str, _UploadFile]]] = []

    async for chunk in stream:
        parser.receive_data(chunk)
        while True:
            event = parser.next_event()
            if isinstance(event, (Epilogue, NeedData)):
                break
            elif isinstance(event, Field):
                field_name = event.name
            elif isinstance(event, File):
                field_name = event.name
                file = file_factory(event.filename, event.headers)
            elif isinstance(event, Data):
                if file is None:
                    data.extend(event.data)
                else:
                    await file.awrite(event.data)

                if not event.more_data:
                    if file is None:
                        items.append((field_name, safe_decode(data, charset)))
                        data.clear()
                    else:
                        await file.aseek(0)
                        items.append((field_name, file))
                        file = None
    return items


def parse_stream(
    stream: Iterable[bytes],
    boundary: bytes,
    charset: str,
    *,
    file_factory: Type[_UploadFile] = UploadFile,  # type: ignore
    # the error is mypy bug, it doesn't understand the type of the bound
    # related link https://github.com/microsoft/pyright/discussions/3090
) -> List[Tuple[str, Union[str, _UploadFile]]]:
    """
    Parse a synchronous stream in multipart format

    ```python
    for field_name, field_or_file in parse_stream(stream, boundary, charset):
        print(field_name, field_or_file)
    ```
    """
    parser = MultipartDecoder(boundary, charset)
    field_name = ""
    data = bytearray()
    file: Optional[_UploadFile] = None

    items: List[Tuple[str, Union[str, _UploadFile]]] = []

    for chunk in stream:
        parser.receive_data(chunk)
        while True:
            event = parser.next_event()
            if isinstance(event, (Epilogue, NeedData)):
                break
            elif isinstance(event, Field):
                field_name = event.name
            elif isinstance(event, File):
                field_name = event.name
                file = file_factory(event.filename, event.headers)
            elif isinstance(event, Data):
                if file is None:
                    data.extend(event.data)
                else:
                    file.write(event.data)

                if not event.more_data:
                    if file is None:
                        items.append((field_name, safe_decode(data, charset)))
                        data.clear()
                    else:
                        file.seek(0)
                        items.append((field_name, file))
                        file = None
    return items
