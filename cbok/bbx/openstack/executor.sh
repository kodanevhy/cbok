#!/bin/bash

set -ex

floating_ip="$1"
address="$2"
hostname="$3"
eth="$4"
block="$5"

if ! ssh root@$address 'grep -q "CentOS Linux release 8.5.2111" /etc/redhat-release'; then
    echo "OS not support, refs to https://github.com/kodanevhy/nozz"
    exit 1
fi

openstack_home="/root/nozz/Xena/OpenStack-Xena-Single"

ssh root@$address 'sed -i -e "s|mirrorlist=|#mirrorlist=|g" /etc/yum.repos.d/CentOS-*'
ssh root@$address 'sed -i -e "s|#baseurl=http://mirror.centos.org|baseurl=https://mirrors.aliyun.com|g" /etc/yum.repos.d/CentOS-*'

ssh root@$address yum -y install git

if [ -f "cbok/bbx/openstack/proxy" ]; then
    cipher=$(grep '^cipher=' cbok/bbx/openstack/proxy | cut -d= -f2)
    password=$(grep '^password=' cbok/bbx/openstack/proxy | cut -d= -f2)
    vps_server=$(grep '^vps_server=' cbok/bbx/openstack/proxy | cut -d= -f2)
    port=$(grep '^port=' cbok/bbx/openstack/proxy | cut -d= -f2)

    echo "Checking remote socks5 service..."

    if ssh root@$address "ss -lnt | grep -q ':1080'"; then
        echo "Remote socks5 already running, skip proxy setup"
    else
        echo "Building proxy client (go-shadowsocks2)"

        scp cbok/bbx/openstack/shadowsocks2-linux root@$address:/root/

        ssh root@$address '
set -e

chmod 755 /root/shadowsocks2-linux

if ss -lnt | grep -q ":1080"; then
    echo "socks5 is already running"
else
    echo "socks5 not running, starting shadowsocks"

    nohup /root/shadowsocks2-linux \
        -c "ss://'"$cipher"':'"$password"'@'"$vps_server"':'"$port"'" \
        -verbose -socks :1080 \
        >/var/log/shadowsocks.log 2>&1 &

    for i in {1..5}; do
        sleep 1
        if ss -lnt | grep -q ":1080"; then
            echo "Shadowsocks started and listening on 1080"
            break
        fi
        if [ $i -eq 5 ]; then
            echo "ERROR: Shadowsocks failed to start"
            exit 1
        fi
    done
fi

git config --global http.proxy  "socks5://127.0.0.1:1080"
git config --global https.proxy "socks5://127.0.0.1:1080"
'
    fi
else
    echo "No config found, skipping proxy build"
fi

ssh root@$address '
if [ ! -f /root/nozz/READY ]; then
    set -ex
    rm -rf /root/nozz
    git clone https://github.com/kodanevhy/nozz.git /root/nozz
    chmod -R 777 /root/nozz
    echo READY > /root/nozz/READY
fi
'

ssh root@$address "sed -i 's/^HOST_IP=.*/HOST_IP=${address}/' $openstack_home/openrc.sh"
ssh root@$address "sed -i 's/^FLOATING_IP=.*/FLOATING_IP=${floating_ip}/' $openstack_home/openrc.sh"
ssh root@$address "sed -i 's/^HOST_NAME=.*/HOST_NAME=${hostname}/' $openstack_home/openrc.sh"
ssh root@$address "sed -i 's/^INTERFACE_NAME=.*/INTERFACE_NAME=${eth}/' $openstack_home/openrc.sh"
ssh root@$address "sed -i 's/^BLOCK_DISK=.*/BLOCK_DISK=${block}/' $openstack_home/openrc.sh"

run_step() {
    local script=$1
    local done_flag=$2

    result=$(ssh root@$address "cd $openstack_home && ./$script")
    if [[ ! "$result" =~ "$done_flag" ]]; then
        echo "FAILED: $script"
        exit 1
    else
        echo "$script" success
    fi

    sleep 3
}

steps=(
  "iaas-pre-host.sh:Done-iaas-pre-host"
  "iaas-install-mysql.sh:Done-iaas-install-mysql"
  "iaas-install-keystone.sh:Done-iaas-install-keystone"
  "iaas-install-glance.sh:Done-iaas-install-glance"
  "iaas-install-placement.sh:Done-iaas-install-placement"
  "iaas-install-nova.sh:Done-iaas-install-nova"
  "iaas-install-neutron.sh:Done-iaas-install-neutron"
  "iaas-install-dashboard.sh:Done-iaas-install-dashboard"
  "iaas-install-cinder.sh:Done-iaas-install-cinder"
  "iaas-install-barbican.sh:Done-iaas-install-barbican"
)

for step in "${steps[@]}"; do
    IFS=: read -r script done_flag <<< "$step"
    run_step "$script" "$done_flag"
done


echo "Congradulations! ;)"
