from typing import Iterable

from baize.routing import BaseHosts, BaseRouter, BaseSubpaths
from baize.typing import Environ, StartResponse, WSGIApp

from .responses import PlainTextResponse, Response


class Router(BaseRouter[WSGIApp]):
    """
    A router to assign different paths to different WSGI applications.

    ```python
    applications = Router(
        ("/static/{filepath:any}", static_files),
        ("/api/{_:any}", api_app),
        ("/about/{name}", about_page),
        ("/", homepage),
    )
    ```
    """

    def __call__(
        self, environ: Environ, start_response: StartResponse
    ) -> Iterable[bytes]:
        result = self.search(environ.get("PATH_INFO", ""))
        if result is None:
            response: WSGIApp = Response(404)
        else:
            route, path_params = result
            environ["PATH_PARAMS"] = path_params
            response = route.endpoint
        yield from response(environ, start_response)


class Subpaths(BaseSubpaths[WSGIApp]):
    """
    A router allocates different prefix requests to different WSGI applications.

    NOTE: This will change the values of `environ["SCRIPT_NAME"]` and `environ["PATH_INFO"]`.

    ```python
    applications = Subpaths(
        ("/static", static_files),
        ("/api", api_app),
        ("", default_app),
    )
    ```
    """

    def __call__(
        self, environ: Environ, start_response: StartResponse
    ) -> Iterable[bytes]:
        path = environ.get("PATH_INFO", "")
        result = self.search(path)
        if result is None:
            response: WSGIApp = Response(404)
        else:
            prefix, response = result
            environ["SCRIPT_NAME"] = environ.get("SCRIPT_NAME", "") + prefix
            environ["PATH_INFO"] = path[len(prefix) :]
        yield from response(environ, start_response)


class Hosts(BaseHosts[WSGIApp]):
    r"""
    A router that distributes requests to different WSGI applications based on Host.

    ```python
    applications = Hosts(
        (r"static\.example\.com", static_files),
        (r"api\.example\.com", api_app),
        (r"(www\.)?example\.com", default_app),
    )
    ```
    """

    def __call__(
        self, environ: Environ, start_response: StartResponse
    ) -> Iterable[bytes]:
        endpoint = self.search(environ.get("HTTP_HOST", ""))
        if endpoint is None:
            response: WSGIApp = PlainTextResponse(b"Invalid host", 404)
        else:
            response = endpoint
        yield from response(environ, start_response)
