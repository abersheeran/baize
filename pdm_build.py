import os
from pathlib import Path


def pdm_build_update_setup_kwargs(context, setup_kwargs):
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
                "baize/asgi/middleware.py",
                "baize/asgi/requests.py",
                "baize/asgi/responses.py",
                "baize/asgi/routing.py",
                "baize/asgi/shortcut.py" if os.name == "nt" else None,
                "baize/asgi/staticfiles.py",
                "baize/asgi/websocket.py",
                # WSGI
                "baize/wsgi/middleware.py",
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
