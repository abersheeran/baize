from pathlib import Path
from tempfile import TemporaryFile

import pytest

from baize.common import BaseFileResponse
from baize.exceptions import HTTPException


def test_base_file_response_parse_range():
    with TemporaryFile("ab+") as file:
        file.write(b" " * 4623)
        file.flush()
        response = BaseFileResponse(str(Path(file.name).absolute()))

        assert response.parse_range("bytes=0-10", 4623) == [(0, 11)]
        assert response.parse_range("bytes=0-10, 11-20", 4623) == [(0, 21)]
        assert response.parse_range("bytes=0-", 4623) == [(0, 4623)]
        assert response.parse_range("bytes=0-10, 5-", 4623) == [(0, 4623)]
        assert [
            (0, 11),
            (20, 30),
            (40, 4623),
        ] == response.parse_range("bytes=0-10, 50-, 20-29, 40-50, 20-29", 4623)

        with pytest.raises(HTTPException):
            response.parse_range("byte=0-10", 4623)

        with pytest.raises(HTTPException):
            response.parse_range("bytes=10-0", 4623)

        with pytest.raises(HTTPException):
            response.parse_range("bytes=0-4623", 4623)
