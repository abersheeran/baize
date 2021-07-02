import os
import re
import stat
from email.utils import formatdate
from hashlib import sha1
from http import cookies as http_cookies
from itertools import chain
from mimetypes import guess_type
from typing import Callable, Iterable, List, Mapping, Sequence, Tuple, Union, overload
from urllib.parse import quote

from . import status
from .datastructures import MutableHeaders
from .exceptions import HTTPException
from .typing import Literal, ServerSentEvent


class BaseResponse:
    def __init__(
        self, status_code: int = status.HTTP_200_OK, headers: Mapping[str, str] = None
    ) -> None:
        self.status_code = status_code
        self.headers = MutableHeaders(headers)
        self.cookies: http_cookies.SimpleCookie = http_cookies.SimpleCookie()

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
        cookies = self.cookies
        cookies[key] = value
        if max_age is not None:
            cookies[key]["max-age"] = max_age
        if expires is not None:
            cookies[key]["expires"] = expires
        if path is not None:
            cookies[key]["path"] = path
        if domain is not None:
            cookies[key]["domain"] = domain
        if secure:
            cookies[key]["secure"] = True
        if httponly:
            cookies[key]["httponly"] = True
        if samesite is not None:
            cookies[key]["samesite"] = samesite

    def delete_cookie(self, key: str, path: str = "/", domain: str = None) -> None:
        self.set_cookie(key, expires=0, max_age=0, path=path, domain=domain)

    @overload
    def list_headers(self, *, as_bytes: Literal[True]) -> List[Tuple[bytes, bytes]]:
        raise NotImplementedError

    @overload
    def list_headers(self, *, as_bytes: Literal[False]) -> List[Tuple[str, str]]:
        raise NotImplementedError

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
                *(
                    (b"set-cookie", c.output(header="").encode("latin-1"))
                    for c in self.cookies.values()
                ),
            ]
        else:
            return [
                *self.headers.items(),
                *(("set-cookie", c.output(header="")) for c in self.cookies.values()),
            ]


class BaseFileResponse(BaseResponse):
    def __init__(
        self,
        filepath: str,
        headers: Mapping[str, str] = None,
        content_type: str = None,
        download_name: str = None,
        stat_result: os.stat_result = None,
        chunk_size: int = 4096 * 64,
    ) -> None:
        self.filepath = filepath
        self.content_type = (
            content_type
            or guess_type(download_name or os.path.basename(filepath))[0]
            or "application/octet-stream"
        )
        self.stat_result = stat_result = stat_result or os.stat(self.filepath)
        self.chunk_size = chunk_size
        if not stat.S_ISREG(stat_result.st_mode):
            raise FileNotFoundError("Filepath exists, but is not a valid file.")
        super().__init__(status_code=status.HTTP_200_OK, headers=headers)

        self.headers["accept-ranges"] = "bytes"
        if download_name is not None or self.content_type == "application/octet-stream":
            download_name = download_name or os.path.basename(self.filepath)
            content_disposition = (
                "attachment; "
                f'filename="{download_name}"; '
                f"filename*=utf-8''{quote(download_name)}"
            )
            self.headers["content-disposition"] = content_disposition
        self.headers["last-modified"] = formatdate(stat_result.st_mtime, usegmt=True)
        self.headers["etag"] = self.generate_etag(stat_result)

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
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)
        if unit != "bytes":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)

        ranges = [
            (int(_[0]), int(_[1]) + 1 if _[1] else max_size)
            for _ in re.findall(r"(\d+)-(\d*)", ranges_str)
        ]

        if any(start > end for start, end in ranges):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)

        if any(end > max_size for _, end in ranges):
            raise HTTPException(
                status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE,
                headers={"Content-Range": f"*/{max_size}"},
            )

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
        self, ranges: Sequence[Tuple[int, int]], boundary: str, max_size: int
    ) -> Tuple[int, Callable[[int, int], bytes]]:
        boundary_len = len(boundary)
        content_length = (
            (
                len(ranges)
                * (44 + boundary_len + len(self.content_type) + len(str(max_size)))
                + sum(len(str(start)) + len(str(end - 1)) for start, end in ranges)
            )  # Headers
            + sum(end - start for start, end in ranges)  # Content
            + (5 + boundary_len)  # --boundary--\n
        )
        return (
            content_length,
            lambda start, end: (
                f"--{boundary}\n"
                f"Content-Type: {self.content_type}\n"
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
            (f"{k}: {v}".encode(charset) for k, v in event.items()),
            data,
            (b"", b""),  # for generate b"\n\n"
        )
    )
