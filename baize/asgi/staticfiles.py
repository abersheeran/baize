import stat

from baize import staticfiles
from baize.datastructures import URL
from baize.exceptions import HTTPException
from baize.typing import Receive, Scope, Send

from .responses import FileResponse, RedirectResponse, Response


class Files(staticfiles.BaseFiles):
    """
    Provide the ASGI application to download files in the specified path or
    the specified directory under the specified package.

    Support request range and cache (304 status code).

    NOTE: Need users handle HTTPException(404).
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
        if is_file and stat_result:
            assert filepath is not None  # Just for type check
            if self.if_none_match(
                FileResponse.generate_etag(stat_result), if_none_match
            ) or self.if_modified_since(stat_result.st_ctime, if_modified_since):
                response = Response(304)
            else:
                response = FileResponse(filepath, stat_result=stat_result)
            self.set_response_headers(response)
            return await response(scope, receive, send)

        raise HTTPException(404)


class Pages(staticfiles.BasePages):
    """
    Provide the ASGI application to download files in the specified path or
    the specified directory under the specified package.
    Unlike `Files`, when you visit a directory, it will try to return the content
    of the file named `index.html` in that directory.

    Support request range and cache (304 status code).

    NOTE: Need users handle HTTPException(404).
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
        if stat_result is not None:
            assert filepath is not None  # Just for type check
            if is_file:
                if self.if_none_match(
                    FileResponse.generate_etag(stat_result), if_none_match
                ) or self.if_modified_since(stat_result.st_ctime, if_modified_since):
                    response = Response(304)
                else:
                    response = FileResponse(filepath, stat_result=stat_result)
                self.set_response_headers(response)
                return await response(scope, receive, send)
            if stat.S_ISDIR(stat_result.st_mode):
                url = URL(scope=scope)
                url = url.replace(scheme="", path=url.path + "/")
                return await RedirectResponse(url)(scope, receive, send)

        raise HTTPException(404)
