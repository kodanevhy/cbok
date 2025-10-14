import os
import subprocess

with open('requirements.txt') as requirements:
    packages = requirements.readlines()

# stage in memory first
origin_packages = packages

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
for i, package in enumerate(packages):
    if package.startswith('xadmin @ file://'):
        packages[i] = 'xadmin @ file://%s/xadmin-django2.zip\n' % BASE_DIR

with open('requirements.txt', 'w') as requirements:
    requirements.writelines(packages)

install_cmd = 'pip3 install -r requirements.txt'

try:
    completed_process = subprocess.run(
        install_cmd,
        shell=True,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    print(completed_process.stdout)
except subprocess.CalledProcessError as e:
    print("STDOUT:\n", e.stdout)
    print("STDERR:\n", e.stderr)
    exit(1)
else:
    with open('requirements.txt', 'w') as f:
        f.writelines(origin_packages)
