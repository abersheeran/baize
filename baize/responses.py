import datetime
import os
import re
import time
from email.utils import formatdate
from hashlib import sha1
from itertools import chain
from typing import (
    Callable,
    Dict,
    Iterable,
    List,
    Mapping,
    Optional,
    Sequence,
    Tuple,
    Union,
    overload,
)
from urllib.parse import quote

try:
    from mypy_extensions import mypyc_attr, trait
except ImportError:  # pragma: no cover

    def trait(cls):  # type: ignore
        return cls

    def mypyc_attr(*attrs, **kwattrs):  # type: ignore
        return lambda x: x


from .datastructures import Cookie, MutableHeaders
from .exceptions import MalformedRangeHeader, RangeNotSatisfiable
from .typing import Literal, ServerSentEvent


@mypyc_attr(allow_interpreted_subclasses=True)
class BaseResponse:
    def __init__(
        self, status_code: int = 200, headers: Optional[Mapping[str, str]] = None
    ) -> None:
        self.status_code = status_code
        self.headers = MutableHeaders(headers)
        self.cookies: List[Cookie] = []

    def set_cookie(
        self,
        key: str,
        value: str = "",
        max_age: int = -1,
        expires: Optional[int] = None,
        path: str = "/",
        domain: Optional[str] = None,
        secure: bool = False,
        httponly: bool = False,
        samesite: Literal["strict", "lax", "none"] = "lax",
    ) -> None:
        expires_datetime: Optional[datetime.datetime] = None
        if expires is not None:
            expires_datetime = datetime.datetime.fromtimestamp(time.time() + expires)

        self.cookies.append(
            Cookie(
                key,
                value,
                expires=expires_datetime,
                max_age=max_age,
                path=path,
                domain=domain,
                secure=secure,
                httponly=httponly,
                samesite=samesite,
            )
        )

    def delete_cookie(
        self,
        key: str,
        value: str = "",
        path: str = "/",
        domain: Optional[str] = None,
        secure: bool = False,
        httponly: bool = False,
        samesite: Literal["strict", "lax", "none"] = "lax",
    ) -> None:
        self.set_cookie(
            key,
            expires=0,
            max_age=0,
            path=path,
            domain=domain,
            secure=secure,
            httponly=httponly,
            samesite=samesite,
        )

    @overload
    def list_headers(self, *, as_bytes: Literal[True]) -> List[Tuple[bytes, bytes]]:
        ...

    @overload
    def list_headers(self, *, as_bytes: Literal[False]) -> List[Tuple[str, str]]:
        ...

    def list_headers(self, *, as_bytes):
        """
        Merge `self.headers` and `self.cookies` then returned as a list.
        """
        if as_bytes:
            return [
                *(
                    (key.encode("latin-1"), value.encode("latin-1"))
                    for key, value in self.headers.items()
                ),
                *((b"set-cookie", bytes(cookie)) for cookie in self.cookies),
            ]
        else:
            return [
                *self.headers.items(),
                *(("set-cookie", str(cookie)) for cookie in self.cookies),
            ]


@trait
class FileResponseMixin:
    def generate_common_headers(
        self,
        filepath: str,
        content_type: str,
        download_name: Optional[str],
        stat_result: os.stat_result,
    ) -> Dict[str, str]:
        headers: Dict[str, str] = {
            "accept-ranges": "bytes",
            "last-modified": formatdate(stat_result.st_mtime, usegmt=True),
            "etag": self.generate_etag(stat_result),
        }
        if download_name or content_type == "application/octet-stream":
            download_name = download_name or os.path.basename(filepath)
            content_disposition = (
                "attachment; "
                f'filename="{download_name}"; '
                f"filename*=utf-8''{quote(download_name)}"
            )
            headers["content-disposition"] = content_disposition

        return headers

    @staticmethod
    def generate_etag(stat_result: os.stat_result) -> str:
        data = f"{stat_result.st_mtime}-{stat_result.st_size}"
        return sha1(data.encode("ascii")).hexdigest()

    @classmethod
    def judge_if_range(
        cls, if_range_raw_line: str, stat_result: os.stat_result
    ) -> bool:
        """
        Judge whether if-range is consistent with the value of etag or last-modified
        """
        return (
            if_range_raw_line == cls.generate_etag(stat_result)
        ) or if_range_raw_line == formatdate(stat_result.st_mtime, usegmt=True)

    @staticmethod
    def parse_range(
        range_raw_line: str, max_size: int
    ) -> Sequence[Tuple[int, Union[int, int]]]:
        """
        Parse the Range header and make appropriate merge or cut processing
        """
        try:
            unit, ranges_str = range_raw_line.split("=", maxsplit=1)
        except ValueError:
            raise MalformedRangeHeader()
        if unit != "bytes":
            raise MalformedRangeHeader("Only support bytes range")

        ranges = [
            (
                int(_[0]) if _[0] else max_size - int(_[1]),
                int(_[1]) + 1 if _[0] and _[1] and int(_[1]) < max_size else max_size,
            )
            for _ in re.findall(r"(\d*)-(\d*)", ranges_str)
            if _ != ("", "")
        ]

        if len(ranges) == 0:
            raise MalformedRangeHeader("Range header: range must be requested")

        if any(not (0 <= start < max_size) for start, _ in ranges):
            raise RangeNotSatisfiable(max_size)

        if any(start > end for start, end in ranges):
            raise MalformedRangeHeader("Range header: start must be less than end")

        if len(ranges) == 1:
            return ranges

        result: List[Tuple[int, int]] = []
        for start, end in ranges:
            for p in range(len(result)):
                p_start, p_end = result[p]
                if start > p_end:
                    continue
                elif end < p_start:
                    result.insert(p, (start, end))
                    break
                else:
                    result[p] = (min(start, p_start), max(end, p_end))
                    break
            else:
                result.append((start, end))
        return result

    def generate_multipart(
        self,
        ranges: Sequence[Tuple[int, int]],
        boundary: str,
        max_size: int,
        content_type: str,
    ) -> Tuple[int, Callable[[int, int], bytes]]:
        r"""
        Multipart response headers generator.

        ```
        --{boundary}\n
        Content-Type: {content_type}\n
        Content-Range: bytes {start}-{end-1}/{max_size}\n
        \n
        ..........content...........\n
        --{boundary}\n
        Content-Type: {content_type}\n
        Content-Range: bytes {start}-{end-1}/{max_size}\n
        \n
        ..........content...........\n
        --{boundary}--\n
        ```
        """
        boundary_len = len(boundary)
        static_header_part_len = (
            44 + boundary_len + len(content_type) + len(str(max_size))
        )
        content_length = sum(
            (len(str(start)) + len(str(end - 1)) + static_header_part_len)  # Headers
            + (end - start)  # Content
            for start, end in ranges
        ) + (
            5 + boundary_len  # --boundary--\n
        )
        return (
            content_length,
            lambda start, end: (
                f"--{boundary}\n"
                f"Content-Type: {content_type}\n"
                f"Content-Range: bytes {start}-{end-1}/{max_size}\n"
                "\n"
            ).encode("latin-1"),
        )


def build_bytes_from_sse(event: ServerSentEvent, charset: str) -> bytes:
    """
    helper function for SendEventResponse
    """
    data: Iterable[bytes]
    if "data" in event:
        data = (f"data: {_}".encode(charset) for _ in event.pop("data").splitlines())
    else:
        data = ()
    return b"\n".join(
        chain(
            map(lambda k, v: f"{k}: {v}".encode(charset), event.keys(), event.values()),
            data,
            (b"", b""),  # for generate b"\n\n"
        )
    )


def iri_to_uri(iri: str) -> str:
    """
    Convert an Internationalized Resource Identifier (IRI) portion to a URI portion
    that is suitable for inclusion in a URL.
    """
    # Copy from django
    # https://github.com/django/django/blob/main/django/utils/encoding.py#L100
    return quote(iri, safe="/#%[]=:;$&()+,!?*@'~")
