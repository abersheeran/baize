from dataclasses import dataclass
from typing import Any, Mapping, NoReturn, Optional


@dataclass
class HTTPException(Exception):
    status_code: int = 400
    headers: Optional[Mapping[str, str]] = None
    content: Any = None


def abort(
    status_code: int = 400,
    headers: Optional[Mapping[str, str]] = None,
    content: Any = None,
) -> NoReturn:
    """
    raise a `HTTPException`. Parameters are completely consistent with `HTTPException`.
    """
    raise HTTPException(status_code=status_code, headers=headers, content=content)
