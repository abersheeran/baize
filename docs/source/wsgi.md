# WSGI (Web Server Gateway Interface)

## HTTPConnection

```{eval-rst}
.. autoclass:: baize.wsgi.HTTPConnection
   :members:
   :inherited-members:
```

## Request

```{eval-rst}
.. autoclass:: baize.wsgi.Request
   :members:
   :undoc-members:
```

## Response

```{eval-rst}
.. autoclass:: baize.wsgi.Response
   :members:
```

## SmallResponse

```{eval-rst}
.. autoclass:: baize.wsgi.SmallResponse
   :show-inheritance:
   :members:
```

## PlainTextResponse

```{eval-rst}
.. autoclass:: baize.wsgi.PlainTextResponse
   :show-inheritance:
   :members:
```

## HTMLResponse

```{eval-rst}
.. autoclass:: baize.wsgi.HTMLResponse
   :show-inheritance:
```

## JSONResponse

```{eval-rst}
.. autoclass:: baize.wsgi.JSONResponse
   :show-inheritance:
```

## RedirectResponse

```{eval-rst}
.. autoclass:: baize.wsgi.RedirectResponse
   :show-inheritance:
```

## StreamResponse

```{eval-rst}
.. autoclass:: baize.wsgi.StreamResponse
   :show-inheritance:
```

## FileResponse

```{eval-rst}
.. autoclass:: baize.wsgi.FileResponse
   :show-inheritance:
```

## SendEventResponse

```{eval-rst}
.. autoclass:: baize.wsgi.SendEventResponse
   :show-inheritance:
```

## Router

```{eval-rst}
.. autoclass:: baize.wsgi.Router
   :members:
   :inherited-members:
```

Use `{}` to mark path parameters, the format is `{name[:type]}`. If type is not explicitly specified, it defaults to `str`.

The built-in types are `str`, `int`, `decimal`, `uuid`, `date`, `any`. Among them, `str` can match all strings except `/`, and `any` can match all strings.

If the built-in types are not enough, then you only need to write a class that inherits `baize.routing.Convertor` and register it in `baize.routing.CONVERTOR_TYPES`.

## Subpaths

```{eval-rst}
.. autoclass:: baize.wsgi.Subpaths
```

## Hosts

```{eval-rst}
.. autoclass:: baize.wsgi.Hosts
```

## Shortcut functions

### request_response

```{eval-rst}
.. autofunction:: baize.wsgi.request_response
```

### decorator

```{eval-rst}
.. autofunction:: baize.wsgi.decorator
```

### middleware

```{eval-rst}
.. autofunction:: baize.wsgi.middleware
```

## Files

```{eval-rst}
.. autoclass:: baize.wsgi.Files
```

## Pages

```{eval-rst}
.. autoclass:: baize.wsgi.Pages
```
