from typing import Iterable, Optional, Tuple

from baize.typing import Message, Send


async def send_http_start(
    send: Send,
    status_code: int,
    headers: Optional[Iterable[Tuple[bytes, bytes]]] = None,
) -> None:
    """
    helper function for send http.response.start

    https://asgi.readthedocs.io/en/latest/specs/www.html#response-start-send-event
    """
    message = {"type": "http.response.start", "status": status_code}
    if headers is not None:
        message["headers"] = headers
    await send(message)


async def send_http_body(
    send: Send, body: bytes = b"", *, more_body: bool = False
) -> None:
    """
    helper function for send http.response.body

    https://asgi.readthedocs.io/en/latest/specs/www.html#response-body-send-event
    """
    await send({"type": "http.response.body", "body": body, "more_body": more_body})


async def empty_receive() -> Message:
    raise NotImplementedError("Receive channel has not been made available")


async def empty_send(message: Message) -> None:
    raise NotImplementedError("Send channel has not been made available")
