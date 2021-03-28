# BáiZé

[![Codecov](https://img.shields.io/codecov/c/github/abersheeran/baize?style=flat-square)](https://codecov.io/gh/abersheeran/baize)

Powerful and exquisite WSGI/ASGI framework/toolkit.

The minimize implementation of methods required in the Web framework. No redundant implementation means that you can freely customize functions without considering the conflict with baize's own implementation.

Under the ASGI/WSGI protocol, the interface of the request object and the response object is almost the same, only need to add or delete `await` in the appropriate place. In addition, it should be noted that ASGI supports WebSocket but WSGI does not.

## Install

```
pip install -U baize
```

Or install from GitHub master branch

```
pip install -U git+https://github.com/abersheeran/baize@setup.py
```

## Usage

```python
from baize.wsgi import request_response, Router, Request, Response, PlainTextResponse


@request_response
def sayhi(request: Request) -> Response:
    return PlainTextResponse("hi, " + request.path_params["name"])


@request_response
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

```python
from baize.asgi import request_response, Router, Request, Response, PlainTextResponse


@request_response
async def sayhi(request: Request) -> Response:
    return PlainTextResponse("hi, " + request.path_params["name"])


@request_response
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

The above are two pieces of code for quick reading. If you are a beginner to BáiZé, please refer to the following document to learn how to use it.
