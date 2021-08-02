try:
    from mypy_extensions import mypyc_attr
except ImportError:
    allow_interpreted_subclasses = lambda x: x
else:
    allow_interpreted_subclasses = mypyc_attr(allow_interpreted_subclasses=True)
