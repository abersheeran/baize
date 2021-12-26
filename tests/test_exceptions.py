import pytest

from baize.exceptions import HTTPException, abort


def test_custom_status_code():
    assert str(HTTPException(0)) == "(0, 'Maybe a custom HTTP status code')"


def test_abort():
    with pytest.raises(HTTPException):
        abort()
