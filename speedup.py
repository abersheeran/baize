import os
import sys

if os.environ.get("WITHOUT_MYPYC", "False") == "False":
    # See if mypyc is installed
    try:
        from mypyc.build import mypycify
    # Do nothing if mypyc is not available
    except ImportError:
        print("Error in import mypyc.build, skip build.", flush=True)
    # mypyc is installed. Compile
    else:
        from pathlib import Path

        # This function will be executed in setup.py:
        def build(setup_kwargs):
            modules = list(
                filter(
                    lambda path: path.replace("\\", "/")
                    not in (
                        "baize/asgi.py",
                        "baize/wsgi.py",
                    ),
                    map(str, Path("baize").glob("**/*.py")),
                )
            )
            setup_kwargs.update(
                {
                    "ext_modules": mypycify(["--ignore-missing-imports", *modules]),
                }
            )


try:
    build
except NameError:
    # Got to provide this function. Otherwise, pdm will fail
    def build(setup_kwargs):
        pass
