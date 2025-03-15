import os
import stat
from typing import Optional

from baize import staticfiles
from baize.datastructures import URL
from baize.exceptions import HTTPException
from baize.typing import ASGIApp, Receive, Scope, Send

from .responses import FileResponse, RedirectResponse, Response


class Files(staticfiles.BaseFiles[ASGIApp]):
    """
    Provide the ASGI application to download files in the specified path or
    the specified directory under the specified package.

    Support request range and cache (304 status code).
    """

    def file_response(
        self,
        filepath: str,
        stat_result: os.stat_result,
        if_none_match: str,
        if_modified_since: str,
    ) -> Response:
        if self.if_none_match(
            FileResponse.generate_etag(stat_result), if_none_match
        ) or self.if_modified_since(stat_result.st_mtime, if_modified_since):
            response = Response(304)
        else:
            response = FileResponse(filepath, stat_result=stat_result)
            self.set_response_headers(response)
        return response

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if_none_match: str = ""
        if_modified_since: str = ""
        for k, v in scope["headers"]:
            if k == b"if-none-match":
                if_none_match = v.decode("latin-1")
            elif k == b"if-modified-since":
                if_modified_since = v.decode("latin-1")
        filepath = self.ensure_absolute_path(scope["path"])
        stat_result, is_file = self.check_path_is_file(filepath)
        if is_file and stat_result:
            assert filepath is not None  # Just for type check
            return await self.file_response(
                filepath, stat_result, if_none_match, if_modified_since
            )(scope, receive, send)

        if self.handle_404 is None:
            raise HTTPException(404)
        else:
            return await self.handle_404(scope, receive, send)


class Pages(Files):
    """
    Provide the ASGI application to download files in the specified path or
    the specified directory under the specified package.
    Unlike `Files`, when you visit a directory, it will try to return the content
    of the file named `index.html` in that directory.

    Support request range and cache (304 status code).
    """

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if_none_match: str = ""
        if_modified_since: str = ""
        for k, v in scope["headers"]:
            if k == b"if-none-match":
                if_none_match = v.decode("latin-1")
            elif k == b"if-modified-since":
                if_modified_since = v.decode("latin-1")
        filepath = self.ensure_absolute_path(scope["path"])
        stat_result, is_file = self.check_path_is_file(filepath)
        if (
            stat_result is None  # filepath is not exist
            and filepath is not None  # Just for type check
            and not filepath.endswith(".html")  # filepath is not a html file
        ):
            filepath += ".html"
            stat_result, is_file = self.check_path_is_file(filepath)

        if stat_result is not None:
            assert filepath is not None  # Just for type check
            if is_file:
                return await self.file_response(
                    filepath, stat_result, if_none_match, if_modified_since
                )(scope, receive, send)
            if stat.S_ISDIR(stat_result.st_mode):
                url = URL(scope=scope)
                url = url.replace(scheme="", path=url.path + "/")
                return await RedirectResponse(url)(scope, receive, send)

        if self.handle_404 is None:
            raise HTTPException(404)
        else:
            return await self.handle_404(scope, receive, send)

    def ensure_absolute_path(self, path: str) -> Optional[str]:
        abspath = super().ensure_absolute_path(path)
        if abspath is not None:
            if abspath.endswith("/"):
                abspath += "index.html"
        return abspath
