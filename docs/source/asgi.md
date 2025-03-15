# ASGI (Asynchronous Server Gateway Interface)

## HTTPConnection

```{eval-rst}
.. autoclass:: baize.asgi.HTTPConnection
   :members:
   :inherited-members:
```

## Request

```{eval-rst}
.. autoclass:: baize.asgi.Request
   :members:
   :undoc-members:
```

## Response

```{eval-rst}
.. autoclass:: baize.asgi.Response
   :members:
```

## SmallResponse

```{eval-rst}
.. autoclass:: baize.asgi.SmallResponse
   :show-inheritance:
   :members:
```

## PlainTextResponse

```{eval-rst}
.. autoclass:: baize.asgi.PlainTextResponse
   :show-inheritance:
   :members:
```

## HTMLResponse

```{eval-rst}
.. autoclass:: baize.asgi.HTMLResponse
   :show-inheritance:
```

## JSONResponse

```{eval-rst}
.. autoclass:: baize.asgi.JSONResponse
   :show-inheritance:
```

## RedirectResponse

```{eval-rst}
.. autoclass:: baize.asgi.RedirectResponse
   :show-inheritance:
```

## StreamResponse

```{eval-rst}
.. autoclass:: baize.asgi.StreamResponse
   :show-inheritance:
```

## FileResponse

```{eval-rst}
.. autoclass:: baize.asgi.FileResponse
   :show-inheritance:
```

## SendEventResponse

```{eval-rst}
.. autoclass:: baize.asgi.SendEventResponse
   :show-inheritance:
```

## WebSocket

```{eval-rst}
.. autoclass:: baize.asgi.WebSocket
   :members:
```

## WebsocketDenialResponse

```{eval-rst}
.. autoclass:: baize.asgi.WebsocketDenialResponse
   :members:
```

## Router

```{eval-rst}
.. autoclass:: baize.asgi.Router
   :members:
   :inherited-members:
```

Use `{}` to mark path parameters, the format is `{name[:type]}`. If type is not explicitly specified, it defaults to `str`.

The built-in types are `str`, `int`, `decimal`, `uuid`, `date`, `any`. Among them, `str` can match all strings except `/`, and `any` can match all strings.

If the built-in types are not enough, then you only need to write a class that inherits `baize.routing.Convertor` and register it in `baize.routing.CONVERTOR_TYPES`.

## Subpaths

```{eval-rst}
.. autoclass:: baize.asgi.Subpaths
```

## Hosts

```{eval-rst}
.. autoclass:: baize.asgi.Hosts
```

## Shortcut functions

### request_response

```{eval-rst}
.. autofunction:: baize.asgi.request_response
```

### decorator

```{eval-rst}
.. autofunction:: baize.asgi.decorator
```

### middleware

```{eval-rst}
.. autofunction:: baize.asgi.middleware
```

### websocket_session

```{eval-rst}
.. autofunction:: baize.asgi.websocket_session
```

## Files

```{eval-rst}
.. autoclass:: baize.asgi.Files
```

## Pages

```{eval-rst}
.. autoclass:: baize.asgi.Pages
```
