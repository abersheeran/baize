import pytest

from baize.exceptions import HTTPException, abort


def test_abort():
    with pytest.raises(HTTPException):
        abort()
