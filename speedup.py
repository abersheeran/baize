import os
from pathlib import Path

if os.name == "nt":
    from distutils.command import build_ext

    def get_export_symbols(self, ext):
        """
        Slightly modified from:
        https://github.com/python/cpython/blob/8849e5962ba481d5d414b3467a256aba2134b4da\
        /Lib/distutils/command/build_ext.py#L686-L703
        """
        # Patch from: https://bugs.python.org/issue35893
        parts = ext.name.split(".")
        if parts[-1] == "__init__":
            suffix = parts[-2]
        else:
            suffix = parts[-1]

        # from here on unchanged
        try:
            # Unicode module name support as defined in PEP-489
            # https://www.python.org/dev/peps/pep-0489/#export-hook-name
            suffix.encode("ascii")
        except UnicodeEncodeError:
            suffix = "U" + suffix.encode("punycode").replace(b"-", b"_").decode("ascii")

        initfunc_name = "PyInit_" + suffix
        if initfunc_name not in ext.export_symbols:
            ext.export_symbols.append(initfunc_name)
        return ext.export_symbols

    build_ext.build_ext.get_export_symbols = get_export_symbols

# See if mypyc is installed
try:
    from mypyc.build import mypycify
# Do nothing if mypyc is not available
except ImportError:
    # Got to provide this function. Otherwise, poetry will fail
    def build(setup_kwargs):
        pass


# Cython is installed. Compile
else:
    from distutils.command.build_ext import build_ext

    # This function will be executed in setup.py:
    def build(setup_kwargs):
        setup_kwargs.update(
            {
                "ext_modules": mypycify(
                    ["--ignore-missing-imports"]
                    + list(map(str, Path("baize").glob("**/*.py"))),
                ),
                "cmdclass": {"build_ext": build_ext},
            }
        )
