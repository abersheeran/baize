# ASGI (Asynchronous Server Gateway Interface)

## HTTPConnection

```eval_rst
.. autoclass:: baize.asgi.HTTPConnection
   :members:
   :inherited-members:
```

## Request

```eval_rst
.. autoclass:: baize.asgi.Request
   :members:
   :undoc-members:
```

## Response

```eval_rst
.. autoclass:: baize.asgi.Response
   :members:
```

## SmallResponse

```eval_rst
.. autoclass:: baize.asgi.SmallResponse
   :show-inheritance:
   :members:
```

## PlainTextResponse

```eval_rst
.. autoclass:: baize.asgi.PlainTextResponse
   :show-inheritance:
   :members:
```

## HTMLResponse

```eval_rst
.. autoclass:: baize.asgi.HTMLResponse
   :show-inheritance:
```

## JSONResponse

```eval_rst
.. autoclass:: baize.asgi.JSONResponse
   :show-inheritance:
```

## RedirectResponse

```eval_rst
.. autoclass:: baize.asgi.RedirectResponse
   :show-inheritance:
```

## StreamResponse

```eval_rst
.. autoclass:: baize.asgi.StreamResponse
   :show-inheritance:
```

## FileResponse

```eval_rst
.. autoclass:: baize.asgi.FileResponse
   :show-inheritance:
```

## SendEventResponse

```eval_rst
.. autoclass:: baize.asgi.SendEventResponse
   :show-inheritance:
```

## WebSocket

```eval_rst
.. autoclass:: baize.asgi.WebSocket
   :members:
```

## WebsocketDenialResponse

```eval_rst
.. autoclass:: baize.asgi.WebsocketDenialResponse
   :members:
```

## Router

```eval_rst
.. autoclass:: baize.asgi.Router
   :members:
   :inherited-members:
```

Use `{}` to mark path parameters, the format is `{name[:type]}`. If type is not explicitly specified, it defaults to `str`.

The built-in types are `str`, `int`, `decimal`, `uuid`, `date`, `any`. Among them, `str` can match all strings except `/`, and `any` can match all strings.

If the built-in types are not enough, then you only need to write a class that inherits `baize.routing.Convertor` and register it in `baize.routing.CONVERTOR_TYPES`.

## Subpaths

```eval_rst
.. autoclass:: baize.asgi.Subpaths
```

## Hosts

```eval_rst
.. autoclass:: baize.asgi.Hosts
```

## Shortcut functions

### request_response

```eval_rst
.. autofunction:: baize.asgi.request_response
```

### decorator

```eval_rst
.. autofunction:: baize.asgi.decorator
```

### middleware

```eval_rst
.. autofunction:: baize.asgi.middleware
```

### websocket_session

```eval_rst
.. autofunction:: baize.asgi.websocket_session
```

## Files

```eval_rst
.. autoclass:: baize.asgi.Files
```

## Pages

```eval_rst
.. autoclass:: baize.asgi.Pages
```
