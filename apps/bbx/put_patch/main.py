import sys

import utils

project_supported = {
    'nova': 'Python3',
    'nova-dashboard-api': 'Python2'
}

project = "nova"

python_style = None

try:
    python_style = project_supported[project]
except KeyError:
    print("error: " + "project not supported")
    sys.exit(1)

# analysis modified file path
# 1.cd project directory
# 2.git commit --amend
result = utils.execute(["bash", "-c",
                        "source analysis_commit.sh; get_diff " + project])
if result.stderr:
    print("error: " + result.stderr)
    sys.exit(1)

# get local file path
fs = []
for filename in result.stdout:
    fs.append(filename)

# Initial pod
# 1.startup script sleep infinity
# 2.decrease deployment app
# 3.delete pod
# 4.install compyle6 if python2

# get target pod name

# copy total file to target

# change startup script

# user execute startup script
