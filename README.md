# BáiZé

[![Codecov](https://img.shields.io/codecov/c/github/abersheeran/baize?style=flat-square)](https://codecov.io/gh/abersheeran/baize)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/baize?label=Support%20Python%20Version&style=flat-square)](https://pypi.org/project/baize/)

Powerful and exquisite WSGI/ASGI framework/toolkit. Use [MyPyC](https://mypyc.readthedocs.io/en/latest/) to improve code running speed.

The minimize implementation of methods required in the Web framework. No redundant implementation means that you can freely customize functions without considering the conflict with baize's own implementation.

Under the ASGI/WSGI protocol, the interface of the request object and the response object is almost the same, only need to add or delete `await` in the appropriate place. In addition, it should be noted that ASGI supports WebSocket but WSGI does not.

- Type annotations as strict as possible (almost no Any)
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

## Document and other website

[BáiZé Document](https://baize.aber.sh/)

If you have questions or idea, you can send it to [Discussions](https://github.com/abersheeran/baize/discussions).

## Quick Start

A short example for WSGI application, if you don't know what is WSGI, please read [PEP3333](https://www.python.org/dev/peps/pep-3333/).

```python
import time
from typing import Callable
from baize.wsgi import (
    middleware,
    request_response,
    Router,
    Request,
    Response,
    PlainTextResponse,
)


@middleware
def timer(request: Request, next_call: Callable[[Request], Response]) -> Response:
    start_time = time.time()
    response = next_call(request)
    end_time = time.time()
    response.headers["x-time"] = str(round((end_time - start_time) * 1000))
    return response


@request_response
@timer
def sayhi(request: Request) -> Response:
    return PlainTextResponse("hi, " + request.path_params["name"])


@request_response
@timer
def echo(request: Request) -> Response:
    return PlainTextResponse(request.body)


application = Router(
    ("/", PlainTextResponse("homepage")),
    ("/echo", echo),
    ("/sayhi/{name}", sayhi),
)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(application, interface="wsgi", port=8000)
```

A short example for ASGI application, if you don't know what is ASGI, please read [ASGI Documention](https://asgi.readthedocs.io/en/latest/).

```python
import time
from typing import Awaitable, Callable
from baize.asgi import (
    middleware,
    request_response,
    Router,
    Request,
    Response,
    PlainTextResponse,
)


@middleware
async def timer(
    request: Request, next_call: Callable[[Request], Awaitable[Response]]
) -> Response:
    start_time = time.time()
    response = await next_call(request)
    end_time = time.time()
    response.headers["x-time"] = str(round((end_time - start_time) * 1000))
    return response


@request_response
@timer
async def sayhi(request: Request) -> Response:
    return PlainTextResponse("hi, " + request.path_params["name"])


@request_response
@timer
async def echo(request: Request) -> Response:
    return PlainTextResponse(await request.body)


application = Router(
    ("/", PlainTextResponse("homepage")),
    ("/echo", echo),
    ("/sayhi/{name}", sayhi),
)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(application, interface="asgi3", port=8000)
```

## License

Apache-2.0.
