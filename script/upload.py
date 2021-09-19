import os
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
os.system(f"pdm version {get_version()}")
os.system(f"git add {package_name}/__version__.py pyproject.toml")
os.system(f'git commit -m "v{get_version()}"')
os.system("git push")
os.system("git tag v{0}".format(get_version()))
os.system("git push --tags")
