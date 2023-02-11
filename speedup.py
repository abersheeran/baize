import os
from pathlib import Path

if os.environ.get("WITHOUT_MYPYC", "False") != "False":

    def build(setup_kwargs):
        pass

else:

    def build(setup_kwargs):
        try:
            from mypyc.build import mypycify
        except ImportError:
            print("Error in import mypyc.build, skip build.", flush=True)
            return

        modules = list(
            filter(
                lambda path: path.replace("\\", "/")
                not in (
                    "baize/multipart_helper.py",
                    # ASGI
                    "baize/asgi/requests.py",
                    "baize/asgi/responses.py",
                    "baize/asgi/routing.py",
                    "baize/asgi/shortcut.py" if os.name == "nt" else None,
                    "baize/asgi/staticfiles.py",
                    "baize/asgi/websocket.py",
                    # WSGI
                    "baize/wsgi/requests.py",
                    "baize/wsgi/responses.py",
                    "baize/wsgi/routing.py",
                    "baize/wsgi/shortcut.py" if os.name == "nt" else None,
                    "baize/wsgi/staticfiles.py",
                ),
                map(str, Path("baize").glob("**/*.py")),
            )
        )
        setup_kwargs.update(
            {
                "ext_modules": mypycify(["--ignore-missing-imports", *modules]),
            }
        )
