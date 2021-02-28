import os
import sys

import httpx
import pytest

from baize.formparsers import UploadFile, _user_safe_decode
from baize.wsgi import JSONResponse, Request


class ForceMultipartDict(dict):
    def __bool__(self):
        return True


# FORCE_MULTIPART is an empty dict that boolean-evaluates as `True`.
FORCE_MULTIPART = ForceMultipartDict()


def app(environ, start_response):
    request = Request(environ)
    data = request.form
    output = {}
    for key, value in data.items():
        if isinstance(value, UploadFile):
            content = value.read()
            output[key] = {
                "filename": value.filename,
                "content": content.decode(),
                "content_type": value.content_type,
            }
        else:
            output[key] = value
    request.close()
    response = JSONResponse(output)
    return response(environ, start_response)


def multi_items_app(environ, start_response):
    request = Request(environ)
    data = request.form
    output = {}
    for key, value in data.multi_items():
        if key not in output:
            output[key] = []
        if isinstance(value, UploadFile):
            content = value.read()
            output[key].append(
                {
                    "filename": value.filename,
                    "content": content.decode(),
                    "content_type": value.content_type,
                }
            )
        else:
            output[key].append(value)
    request.close()
    response = JSONResponse(output)
    return response(environ, start_response)


def app_read_body(environ, start_response):
    request = Request(environ)
    data = request.form
    output = {}
    for key, value in data.items():
        output[key] = value
    request.close()
    response = JSONResponse(output)
    return response(environ, start_response)


@pytest.mark.skipif("multipart" not in sys.modules, reason="Missing python-multipart")
def test_multipart_request_data(tmpdir):
    with httpx.Client(app=app, base_url="http://testServer/") as client:
        response = client.post("/", data={"some": "data"}, files=FORCE_MULTIPART)
        assert response.json() == {"some": "data"}


@pytest.mark.skipif("multipart" not in sys.modules, reason="Missing python-multipart")
def test_multipart_request_files(tmpdir):
    path = os.path.join(tmpdir, "test.txt")
    with open(path, "wb") as file:
        file.write(b"<file content>")

    with httpx.Client(app=app, base_url="http://testServer/") as client:
        with open(path, "rb") as f:
            response = client.post("/", files={"test": f})
            assert response.json() == {
                "test": {
                    "filename": "test.txt",
                    "content": "<file content>",
                    "content_type": "text/plain",
                }
            }


@pytest.mark.skipif("multipart" not in sys.modules, reason="Missing python-multipart")
def test_multipart_request_files_with_content_type(tmpdir):
    path = os.path.join(tmpdir, "test.txt")
    with open(path, "wb") as file:
        file.write(b"<file content>")

    with httpx.Client(app=app, base_url="http://testServer/") as client:
        with open(path, "rb") as f:
            response = client.post("/", files={"test": ("test.txt", f, "text/plain")})
            assert response.json() == {
                "test": {
                    "filename": "test.txt",
                    "content": "<file content>",
                    "content_type": "text/plain",
                }
            }


@pytest.mark.skipif("multipart" not in sys.modules, reason="Missing python-multipart")
def test_multipart_request_multiple_files(tmpdir):
    path1 = os.path.join(tmpdir, "test1.txt")
    with open(path1, "wb") as file:
        file.write(b"<file1 content>")

    path2 = os.path.join(tmpdir, "test2.txt")
    with open(path2, "wb") as file:
        file.write(b"<file2 content>")

    with httpx.Client(app=app, base_url="http://testServer/") as client:
        with open(path1, "rb") as f1, open(path2, "rb") as f2:
            response = client.post(
                "/", files={"test1": f1, "test2": ("test2.txt", f2, "text/plain")}
            )
            assert response.json() == {
                "test1": {
                    "filename": "test1.txt",
                    "content": "<file1 content>",
                    "content_type": "text/plain",
                },
                "test2": {
                    "filename": "test2.txt",
                    "content": "<file2 content>",
                    "content_type": "text/plain",
                },
            }


@pytest.mark.skipif("multipart" not in sys.modules, reason="Missing python-multipart")
def test_multi_items(tmpdir):
    path1 = os.path.join(tmpdir, "test1.txt")
    with open(path1, "wb") as file:
        file.write(b"<file1 content>")

    path2 = os.path.join(tmpdir, "test2.txt")
    with open(path2, "wb") as file:
        file.write(b"<file2 content>")

    with httpx.Client(app=multi_items_app, base_url="http://testServer/") as client:
        with open(path1, "rb") as f1, open(path2, "rb") as f2:
            response = client.post(
                "/",
                data={"test1": "abc"},
                files=[("test1", f1), ("test1", ("test2.txt", f2, "text/plain"))],
            )
            assert response.json() == {
                "test1": [
                    "abc",
                    {
                        "filename": "test1.txt",
                        "content": "<file1 content>",
                        "content_type": "text/plain",
                    },
                    {
                        "filename": "test2.txt",
                        "content": "<file2 content>",
                        "content_type": "text/plain",
                    },
                ]
            }


@pytest.mark.skipif("multipart" not in sys.modules, reason="Missing python-multipart")
def test_multipart_request_mixed_files_and_data(tmpdir):
    with httpx.Client(app=app, base_url="http://testServer/") as client:
        response = client.post(
            "/",
            data=(
                # data
                b"--a7f7ac8d4e2e437c877bb7b8d7cc549c\r\n"
                b'Content-Disposition: form-data; name="field0"\r\n\r\n'
                b"value0\r\n"
                # file
                b"--a7f7ac8d4e2e437c877bb7b8d7cc549c\r\n"
                b'Content-Disposition: form-data; name="file"; filename="file.txt"\r\n'
                b"Content-Type: text/plain\r\n\r\n"
                b"<file content>\r\n"
                # data
                b"--a7f7ac8d4e2e437c877bb7b8d7cc549c\r\n"
                b'Content-Disposition: form-data; name="field1"\r\n\r\n'
                b"value1\r\n"
                b"--a7f7ac8d4e2e437c877bb7b8d7cc549c--\r\n"
            ),
            headers={
                "Content-Type": (
                    "multipart/form-data; boundary=a7f7ac8d4e2e437c877bb7b8d7cc549c"
                )
            },
        )
        assert response.json() == {
            "file": {
                "filename": "file.txt",
                "content": "<file content>",
                "content_type": "text/plain",
            },
            "field0": "value0",
            "field1": "value1",
        }


@pytest.mark.skipif("multipart" not in sys.modules, reason="Missing python-multipart")
def test_multipart_request_with_charset_for_filename(tmpdir):
    with httpx.Client(app=app, base_url="http://testServer/") as client:
        response = client.post(
            "/",
            data=(
                # file
                b"--a7f7ac8d4e2e437c877bb7b8d7cc549c\r\n"
                b'Content-Disposition: form-data; name="file"; filename="\xe6\x96\x87\xe6\x9b\xb8.txt"\r\n'  # noqa: E501
                b"Content-Type: text/plain\r\n\r\n"
                b"<file content>\r\n"
                b"--a7f7ac8d4e2e437c877bb7b8d7cc549c--\r\n"
            ),
            headers={
                "Content-Type": (
                    "multipart/form-data; charset=utf-8; "
                    "boundary=a7f7ac8d4e2e437c877bb7b8d7cc549c"
                )
            },
        )
        assert response.json() == {
            "file": {
                "filename": "文書.txt",
                "content": "<file content>",
                "content_type": "text/plain",
            }
        }


@pytest.mark.skipif("multipart" not in sys.modules, reason="Missing python-multipart")
def test_multipart_request_without_charset_for_filename(tmpdir):
    with httpx.Client(app=app, base_url="http://testServer/") as client:
        response = client.post(
            "/",
            data=(
                # file
                b"--a7f7ac8d4e2e437c877bb7b8d7cc549c\r\n"
                b'Content-Disposition: form-data; name="file"; filename="\xe7\x94\xbb\xe5\x83\x8f.jpg"\r\n'  # noqa: E501
                b"Content-Type: image/jpeg\r\n\r\n"
                b"<file content>\r\n"
                b"--a7f7ac8d4e2e437c877bb7b8d7cc549c--\r\n"
            ),
            headers={
                "Content-Type": (
                    "multipart/form-data; boundary=a7f7ac8d4e2e437c877bb7b8d7cc549c"
                )
            },
        )
        assert response.json() == {
            "file": {
                "filename": "画像.jpg",
                "content": "<file content>",
                "content_type": "image/jpeg",
            }
        }


@pytest.mark.skipif("multipart" not in sys.modules, reason="Missing python-multipart")
def test_multipart_request_with_encoded_value(tmpdir):
    with httpx.Client(app=app, base_url="http://testServer/") as client:
        response = client.post(
            "/",
            data=(
                b"--20b303e711c4ab8c443184ac833ab00f\r\n"
                b"Content-Disposition: form-data; "
                b'name="value"\r\n\r\n'
                b"Transf\xc3\xa9rer\r\n"
                b"--20b303e711c4ab8c443184ac833ab00f--\r\n"
            ),
            headers={
                "Content-Type": (
                    "multipart/form-data; charset=utf-8; "
                    "boundary=20b303e711c4ab8c443184ac833ab00f"
                )
            },
        )
        assert response.json() == {"value": "Transférer"}


def test_urlencoded_request_data(tmpdir):
    with httpx.Client(app=app, base_url="http://testServer/") as client:
        response = client.post("/", data={"some": "data"})
        assert response.json() == {"some": "data"}


def test_no_request_data(tmpdir):
    with httpx.Client(app=app, base_url="http://testServer/") as client:
        response = client.post(
            "/", headers={"content-type": "application/x-www-form-urlencoded"}
        )
        assert response.json() == {}


def test_urlencoded_percent_encoding(tmpdir):
    with httpx.Client(app=app, base_url="http://testServer/") as client:
        response = client.post("/", data={"some": "da ta"})
        assert response.json() == {"some": "da ta"}


def test_urlencoded_percent_encoding_keys(tmpdir):
    with httpx.Client(app=app, base_url="http://testServer/") as client:
        response = client.post("/", data={"so me": "data"})
        assert response.json() == {"so me": "data"}


def test_urlencoded_multi_field_app_reads_body(tmpdir):
    with httpx.Client(app=app_read_body, base_url="http://testServer/") as client:
        response = client.post("/", data={"some": "data", "second": "key pair"})
        assert response.json() == {"some": "data", "second": "key pair"}


@pytest.mark.skipif("multipart" not in sys.modules, reason="Missing python-multipart")
def test_multipart_multi_field_app_reads_body(tmpdir):
    with httpx.Client(app=app_read_body, base_url="http://testServer/") as client:
        response = client.post(
            "/", data={"some": "data", "second": "key pair"}, files=FORCE_MULTIPART
        )
        assert response.json() == {"some": "data", "second": "key pair"}


def test_user_safe_decode_helper():
    result = _user_safe_decode(b"\xc4\x99\xc5\xbc\xc4\x87", "utf-8")
    assert result == "ężć"


def test_user_safe_decode_ignores_wrong_charset():
    result = _user_safe_decode(b"abc", "latin-8")
    assert result == "abc"
