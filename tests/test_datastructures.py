import io

import pytest

from baize.datastructures import (
    URL,
    ContentType,
    FormData,
    Headers,
    MediaType,
    MultiDict,
    MutableHeaders,
    QueryParams,
    UploadFile,
)


def test_url():
    u = URL("https://example.org:123/path/to/somewhere?abc=123#anchor")
    assert u.scheme == "https"
    assert u.hostname == "example.org"
    assert u.port == 123
    assert u.netloc == "example.org:123"
    assert u.username is None
    assert u.password is None
    assert u.path == "/path/to/somewhere"
    assert u.query == "abc=123"
    assert u.fragment == "anchor"

    new = u.replace(scheme="http")
    assert new == "http://example.org:123/path/to/somewhere?abc=123#anchor"
    assert new.scheme == "http"

    new = u.replace(port=None)
    assert new == "https://example.org/path/to/somewhere?abc=123#anchor"
    assert new.port is None

    new = u.replace(hostname="example.com")
    assert new == "https://example.com:123/path/to/somewhere?abc=123#anchor"
    assert new.hostname == "example.com"

    new = URL(**u.components._asdict())
    assert new == u


def test_url_query_params():
    u = URL("https://example.org/path/?page=3")
    assert u.query == "page=3"
    u = u.include_query_params(page=4)
    assert str(u) == "https://example.org/path/?page=4"
    u = u.include_query_params(search="testing")
    assert str(u) == "https://example.org/path/?page=4&search=testing"
    u = u.replace_query_params(order="name")
    assert str(u) == "https://example.org/path/?order=name"
    u = u.remove_query_params("order")
    assert str(u) == "https://example.org/path/"


def test_hidden_password():
    u = URL("https://example.org/path/to/somewhere")
    assert repr(u) == "URL('https://example.org/path/to/somewhere')"

    u = URL("https://username@example.org/path/to/somewhere")
    assert repr(u) == "URL('https://username@example.org/path/to/somewhere')"

    u = URL("https://username:password@example.org/path/to/somewhere")
    assert repr(u) == "URL('https://username:********@example.org/path/to/somewhere')"


def test_url_from_scope():
    u = URL(
        scope={"path": "/path/to/somewhere", "query_string": b"abc=123", "headers": []}
    )
    assert u == "/path/to/somewhere?abc=123"
    assert repr(u) == "URL('/path/to/somewhere?abc=123')"

    u = URL(
        scope={
            "scheme": "https",
            "server": ("example.org", 123),
            "path": "/path/to/somewhere",
            "query_string": b"abc=123",
            "headers": [],
        }
    )
    assert u == "https://example.org:123/path/to/somewhere?abc=123"
    assert repr(u) == "URL('https://example.org:123/path/to/somewhere?abc=123')"

    u = URL(
        scope={
            "scheme": "https",
            "server": ("example.org", 443),
            "path": "/path/to/somewhere",
            "query_string": b"abc=123",
            "headers": [],
        }
    )
    assert u == "https://example.org/path/to/somewhere?abc=123"
    assert repr(u) == "URL('https://example.org/path/to/somewhere?abc=123')"

    u = URL(
        scope={
            "scheme": "https",
            "server": ("127.0.0.1", 80),
            "path": "/path/to/somewhere",
            "query_string": b"abc=123",
            "headers": [(b"host", b"example.org")],
        }
    )
    assert u == "https://example.org/path/to/somewhere?abc=123"
    assert repr(u) == "URL('https://example.org/path/to/somewhere?abc=123')"


def test_url_from_environ():
    u = URL(
        environ={
            "wsgi.url_scheme": "http",
            "SERVER_NAME": "127.0.0.1",
            "SERVER_PORT": "80",
            "PATH_INFO": "/path/to/somewhere",
            "QUERY_STRING": "abc=123",
        }
    )
    assert u == "http://127.0.0.1:80/path/to/somewhere?abc=123"
    assert repr(u) == "URL('http://127.0.0.1:80/path/to/somewhere?abc=123')"


def test_content_type():
    content_type = ContentType("application/json; charset=utf-8")
    assert content_type == "application/json"
    assert not content_type == 0
    assert content_type in ("application/json", "")
    assert content_type.options == {"charset": "utf-8"}
    assert str(content_type) == "application/json; charset=utf-8"
    assert repr(content_type) == "<ContentType: application/json; charset=utf-8>"


def test_media_type():
    assert MediaType("text/html").match("text/html")
    assert not MediaType("text/html").match("text/plain")
    assert MediaType("text/*").match("text/html")
    assert MediaType("*/*").is_all_types
    assert MediaType("*/*").match("text/html")
    assert str(MediaType("text/html")) == "text/html"
    assert str(MediaType("text")) == "text"
    assert repr(MediaType("text/html")) == "<MediaType: text/html>"


def test_headers():
    h = Headers(raw=[("a", "123"), ("a", "456"), ("b", "789")])
    assert "a" in h
    assert "A" in h
    assert "b" in h
    assert "B" in h
    assert "c" not in h
    assert h["a"] == "123"
    assert h.get("a") == "123"
    assert h.get("nope", default=None) is None
    assert h.getlist("a") == ["123", "456"]
    assert h.keys() == ["a", "a", "b"]
    assert h.values() == ["123", "456", "789"]
    assert h.items() == [("a", "123"), ("a", "456"), ("b", "789")]
    assert list(h) == ["a", "a", "b"]
    assert dict(h) == {"a": "123", "b": "789"}
    assert repr(h) == "Headers(raw=[('a', '123'), ('a', '456'), ('b', '789')])"
    assert h == Headers(raw=[("a", "123"), ("b", "789"), ("a", "456")])
    assert h != [("a", "123"), ("A", "456"), ("b", "789")]

    h = Headers({"a": "123", "b": "789"})
    assert h["A"] == "123"
    assert h["B"] == "789"
    assert repr(h) == "Headers({'a': '123', 'b': '789'})"


def test_mutable_headers():
    h = MutableHeaders()
    assert dict(h) == {}
    h["a"] = "1"
    assert dict(h) == {"a": "1"}
    h["a"] = "2"
    assert dict(h) == {"a": "2"}
    h.setdefault("a", "3")
    assert dict(h) == {"a": "2"}
    h.setdefault("b", "4")
    assert dict(h) == {"a": "2", "b": "4"}
    del h["a"]
    assert dict(h) == {"b": "4"}
    h.update({"a": "0"})
    assert dict(h) == {"a": "0", "b": "4"}
    h.append("c", "8")
    assert dict(h) == {"a": "0", "b": "4", "c": "8"}
    h.add_vary_header("vary")
    assert dict(h) == {"vary": "vary", "a": "0", "b": "4", "c": "8"}
    h.add_vary_header("vary2")
    assert dict(h) == {"vary": "vary, vary2", "a": "0", "b": "4", "c": "8"}


def test_headers_mutablecopy():
    h = Headers(raw=[("a", "123"), ("a", "456"), ("b", "789")])
    c = h.mutablecopy()
    assert c.items() == [("a", "123"), ("a", "456"), ("b", "789")]
    c["a"] = "abc"
    assert c.items() == [("a", "abc"), ("b", "789")]


def test_url_blank_params():
    q = QueryParams("a=123&abc&def&b=456")
    assert "a" in q
    assert "abc" in q
    assert "def" in q
    assert "b" in q
    assert len(q.get("abc")) == 0
    assert len(q["a"]) == 3
    assert list(q.keys()) == ["a", "abc", "def", "b"]


def test_queryparams():
    q = QueryParams("a=123&a=456&b=789")
    assert "a" in q
    assert "A" not in q
    assert "c" not in q
    assert q["a"] == "456"
    assert q.get("a") == "456"
    assert q.get("nope", default=None) is None
    assert q.getlist("a") == ["123", "456"]
    assert list(q.keys()) == ["a", "b"]
    assert list(q.values()) == ["456", "789"]
    assert list(q.items()) == [("a", "456"), ("b", "789")]
    assert len(q) == 2
    assert list(q) == ["a", "b"]
    assert dict(q) == {"a": "456", "b": "789"}
    assert str(q) == "a=123&a=456&b=789"
    assert repr(q) == "QueryParams('a=123&a=456&b=789')"
    assert QueryParams({"a": "123", "b": "456"}) == QueryParams(
        [("a", "123"), ("b", "456")]
    )
    assert QueryParams({"a": "123", "b": "456"}) == QueryParams("a=123&b=456")
    assert QueryParams({"a": "123", "b": "456"}) == QueryParams(
        {"b": "456", "a": "123"}
    )
    assert QueryParams() == QueryParams({})
    assert QueryParams([("a", "123"), ("a", "456")]) == QueryParams("a=123&a=456")
    assert QueryParams({"a": "123", "b": "456"}) != "invalid"

    q = QueryParams([("a", "123"), ("a", "456")])
    assert QueryParams(q) == q


def test_sync_upload_file():
    file = UploadFile("file")
    file.write(b"data" * 512)
    file.write(b"data")
    file.seek(0)
    assert file.read(4 * 128) == b"data" * 128
    file.close()


@pytest.mark.asyncio
async def test_async_upload_file():
    file = UploadFile("file")
    await file.awrite(b"data" * 512)
    await file.awrite(b"data")
    await file.aseek(0)
    assert await file.aread(4 * 128) == b"data" * 128
    await file.aclose()


@pytest.mark.asyncio
async def test_async_big_upload_file():
    class BigUploadFile(UploadFile):
        spool_max_size = 1024

    big_file = BigUploadFile("big-file")
    await big_file.awrite(b"big-data" * 512)
    await big_file.awrite(b"big-data")
    await big_file.aseek(0)
    assert await big_file.aread(8 * 128) == b"big-data" * 128
    await big_file.aclose()


def test_formdata():
    upload = io.BytesIO(b"test")
    form = FormData([("a", "123"), ("a", "456"), ("b", upload)])
    assert "a" in form
    assert "A" not in form
    assert "c" not in form
    assert form["a"] == "456"
    assert form.get("a") == "456"
    assert form.get("nope", default=None) is None
    assert form.getlist("a") == ["123", "456"]
    assert list(form.keys()) == ["a", "b"]
    assert list(form.values()) == ["456", upload]
    assert list(form.items()) == [("a", "456"), ("b", upload)]
    assert len(form) == 2
    assert list(form) == ["a", "b"]
    assert dict(form) == {"a": "456", "b": upload}
    assert (
        repr(form)
        == "FormData([('a', '123'), ('a', '456'), ('b', " + repr(upload) + ")])"
    )
    assert FormData(form) == form
    assert FormData({"a": "123", "b": "789"}) == FormData([("a", "123"), ("b", "789")])
    assert FormData({"a": "123", "b": "789"}) != {"a": "123", "b": "789"}


def test_multidict():
    q = MultiDict([("a", "123"), ("a", "456"), ("b", "789")])
    assert "a" in q
    assert "A" not in q
    assert "c" not in q
    assert q["a"] == "456"
    assert q.get("a") == "456"
    assert q.get("nope", default=None) is None
    assert q.getlist("a") == ["123", "456"]
    assert list(q.keys()) == ["a", "b"]
    assert list(q.values()) == ["456", "789"]
    assert list(q.items()) == [("a", "456"), ("b", "789")]
    assert len(q) == 2
    assert list(q) == ["a", "b"]
    assert dict(q) == {"a": "456", "b": "789"}
    assert str(q) == "MultiDict([('a', '123'), ('a', '456'), ('b', '789')])"
    assert repr(q) == "MultiDict([('a', '123'), ('a', '456'), ('b', '789')])"
    assert MultiDict({"a": "123", "b": "456"}) == MultiDict(
        [("a", "123"), ("b", "456")]
    )
    assert MultiDict({"a": "123", "b": "456"}) == MultiDict(
        [("a", "123"), ("b", "456")]
    )
    assert MultiDict({"a": "123", "b": "456"}) == MultiDict({"b": "456", "a": "123"})
    assert MultiDict() == MultiDict({})
    assert MultiDict({"a": "123", "b": "456"}) != "invalid"

    q = MultiDict([("a", "123"), ("a", "456")])
    assert MultiDict(q) == q

    q = MultiDict([("a", "123"), ("a", "456")])
    q["a"] = "789"
    assert q["a"] == "789"
    assert q.getlist("a") == ["789"]

    q = MultiDict([("a", "123"), ("a", "456")])
    del q["a"]
    assert q.get("a") is None
    assert repr(q) == "MultiDict([])"

    q = MultiDict([("a", "123"), ("a", "456"), ("b", "789")])
    assert q.pop("a") == "456"
    assert q.get("a", None) is None
    assert repr(q) == "MultiDict([('b', '789')])"

    q = MultiDict([("a", "123"), ("a", "456"), ("b", "789")])
    item = q.popitem()
    assert q.get(item[0]) is None

    q = MultiDict([("a", "123"), ("a", "456"), ("b", "789")])
    assert q.poplist("a") == ["123", "456"]
    assert q.get("a") is None
    assert repr(q) == "MultiDict([('b', '789')])"

    q = MultiDict([("a", "123"), ("a", "456"), ("b", "789")])
    q.clear()
    assert q.get("a") is None
    assert repr(q) == "MultiDict([])"

    q = MultiDict([("a", "123")])
    q.setlist("a", ["456", "789"])
    assert q.getlist("a") == ["456", "789"]
    q.setlist("b", [])
    assert "b" not in q

    q = MultiDict([("a", "123")])
    assert q.setdefault("a", "456") == "123"
    assert q.getlist("a") == ["123"]
    assert q.setdefault("b", "456") == "456"
    assert q.getlist("b") == ["456"]
    assert repr(q) == "MultiDict([('a', '123'), ('b', '456')])"

    q = MultiDict([("a", "123")])
    q.append("a", "456")
    assert q.getlist("a") == ["123", "456"]
    assert repr(q) == "MultiDict([('a', '123'), ('a', '456')])"

    q = MultiDict([("a", "123"), ("b", "456")])
    q.update({"a": "789"})
    assert q.getlist("a") == ["789"]
    q == MultiDict([("a", "789"), ("b", "456")])

    q = MultiDict([("a", "123"), ("b", "456")])
    q.update(q)
    assert repr(q) == "MultiDict([('a', '123'), ('b', '456')])"

    q = MultiDict([("a", "123"), ("b", "456")])
    q.update(None)
    assert repr(q) == "MultiDict([('a', '123'), ('b', '456')])"

    q = MultiDict([("a", "123"), ("a", "456")])
    q.update([("a", "123")])
    assert q.getlist("a") == ["123"]
    q.update([("a", "456")], a="789", b="123")
    assert q == MultiDict([("a", "456"), ("a", "789"), ("b", "123")])
