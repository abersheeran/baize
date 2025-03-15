import re
from pathlib import Path

if __name__ == "__main__":
    pyproject_toml = Path("pyproject.toml")
    without_build = "\n".join(
        map(
            lambda line: re.sub(r'^(run-setuptools = true)', r"# \1", line),
            pyproject_toml.read_text().splitlines(),
        )
    )
    pyproject_toml.write_text(without_build)
