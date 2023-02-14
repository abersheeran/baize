import tempfile
import time
from inspect import cleandoc
from pathlib import Path
from typing import Callable, Generator

import httpx
import pytest

from baize.datastructures import Address, UploadFile
from baize.exceptions import (
    HTTPException,
    MalformedJSON,
    MalformedMultipart,
    UnsupportedMediaType,
)
from baize.typing import ServerSentEvent
from baize.wsgi import (
    FileResponse,
    Files,
    Hosts,
    HTMLResponse,
    JSONResponse,
    Pages,
    PlainTextResponse,
    RedirectResponse,
    Request,
    Response,
    Router,
    SendEventResponse,
    StreamResponse,
    Subpaths,
    middleware,
    request_response,
)


def test_request_environ_interface():
    """
    A Request can be instantiated with a environ, and presents a `Mapping`
    interface.
    """
    request = Request({"type": "http", "method": "GET", "path": "/abc/"})
    assert request["method"] == "GET"
    assert dict(request) == {"type": "http", "method": "GET", "path": "/abc/"}
    assert len(request) == 3
    # test eq
    assert request == Request({"type": "http", "method": "GET", "path": "/abc/"})
    assert request != Request(
        {"type": "http", "method": "GET", "path": "/abc/", "query_params": {}}
    )
    assert request != dict({"type": "http", "method": "GET", "path": "/abc/"})


def test_request_url():
    def app(environ, start_response):
        request = Request(environ)
        response = PlainTextResponse(request.method + " " + str(request.url))
        return response(environ, start_response)

    with httpx.Client(app=app, base_url="http://testServer/") as client:
        response = client.get("/123?a=abc")
        assert response.text == "GET http://testserver/123?a=abc"

        response = client.get("https://example.org:123/")
        assert response.text == "GET https://example.org:123/"


def test_request_query_params():
    def app(environ, start_response):
        request = Request(environ)
        params = dict(request.query_params)
        response = JSONResponse({"params": params})
        return response(environ, start_response)

    with httpx.Client(app=app, base_url="http://testServer/") as client:
        response = client.get("/?a=123&b=456")
        assert response.json() == {"params": {"a": "123", "b": "456"}}


def test_request_headers():
    def app(environ, start_response):
        request = Request(environ)
        headers = dict(request.headers)
        headers.pop("user-agent")  # this is httpx version, delete it
        response = JSONResponse({"headers": headers})
        return response(environ, start_response)

    with httpx.Client(app=app, base_url="http://testServer/") as client:
        response = client.get("/", headers={"host": "example.org"})
        assert response.json() == {
            "headers": {
                "host": "example.org",
                "accept-encoding": "gzip, deflate",
                "accept": "*/*",
                "connection": "keep-alive",
            }
        }


def test_request_client():
    def app(environ, start_response):
        request = Request(environ)
        response = JSONResponse(
            {"host": request.client.host, "port": request.client.port}
        )
        return response(environ, start_response)

    with httpx.Client(app=app, base_url="http://testServer/") as client:
        response = client.get("/")
        assert response.json() == {"host": None, "port": None}

    request = Request({"REMOTE_ADDR": "127.0.0.1", "REMOTE_PORT": "62124"})
    assert request.client == Address("127.0.0.1", 62124)


def test_request_body():
    def app(environ, start_response):
        request = Request(environ)
        body = request.body
        response = JSONResponse({"body": body.decode()})
        return response(environ, start_response)

    with httpx.Client(app=app, base_url="http://testServer/") as client:
        response = client.get("/")
        assert response.json() == {"body": ""}

        response = client.post("/", json={"a": "123"})
        assert response.json() == {"body": '{"a": "123"}'}

        response = client.post("/", content="abc")
        assert response.json() == {"body": "abc"}


def test_request_stream():
    def app(environ, start_response):
        request = Request(environ)
        body = b""
        for chunk in request.stream():
            body += chunk
        response = PlainTextResponse(body)
        return response(environ, start_response)

    with httpx.Client(app=app, base_url="http://testServer/") as client:
        response = client.get("/")
        assert response.text == ""

        response = client.post("/", json={"a": "123"})
        assert response.text == '{"a": "123"}'

        response = client.post("/", content="abc")
        assert response.text == "abc"


def test_request_form_urlencoded():
    def app(environ, start_response):
        request = Request(environ)
        form = request.form
        response = JSONResponse({"form": dict(form)})
        return response(environ, start_response)
        request.close()

    with httpx.Client(app=app, base_url="http://testServer/") as client:
        response = client.post("/", data={"abc": "123 @"})
        assert response.json() == {"form": {"abc": "123 @"}}

        with pytest.raises(UnsupportedMediaType):
            response = client.post(
                "/", data={"abc": "123 @"}, headers={"content-type": "application/json"}
            )


def test_request_multipart_form():
    def app(environ, start_response):
        request = Request(environ)
        form = request.form
        file = form["file-key"]
        assert isinstance(file, UploadFile)
        assert file.read() == b"temporary file"
        response = JSONResponse({"file": file.filename})
        request.close()
        return response(environ, start_response)

    with httpx.Client(app=app, base_url="http://testServer/") as client:
        with tempfile.SpooledTemporaryFile(1024) as file:
            file.write(b"temporary file")
            file.seek(0, 0)
            response = client.post("/", data={"abc": "123 @"}, files={"file-key": file})
            assert response.json() == {"file": "None"}

        with pytest.raises(MalformedMultipart):
            response = client.post(
                "/", content=b"xxxx", headers={"content-type": "multipart/form-data"}
            )


def test_request_body_then_stream():
    def app(environ, start_response):
        request = Request(environ)
        body = request.body
        chunks = b""
        for chunk in request.stream():
            chunks += chunk
        response = JSONResponse({"body": body.decode(), "stream": chunks.decode()})
        return response(environ, start_response)

    with httpx.Client(app=app, base_url="http://testServer/") as client:
        response = client.post("/", content="abc")
        assert response.json() == {"body": "abc", "stream": "abc"}


def test_request_stream_then_body():
    def app(environ, start_response):
        request = Request(environ)
        chunks = b""
        for chunk in request.stream():
            chunks += chunk
        try:
            body = request.body
        except RuntimeError:
            body = b"<stream consumed>"
        response = JSONResponse({"body": body.decode(), "stream": chunks.decode()})
        return response(environ, start_response)

    with httpx.Client(app=app, base_url="http://testServer/") as client:
        response = client.post("/", content="abc")
        assert response.json() == {"body": "<stream consumed>", "stream": "abc"}


def test_request_json():
    def app(environ, start_response):
        request = Request(environ)
        data = request.json
        response = JSONResponse({"json": data})
        return response(environ, start_response)

    with httpx.Client(app=app, base_url="http://testServer/") as client:
        response = client.post("/", json={"a": "123"})
        assert response.json() == {"json": {"a": "123"}}

        with pytest.raises(UnsupportedMediaType):
            response = client.post(
                "/",
                data={"abc": "123 @"},
                headers={"content-type": "application/x-www-form-urlencoded"},
            )

        with pytest.raises(MalformedJSON):
            response = client.post(
                "/", content=b"abc", headers={"content-type": "application/json"}
            )


def test_request_accpet():
    data = "hello world"

    def app(environ, start_response):
        request = Request(environ)
        if request.accepts("application/json"):
            response = JSONResponse({"data": data})
        else:
            response = PlainTextResponse(data)
        return response(environ, start_response)

    with httpx.Client(app=app, base_url="http://testServer/") as client:
        response = client.get("/", headers={"Accept": "application/json"})
        assert response.json() == {"data": data}


# ######################################################################################
# ################################# Responses tests ####################################
# ######################################################################################


def test_unknown_status():
    with httpx.Client(app=Response(600), base_url="http://testServer/") as client:
        response = client.get("/")
        assert response.status_code == 600


def test_redirect_response():
    def app(environ, start_response):
        if environ["PATH_INFO"] == "/":
            response = PlainTextResponse("hello, world")
        else:
            response = RedirectResponse("/")
        return response(environ, start_response)

    with httpx.Client(app=app, base_url="http://testServer/") as client:
        response = client.get("/redirect", follow_redirects=True)
        assert response.text == "hello, world"
        assert response.url == "http://testserver/"


def test_stream_response():
    def generator(num: int) -> Generator[bytes, None, None]:
        for i in range(num):
            yield str(i).encode("utf-8")

    with httpx.Client(
        app=StreamResponse(generator(10)), base_url="http://testServer/"
    ) as client:
        response = client.get("/")
        assert response.content == b"".join(str(i).encode("utf-8") for i in range(10))


README = """\
# BáiZé

Powerful and exquisite WSGI/ASGI framework/toolkit.

The minimize implementation of methods required in the Web framework. No redundant implementation means that you can freely customize functions without considering the conflict with baize's own implementation.

Under the ASGI/WSGI protocol, the interface of the request object and the response object is almost the same, only need to add or delete `await` in the appropriate place. In addition, it should be noted that ASGI supports WebSocket but WSGI does not.
"""


def test_file_response(tmp_path: Path):
    filepath = tmp_path / "README.txt"
    filepath.write_bytes(README.encode("utf8"))
    file_response = FileResponse(str(filepath))
    with httpx.Client(app=file_response, base_url="http://testServer/") as client:
        response = client.get("/")
        assert response.status_code == 200
        assert response.headers["content-length"] == str(len(README.encode("utf8")))
        assert response.text == README

        response = client.head("/")
        assert response.status_code == 200
        assert response.headers["content-length"] == str(len(README.encode("utf8")))
        assert response.content == b""

        response = client.get("/", headers={"Range": "bytes=0-100"})
        assert response.status_code == 206
        assert response.headers["content-length"] == str(101)
        assert response.content == README.encode("utf8")[:101]

        response = client.head("/", headers={"Range": "bytes=0-100"})
        assert response.status_code == 206
        assert response.headers["content-length"] == str(101)
        assert response.content == b""

        response = client.get("/", headers={"Range": "bytes=0-100, 200-300"})
        assert response.status_code == 206
        assert response.headers["content-length"] == str(370)

        response = client.head("/", headers={"Range": "bytes=0-100, 200-300"})
        assert response.status_code == 206
        assert response.headers["content-length"] == str(370)
        assert response.content == b""

        response = client.head(
            "/",
            headers={
                "Range": "bytes=200-300",
                "if-range": response.headers["etag"][:-1],
            },
        )
        assert response.status_code == 200
        response = client.head(
            "/",
            headers={
                "Range": "bytes=200-300",
                "if-range": response.headers["etag"],
            },
        )
        assert response.status_code == 206

        response = client.head("/", headers={"Range": "bytes: 0-1000"})
        assert response.status_code == 400

        response = client.head(
            "/",
            headers={
                "Range": f"bytes={len(README.encode('utf8'))+1}-{len(README.encode('utf8'))+12}"
            },
        )
        assert response.status_code == 416
        assert response.headers["Content-Range"] == f"*/{len(README.encode('utf8'))}"


def test_file_response_with_directory(tmp_path: Path):
    with pytest.raises(IsADirectoryError):
        FileResponse(str(tmp_path))


def test_file_response_with_download_name(tmp_path: Path):
    filepath = tmp_path / "README"
    filepath.write_bytes(README.encode("utf8"))
    file_response = FileResponse(str(filepath), download_name="README.txt")
    with httpx.Client(app=file_response, base_url="http://testServer/") as client:
        response = client.get("/")
        assert (
            response.headers["content-disposition"]
            == "attachment; filename=\"README.txt\"; filename*=utf-8''README.txt"
        )


def test_send_event_response():
    def send_events() -> Generator[ServerSentEvent, None, None]:
        yield ServerSentEvent(data="hello\nworld")
        time.sleep(0.2)
        yield ServerSentEvent(data="nothing", event="nothing")
        yield ServerSentEvent(event="only-event")

    expected_events = (
        cleandoc(
            """
            data: hello
            data: world

            event: nothing
            data: nothing

            event: only-event
            """
        )
        + "\n\n"
    )

    with httpx.Client(
        app=SendEventResponse(send_events(), ping_interval=0.1),
        base_url="http://testServer/",
    ) as client:
        with client.stream("GET", "/") as resp:
            resp.raise_for_status()
            events = ""
            for line in resp.iter_lines():
                events += line
            assert events.replace(": ping\n\n", "") == expected_events

    with httpx.Client(
        app=SendEventResponse(
            send_events(),
            headers={"custom-header": "value"},
            ping_interval=0.1,
        ),
        base_url="http://testServer/",
    ) as client:
        with client.stream("GET", "/") as resp:
            resp.raise_for_status()
            assert resp.headers["custom-header"] == "value"
            events = ""
            for line in resp.iter_lines():
                events += line
            assert events.replace(": ping\n\n", "") == expected_events


@pytest.mark.parametrize(
    "response_class",
    [
        PlainTextResponse,
        HTMLResponse,
        JSONResponse,
        RedirectResponse,
        StreamResponse,
        FileResponse,
        SendEventResponse,
    ],
)
def test_responses_inherit(response_class):
    assert issubclass(response_class, Response)


# ######################################################################################
# #################################### Route tests #####################################
# ######################################################################################


def test_request_response():
    @request_response
    def view(request: Request) -> Response:
        return PlainTextResponse(request.body)

    with httpx.Client(app=view, base_url="http://testServer/") as client:
        assert client.get("/").text == ""
        assert client.post("/", content="hello").text == "hello"


def test_middleware():
    @middleware
    def middleware_func(
        request: Request, handler: Callable[[Request], Response]
    ) -> Response:
        response = handler(request)
        response.headers["X-Middleware"] = "1"
        return response

    @request_response
    @middleware_func
    def view(request: Request) -> Response:
        return PlainTextResponse(request.body)

    with httpx.Client(app=view, base_url="http://testServer/") as client:
        assert client.get("/").headers["X-Middleware"] == "1"


def test_router():
    @request_response
    def path(request: Request) -> Response:
        return JSONResponse(request.path_params)

    @request_response
    def redirect(request: Request) -> Response:
        return RedirectResponse("/cat")

    router = Router(
        ("/", PlainTextResponse("homepage")),
        ("/redirect", redirect),
        ("/{path}", path),
    )
    with httpx.Client(app=router, base_url="http://testServer/") as client:
        assert client.get("/").text == "homepage"
        assert client.get("/baize").json() == {"path": "baize"}
        assert client.get("/baize/").status_code == 404
        assert client.get("/redirect").headers["location"] == "/cat"


def test_subpaths():
    @request_response
    def root(request: Request) -> Response:
        return PlainTextResponse(request.get("SCRIPT_NAME", ""))

    @request_response
    def path(request: Request) -> Response:
        return PlainTextResponse(request.get("PATH_INFO", ""))

    with httpx.Client(
        app=Subpaths(
            ("/frist", root),
            ("/latest", path),
        ),
        base_url="http://testServer/",
    ) as client:
        assert client.get("/").status_code == 404
        assert client.get("/frist").text == "/frist"
        assert client.get("/latest").text == ""

    with httpx.Client(
        app=Subpaths(
            ("", path),
            ("/root", root),
        ),
        base_url="http://testServer/",
    ) as client:
        assert client.get("/").text == "/"
        assert client.get("/root/").text == "/root/"


def test_hosts():
    with httpx.Client(
        app=Hosts(
            ("testServer", PlainTextResponse("testServer")),
            (".*", PlainTextResponse("default host")),
        ),
        base_url="http://testServer/",
    ) as client:
        assert client.get("/", headers={"host": "testServer"}).text == "testServer"
        assert client.get("/", headers={"host": "hhhhhhh"}).text == "default host"
        assert client.get("/", headers={"host": "qwe\ndsf"}).text == "Invalid host"


@pytest.mark.parametrize(
    "app",
    [
        Files(Path(__file__).absolute().parent.parent / "baize"),
        Files(".", "baize"),
        Files(".", "baize", handle_404=PlainTextResponse("", 404)),
    ],
)
def test_files(app):
    with httpx.Client(app=app, base_url="http://testServer/") as client:
        resp = client.get("/py.typed")
        assert resp.text == ""

        assert (
            client.get("/py.typed", headers={"if-none-match": resp.headers["etag"]})
        ).status_code == 304

        assert (
            client.get(
                "/py.typed", headers={"if-none-match": "W/" + resp.headers["etag"]}
            )
        ).status_code == 304

        assert (
            client.get("/py.typed", headers={"if-none-match": "*"})
        ).status_code == 304

        assert (
            client.get(
                "/py.typed",
                headers={"if-modified-since": resp.headers["last-modified"]},
            )
        ).status_code == 304

        assert (
            client.get(
                "/py.typed",
                headers={
                    "if-modified-since": resp.headers["last-modified"],
                    "if-none-match": resp.headers["etag"],
                },
            )
        ).status_code == 304

        if app.handle_404 is None:

            with pytest.raises(HTTPException):
                client.get("/")

            with pytest.raises(HTTPException):
                client.get("/%2E%2E/baize/%2E%2E/%2E%2E/README.md")

        else:
            assert client.get("/").status_code == 404


def test_pages(tmpdir):
    (tmpdir / "index.html").write_text(
        "<html><body>index</body></html>", encoding="utf8"
    )
    (tmpdir / "dir").mkdir()
    (tmpdir / "dir" / "index.html").write_text(
        "<html><body>dir index</body></html>", encoding="utf8"
    )

    app = Pages(tmpdir)
    with httpx.Client(app=app, base_url="http://testServer/") as client:
        resp = client.get("/")
        assert resp.status_code == 200
        assert resp.text == "<html><body>index</body></html>"

        resp = client.get("/")
        assert resp.status_code == 200
        assert resp.text == "<html><body>index</body></html>"

        assert (
            client.get(
                "/", headers={"if-modified-since": resp.headers["last-modified"]}
            )
        ).status_code == 304

        assert (
            client.get("/", headers={"if-none-match": resp.headers["etag"]})
        ).status_code == 304

        assert (
            client.get(
                "/",
                headers={
                    "if-modified-since": resp.headers["last-modified"],
                    "if-none-match": resp.headers["etag"],
                },
            )
        ).status_code == 304

        resp = client.get("/dir")
        assert resp.status_code == 307
        assert resp.headers["location"] == "//testserver/dir/"

        with pytest.raises(HTTPException):
            client.get("/d")

    app = Pages(tmpdir, handle_404=PlainTextResponse("", 404))
    with httpx.Client(app=app, base_url="http://testServer/") as client:
        assert client.get("/d").status_code == 404
