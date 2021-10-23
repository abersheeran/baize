import os

import httpx

from baize.datastructures import Headers, UploadFile
from baize.multipart import (
    Data,
    Epilogue,
    Field,
    File,
    MultipartDecoder,
    NeedData,
    Preamble,
    safe_decode,
)
from baize.wsgi import JSONResponse, Request


def test_decoder_simple() -> None:
    boundary = b"---------------------------9704338192090380615194531385$"
    decoder = MultipartDecoder(boundary, "utf8")
    data = """
-----------------------------9704338192090380615194531385$
Content-Disposition: form-data; name="fname"

ß∑œß∂ƒå∂
-----------------------------9704338192090380615194531385$
Content-Disposition: form-data; name="lname"; filename="bob"

asdasd
-----------------------------9704338192090380615194531385$--
    """.replace(
        "\n", "\r\n"
    ).encode(
        "utf-8"
    )
    decoder.receive_data(data)
    decoder.receive_data(None)
    events = [decoder.next_event()]
    while not isinstance(events[-1], Epilogue) and len(events) < 6:
        events.append(decoder.next_event())
    assert events == [
        Preamble(data=b""),
        Field(
            name="fname",
            headers=Headers([("Content-Disposition", 'form-data; name="fname"')]),
        ),
        Data(data="ß∑œß∂ƒå∂".encode(), more_data=False),
        File(
            name="lname",
            filename="bob",
            headers=Headers(
                [("Content-Disposition", 'form-data; name="lname"; filename="bob"')]
            ),
        ),
        Data(data=b"asdasd", more_data=False),
        Epilogue(data=b"    "),
    ]


def test_chunked_boundaries() -> None:
    boundary = b"boundary"
    decoder = MultipartDecoder(boundary, "utf8")
    decoder.receive_data(b"--")
    assert isinstance(decoder.next_event(), NeedData)
    decoder.receive_data(b"boundary\r\n")
    assert isinstance(decoder.next_event(), Preamble)
    decoder.receive_data(b"Content-Disposition: form-data;")
    assert isinstance(decoder.next_event(), NeedData)
    decoder.receive_data(b'name="fname"\r\n\r\n')
    assert isinstance(decoder.next_event(), Field)
    decoder.receive_data(b"longer than the boundary")
    assert isinstance(decoder.next_event(), Data)
    decoder.receive_data(b"also longer, but includes a linebreak\r\n--")
    assert isinstance(decoder.next_event(), Data)
    assert isinstance(decoder.next_event(), NeedData)
    decoder.receive_data(b"boundary-")
    event = decoder.next_event()
    assert isinstance(event, NeedData)
    decoder.receive_data(b"-\r\n")
    event = decoder.next_event()
    assert isinstance(event, Data)
    assert not event.more_data
    decoder.receive_data(None)
    assert isinstance(decoder.next_event(), Epilogue)


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


def test_multipart_request_empty_data(tmpdir):
    with httpx.Client(app=app, base_url="http://testServer/") as client:
        response = client.post("/", data={}, files=FORCE_MULTIPART)
        assert response.json() == {}


def test_multipart_request_data(tmpdir):
    with httpx.Client(app=app, base_url="http://testServer/") as client:
        response = client.post("/", data={"some": "data"}, files=FORCE_MULTIPART)
        assert response.json() == {"some": "data"}


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


def test_multipart_request_mixed_files_and_data(tmpdir):
    with httpx.Client(app=app, base_url="http://testServer/") as client:
        response = client.post(
            "/",
            content=(
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


def test_multipart_request_with_charset_for_filename(tmpdir):
    with httpx.Client(app=app, base_url="http://testServer/") as client:
        response = client.post(
            "/",
            content=(
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


def test_multipart_request_without_charset_for_filename(tmpdir):
    with httpx.Client(app=app, base_url="http://testServer/") as client:
        response = client.post(
            "/",
            content=(
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


def test_multipart_request_with_encoded_value(tmpdir):
    with httpx.Client(app=app, base_url="http://testServer/") as client:
        response = client.post(
            "/",
            content=(
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


def test_multipart_multi_field_app_reads_body(tmpdir):
    with httpx.Client(app=app_read_body, base_url="http://testServer/") as client:
        response = client.post(
            "/", data={"some": "data", "second": "key pair"}, files=FORCE_MULTIPART
        )
        assert response.json() == {"some": "data", "second": "key pair"}


def test_safe_decode_helper():
    result = safe_decode(b"\xc4\x99\xc5\xbc\xc4\x87", "utf-8")
    assert result == "ężć"


def test_safe_decode_ignores_wrong_charset():
    result = safe_decode(b"abc", "latin-8")
    assert result == "abc"
