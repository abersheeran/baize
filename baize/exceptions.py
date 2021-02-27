from dataclasses import dataclass
from typing import Any, Mapping, Optional


@dataclass
class HTTPException(Exception):
    status_code: int = 400
    headers: Optional[Mapping[str, str]] = None
    content: Any = None
