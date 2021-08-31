
# -*- coding: utf-8 -*-
from setuptools import setup

import codecs

with codecs.open('README.md', encoding="utf-8") as fp:
    long_description = fp.read()
INSTALL_REQUIRES = [
    'typing-extensions<4.0.0,>=3.7.4; python_version < "3.8"',
]
EXTRAS_REQUIRE = {
    'multipart': [
        'python-multipart<1.0.0,>=0.0.5',
    ],
}

setup_kwargs = {
    'name': 'baize',
    'version': '0.10.1',
    'description': 'Powerful and exquisite WSGI/ASGI framework/toolkit.',
    'long_description': long_description,
    'license': 'Apache-2.0',
    'author': '',
    'author_email': 'abersheeran <me@abersheeran.com>',
    'maintainer': None,
    'maintainer_email': None,
    'url': 'https://github.com/abersheeran/baize',
    'packages': [
        'baize',
    ],
    'package_data': {'': ['*']},
    'long_description_content_type': 'text/markdown',
    'classifiers': [
        'License :: OSI Approved :: Apache Software License',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: Implementation :: CPython',
        'Programming Language :: Python :: Implementation :: PyPy',
        'Topic :: Internet :: WWW/HTTP',
        'Topic :: Internet :: WWW/HTTP :: WSGI',
        'Topic :: Internet :: WWW/HTTP :: WSGI :: Application',
    ],
    'install_requires': INSTALL_REQUIRES,
    'extras_require': EXTRAS_REQUIRE,
    'python_requires': '>=3.6',

}
from speedup import build
build(setup_kwargs)


setup(**setup_kwargs)
