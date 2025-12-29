#!/usr/bin/env bash

set -ex

function die() {
    echo "error: $1" >&2
    exit 1
}


function distro() {
    # Suggest that format with CentOS x.x(Major.Minor version) or
    # Ubuntu xx.xx, and notice letter case.
    os_version=$1
    python_version=$2

    echo "Forced with Python $python_version and $os_version based distribution."
    python3_version_env=$(echo "$(python3 --version)" | grep $python_version)
    if [ ! "$python3_version_env" ]; then
        die "Python version does not match, required $python_version, but $python3_version_env."
    fi

    os_release_env=$(echo "$(lsb_release -a | grep $os_version)" | grep "Description")
    if [ ! "$os_release" =~ "$os_release_env" ]; then
        die "OS release does not match, required $os_version, but $os_release_env."
    fi
}
