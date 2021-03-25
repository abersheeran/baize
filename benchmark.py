import asyncio
import time
import sys

import httpx
from baize.asgi import request_response, Request, Response

print(sys.path)


@request_response
async def asgi(request: Request):
    request.client
    request.url
    request.path_params
    request.query_params
    request.headers
    request.content_type
    request.accepted_types
    response = Response()
    response.headers
    return response


async def main():
    async with httpx.AsyncClient(app=asgi, base_url="http://testServer") as client:
        tasks = [client.get("/") for _ in range(10000)]
        start_time = time.time_ns()
        await asyncio.gather(*tasks)
        end_time = time.time_ns()
        print("Time:", (end_time - start_time) / 10 ** 9, flush=True)


asyncio.run(main())
