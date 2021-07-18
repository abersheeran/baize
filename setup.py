# -*- coding: utf-8 -*-
from setuptools import setup

packages = \
['baize']

package_data = \
{'': ['*']}

extras_require = \
{':python_version < "3.8"': ['typing-extensions>=3.7.4,<4.0.0'],
 'multipart': ['python-multipart>=0.0.5,<0.0.6']}

setup_kwargs = {
    'name': 'baize',
    'version': '0.9.0',
    'description': 'Powerful and exquisite WSGI/ASGI framework/toolkit.',
    'long_description': '# BáiZé\n\n[![Codecov](https://img.shields.io/codecov/c/github/abersheeran/baize?style=flat-square)](https://codecov.io/gh/abersheeran/baize)\n[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/baize?label=Support%20Python%20Version&style=flat-square)](https://pypi.org/project/baize/)\n\nPowerful and exquisite WSGI/ASGI framework/toolkit.\n\nThe minimize implementation of methods required in the Web framework. No redundant implementation means that you can freely customize functions without considering the conflict with baize\'s own implementation.\n\nUnder the ASGI/WSGI protocol, the interface of the request object and the response object is almost the same, only need to add or delete `await` in the appropriate place. In addition, it should be noted that ASGI supports WebSocket but WSGI does not.\n\n- Support range file response, server-sent event response\n- Support WebSocket (only ASGI)\n- WSGI, ASGI routing to combine any application like [Django(wsgi)](https://docs.djangoproject.com/en/3.0/howto/deployment/wsgi/)/[Pyramid](https://trypyramid.com/)/[Bottle](https://bottlepy.org/)/[Flask](https://flask.palletsprojects.com/) or [Django(asgi)](https://docs.djangoproject.com/en/3.0/howto/deployment/asgi/)/[Index.py](https://index-py.aber.sh/)/[Starlette](https://www.starlette.io/)/[FastAPI](https://fastapi.tiangolo.com/)/[Sanic](https://sanic.readthedocs.io/en/stable/)/[Quart](https://pgjones.gitlab.io/quart/)\n\n## Install\n\n```\npip install -U baize\n```\n\nOr install from GitHub master branch\n\n```\npip install -U git+https://github.com/abersheeran/baize@setup.py\n```\n\n## Document and other website\n\n[BáiZé Document](https://baize.aber.sh/)\n\nIf you have questions or idea, you can send it to [Discussions](https://github.com/abersheeran/baize/discussions).\n\n## Quick Start\n\nA short example for WSGI application, if you don\'t know what is WSGI, please read [PEP3333](https://www.python.org/dev/peps/pep-3333/).\n\n```python\nfrom baize.wsgi import request_response, Router, Request, Response, PlainTextResponse\n\n\n@request_response\ndef sayhi(request: Request) -> Response:\n    return PlainTextResponse("hi, " + request.path_params["name"])\n\n\n@request_response\ndef echo(request: Request) -> Response:\n    return PlainTextResponse(request.body)\n\n\napplication = Router(\n    ("/", PlainTextResponse("homepage")),\n    ("/echo", echo),\n    ("/sayhi/{name}", sayhi),\n)\n\n\nif __name__ == "__main__":\n    import uvicorn\n\n    uvicorn.run(application, interface="wsgi", port=8000)\n```\n\nA short example for ASGI application, if you don\'t know what is ASGI, please read [ASGI Documention](https://asgi.readthedocs.io/en/latest/).\n\n```python\nfrom baize.asgi import request_response, Router, Request, Response, PlainTextResponse\n\n\n@request_response\nasync def sayhi(request: Request) -> Response:\n    return PlainTextResponse("hi, " + request.path_params["name"])\n\n\n@request_response\nasync def echo(request: Request) -> Response:\n    return PlainTextResponse(await request.body)\n\n\napplication = Router(\n    ("/", PlainTextResponse("homepage")),\n    ("/echo", echo),\n    ("/sayhi/{name}", sayhi),\n)\n\n\nif __name__ == "__main__":\n    import uvicorn\n\n    uvicorn.run(application, interface="asgi3", port=8000)\n```\n\n## License\n\nApache-2.0.\n\nYou can do whatever you want with the permission of the license.\n',
    'author': 'abersheeran',
    'author_email': 'me@abersheeran.com',
    'maintainer': None,
    'maintainer_email': None,
    'url': 'https://github.com/abersheeran/baize',
    'packages': packages,
    'package_data': package_data,
    'extras_require': extras_require,
    'python_requires': '>=3.6,<4.0',
}
from speedup import *
build(setup_kwargs)

setup(**setup_kwargs)

