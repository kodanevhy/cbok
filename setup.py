from setuptools import setup, find_packages

setup(
    name="CBoK",
    version="0.3",
    packages=find_packages(),
    entry_points={
        'console_scripts': [
            'cbok=cbok.cmd.base:main',
        ],
    },
)
