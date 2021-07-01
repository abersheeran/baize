from datetime import datetime, timezone
from typing import Mapping

from baize.datastructures import URL, Headers
from baize.requests import MoreInfoFromHeaderMixin
from baize.utils import cached_property


class FakeRequest(MoreInfoFromHeaderMixin):
    def __init__(self, headers: Mapping[str, str]) -> None:
        self.raw_headers = headers

    @cached_property
    def headers(self) -> Headers:
        return Headers(self.raw_headers)


def test_content_length():
    assert FakeRequest({"Content-Length": "0"}).content_length == 0
    assert FakeRequest({"Content-Length": "-1"}).content_length == 0
    assert FakeRequest({"Content-Length": "abc"}).content_length is None
    assert FakeRequest({}).content_length is None
    assert FakeRequest({"transfer-encoding": "chunked"}).content_length is None


def test_date():
    assert FakeRequest({"Date": "Tue, 15 Nov 1994 08:12:31 GMT"}).date == datetime(
        1994, 11, 15, 8, 12, 31, tzinfo=timezone.utc
    )
    assert FakeRequest({"Date": "Tue, 15 Nov 1994 08:12:31"}).date == datetime(
        1994, 11, 15, 8, 12, 31, tzinfo=timezone.utc
    )
    assert FakeRequest({"Date": "abv"}).date is None
    assert FakeRequest({}).date is None


def test_referrer():
    assert FakeRequest(
        {"referer": "http://www.example.org/hypertext/Overview.html"}
    ).referrer == URL("http://www.example.org/hypertext/Overview.html")
    assert FakeRequest({}).referrer is None
