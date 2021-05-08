# BáiZé's documentation

[![Codecov](https://img.shields.io/codecov/c/github/abersheeran/baize?style=flat-square)](https://codecov.io/gh/abersheeran/baize)

Powerful and exquisite WSGI/ASGI framework/toolkit.

The minimize implementation of methods required in the Web framework. No redundant implementation means that you can freely customize functions without considering the conflict with baize's own implementation.

Under the ASGI/WSGI protocol, the interface of the request object and the response object is almost the same, only need to add or delete `await` in the appropriate place. In addition, it should be noted that ASGI supports WebSocket but WSGI does not.

- Support range file response, server-sent event response
- Support WebSocket (only ASGI)
- WSGI, ASGI routing to combine any application like [Django(wsgi)](https://docs.djangoproject.com/en/3.0/howto/deployment/wsgi/)/[Pyramid](https://trypyramid.com/)/[Bottle](https://bottlepy.org/)/[Flask](https://flask.palletsprojects.com/) or [Django(asgi)](https://docs.djangoproject.com/en/3.0/howto/deployment/asgi/)/[Index.py](https://index-py.aber.sh/)/[Starlette](https://www.starlette.io/)/[FastAPI](https://fastapi.tiangolo.com/)/[Sanic](https://sanic.readthedocs.io/en/stable/)/[Quart](https://pgjones.gitlab.io/quart/)

## Install

```
pip install -U baize
```

Or install from GitHub master branch

```
pip install -U git+https://github.com/abersheeran/baize@setup.py
```

## Usage

BáiZé is a framework and toolkit that directly faces the WSGI and ASGI protocols. Please read the corresponding chapters according to your needs.

```eval_rst
.. toctree::
   :maxdepth: 2

   wsgi
   asgi
```
