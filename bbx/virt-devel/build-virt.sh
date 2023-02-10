#!/usr/bin/env bash

# For building virt develop environment.

set -ex

function main() {
    bash compile-python3.sh
    bash compile-qemu.sh
    bash compile-libvirt.sh

    echo "Building virt develop environment success."
}

main
