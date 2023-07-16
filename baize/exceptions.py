from http import HTTPStatus
from typing import Any, Generic, Mapping, NoReturn, Optional, TypeVar

T = TypeVar("T")


class HTTPException(Exception, Generic[T]):
    """
    Base HTTP Exception
    """

    def __init__(
        self,
        status_code: int = 400,
        headers: Optional[Mapping[str, str]] = None,
        content: Optional[T] = None,
    ) -> None:
        self.status_code = status_code
        self.headers = headers
        self.content = content
        if content is not None:
            status_description = repr(content)
        else:
            try:
                status_description = HTTPStatus(status_code).description
            except ValueError:
                status_description = "Maybe a custom HTTP status code"
        super().__init__(status_code, status_description)


def abort(
    status_code: int = 400,
    headers: Optional[Mapping[str, str]] = None,
    content: Any = None,
) -> NoReturn:
    """
    raise a `HTTPException`. Parameters are completely consistent with `HTTPException`.
    """
    raise HTTPException(status_code=status_code, headers=headers, content=content)


class RequestEntityTooLarge(HTTPException[None]):
    """
    413 Request Entity Too Large
    """

    def __init__(self, retry_after: Optional[int] = None) -> None:
        super().__init__(
            413, {"Retry-After": str(retry_after)} if retry_after is not None else None
        )


class UnsupportedMediaType(HTTPException[None]):
    """
    415 Unsupported Media Type
    """

    def __init__(self, *supported_media_types: str) -> None:
        super().__init__(415, {"Accpet": ", ".join(supported_media_types)}, None)


class RangeNotSatisfiable(HTTPException[None]):
    """
    416 Range Not Satisfiable
    """

    def __init__(self, max_size: int) -> None:
        super().__init__(416, {"Content-Range": f"*/{max_size}"}, None)


# ###################################################################################
# ################################ Custom Exception #################################
# ###################################################################################


class MalformedJSON(HTTPException[str]):
    def __init__(self, message: str = "Malformed JSON") -> None:
        super().__init__(content=message)


class MalformedMultipart(HTTPException[str]):
    def __init__(self, message: str = "Malformed multipart") -> None:
        super().__init__(content=message)


class MalformedRangeHeader(HTTPException[str]):
    def __init__(self, message: str = "Malformed Range header") -> None:
        super().__init__(content=message)
