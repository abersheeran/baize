import stat
from typing import Iterable

from baize import staticfiles
from baize.datastructures import URL
from baize.exceptions import HTTPException
from baize.typing import Environ, StartResponse

from .responses import FileResponse, RedirectResponse, Response


class Files(staticfiles.BaseFiles):
    """
    Provide the WSGI application to download files in the specified path or
    the specified directory under the specified package.

    Support request range and cache (304 status code).

    NOTE: Need users handle HTTPException(404).
    """

    def __call__(
        self, environ: Environ, start_response: StartResponse
    ) -> Iterable[bytes]:
        if_none_match: str = environ.get("HTTP_IF_NONE_MATCH", "")
        if_modified_since: str = environ.get("HTTP_IF_MODIFIED_SINCE", "")
        filepath = self.ensure_absolute_path(environ.get("PATH_INFO", ""))
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
            return response(environ, start_response)

        raise HTTPException(404)


class Pages(staticfiles.BasePages):
    """
    Provide the WSGI application to download files in the specified path or
    the specified directory under the specified package.
    Unlike `Files`, when you visit a directory, it will try to return the content
    of the file named `index.html` in that directory.

    Support request range and cache (304 status code).

    NOTE: Need users handle HTTPException(404).
    """

    def __call__(
        self, environ: Environ, start_response: StartResponse
    ) -> Iterable[bytes]:
        if_none_match: str = environ.get("HTTP_IF_NONE_MATCH", "")
        if_modified_since: str = environ.get("HTTP_IF_MODIFIED_SINCE", "")
        filepath = self.ensure_absolute_path(environ.get("PATH_INFO", ""))
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
                return response(environ, start_response)
            if stat.S_ISDIR(stat_result.st_mode):
                url = URL(environ=environ)
                url = url.replace(scheme="", path=url.path + "/")
                return RedirectResponse(url)(environ, start_response)

        raise HTTPException(404)
