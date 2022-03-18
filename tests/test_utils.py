import pytest

from baize.utils import cached_property, parse_header


def test_cached_property():
    class T:
        @cached_property
        def li(self):
            return object()

    assert T.li.__name__ == "li"
    assert not callable(T.li)


@pytest.mark.parametrize(
    "line,result",
    [
        (
            "application/json",
            ("application/json", {}),
        ),
        (
            "text/html; charset=utf-8",
            ("text/html", {"charset": "utf-8"}),
        ),
        (
            'form-data; name="lname"; filename="bob"',
            ("form-data", {"name": "lname", "filename": "bob"}),
        ),
        (
            'value; name="baize;tests"',
            ("value", {"name": "baize;tests"}),
        ),
    ],
)
def test_parse_header(line, result):
    assert parse_header(line) == result
