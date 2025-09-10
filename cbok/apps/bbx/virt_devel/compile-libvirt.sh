#!/usr/bin/env bash

# For compiling libvirt-6.0.0.

set -ex

pip_list=$(pip3 list)
if test "$(echo "$pip_list" | grep rst2html5)";then
    pip3 uninstall -y rst2html5
fi
if test "$(echo "$pip_list" | grep importlib_metadata)";then
    pip3 uninstall -y importlib_metadata
fi

yum -y install wget gcc apr-devel apr-util-devel atk-devel bzip2-devel cairo-devel cairo-gobject-devel \
    cyrus-sasl-devel device-mapper-devel elfutils-libelf-devel expat-devel fontconfig-devel freetype-devel \
    fribidi-devel gdbm-devel gdk-pixbuf2-devel glib2-devel glibc-devel gmp-devel gnutls-devel \
    gobject-introspection-devel graphite2-devel gtk2-devel harfbuzz-devel httpd-devel keyutils-libs-devel \
    krb5-devel libX11-devel libXau-devel libXcomposite-devel libXcursor-devel libXdamage-devel libXext-devel \
    libXfixes-devel libXft-devel libXi-devel libXinerama-devel libXrandr-devel libXrender-devel libXxf86vm-devel \
    libcom_err-devel libcurl-devel libdb-devel libdrm-devel libevent-devel libffi-devel libgcrypt-devel \
    libglvnd-core-devel libglvnd-devel libgpg-error-devel libicu-devel libjpeg-turbo-devel libnl3-devel \
    libpciaccess-devel libpng-devel libselinux-devel libsepol-devel libstdc++-devel libtasn1-devel libuuid-devel \
    libva-devel libverto-devel libvirt-devel libxcb-devel libxml2-devel libxslt-devel libyaml-devel mariadb-devel \
    mesa-khr-devel mesa-libEGL-devel mesa-libGL-devel ncurses-devel nettle-devel numactl-devel openldap-devel \
    openssl-devel p11-kit-devel pango-devel pcre-devel perl-devel pixman-devel postgresql-devel python-devel \
    readline-devel sqlite-devel systemd-devel systemtap-sdt-devel tcl-devel tk-devel wayland-devel \
    xorg-x11-proto-devel.noarch xz-devel yajl-devel zlib-devel dnsmasq ebtables

pip3 install --index https://pypi.tuna.tsinghua.edu.cn/simple/ rst2html5
pip3 install --index https://pypi.tuna.tsinghua.edu.cn/simple/ importlib_metadata

# Avoid an ImportError.
# In self testing, the importlib.metadata call always failed in rst2html5 package,
# may caused by the rst2html5 package version dependency, it's no better solution
# yet. If the ImportError occurred, just replace it to
# importlib_metadata.metadata.
sed -i 's/from importlib import metadata/try:\n    from importlib import metadata\nexcept ImportError:\n    import importlib_metadata as metadata/g' /usr/lib/python3.6/site-packages/rst2html5/__init__.py

cd local

if [ -d libvirt-6.0.0 ]; then
    rm -rf libvirt-6.0.0
fi

if [ ! -f libvirt-6.0.0.tar.xz ]; then
    # Download the source code from official website "libvirt.org/sources" instead
    # of git repository such as gitlab or github etc. The consideration for this
    # is that the source code from official website already includes the
    # executable script "configure" for compiling.
    wget https://libvirt.org/sources/libvirt-6.0.0.tar.xz --no-check-certificate -O libvirt-6.0.0.tar.xz
fi
tar xvf libvirt-6.0.0.tar.xz -C . && cd libvirt-6.0.0

# Find all the "--" flags to replace it to be "-" in compile docs, because
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

../configure --prefix=/ --enable-debug=yes --with-numactl

make
make install

popd
echo "Compile libvirt-6.0.0 success."
