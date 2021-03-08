import os
import re
import stat
from email.utils import formatdate
from hashlib import sha1
from http import cookies as http_cookies
from mimetypes import guess_type
from typing import List, Mapping, MutableSequence, Sequence, Tuple, Union
from urllib.parse import quote

from .datastructures import MutableHeaders
from .exceptions import HTTPException
from .typing import Literal
from .utils import cached_property


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


class BaseFileResponse(BaseResponse):
    range_re = re.compile(r"(\d+)-(\d*)")

    def __init__(
        self,
        filepath: str,
        headers: Mapping[str, str] = None,
        media_type: str = None,
        download_name: str = None,
        stat_result: os.stat_result = None,
    ) -> None:
        self.filepath = filepath
        self.media_type = (
            media_type
            or guess_type(download_name or os.path.basename(filepath))[0]
            or "application/octet-stream"
        )
        self.download_name = download_name
        self.stat_result = stat_result or os.stat(self.filepath)
        if not stat.S_ISREG(self.stat_result.st_mode):
            raise FileNotFoundError("Filepath exists, but is not a valid file.")
        super().__init__(status_code=200, headers=headers)

    def generate_required_header(
        self, stat_result: os.stat_result
    ) -> MutableSequence[Tuple[str, str]]:
        """
        Generate `accept-ranges`, `last-modified` and `etag`.
        If necessary, `content-disposition` will also be generated.
        """
        headers: List[Tuple[str, str]] = []
        headers.append(("accept-ranges", "bytes"))

        if (
            self.download_name is not None
            or self.media_type == "application/octet-stream"
        ):
            content_disposition = "attachment; filename*=utf-8''{}".format(
                quote(self.download_name or os.path.basename(self.filepath))
            )
            headers.append(("content-disposition", content_disposition))

        headers.append(("last-modified", formatdate(stat_result.st_mtime, usegmt=True)))
        headers.append(("etag", self.generate_etag(stat_result)))

        return headers

    def generate_etag(self, stat_result: os.stat_result) -> str:
        return sha1(
            f"{stat_result.st_mtime}-{stat_result.st_size}".encode("ascii")
        ).hexdigest()

    def judge_if_range(
        self, if_range_raw_line: str, stat_result: os.stat_result
    ) -> bool:
        """
        Judge whether if-range is consistent with the value of etag or last-modified
        """
        return (
            if_range_raw_line == self.generate_etag(stat_result)
        ) or if_range_raw_line == formatdate(stat_result.st_mtime, usegmt=True)

    def parse_range(
        self, range_raw_line: str, max_size: int
    ) -> Sequence[Tuple[int, Union[int, int]]]:
        """
        Parse the Range header and make appropriate merge or cut processing
        """
        try:
            unit, ranges_str = range_raw_line.split("=", maxsplit=1)
        except ValueError:
            raise HTTPException(status_code=400)
        if unit != "bytes":
            raise HTTPException(status_code=400)

        ranges = [
            (int(_[0]), int(_[1]) + 1 if _[1] else max_size)
            for _ in self.range_re.findall(ranges_str)
        ]

        if any(start > end for start, end in ranges):
            raise HTTPException(status_code=400)

        if any(end > max_size for _, end in ranges):
            raise HTTPException(
                status_code=416,
                headers={
                    "Content-Range": f"*/{max_size}",
                },
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
