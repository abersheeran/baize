from baize.routing import BaseHosts, BaseRouter, BaseSubpaths
from baize.typing import ASGIApp, Receive, Scope, Send

from .responses import PlainTextResponse, Response


class Router(BaseRouter[ASGIApp]):
    """
    A router to assign different paths to different ASGI applications.

    :param routes: A triple composed of path, endpoint, and name. The name is optional. \
        If the name is not given, the corresponding URL cannot be constructed through \
        build_url.

    ```python
    applications = Router(
        ("/static/{filepath:any}", static_files),
        ("/api/{_:any}", api_app),
        ("/about/{name}", about_page),
        ("/", homepage),
    )
    """

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        result = self.search(scope["path"])
        if result is None:
            response: ASGIApp = Response(404)
        else:
            route, path_params = result
            scope["path_params"] = path_params
            response = route.endpoint
        return await response(scope, receive, send)


class Subpaths(BaseSubpaths[ASGIApp]):
    """
    A router allocates different prefix requests to different ASGI applications.

    NOTE: This will change the values of `scope["root_path"]` and `scope["path"]`.

    ```python
    applications = Subpaths(
        ("/static", static_files),
        ("/api", api_app),
        ("", default_app),
    )
    ```
    """

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope["path"]
        result = self.search(path)
        if result is None:
            response: ASGIApp = Response(404)
        else:
            prefix, response = result
            scope["root_path"] = scope.get("root_path", "") + prefix
            scope["path"] = path[len(prefix) :]
        return await response(scope, receive, send)


class Hosts(BaseHosts[ASGIApp]):
    r"""
    A router that distributes requests to different ASGI applications based on Host.

    ```python
    applications = Hosts(
        (r"static\.example\.com", static_files),
        (r"api\.example\.com", api_app),
        (r"(www\.)?example\.com", default_app),
    )
    ```
    """

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        host = ""
        for k, v in scope["headers"]:
            if k == b"host":
                host = v.decode("latin-1")
        endpoint = self.search(host)
        if endpoint is None:
            response: ASGIApp = PlainTextResponse(b"Invalid host", 404)
        else:
            response = endpoint
        return await response(scope, receive, send)
