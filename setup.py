import re
from pathlib import Path

from setuptools import find_packages, setup


def _read_version():
    init_py = Path(__file__).parent / "cbok" / "__init__.py"
    m = re.search(r'^__version__\s*=\s*"([^"]+)"\s*$', init_py.read_text(encoding="utf-8"), re.M)
    if not m:
        raise RuntimeError("Cannot find __version__ in cbok/__init__.py")
    return m.group(1)


setup(
    name="CBoK",
    version=_read_version(),
    packages=find_packages(),
    entry_points={
        'console_scripts': [
            'cbok=cbok.cmd.main:main',
        ],
    },
)
