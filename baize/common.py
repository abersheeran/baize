from http import cookies as http_cookies
from typing import Dict, List, Mapping

from .datastructures import ContentType, Headers, MediaType, MutableHeaders
from .typing import Literal
from .utils import cached_property

# Workaround for adding samesite support to pre 3.8 python
http_cookies.Morsel._reserved["samesite"] = "SameSite"  # type: ignore


class MoreInfoFromHeaderMixin:
    """
    Parse more information from the header for quick use
    """

    @property
    def headers(self) -> Headers:
        raise NotImplementedError

    @cached_property
    def accepted_types(self) -> List[MediaType]:
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

        # This function parses a ``Cookie`` HTTP header into a dict of key/value pairs.
        # It attempts to mimic browser cookie parsing behavior: browsers and web servers
        # frequently disregard the spec (RFC 6265) when setting and reading cookies,
        # so we attempt to suit the common scenarios here.

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


class BaseResponse:
    def __init__(
        self, status_code: int = 200, headers: Mapping[str, str] = None
    ) -> None:
        self.status_code = status_code
        if headers is None:
            self.raw_headers = []
        else:
            self.raw_headers = [(k.lower(), v) for k, v in headers.items()]

    @cached_property
    def headers(self) -> MutableHeaders:
        return MutableHeaders(raw=self.raw_headers)

    def set_cookie(
        self,
        key: str,
        value: str = "",
        max_age: int = None,
        expires: int = None,
        path: str = "/",
        domain: str = None,
        secure: bool = False,
        httponly: bool = False,
        samesite: Literal["strict", "lax", "none"] = "lax",
    ) -> None:
        cookie: http_cookies.SimpleCookie = http_cookies.SimpleCookie()
        cookie[key] = value
        if max_age is not None:
            cookie[key]["max-age"] = max_age
        if expires is not None:
            cookie[key]["expires"] = expires
        if path is not None:
            cookie[key]["path"] = path
        if domain is not None:
            cookie[key]["domain"] = domain
        if secure:
            cookie[key]["secure"] = True
        if httponly:
            cookie[key]["httponly"] = True
        if samesite is not None:
            cookie[key]["samesite"] = samesite
        cookie_val = cookie.output(header="").strip()
        self.raw_headers.append(("set-cookie", cookie_val))

    def delete_cookie(self, key: str, path: str = "/", domain: str = None) -> None:
        self.set_cookie(key, expires=0, max_age=0, path=path, domain=domain)
