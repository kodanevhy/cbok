from setuptools import setup, find_packages

setup(
    name="CBoK",
    version="0.1",
    packages=find_packages(),
    entry_points={
        'console_scripts': [
            'cbok-bbx=cbok.cmd.bbx_manage:main',
        ],
    },
)
