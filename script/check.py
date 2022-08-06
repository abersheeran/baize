import subprocess

source_dirs = "baize tests"
subprocess.check_call(f"pdm run isort --check --diff {source_dirs}", shell=True)
subprocess.check_call(f"pdm run black --check --diff {source_dirs}", shell=True)
subprocess.check_call(f"pdm run flake8 --ignore W503,E203,E501,E731 {source_dirs}", shell=True)
subprocess.check_call(f"pdm run mypy {source_dirs}", shell=True)
