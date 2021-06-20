import pytest

from baize.routing import CONVERTOR_TYPES as CTS
from baize.routing import compile_path


@pytest.mark.parametrize(
    "convertor,value",
    [
        (CTS["str"], "baize"),
        (CTS["str"], ""),
        (CTS["str"], "123/123/123"),
        (CTS["int"], "10"),
        (CTS["int"], "-10"),
        (CTS["decimal"], "123"),
        (CTS["decimal"], "123.09"),
        (CTS["decimal"], "-123.09"),
        (CTS["decimal"], "nan"),
        (CTS["decimal"], "inf"),
        (CTS["uuid"], "90478484-0988-45fc-91fe-757d90136892"),
        (CTS["date"], "2021-03-07"),
        (CTS["any"], "123/123/123"),
    ],
)
def test_convertors(convertor, value):
    try:
        assert convertor.to_string(convertor.to_python(value)) == value
    except ValueError:
        pass


def test_compile_path_error():
    with pytest.raises(ValueError):
        compile_path("/{id:integer}")
