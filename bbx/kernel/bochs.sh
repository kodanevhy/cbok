#!/usr/bin/env bash

set -ex

yum -y install wget gcc-c++ pcre pcre-devel zlib zlib-devel openssl openssl-devel

if [ -d bochs-2.6.11 ]; then
    rm -rf bochs-2.6.11
fi

if [ ! -f bochs-2.6.11.tar.gz ]; then
    wget https://pilotfiber.dl.sourceforge.net/project/bochs/bochs/2.6.11/bochs-2.6.11.tar.gz --no-check-certificate
fi
tar zxvf bochs-2.6.11.tar.gz -C .

pushd bochs-2.6.11

./configure \
--prefix=/usr/local/bochs \
--enable-debugger \
--enable-disasm \
--enable-iodebug \
--enable-x86-debugger \
--with-x \
--with-x11

make && make install

popd

echo "Succeed, now can run /usr/local/bochs/bin/bochs to start."
