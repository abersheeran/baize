from http import cookies as http_cookies
from typing import Dict, List

from .datastructures import ContentType, Headers, MediaType
from .utils import cached_property

# Workaround for adding samesite support to pre 3.8 python
http_cookies.Morsel._reserved["samesite"] = "SameSite"  # type: ignore


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
