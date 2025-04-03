#!/usr/bin/env bash

# For compiling qemu-4.2.0.

set -ex

yum install -y gtk3-devel spice-server spice-protocol spice-server-devel bzip2 usbredir-devel numactl-devel

cd local

if [ -d qemu-4.2.0 ]; then
    rm -rf qemu-4.2.0
fi

if [ ! -f qemu-4.2.0.tar.xz ]; then
    wget https://download.qemu.org/qemu-4.2.0.tar.xz
fi
tar xvf qemu-4.2.0.tar.xz -C . && cd qemu-4.2.0

mkdir build && cd build

CC=gcc ../configure --prefix=/ --target-list=x86_64-softmmu --enable-usb-redir --enable-debug --enable-vnc --enable-gtk --enable-kvm --enable-numa --enable-tools --enable-spice

make
make install

echo "Compile qemu-4.2.0 success."
