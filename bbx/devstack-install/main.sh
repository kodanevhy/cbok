#!/usr/bin/env bash

# WARNING\
# WARNING : HAVEN'T TESTED PASS, please referred to https://github.com/kodanevhy/nozz.git
# WARNING : to acquire the installation solutions.
# WARNING/
# For installing OpenStack Xena by Devstack.

set -ex

source ../common.sh

distro "Ubuntu 22.04" "3.7"


function add_user() {
    sudo useradd -s /bin/bash -d /opt/stack -m stack
    sudo chmod 755 /opt/stack
    echo "stack ALL=(ALL) NOPASSWD: ALL" | sudo tee /etc/sudoers.d/stack
    sudo -u stack -i
}


function main() {
    add_user

    sudo apt install -y git && sudo git config --global http.sslverify false

    sudo rm -rf devstack
    sudo git clone https://opendev.org/openstack/devstack

    sudo rm -rf /opt/stack/devstack/
    sudo mv devstack /opt/stack/
    sudo chmod 777 /opt/stack/devstack/

    sudo cp example/local.conf /opt/stack/devstack/
    sudo cp local/etcd-v3.3.12-linux-amd64.tar.gz /opt/stack/devstack/files/
    # Last time changing the directory owner.
    sudo chown -R stack:stack /opt/stack
    cd /opt/stack/devstack/
    FORCE=yes ./stack.sh
}

main