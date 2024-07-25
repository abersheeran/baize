import time
from typing import Callable
from baize.wsgi import (
    decorator,
    request_response,
    Router,
    Request,
    Response,
    PlainTextResponse,
)


@decorator
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
