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
                        "baize/wsgi.py" if os.name == "nt" else "",
                        # Build with mypyc would fail on these files
                        # ------------------------------------------
                        # Fatal Python error: Segmentation fault
                        "baize/requests.py",
                        # because compile delete_cookies is not supported in python 3.6-3.8
                        # and I don't know how to fix it
                        "baize/responses.py" if sys.version_info[:2] < (3, 9) else "",
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
