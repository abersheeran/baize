from baize.utils import cached_property


def test_cached_property():
    class T:
        @cached_property
        def li(self):
            return object()

    assert T.li.__name__ == "li"
    assert not callable(T.li)
