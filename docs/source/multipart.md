# Multipart parser

BáiZé provides a "bring your own I/O" multipart parser with excellent performance.

## Synchronous example

```eval_rst
.. literalinclude:: wsgi/requests.py
   :language: python
   :emphasize-lines: 6,170-208
   :linenos:
```

## Asynchronous example

```eval_rst
.. literalinclude:: asgi/requests.py
   :language: python
   :emphasize-lines: 17,200-238
   :linenos:
```
