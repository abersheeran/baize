import subprocess

source_dirs = "baize tests"
subprocess.check_call(f"pdm run isort {source_dirs}", shell=True)
subprocess.check_call(f"pdm run black {source_dirs}", shell=True)
