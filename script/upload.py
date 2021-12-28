import os
import subprocess
from pathlib import Path

here = Path(__file__).absolute().parent.parent

package_name = "baize"


def get_version(package: str = package_name) -> str:
    """
    Return version.
    """
    _globals: dict = {}
    exec((here / package / "__version__.py").read_text(encoding="utf8"), _globals)
    return _globals["__version__"]


os.chdir(here)
subprocess.check_call(f"pdm version {get_version()}", shell=True)
subprocess.check_call(f"git add {package_name}/__version__.py pyproject.toml", shell=True)
subprocess.check_call(f'git commit -m "v{get_version()}"', shell=True)
subprocess.check_call("git push", shell=True)
subprocess.check_call("git tag v{0}".format(get_version()), shell=True)
subprocess.check_call("git push --tags", shell=True)
