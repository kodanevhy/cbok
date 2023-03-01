#!/usr/bin/env bash

# For compiling Python3.6.

set -ex

yum -y install wget gcc-c++ pcre pcre-devel zlib zlib-devel openssl openssl-devel

cd local

if [ -d Python-3.6.6 ]; then
    rm -rf Python-3.6.6
fi

if [ ! -f Python-3.6.6.tar.xz ]; then
    wget https://www.python.org/ftp/python/3.6.6/Python-3.6.6.tar.xz --no-check-certificate
fi
tar xvf Python-3.6.6.tar.xz -C .

cd Python-3.6.6

./configure --prefix=/
make && make install

echo "Compile Python-3.6 success."