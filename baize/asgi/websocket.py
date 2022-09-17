import enum
from typing import AsyncIterator, Optional

from baize.typing import Message, Receive, Scope, Send

from .requests import HTTPConnection
from .responses import Response


class WebSocketDisconnect(Exception):
    def __init__(self, code: int = 1000) -> None:
        self.code = code


class WebSocketState(enum.Enum):
    CONNECTING = enum.auto()
    CONNECTED = enum.auto()
    DISCONNECTED = enum.auto()


class WebSocket(HTTPConnection):
    def __init__(self, scope: Scope, receive: Receive, send: Send) -> None:
        assert scope["type"] == "websocket"
        super().__init__(scope, receive, send)
        self.client_state = WebSocketState.CONNECTING
        self.application_state = WebSocketState.CONNECTING

    async def receive(self) -> Message:
        """
        Receive ASGI websocket messages, ensuring valid state transitions.
        """
        if self.client_state == WebSocketState.CONNECTING:
            message = await self._receive()
            message_type = message["type"]
            assert message_type == "websocket.connect"
            self.client_state = WebSocketState.CONNECTED
            return message
        elif self.client_state == WebSocketState.CONNECTED:
            message = await self._receive()
            message_type = message["type"]
            assert message_type in {"websocket.receive", "websocket.disconnect"}
            if message_type == "websocket.disconnect":
                self.client_state = WebSocketState.DISCONNECTED
            return message
        else:
            raise RuntimeError(
                'Cannot call "receive" once a disconnect message has been received.'
            )

    async def send(self, message: Message) -> None:
        """
        Send ASGI websocket messages, ensuring valid state transitions.
        """
        if self.application_state == WebSocketState.CONNECTING:
            message_type = message["type"]
            assert message_type in {"websocket.accept", "websocket.close"}
            if message_type == "websocket.close":
                self.application_state = WebSocketState.DISCONNECTED
            else:
                self.application_state = WebSocketState.CONNECTED
            await self._send(message)
        elif self.application_state == WebSocketState.CONNECTED:
            message_type = message["type"]
            assert message_type in {"websocket.send", "websocket.close"}
            if message_type == "websocket.close":
                self.application_state = WebSocketState.DISCONNECTED
            await self._send(message)
        else:
            raise RuntimeError('Cannot call "send" once a close message has been sent.')

    async def accept(self, subprotocol: Optional[str] = None) -> None:
        """
        Accept websocket connection.
        """
        if self.client_state == WebSocketState.CONNECTING:
            # If we haven't yet seen the 'connect' message, then wait for it first.
            await self.receive()
        await self.send({"type": "websocket.accept", "subprotocol": subprotocol})

    def _raise_on_disconnect(self, message: Message) -> None:
        if message["type"] == "websocket.disconnect":
            raise WebSocketDisconnect(message["code"])

    async def receive_text(self) -> str:
        """
        Receive a WebSocket text frame and return.
        """
        assert self.application_state == WebSocketState.CONNECTED
        message = await self.receive()
        self._raise_on_disconnect(message)
        return message["text"]

    async def receive_bytes(self) -> bytes:
        """
        Receive a WebSocket binary frame and return.
        """
        assert self.application_state == WebSocketState.CONNECTED
        message = await self.receive()
        self._raise_on_disconnect(message)
        return message["bytes"]

    async def iter_text(self) -> AsyncIterator[str]:
        """
        Keep receiving text frames until the WebSocket connection is disconnected.
        """
        try:
            while True:
                yield await self.receive_text()
        except WebSocketDisconnect:
            pass

    async def iter_bytes(self) -> AsyncIterator[bytes]:
        """
        Keep receiving binary frames until the WebSocket connection is disconnected.
        """
        try:
            while True:
                yield await self.receive_bytes()
        except WebSocketDisconnect:
            pass

    async def send_text(self, data: str) -> None:
        """
        Send a WebSocket text frame.
        """
        await self.send({"type": "websocket.send", "text": data})

    async def send_bytes(self, data: bytes) -> None:
        """
        Send a WebSocket binary frame.
        """
        await self.send({"type": "websocket.send", "bytes": data})

    async def close(self, code: int = 1000) -> None:
        """
        Close WebSocket connection. It can be called multiple times.
        """
        if self.application_state != WebSocketState.DISCONNECTED:
            await self.send({"type": "websocket.close", "code": code})


WEBSOCKET_DENIAL_RESPONSE_MAPPING = {
    "http.response.start": "websocket.http.response.start",
    "http.response.body": "websocket.http.response.body",
}


class WebsocketDenialResponse:
    """
    A response that will deny a WebSocket connection.

    https://asgi.readthedocs.io/en/latest/extensions.html#websocket-denial-response
    """

    def __init__(self, response: Response) -> None:
        self.response = response

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        assert (
            scope["type"] == "websocket"
        ), "WebsocketDenialResponse requires a websocket scope"

        # Check if Websocket Denial Response can be used
        if self.response is None or "websocket.http.response" not in scope.get(
            "extensions", {}
        ):
            await send({"type": "websocket.close"})
            return
        else:  # pragma: no cover

            # call the specified response, mapping send/receive events
            # between http/websocket ASGI protocols

            async def ws_send(msg: Message) -> None:
                if msg["type"] not in WEBSOCKET_DENIAL_RESPONSE_MAPPING:
                    raise ValueError(f"Unsupported message type: {msg['type']}")
                else:
                    msg["type"] = WEBSOCKET_DENIAL_RESPONSE_MAPPING[msg["type"]]
                await send(msg)

            async def ws_receive() -> Message:
                while True:
                    msg = await receive()
                    if msg["type"] == "websocket.disconnect":
                        msg["type"] = "http.disconnect"
                        return msg

            await self.response(scope, ws_receive, ws_send)
