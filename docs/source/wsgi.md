# WSGI (Web Server Gateway Interface)

## HTTPConnection

```eval_rst
.. autoclass:: baize.wsgi.HTTPConnection
   :members:
   :inherited-members:
```

## Request

```eval_rst
.. autoclass:: baize.wsgi.Request
   :members:
   :undoc-members:
```

## Response

```eval_rst
.. autoclass:: baize.wsgi.Response
   :members:
```

## SmallResponse

```eval_rst
.. autoclass:: baize.wsgi.SmallResponse
   :show-inheritance:
   :members:
```

## PlainTextResponse

```eval_rst
.. autoclass:: baize.wsgi.PlainTextResponse
   :show-inheritance:
   :members:
```

## HTMLResponse

```eval_rst
.. autoclass:: baize.wsgi.HTMLResponse
   :show-inheritance:
```

## JSONResponse

```eval_rst
.. autoclass:: baize.wsgi.JSONResponse
   :show-inheritance:
```

## RedirectResponse

```eval_rst
.. autoclass:: baize.wsgi.RedirectResponse
   :show-inheritance:
```

## StreamResponse

```eval_rst
.. autoclass:: baize.wsgi.StreamResponse
   :show-inheritance:
```

## FileResponse

```eval_rst
.. autoclass:: baize.wsgi.FileResponse
   :show-inheritance:
```

## SendEventResponse

```eval_rst
.. autoclass:: baize.wsgi.SendEventResponse
   :show-inheritance:
```

## Router

```eval_rst
.. autoclass:: baize.wsgi.Router
```

### mark parameters

Use `{}` to mark path parameters, the format is `{name[:type]}`. If type is not explicitly specified, it defaults to `str`.

The built-in types are `str`, `int`, `decimal`, `uuid`, `date`, `path`. Among them, `str` can match all strings except `/`, and `path` can match all strings.

If the built-in types are not enough, then you only need to write a class that inherits `baize.routing.Convertor` and register it in `baize.routing.CONVERTOR_TYPES`.

### `build_url`

In order to construct the URL path by the route name, you can add a third parameter to the route when writing the route. It must be a string and will be indexed as the name of the route.

```python
router = Router(
    ("/about/{name}", about_page, "about"),
    ("/", homepage, "homepage"),
)

assert router.routes["about"].build_url({"name": "baize"}) == "/about/baize"
assert router.routes["homepage"].build_url({}) == "/"
```

## Subpaths

```eval_rst
.. autoclass:: baize.wsgi.Subpaths
```

## Hosts

```eval_rst
.. autoclass:: baize.wsgi.Hosts
```
