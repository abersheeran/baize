import importlib.util
import os
import stat
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Literal, Optional, Tuple

from .responses import BaseResponse

try:
    from mypy_extensions import mypyc_attr
except ImportError:  # pragma: no cover

    def mypyc_attr(*attrs, **kwattrs):  # type: ignore
        return lambda x: x


@mypyc_attr(allow_interpreted_subclasses=True)
class BaseFiles:
    def __init__(
        self,
        directory: str,
        package: str = None,
        *,
        cacheability: Literal["public", "private", "no-cache", "no-store"] = "public",
        max_age: int = 60 * 10,  # 10 minutes
    ) -> None:
        if os.path.isabs(directory) and package is None:
            raise ValueError(
                "directory must be a relative path, with package is not None"
            )
        self.directory = self.normalize_dir_path(directory, package)
        self.cacheability = cacheability
        self.max_age = max_age

    def normalize_dir_path(self, directory: str, package: str = None) -> str:
        if package is None:
            return os.path.abspath(directory)
        else:
            spec = importlib.util.find_spec(package)
            assert spec is not None, f"Package {package!r} could not be found."
            assert (
                spec.origin is not None
            ), f"Directory 'statics' in package {package!r} could not be found."
            package_directory = os.path.normpath(
                os.path.join(spec.origin, "..", "statics")
            )
            assert os.path.isdir(
                package_directory
            ), f"Directory 'statics' in package {package!r} could not be found."
            return package_directory

    def ensure_absolute_path(self, path: str) -> Optional[str]:
        abspath = os.path.abspath(os.path.join(self.directory, path.lstrip("/")))

        if os.path.relpath(abspath, self.directory).startswith(".."):
            return None

        return abspath

    def check_path_is_file(
        self, path: Optional[str]
    ) -> Tuple[Optional[os.stat_result], bool]:
        if path is None:
            return None, False
        try:
            stat_result = os.stat(path)
            return stat_result, stat.S_ISREG(stat_result.st_mode)
        except FileNotFoundError:
            return None, False

    def if_none_match(self, etag: str, if_none_match: str) -> bool:
        if not if_none_match:
            return False

        if if_none_match == "*":
            return True

        if if_none_match.startswith("W/"):
            if_none_match = if_none_match[2:]

        return any(etag == i.strip() for i in if_none_match.split(","))

    def if_modified_since(self, last_modified: float, if_modified_since: str) -> bool:
        if not if_modified_since:
            return False

        try:
            modified_time = parsedate_to_datetime(if_modified_since).timestamp()
        except ValueError:
            return False

        return last_modified <= modified_time

    def set_response_headers(self, response: BaseResponse) -> None:
        response.headers.append(
            "Cache-Control", f"{self.cacheability}, max-age={self.max_age}"
        )
        response.headers.append("Vary", "Accept-Encoding, User-Agent, Cookie, Referer")


@mypyc_attr(allow_interpreted_subclasses=True)
class BasePages(BaseFiles):
    def ensure_absolute_path(self, path: str) -> Optional[str]:
        abspath = super().ensure_absolute_path(path)
        if abspath is not None:
            if abspath.endswith("/"):
                abspath += "index.html"
        return abspath
