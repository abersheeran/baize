from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from http import cookies as http_cookies
from typing import Dict, List, Optional

try:
    from mypy_extensions import mypyc_attr, trait
except ImportError:  # pragma: no cover

    def trait(cls):  # type: ignore
        return cls

    def mypyc_attr(*attrs, **kwattrs):  # type: ignore
        return lambda x: x


from .datastructures import URL, ContentType, Headers, MediaType
from .utils import cached_property


@mypyc_attr(allow_interpreted_subclasses=True)
class MoreInfoFromHeaderMixin:
    """
    Parse more information from the header for quick use
    """

    @cached_property
    def headers(self) -> Headers:
        raise NotImplementedError

    @cached_property
    def accepted_types(self) -> List[MediaType]:
        """
        Request's accepted types
        """
        return [
            MediaType(token)
            for token in self.headers.get("Accept", "*/*").split(",")
            if token.strip()
        ]

    def accepts(self, media_type: str) -> bool:
        """
        e.g. `request.accepts("application/json")`
        """
        return any(
            accepted_type.match(media_type) for accepted_type in self.accepted_types
        )

    @cached_property
    def content_type(self) -> ContentType:
        """
        Request's content-type
        """
        return ContentType(self.headers.get("content-type", ""))

    @cached_property
    def content_length(self) -> Optional[int]:
        """
        Request's content-length
        """
        if self.headers.get("transfer-encoding", "") == "chunked":
            return None

        content_length = self.headers.get("content-length", None)
        if content_length is None:
            return None

        try:
            return max(0, int(content_length))
        except (ValueError, TypeError):
            return None

    @cached_property
    def cookies(self) -> Dict[str, str]:
        """
        Returns cookies in as a `dict`.

        NOTE: Modifications to this dictionary will not affect the
        response value. In fact, this value should not be modified.
        """
        cookies: Dict[str, str] = {}
        cookie_header = self.headers.get("cookie", "")

        # This function has been adapted from Django 3.1.0.
        # Note: we are explicitly _NOT_ using `SimpleCookie.load` because it is based
        # on an outdated spec and will fail on lots of input we want to support
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
        return cookies

    @cached_property
    def date(self) -> Optional[datetime]:
        """
        The sending time of the request.

        NOTE: The datetime object is timezone-aware.
        """
        value = self.headers.get("date", None)
        if value is None:
            return None

        try:
            date = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None

        if date.tzinfo is None:
            return date.replace(tzinfo=timezone.utc)

        return date

    @cached_property
    def referrer(self) -> Optional[URL]:
        """
        The `Referer` HTTP request header contains an absolute or partial address
        of the page making the request.
        """
        referrer = self.headers.get("referer", None)
        if referrer is None:
            return None

        return URL(url=referrer)
