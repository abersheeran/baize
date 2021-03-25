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
    'version': '0.6.0',
    'description': 'Powerful and exquisite WSGI/ASGI framework/toolkit.',
    'long_description': "# BaíZé\n\n[![Codecov](https://img.shields.io/codecov/c/github/abersheeran/baize?style=flat-square)](https://codecov.io/gh/abersheeran/baize)\n\nPowerful and exquisite WSGI/ASGI framework/toolkit.\n\nThe minimize implementation of methods required in the Web framework. No redundant implementation means that you can freely customize functions without considering the conflict with baize's own implementation.\n\nUnder the ASGI/WSGI protocol, the interface of the request object and the response object is almost the same, only need to add or delete `await` in the appropriate place. In addition, it should be noted that ASGI supports WebSocket but WSGI does not.\n\n## Install\n\n```\npip install -U baize\n```\n\nOr install from GitHub master branch\n\n```\npip install -U git+https://github.com/abersheeran/baize@setup.py\n```\n",
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
