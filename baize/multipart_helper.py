from typing import AsyncIterable, Iterable, List, Optional, Tuple, Type, TypeVar, Union

from .datastructures import Headers
from .exceptions import RequestEntityTooLarge
from .multipart import (
    Data,
    Epilogue,
    Field,
    File,
    MultipartDecoder,
    NeedData,
    safe_decode,
)
from .typing import Protocol, runtime_checkable


@runtime_checkable
class SyncUploadFileInterface(Protocol):
    def __init__(self, filename: str, headers: Headers) -> None: ...

    def write(self, data: bytes) -> None: ...

    def seek(self, offset: int) -> None: ...


@runtime_checkable
class AsyncUploadFileInterface(Protocol):
    def __init__(self, filename: str, headers: Headers) -> None: ...

    async def awrite(self, data: bytes) -> None: ...

    async def aseek(self, offset: int) -> None: ...


_SyncUploadFile = TypeVar("_SyncUploadFile", bound=SyncUploadFileInterface)
_AsyncUploadFile = TypeVar("_AsyncUploadFile", bound=AsyncUploadFileInterface)


async def parse_async_stream(
    stream: AsyncIterable[bytes],
    boundary: bytes,
    charset: str,
    *,
    file_factory: Type[_AsyncUploadFile],
    max_form_parts: int = 324,
    max_form_memory_size: Union[int, None] = None,
) -> List[Tuple[str, Union[str, _AsyncUploadFile]]]:
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
    file: Optional[_AsyncUploadFile] = None
    form_parts_count = 0
    form_memory_size_count = 0

    items: List[Tuple[str, Union[str, _AsyncUploadFile]]] = []

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

                    # Check if we have exceeded the maximum memory size
                    form_memory_size_count += len(event.data)
                    if (
                        max_form_memory_size is not None
                        and form_memory_size_count > max_form_memory_size
                    ):
                        raise RequestEntityTooLarge()
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

                    # Check if we have exceeded the maximum number of form parts
                    form_parts_count += 1
                    if form_parts_count > max_form_parts:
                        raise RequestEntityTooLarge()
    return items


def parse_stream(
    stream: Iterable[bytes],
    boundary: bytes,
    charset: str,
    *,
    file_factory: Type[_SyncUploadFile],
    max_form_parts: int = 324,
    max_form_memory_size: Union[int, None] = None,
) -> List[Tuple[str, Union[str, _SyncUploadFile]]]:
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
    file: Optional[_SyncUploadFile] = None
    form_parts_count = 0
    form_memory_size_count = 0

    items: List[Tuple[str, Union[str, _SyncUploadFile]]] = []

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

                    # Check if we have exceeded the maximum memory size
                    form_memory_size_count += len(event.data)
                    if (
                        max_form_memory_size is not None
                        and form_memory_size_count > max_form_memory_size
                    ):
                        raise RequestEntityTooLarge()
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

                    # Check if we have exceeded the maximum number of form parts
                    form_parts_count += 1
                    if form_parts_count > max_form_parts:
                        raise RequestEntityTooLarge()
    return items
