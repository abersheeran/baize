from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from http import cookies as http_cookies
from typing import Dict, List, Optional

try:
    from mypy_extensions import trait
except ImportError:  # pragma: no cover

    def trait(cls):  # type: ignore
        return cls


from .datastructures import URL, ContentType, Headers, MediaType

# Workaround for adding samesite support to pre 3.8 python
http_cookies.Morsel._reserved["samesite"] = "SameSite"  # type: ignore


@trait
class MoreInfoFromHeaderMixin:
    """
    Parse more information from the header for quick use
    """

    @property
    def headers(self) -> Headers:
        raise NotImplementedError

    _accepted_types: List[MediaType]

    @property
    def accepted_types(self) -> List[MediaType]:
        """
        Request's accepted types
        """
        if not hasattr(self, "_accepted_types"):
            self._accepted_types = [
                MediaType(token)
                for token in self.headers.get("Accept", "*/*").split(",")
                if token.strip()
            ]
        return self._accepted_types

    def accepts(self, media_type: str) -> bool:
        """
        e.g. `request.accepts("application/json")`
        """
        return any(
            accepted_type.match(media_type) for accepted_type in self.accepted_types
        )

    _content_type: ContentType

    @property
    def content_type(self) -> ContentType:
        """
        Request's content-type
        """
        if not hasattr(self, "_content_type"):
            self._content_type = ContentType(self.headers.get("content-type", ""))
        return self._content_type

    _content_length: Optional[int]

    @property
    def content_length(self) -> Optional[int]:
        """
        Request's content-length
        """
        if not hasattr(self, "_content_length"):
            if self.headers.get("transfer-encoding", "") == "chunked":
                self._content_length = None
            else:
                content_length = self.headers.get("content-length", None)
                if content_length is None:
                    self._content_length = None
                else:
                    try:
                        self._content_length = max(0, int(content_length))
                    except (ValueError, TypeError):
                        self._content_length = None
        return self._content_length

    _cookies: Dict[str, str]

    @property
    def cookies(self) -> Dict[str, str]:
        """
        Returns cookies in as a `dict`.

        NOTE: Modifications to this dictionary will not affect the
        response value. In fact, this value should not be modified.
        """
        if not hasattr(self, "_cookies"):
            cookies: Dict[str, str] = {}
            cookie_header = self.headers.get("cookie", "")

            # This function has been adapted from Django 3.1.0.
            for chunk in cookie_header.split(";"):
                if not chunk:
                    continue
                if "=" in chunk:
                    key, val = chunk.split("=", 1)
                else:
                    # Assume an empty name per
                    # https://bugzilla.mozilla.org/show_bug.cgi?id=169091
                    key, val = "", chunk
                key, val = key.strip(), val.strip()
                if key or val:
                    # unquote using Python's algorithm.
                    cookies[key] = http_cookies._unquote(val)  # type: ignore

            self._cookies = cookies
        return self._cookies

    _date: Optional[datetime]

    @property
    def date(self) -> Optional[datetime]:
        """
        The sending time of the request.

        NOTE: The datetime object is timezone-aware.
        """
        if not hasattr(self, "_date"):
            value = self.headers.get("date", None)
            if value is None:
                self._date = None
            else:
                try:
                    date = parsedate_to_datetime(value)
                except (TypeError, ValueError):
                    self._date = None
                else:
                    if date.tzinfo is None:
                        self._date = date.replace(tzinfo=timezone.utc)
                    else:
                        self._date = date
        return self._date

    _referrer: Optional[URL]

    @property
    def referrer(self) -> Optional[URL]:
        """
        The `Referer` HTTP request header contains an absolute or partial address
        of the page making the request.
        """
        if not hasattr(self, "_referrer"):
            referrer = self.headers.get("referer", None)
            if referrer is None:
                self._referrer = None
            else:
                self._referrer = URL(url=referrer)
        return self._referrer
