from pathlib import Path

import pytest

from baize.exceptions import MalformedRangeHeader, RangeNotSatisfiable
from baize.responses import FileResponseMixin


def test_base_file_response_parse_range(tmp_path: Path):
    (tmp_path / "file").touch()
    response = FileResponseMixin

    assert response.parse_range("bytes=0-10", 4623) == [(0, 11)]
    assert response.parse_range("bytes=0-10,hello", 4623) == [(0, 11)]
    assert response.parse_range("bytes=0-10,-", 4623) == [(0, 11)]
    assert response.parse_range("bytes=0-10, 11-20", 4623) == [(0, 21)]
    assert response.parse_range("bytes=0-", 4623) == [(0, 4623)]
    assert response.parse_range("bytes=0-10, 5-", 4623) == [(0, 4623)]
    assert [
        (0, 11),
        (20, 30),
        (40, 4623),
    ] == response.parse_range("bytes=0-10, 50-, 20-29, 40-50, 20-29", 4623)
    assert response.parse_range("bytes=0-54321", 4623) == [(0, 4623)]
    assert response.parse_range("bytes=-500", 4623) == [(4123, 4623)]
    assert response.parse_range("bytes=20-29, -500", 4623) == [(20, 30), (4123, 4623)]
    assert response.parse_range("bytes=4100-4200, -500", 4623) == [(4100, 4623)]

    with pytest.raises(MalformedRangeHeader):
        response.parse_range("bytes=-", 4623)

    with pytest.raises(MalformedRangeHeader):
        response.parse_range("bytes=", 4623)

    with pytest.raises(MalformedRangeHeader):
        response.parse_range("byte=0-10", 4623)

    with pytest.raises(MalformedRangeHeader):
        response.parse_range("bytes=10-0", 4623)

    with pytest.raises(RangeNotSatisfiable):
        response.parse_range("bytes=4625-4635", 4623)

    with pytest.raises(RangeNotSatisfiable):
        response.parse_range("bytes=0-10, 4625-4635", 4623)

    with pytest.raises(RangeNotSatisfiable):
        response.parse_range("bytes=8000-", 4623)

    with pytest.raises(RangeNotSatisfiable):
        response.parse_range("bytes=-9999", 4623)
