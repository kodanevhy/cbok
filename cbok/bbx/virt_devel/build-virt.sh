#!/usr/bin/env bash

# For building virt develop environment.

set -ex

base_path=$(python -c "from cbok import settings; print(settings.BASE_DIR)")
source "$base_path/utils.sh"

distro "CentOS 7.9" "3.6"

function main() {
    code=$1
    if [ ! "$code" ]; then
        die "Execute code must be given, please select in [0, 1, 2, 3]."
    fi

    if [ "$code" -eq "0" ]; then
        bash compile-python3.sh
        bash compile-qemu.sh
        bash compile-libvirt.sh
        echo "Building virt develop environment success."
    elif [ "$code" -eq "1" ]; then
        bash compile-python3.sh
    elif [ "$code" -eq "2" ]; then
        bash compile-qemu.sh
    elif [ "$code" -eq "3" ]; then
        bash compile-libvirt.sh
    fi
}

main "$1"
