from setuptools import setup, find_packages

from cbok import __version__

setup(
    name="CBoK",
    version=__version__,
    packages=find_packages(),
    entry_points={
        'console_scripts': [
            'cbok=cbok.cmd.base:main',
        ],
    },
)
