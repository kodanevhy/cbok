import subprocess


def execute(cmd, capture_output=True):
    if capture_output:
        return subprocess.run(cmd, shell=True, capture_output=True, text=True)
    else:
        return subprocess.run(cmd, shell=True)
