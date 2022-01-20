# Multipart parser

BáiZé provides a "bring your own I/O" multipart parser with excellent performance.

## Example

### Synchronous example

```eval_rst
.. literalinclude:: ../../baize/wsgi/requests.py
   :language: python
   :emphasize-lines: 6,170-208
```

### Asynchronous example

```eval_rst
.. literalinclude:: ../../baize/asgi/requests.py
   :language: python
   :emphasize-lines: 17,200-238
```
