from http import HTTPStatus
from typing import Any, Mapping, NoReturn, Optional


class HTTPException(Exception):
    def __init__(
        self,
        status_code: int = 400,
        headers: Optional[Mapping[str, str]] = None,
        content: Any = None,
    ) -> None:
        self.status_code = status_code
        self.headers = headers
        self.content = content
        super().__init__(status_code, HTTPStatus(status_code).description)


def abort(
    status_code: int = 400,
    headers: Optional[Mapping[str, str]] = None,
    content: Any = None,
) -> NoReturn:
    """
    raise a `HTTPException`. Parameters are completely consistent with `HTTPException`.
    """
    raise HTTPException(status_code=status_code, headers=headers, content=content)
