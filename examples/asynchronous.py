import time
from typing import Awaitable, Callable
from baize.asgi import (
    decorator,
    request_response,
    Router,
    Request,
    Response,
    PlainTextResponse,
)


@decorator
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
