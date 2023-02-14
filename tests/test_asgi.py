import asyncio
import tempfile
from functools import partial
from inspect import cleandoc
from pathlib import Path
from typing import AsyncGenerator, Awaitable, Callable, Type

import httpx
import pytest
import starlette.testclient
from starlette.testclient import TestClient

from baize.asgi import (
    ClientDisconnect,
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
    WebSocket,
    WebSocketDisconnect,
    middleware,
    request_response,
    websocket_session,
)
from baize.datastructures import UploadFile
from baize.exceptions import (
    HTTPException,
    MalformedJSON,
    MalformedMultipart,
    UnsupportedMediaType,
)
from baize.typing import Message, ServerSentEvent

starlette.testclient.WebSocketDisconnect = WebSocketDisconnect  # type: ignore


def test_request_scope_interface():
    """
    A Request can be instantiated with a scope, and presents a `Mapping`
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

    async def mock_receive() -> Message:
        return {}

    assert request != Request(
        {"type": "http", "method": "GET", "path": "/abc/"}, mock_receive
    )
    assert request != dict({"type": "http", "method": "GET", "path": "/abc/"})


@pytest.mark.asyncio
async def test_request_url():
    async def app(scope, receive, send):
        request = Request(scope, receive)
        data = {"method": request.method, "url": str(request.url)}
        response = JSONResponse(data)
        await response(scope, receive, send)

    async with httpx.AsyncClient(app=app, base_url="http://testServer/") as client:
        response = await client.get("/123?a=abc")
        assert response.json() == {
            "method": "GET",
            "url": "http://testserver/123?a=abc",
        }

        response = await client.get("https://example.org:123/")
        assert response.json() == {"method": "GET", "url": "https://example.org:123/"}


@pytest.mark.asyncio
async def test_request_query_params():
    async def app(scope, receive, send):
        request = Request(scope, receive)
        params = dict(request.query_params)
        response = JSONResponse({"params": params})
        await response(scope, receive, send)

    async with httpx.AsyncClient(app=app, base_url="http://testServer/") as client:
        response = await client.get("/?a=123&b=456")
        assert response.json() == {"params": {"a": "123", "b": "456"}}


@pytest.mark.asyncio
async def test_request_headers():
    async def app(scope, receive, send):
        request = Request(scope, receive)
        headers = dict(request.headers)
        headers.pop("user-agent")  # this is httpx version, delete it
        response = JSONResponse({"headers": headers})
        await response(scope, receive, send)

    async with httpx.AsyncClient(app=app, base_url="http://testServer/") as client:
        response = await client.get("/", headers={"host": "example.org"})
        assert response.json() == {
            "headers": {
                "host": "example.org",
                "accept-encoding": "gzip, deflate",
                "accept": "*/*",
                "connection": "keep-alive",
            }
        }


@pytest.mark.asyncio
async def test_request_client():
    async def app(scope, receive, send):
        request = Request(scope, receive)
        response = JSONResponse(
            {"host": request.client.host, "port": request.client.port}
        )
        await response(scope, receive, send)

    async with httpx.AsyncClient(app=app, base_url="http://testServer/") as client:
        response = await client.get("/")
        assert response.json() == {"host": "127.0.0.1", "port": 123}


@pytest.mark.asyncio
async def test_request_body():
    async def app(scope, receive, send):
        request = Request(scope, receive)
        body = await request.body
        response = JSONResponse({"body": body.decode()})
        await response(scope, receive, send)

    async with httpx.AsyncClient(app=app, base_url="http://testServer/") as client:
        response = await client.get("/")
        assert response.json() == {"body": ""}

        response = await client.post("/", json={"a": "123"})
        assert response.json() == {"body": '{"a": "123"}'}

        response = await client.post("/", content="abc")
        assert response.json() == {"body": "abc"}


@pytest.mark.asyncio
async def test_request_stream():
    async def app(scope, receive, send):
        request = Request(scope, receive)
        body = b""
        async for chunk in request.stream():
            body += chunk
        response = JSONResponse({"body": body.decode()})
        await response(scope, receive, send)

    async with httpx.AsyncClient(app=app, base_url="http://testServer/") as client:
        response = await client.get("/")
        assert response.json() == {"body": ""}

        response = await client.post("/", json={"a": "123"})
        assert response.json() == {"body": '{"a": "123"}'}

        response = await client.post("/", content="abc")
        assert response.json() == {"body": "abc"}


@pytest.mark.asyncio
async def test_request_form_urlencoded():
    async def app(scope, receive, send):
        request = Request(scope, receive)
        form = await request.form
        response = JSONResponse({"form": dict(form)})
        await response(scope, receive, send)
        await request.close()

    async with httpx.AsyncClient(app=app, base_url="http://testServer/") as client:
        response = await client.post("/", data={"abc": "123 @"})
        assert response.json() == {"form": {"abc": "123 @"}}

        with pytest.raises(UnsupportedMediaType):
            response = await client.post(
                "/", data={"abc": "123 @"}, headers={"content-type": "application/json"}
            )


@pytest.mark.asyncio
async def test_request_multipart_form():
    async def app(scope, receive, send):
        request = Request(scope, receive)
        form = await request.form
        file = form["file-key"]
        assert isinstance(file, UploadFile)
        assert await file.aread() == b"temporary file"
        response = JSONResponse({"file": file.filename})
        await response(scope, receive, send)
        await request.close()

    async with httpx.AsyncClient(app=app, base_url="http://testServer/") as client:
        with tempfile.SpooledTemporaryFile(1024) as file:
            file.write(b"temporary file")
            file.seek(0, 0)
            response = await client.post(
                "/", data={"abc": "123 @"}, files={"file-key": file}
            )
            assert response.json() == {"file": "None"}

        with pytest.raises(MalformedMultipart):
            response = await client.post(
                "/", content=b"xxxx", headers={"content-type": "multipart/form-data"}
            )


@pytest.mark.asyncio
async def test_request_body_then_stream():
    async def app(scope, receive, send):
        request = Request(scope, receive)
        body = await request.body
        chunks = b""
        async for chunk in request.stream():
            chunks += chunk
        response = JSONResponse({"body": body.decode(), "stream": chunks.decode()})
        await response(scope, receive, send)

    async with httpx.AsyncClient(app=app, base_url="http://testServer/") as client:
        response = await client.post("/", content="abc")
        assert response.json() == {"body": "abc", "stream": "abc"}


@pytest.mark.asyncio
async def test_request_stream_then_body():
    async def app(scope, receive, send):
        request = Request(scope, receive)
        chunks = b""
        async for chunk in request.stream():
            chunks += chunk
        try:
            body = await request.body
        except RuntimeError:
            body = b"<stream consumed>"
        response = JSONResponse({"body": body.decode(), "stream": chunks.decode()})
        await response(scope, receive, send)

    async with httpx.AsyncClient(app=app, base_url="http://testServer/") as client:
        response = await client.post("/", content="abc")
        assert response.json() == {"body": "<stream consumed>", "stream": "abc"}


@pytest.mark.asyncio
async def test_request_json():
    async def app(scope, receive, send):
        request = Request(scope, receive)
        data = await request.json
        response = JSONResponse({"json": data})
        await response(scope, receive, send)

    async with httpx.AsyncClient(app=app, base_url="http://testServer/") as client:
        response = await client.post("/", json={"a": "123"})
        assert response.json() == {"json": {"a": "123"}}

        with pytest.raises(UnsupportedMediaType):
            response = await client.post(
                "/",
                data={"abc": "123 @"},
                headers={"content-type": "application/x-www-form-urlencoded"},
            )

        with pytest.raises(MalformedJSON):
            response = await client.post(
                "/", content=b"abc", headers={"content-type": "application/json"}
            )


@pytest.mark.asyncio
async def test_request_without_setting_receive():
    """
    If Request is instantiated without the receive channel, then .body()
    is not available.
    """

    async def app(scope, receive, send):
        request = Request(scope)
        try:
            data = await request.json
        except NotImplementedError:
            data = "Receive channel not available"
        response = JSONResponse({"json": data})
        await response(scope, receive, send)

    async with httpx.AsyncClient(app=app, base_url="http://testServer/") as client:
        response = await client.post("/", json={"a": "123"})
        assert response.json() == {"json": "Receive channel not available"}


@pytest.mark.asyncio
async def test_request_disconnect():
    """
    If a client disconnect occurs while reading request body
    then ClientDisconnect should be raised.
    """

    async def app(scope, receive, send):
        request = Request(scope, receive)
        await request.body

    async def receiver():
        return {"type": "http.disconnect"}

    scope = {"type": "http", "method": "POST", "path": "/"}
    with pytest.raises(ClientDisconnect):
        await app(scope, receiver, None)


@pytest.mark.asyncio
async def test_request_is_disconnected():
    """
    If a client disconnect occurs while reading request body
    then ClientDisconnect should be raised.
    """
    disconnected_after_response = None

    async def app(scope, receive, send):
        nonlocal disconnected_after_response

        request = Request(scope, receive)
        await request.body
        disconnected = await request.is_disconnected()
        response = JSONResponse({"disconnected": disconnected})
        await response(scope, receive, send)
        disconnected_after_response = await request.is_disconnected()

    async with httpx.AsyncClient(app=app, base_url="http://testServer/") as client:
        response = await client.get("/")
        assert response.json() == {"disconnected": False}
        assert disconnected_after_response


@pytest.mark.asyncio
async def test_request_cookies():
    async def app(scope, receive, send):
        request = Request(scope, receive)
        mycookie = request.cookies.get("mycookie")
        if mycookie:
            response = PlainTextResponse(mycookie)
        else:
            response = PlainTextResponse("Hello, world!")
            response.set_cookie("mycookie", "Hello, cookies!")

        await response(scope, receive, send)

    async with httpx.AsyncClient(app=app, base_url="http://testServer/") as client:
        response = await client.get("/")
        assert response.text == "Hello, world!"
        response = await client.get("/")
        assert response.text == "Hello, cookies!"


@pytest.mark.asyncio
async def test_cookie_lenient_parsing():
    """
    The following test is based on a cookie set by Okta, a well-known authorization
    service. It turns out that it's common practice to set cookies that would be
    invalid according to the spec.
    """
    tough_cookie = (
        "provider-oauth-nonce=validAsciiblabla; "
        'okta-oauth-redirect-params={"responseType":"code","state":"somestate",'
        '"nonce":"somenonce","scopes":["openid","profile","email","phone"],'
        '"urls":{"issuer":"https://subdomain.okta.com/oauth2/authServer",'
        '"authorizeUrl":"https://subdomain.okta.com/oauth2/authServer/v1/authorize",'
        '"userinfoUrl":"https://subdomain.okta.com/oauth2/authServer/v1/userinfo"}}; '
        "importantCookie=importantValue; sessionCookie=importantSessionValue"
    )
    expected_keys = {
        "importantCookie",
        "okta-oauth-redirect-params",
        "provider-oauth-nonce",
        "sessionCookie",
    }

    async def app(scope, receive, send):
        request = Request(scope, receive)
        response = JSONResponse({"cookies": request.cookies})
        await response(scope, receive, send)

    async with httpx.AsyncClient(app=app, base_url="http://testServer/") as client:
        response = await client.get("/", headers={"cookie": tough_cookie})
        result = response.json()
        assert len(result["cookies"]) == 4
        assert set(result["cookies"].keys()) == expected_keys


# These test cases copied from Tornado's implementation
@pytest.mark.parametrize(
    "set_cookie,expected",
    [
        ("chips=ahoy; vienna=finger", {"chips": "ahoy", "vienna": "finger"}),
        # all semicolons are delimiters, even within quotes
        (
            'keebler="E=mc2; L=\\"Loves\\"; fudge=\\012;"',
            {"keebler": '"E=mc2', "L": '\\"Loves\\"', "fudge": "\\012", "": '"'},
        ),
        # Illegal cookies that have an '=' char in an unquoted value.
        ("keebler=E=mc2", {"keebler": "E=mc2"}),
        # Cookies with ':' character in their name.
        ("key:term=value:term", {"key:term": "value:term"}),
        # Cookies with '[' and ']'.
        ("a=b; c=[; d=r; f=h", {"a": "b", "c": "[", "d": "r", "f": "h"}),
        # Cookies that RFC6265 allows.
        ("a=b; Domain=example.com", {"a": "b", "Domain": "example.com"}),
        # parse_cookie() keeps only the last cookie with the same name.
        ("a=b; h=i; a=c", {"a": "c", "h": "i"}),
    ],
)
@pytest.mark.asyncio
async def test_cookies_edge_cases(set_cookie, expected):
    async def app(scope, receive, send):
        request = Request(scope, receive)
        response = JSONResponse({"cookies": request.cookies})
        await response(scope, receive, send)

    async with httpx.AsyncClient(app=app, base_url="http://testServer/") as client:
        response = await client.get("/", headers={"cookie": set_cookie})
        result = response.json()
        assert result["cookies"] == expected


@pytest.mark.parametrize(
    "set_cookie,expected",
    [
        # Chunks without an equals sign appear as unnamed values per
        # https://bugzilla.mozilla.org/show_bug.cgi?id=169091
        (
            "abc=def; unnamed; django_language=en",
            {"": "unnamed", "abc": "def", "django_language": "en"},
        ),
        # Even a double quote may be an unamed value.
        ('a=b; "; c=d', {"a": "b", "": '"', "c": "d"}),
        # Spaces in names and values, and an equals sign in values.
        ("a b c=d e = f; gh=i", {"a b c": "d e = f", "gh": "i"}),
        # More characters the spec forbids.
        ('a   b,c<>@:/[]?{}=d  "  =e,f g', {"a   b,c<>@:/[]?{}": 'd  "  =e,f g'}),
        # Unicode characters. The spec only allows ASCII.
        # ("saint=André Bessette", {"saint": "André Bessette"}),
        # Browsers don't send extra whitespace or semicolons in Cookie headers,
        # but cookie_parser() should parse whitespace the same way
        # document.cookie parses whitespace.
        # ("  =  b  ;  ;  =  ;   c  =  ;  ", {"": "b", "c": ""}),
    ],
)
@pytest.mark.asyncio
async def test_cookies_invalid(set_cookie, expected):
    """
    Cookie strings that are against the RFC6265 spec but which browsers will send if set
    via document.cookie.
    """

    async def app(scope, receive, send):
        request = Request(scope, receive)
        response = JSONResponse({"cookies": request.cookies})
        await response(scope, receive, send)

    async with httpx.AsyncClient(app=app, base_url="http://testServer/") as client:
        response = await client.get("/", headers={"cookie": set_cookie})
        result = response.json()
        assert result["cookies"] == expected


# ######################################################################################
# ################################# Responses tests ####################################
# ######################################################################################


@pytest.mark.asyncio
async def test_response_headers():
    async def app(scope, receive, send):
        headers = {"x-header-1": "123", "x-header-2": "456"}
        response = PlainTextResponse("hello, world", headers=headers)
        response.headers["x-header-2"] = "789"
        await response(scope, receive, send)

    async with httpx.AsyncClient(app=app, base_url="http://testServer/") as client:
        response = await client.get("/")
        assert response.headers["x-header-1"] == "123"
        assert response.headers["x-header-2"] == "789"


@pytest.mark.asyncio
async def test_set_cookie():
    response = PlainTextResponse("Hello, world!", media_type="text/plain")
    response.set_cookie(
        "mycookie",
        "myvalue",
        max_age=10,
        expires=10,
        path="/",
        domain="localhost",
        secure=True,
        httponly=True,
        samesite="none",
    )

    async with httpx.AsyncClient(app=response, base_url="http://testServer/") as client:
        response = await client.get("/")
        assert response.text == "Hello, world!"


@pytest.mark.asyncio
async def test_delete_cookie():
    async def app(scope, receive, send):
        request = Request(scope, receive)
        response = PlainTextResponse("Hello, world!", media_type="text/plain")
        if request.cookies.get("mycookie"):
            response.delete_cookie("mycookie")
        else:
            response.set_cookie("mycookie", "myvalue")
        await response(scope, receive, send)

    async with httpx.AsyncClient(app=app, base_url="http://testServer/") as client:
        response = await client.get("/")
        assert response.cookies["mycookie"]
        response = await client.get("/")
        assert not response.cookies.get("mycookie")


@pytest.mark.asyncio
async def test_redirect_response():
    async def app(scope, receive, send):
        if scope["path"] == "/":
            response = PlainTextResponse("hello, world")
        else:
            response = RedirectResponse("/")
        await response(scope, receive, send)

    async with httpx.AsyncClient(app=app, base_url="http://testServer/") as client:
        response = await client.get("/redirect", follow_redirects=True)
        assert response.text == "hello, world"
        assert response.url == "http://testserver/"


@pytest.mark.asyncio
async def test_stream_response():
    async def generator(num: int) -> AsyncGenerator[bytes, None]:
        for i in range(num):
            yield str(i).encode("utf-8")

    async with httpx.AsyncClient(
        app=StreamResponse(generator(10)), base_url="http://testServer/"
    ) as client:
        response = await client.get("/")
        assert response.content == b"".join(str(i).encode("utf-8") for i in range(10))


README = """\
# BáiZé

Powerful and exquisite WSGI/ASGI framework/toolkit.

The minimize implementation of methods required in the Web framework. No redundant implementation means that you can freely customize functions without considering the conflict with baize's own implementation.

Under the ASGI/WSGI protocol, the interface of the request object and the response object is almost the same, only need to add or delete `await` in the appropriate place. In addition, it should be noted that ASGI supports WebSocket but WSGI does not.
"""


@pytest.mark.parametrize(
    "response_class",
    [
        FileResponse,
        partial(FileResponse, chunk_size=1),
        partial(FileResponse, chunk_size=len(README.encode("utf8"))),
    ],
)
@pytest.mark.asyncio
async def test_file_response(tmp_path: Path, response_class: Type[FileResponse]):
    filepath = tmp_path / "README.txt"
    filepath.write_bytes(README.encode("utf8"))

    async def app(scope, r, s):
        return await response_class(str(filepath))(scope, r, s)

    async with httpx.AsyncClient(app=app, base_url="http://testServer/") as client:
        response = await client.get("/")
        assert response.status_code == 200
        assert response.headers["content-length"] == str(len(README.encode("utf8")))
        assert response.text == README

        response = await client.head("/")
        assert response.status_code == 200
        assert response.headers["content-length"] == str(len(README.encode("utf8")))
        assert response.content == b""

        response = await client.get("/", headers={"Range": "bytes=0-100"})
        assert response.status_code == 206
        assert response.headers["content-length"] == str(101)
        assert response.content == README.encode("utf8")[:101]

        response = await client.head("/", headers={"Range": "bytes=0-100"})
        assert response.status_code == 206
        assert response.headers["content-length"] == str(101)
        assert response.content == b""

        response = await client.get("/", headers={"Range": "bytes=0-100, 200-300"})
        assert response.status_code == 206
        assert response.headers["content-length"] == str(370)

        response = await client.head("/", headers={"Range": "bytes=0-100, 200-300"})
        assert response.status_code == 206
        assert response.headers["content-length"] == str(370)
        assert response.content == b""

        response = await client.head(
            "/",
            headers={
                "Range": "bytes=200-300",
                "if-range": response.headers["etag"][:-1],
            },
        )
        assert response.status_code == 200
        response = await client.head(
            "/",
            headers={
                "Range": "bytes=200-300",
                "if-range": response.headers["etag"],
            },
        )
        assert response.status_code == 206

        response = await client.head("/", headers={"Range": "bytes: 0-1000"})
        assert response.status_code == 400

        response = await client.head(
            "/", headers={"Range": f"bytes=0-{len(README.encode('utf8'))+1}"}
        )
        assert response.status_code == 206

        response = await client.head(
            "/", headers={"Range": f"bytes={len(README.encode('utf8'))+1}-"}
        )
        assert response.status_code == 416
        assert response.headers["Content-Range"] == f"*/{len(README.encode('utf8'))}"


@pytest.mark.asyncio
async def test_file_response_with_directory(tmp_path: Path):
    with pytest.raises(IsADirectoryError):
        FileResponse(str(tmp_path))


@pytest.mark.asyncio
async def test_file_response_with_download_name(tmp_path: Path):
    filepath = tmp_path / "README"
    filepath.write_bytes(README.encode("utf8"))
    file_response = FileResponse(str(filepath), download_name="README.txt")
    async with httpx.AsyncClient(
        app=file_response, base_url="http://testServer/"
    ) as client:
        response = await client.get("/")
        assert (
            response.headers["content-disposition"]
            == "attachment; filename=\"README.txt\"; filename*=utf-8''README.txt"
        )


@pytest.mark.asyncio
async def test_send_event_response():
    async def send_events() -> AsyncGenerator[ServerSentEvent, None]:
        yield ServerSentEvent(data="hello\nworld")
        await asyncio.sleep(0.2)
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

    async with httpx.AsyncClient(
        app=SendEventResponse(send_events(), ping_interval=0.1),
        base_url="http://testServer/",
    ) as client:
        async with client.stream("GET", "/") as resp:
            resp.raise_for_status()
            events = ""
            async for line in resp.aiter_lines():
                events += line
            assert events.replace(": ping\n\n", "") == expected_events

    async with httpx.AsyncClient(
        app=SendEventResponse(
            send_events(),
            headers={"custom-header": "value"},
            ping_interval=0.1,
        ),
        base_url="http://testServer/",
    ) as client:
        async with client.stream("GET", "/") as resp:
            resp.raise_for_status()
            assert resp.headers["custom-header"] == "value"
            events = ""
            async for line in resp.aiter_lines():
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
# ################################# WebSocket tests ####################################
# ######################################################################################

# Hook websocket TestClient
starlette.testclient._is_asgi3 = lambda *args, **kwargs: True


def test_websocket_send_and_receive_text():
    @websocket_session
    async def app(websocket: WebSocket) -> None:
        await websocket.accept()
        data = await websocket.receive_text()
        await websocket.send_text("Message was: " + data)
        await websocket.close()

    client = TestClient(app)
    with client.websocket_connect("/") as websocket:
        websocket.send_text("Hello, world!")
        data = websocket.receive_text()
        assert data == "Message was: Hello, world!"


def test_websocket_send_and_receive_bytes():
    @websocket_session
    async def app(websocket: WebSocket) -> None:
        await websocket.accept()
        data = await websocket.receive_bytes()
        await websocket.send_bytes(b"Message was: " + data)
        await websocket.close()

    client = TestClient(app)
    with client.websocket_connect("/") as websocket:
        websocket.send_bytes(b"Hello, world!")
        data = websocket.receive_bytes()
        assert data == b"Message was: Hello, world!"


def test_websocket_iter_text():
    @websocket_session
    async def app(websocket: WebSocket) -> None:
        await websocket.accept()
        async for data in websocket.iter_text():
            await websocket.send_text("Message was: " + data)

    client = TestClient(app)
    with client.websocket_connect("/") as websocket:
        websocket.send_text("Hello, world!")
        data = websocket.receive_text()
        assert data == "Message was: Hello, world!"


def test_websocket_iter_bytes():
    @websocket_session
    async def app(websocket: WebSocket) -> None:
        await websocket.accept()
        async for data in websocket.iter_bytes():
            await websocket.send_bytes(b"Message was: " + data)

    client = TestClient(app)
    with client.websocket_connect("/") as websocket:
        websocket.send_bytes(b"Hello, world!")
        data = websocket.receive_bytes()
        assert data == b"Message was: Hello, world!"


def test_websocket_concurrency_pattern():
    @websocket_session
    async def app(websocket: WebSocket) -> None:
        async def reader(websocket: WebSocket, queue: "asyncio.Queue[str]") -> None:
            async for data in websocket.iter_text():
                await queue.put(data)

        async def writer(websocket: WebSocket, queue: "asyncio.Queue[str]") -> None:
            while True:
                message = await queue.get()
                await websocket.send_text(message)

        queue: "asyncio.Queue[str]" = asyncio.Queue()
        await websocket.accept()
        done, pending = await asyncio.wait(
            (
                asyncio.ensure_future(reader(websocket=websocket, queue=queue)),
                asyncio.ensure_future(writer(websocket=websocket, queue=queue)),
            ),
            return_when=asyncio.FIRST_COMPLETED,
        )
        [task.cancel() for task in pending]
        [task.result() for task in done]
        await websocket.close()

    client = TestClient(app)
    with client.websocket_connect("/") as websocket:
        websocket.send_text("hello world")
        data = websocket.receive_text()
        assert data == "hello world"


def test_client_close():
    @websocket_session
    async def app(websocket: WebSocket) -> None:
        await websocket.accept()
        try:
            await websocket.receive_text()
        except WebSocketDisconnect as exc:
            assert exc.code == 1001

    client = TestClient(app)
    with client.websocket_connect("/") as websocket:
        websocket.close(code=1001)


def test_application_close():
    async def app_close(scope, receive, send):
        websocket = WebSocket(scope, receive=receive, send=send)
        await websocket.accept()
        await websocket.close(1001)

    client = TestClient(app_close)
    with client.websocket_connect("/") as websocket:
        with pytest.raises(WebSocketDisconnect) as exc:
            websocket.receive_text()
        assert exc.value.code == 1001

    async def app_after_close(scope, receive, send):
        websocket = WebSocket(scope, receive=receive, send=send)
        await websocket.accept()
        await websocket.close()
        with pytest.raises(RuntimeError):
            await websocket.send_text("after close")

    client = TestClient(app_after_close)
    with client.websocket_connect("/") as websocket:
        with pytest.raises(WebSocketDisconnect) as exc:
            websocket.receive_text()
        assert exc.value.code == 1000


def test_rejected_connection():
    @websocket_session
    async def app(websocket: WebSocket) -> None:
        await websocket.close(1001)

    client = TestClient(app)
    with pytest.raises(WebSocketDisconnect) as exc:
        client.websocket_connect("/")
    assert exc.value.code == 1001


def test_subprotocol():
    @websocket_session
    async def app(websocket: WebSocket) -> None:
        assert websocket["subprotocols"] == ["soap", "wamp"]
        await websocket.accept(subprotocol="wamp")
        await websocket.close()

    client = TestClient(app)
    with client.websocket_connect("/", subprotocols=["soap", "wamp"]) as websocket:
        assert websocket.accepted_subprotocol == "wamp"


def test_duplicate_disconnect():
    @websocket_session
    async def app(websocket: WebSocket) -> None:
        await websocket.accept()
        message = await websocket.receive()
        assert message["type"] == "websocket.disconnect"
        message = await websocket.receive()

    client = TestClient(app)
    with pytest.raises(RuntimeError):
        with client.websocket_connect("/") as websocket:
            websocket.close()


def test_websocket_scope_interface():
    """
    A WebSocket can be instantiated with a scope, and presents a `Mapping`
    interface.
    """

    async def mock_receive() -> Message:
        return {}

    async def mock_send(message: Message) -> None:
        ...  # pragma: no cover

    websocket = WebSocket(
        {"type": "websocket", "path": "/abc/", "headers": []},
        receive=mock_receive,
        send=mock_send,
    )
    assert websocket["type"] == "websocket"
    assert dict(websocket) == {"type": "websocket", "path": "/abc/", "headers": []}
    assert len(websocket) == 3


# ######################################################################################
# #################################### Route tests #####################################
# ######################################################################################


@pytest.mark.asyncio
async def test_request_response():
    @request_response
    async def view(request: Request) -> Response:
        return PlainTextResponse(await request.body)

    async with httpx.AsyncClient(app=view, base_url="http://testServer/") as client:
        assert (await client.get("/")).text == ""
        assert (await client.post("/", content="hello")).text == "hello"

    client = TestClient(view)
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/"):
            pass
    assert exc.value.code == 1000


@pytest.mark.asyncio
async def test_websocket_session():
    @websocket_session
    async def view(websocket: WebSocket) -> None:
        await websocket.accept()
        await websocket.close()

    async with httpx.AsyncClient(app=view, base_url="http://testServer/") as client:
        assert (await client.get("/")).status_code == 404


@pytest.mark.asyncio
async def test_middleware():
    @middleware
    async def middleware_func(
        request: Request, handler: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await handler(request)
        response.headers["X-Middleware"] = "1"
        return response

    @request_response
    @middleware_func
    async def view(request: Request) -> Response:
        return PlainTextResponse(await request.body)

    async with httpx.AsyncClient(app=view, base_url="http://testServer/") as client:
        assert (await client.get("/")).headers["X-Middleware"] == "1"


@pytest.mark.asyncio
async def test_router():
    @request_response
    async def path(request: Request) -> Response:
        return JSONResponse(request.path_params)

    @request_response
    async def redirect(request: Request) -> Response:
        return RedirectResponse("/cat")

    router = Router(
        ("/", PlainTextResponse("homepage")),
        ("/redirect", redirect),
        ("/{path}", path),
    )
    async with httpx.AsyncClient(app=router, base_url="http://testServer/") as client:
        assert (await client.get("/")).text == "homepage"
        assert (await client.get("/baize")).json() == {"path": "baize"}
        assert (await client.get("/baize/")).status_code == 404
        assert (await (client.get("/redirect"))).headers["location"] == "/cat"


@pytest.mark.asyncio
async def test_subpaths():
    @request_response
    async def root(request: Request) -> Response:
        return PlainTextResponse(request.get("root_path", ""))

    @request_response
    async def path(request: Request) -> Response:
        return PlainTextResponse(request["path"])

    async with httpx.AsyncClient(
        app=Subpaths(
            ("/frist", root),
            ("/latest", path),
        ),
        base_url="http://testServer/",
    ) as client:
        assert (await client.get("/")).status_code == 404
        assert (await client.get("/frist")).text == "/frist"
        assert (await client.get("/latest")).text == ""

    async with httpx.AsyncClient(
        app=Subpaths(
            ("", path),
            ("/root", root),
        ),
        base_url="http://testServer/",
    ) as client:
        assert (await client.get("/")).text == "/"
        assert (await client.get("/root/")).text == "/root/"


@pytest.mark.asyncio
async def test_hosts():
    async with httpx.AsyncClient(
        app=Hosts(
            ("testServer", PlainTextResponse("testServer")),
            (".*", PlainTextResponse("default host")),
        ),
        base_url="http://testServer/",
    ) as client:
        assert (
            await client.get("/", headers={"host": "testServer"})
        ).text == "testServer"
        assert (
            await client.get("/", headers={"host": "hhhhhhh"})
        ).text == "default host"
        assert (
            await client.get("/", headers={"host": "qwe\ndsf"})
        ).text == "Invalid host"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "app",
    [
        Files(Path(__file__).absolute().parent.parent / "baize"),
        Files(".", "baize"),
        Files(".", "baize", handle_404=PlainTextResponse("", 404)),
    ],
)
async def test_files(app):
    async with httpx.AsyncClient(app=app, base_url="http://testServer/") as client:
        resp = await client.get("/py.typed")
        assert resp.text == ""

        assert (
            await client.get(
                "/py.typed", headers={"if-none-match": resp.headers["etag"]}
            )
        ).status_code == 304

        assert (
            await client.get(
                "/py.typed", headers={"if-none-match": "W/" + resp.headers["etag"]}
            )
        ).status_code == 304

        assert (
            await client.get("/py.typed", headers={"if-none-match": "*"})
        ).status_code == 304

        assert (
            await client.get(
                "/py.typed",
                headers={"if-modified-since": resp.headers["last-modified"]},
            )
        ).status_code == 304

        assert (
            await client.get(
                "/py.typed",
                headers={
                    "if-modified-since": resp.headers["last-modified"],
                    "if-none-match": resp.headers["etag"],
                },
            )
        ).status_code == 304

        if app.handle_404 is None:

            with pytest.raises(HTTPException):
                await client.get("/")

            with pytest.raises(HTTPException):
                await client.get("/%2E%2E/baize/%2E%2E/%2E%2E/README.md")

        else:
            assert (await client.get("/")).status_code == 404


@pytest.mark.asyncio
async def test_pages(tmpdir):
    (tmpdir / "index.html").write_text(
        "<html><body>index</body></html>", encoding="utf8"
    )
    (tmpdir / "dir").mkdir()
    (tmpdir / "dir" / "index.html").write_text(
        "<html><body>dir index</body></html>", encoding="utf8"
    )

    app = Pages(tmpdir)
    async with httpx.AsyncClient(app=app, base_url="http://testServer/") as client:
        resp = await client.get("/")
        assert resp.status_code == 200
        assert resp.text == "<html><body>index</body></html>"

        resp = await client.get("/index")
        assert resp.status_code == 200
        assert resp.text == "<html><body>index</body></html>"

        assert (
            await client.get(
                "/", headers={"if-modified-since": resp.headers["last-modified"]}
            )
        ).status_code == 304

        assert (
            await client.get("/", headers={"if-none-match": resp.headers["etag"]})
        ).status_code == 304

        assert (
            await client.get(
                "/",
                headers={
                    "if-modified-since": resp.headers["last-modified"],
                    "if-none-match": resp.headers["etag"],
                },
            )
        ).status_code == 304

        resp = await client.get("/dir")
        assert resp.status_code == 307
        assert resp.headers["location"] == "//testserver/dir/"

        with pytest.raises(HTTPException):
            await client.get("/d")

    app = Pages(tmpdir, handle_404=PlainTextResponse("", 404))
    async with httpx.AsyncClient(app=app, base_url="http://testServer/") as client:
        assert (await client.get("/d")).status_code == 404
