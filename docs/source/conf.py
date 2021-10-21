# Configuration file for the Sphinx documentation builder.
#
# This file only contains a selection of the most common options. For a full
# list see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Path setup --------------------------------------------------------------

# If extensions (or modules to document with autodoc) are in another directory,
# add these directories to sys.path here. If the directory is relative to the
# documentation root, use os.path.abspath to make it absolute, like shown here.

import importlib
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).absolute().parent.parent.parent))


# -- Project information -----------------------------------------------------

project = "BáiZé"
copyright = "Aber"
author = "aber"

# The full version, including alpha/beta/rc tags
release = importlib.import_module("baize.__version__").__version__


# -- General configuration ---------------------------------------------------

# Add any Sphinx extension module names here, as strings. They can be
# extensions coming with Sphinx (named 'sphinx.ext.*') or your custom
# ones.
extensions = ["recommonmark", "sphinx.ext.autodoc"]

# Add any paths that contain templates here, relative to this directory.
templates_path = ["_templates"]

# List of patterns, relative to source directory, that match files and
# directories to ignore when looking for source files.
# This pattern also affects html_static_path and html_extra_path.
exclude_patterns = []

autodoc_type_aliases = {}
autodoc_member_order = "bysource"
autodoc_inherit_docstrings = True

# -- Options for HTML output -------------------------------------------------

# The theme to use for HTML and HTML Help pages.  See the documentation for
# a list of builtin themes.
#
html_theme = "alabaster"

html_theme_options = {
    "show_powered_by": False,
    "github_user": "abersheeran",
    "github_repo": "baize",
    "github_type": "star",
    "github_banner": True,
    "show_related": False,
    "note_bg": "#FFF59C",
}

# Add any paths that contain custom static files (such as style sheets) here,
# relative to this directory. They are copied after the builtin static files,
# so a file named "default.css" will overwrite the builtin "default.css".
html_static_path = []


def setup(app):
    from recommonmark.transform import AutoStructify

    app.add_transform(AutoStructify)

    import commonmark

    def docstring(app, what, name, obj, options, lines):
        md = "\n".join(lines)
        ast = commonmark.Parser().parse(md)
        rst = commonmark.ReStructuredTextRenderer().render(ast)
        lines.clear()
        lines += rst.splitlines()

    app.connect("autodoc-process-docstring", docstring)

    from sphinx.util import inspect

    from baize.utils import cached_property

    inspect.isproperty = lambda obj: isinstance(obj, (property, cached_property))
