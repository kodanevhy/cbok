#!/usr/bin/env bash

# For compiling libvirt-6.0.0.

set -ex

echo "Suggest that compile libvirt 6.0.0 with Python 3.6.8 and CentOS 7.9(3.10.0-1160.el7.x86_64) based distribution."
which python3
centos_release=$(cat /etc/redhat-release | grep CentOS)
if [ ! "$centos_release" ]; then
    exit 0
fi

pip3 uninstall -y rst2html5
if [ -d libvirt-6.0.0 ]; then
    rm -rf libvirt-6.0.0
fi

yum -y install glib2-devel gnutls-devel libnl3-devel libxml2-devel device-mapper-devel libpciaccess-devel
pip3 install rst2html5

# Avoid an ImportError.
# In self testing, the importlib.metadata call always failed in rst2html5 package,
# may caused by the rst2html5 package version dependency, it's no better solution
# yet. If the ImportError occurred, just replace it to
# importlib_metadata.metadata.
sed -i 's/from importlib import metadata/try:\n    from importlib import metadata\nexcept ImportError:\n    import importlib_metadata as metadata/g' /usr/local/lib/python3.6/site-packages/rst2html5/__init__.py

if [ ! -f libvirt-official-6.0.0.tar.xz ]; then
    # Download the source code from official website "libvirt.org/sources" instead
    # of git repository such as gitlab or github etc. The consideration for this
    # is that the source code from official website already includes the
    # executable script "configure" for compiling.
    wget https://libvirt.org/sources/libvirt-6.0.0.tar.xz --no-check-certificate -O libvirt-official-6.0.0.tar.xz
fi
tar xvf libvirt-official-6.0.0.tar.xz -C . && cd libvirt-6.0.0

# Find all the "--" flags to replace it to be "-" when compile docs, because
# it may cause a parser error: "Double hyphen within comment".
pushd docs/manpages
for filename in $(ls ./*);do
    orig_cmd="$(cat $filename | { grep keymap-gen || true; })"
    if [ ! "$orig_cmd" ];then
        continue
    fi
    converted="$(echo ${orig_cmd//--/-})"
    sed -i "/keymap-gen/c$converted" $filename
    sed -i "s/keymap-gen/     &/" $filename
done
popd

mkdir build && pushd build

../autogen.sh --system

make
make install

popd
echo "Compile libvirt-6.0.0 success."
