#!/bin/bash

set -ex

floating_ip="$1"
address="$2"
hostname="$3"
eth="$4"
block="$5"

base_path=$(python -c "from cbok import settings; print(settings.BASE_DIR)")
source "$base_path/scriptlet/bootstrap.sh"

if ! remote_exec "$address" grep -q "CentOS Linux release 8.5.2111" /etc/redhat-release; then
    die "OS not support, refs to https://github.com/kodanevhy/nozz"
fi

openstack_home="/root/nozz/Xena/OpenStack-Xena-Single"

remote_bash "$address" 'sed -i -e "s|mirrorlist=|#mirrorlist=|g" /etc/yum.repos.d/CentOS-*'
remote_bash "$address" 'sed -i -e "s|#baseurl=http://mirror.centos.org|baseurl=https://mirrors.aliyun.com|g" /etc/yum.repos.d/CentOS-*'

remote_exec "$address" yum -y install git

ss5_client_setup_remote_from_proxy_file "$address" "cbok/bbx/openstack/proxy" "cbok/bbx/openstack/shadowsocks2-linux" 1080

remote_bash "$address" '
if [ ! -f /root/nozz/READY ]; then
    set -ex
    rm -rf /root/nozz
    git clone https://github.com/kodanevhy/nozz.git /root/nozz
    chmod -R 777 /root/nozz
    echo READY > /root/nozz/READY
fi
'

remote_exec "$address" sed -i "s/^HOST_IP=.*/HOST_IP=${address}/" "$openstack_home/openrc.sh"
remote_exec "$address" sed -i "s/^FLOATING_IP=.*/FLOATING_IP=${floating_ip}/" "$openstack_home/openrc.sh"
remote_exec "$address" sed -i "s/^HOST_NAME=.*/HOST_NAME=${hostname}/" "$openstack_home/openrc.sh"
remote_exec "$address" sed -i "s/^INTERFACE_NAME=.*/INTERFACE_NAME=${eth}/" "$openstack_home/openrc.sh"
remote_exec "$address" sed -i "s/^BLOCK_DISK=.*/BLOCK_DISK=${block}/" "$openstack_home/openrc.sh"

run_step() {
    local script=$1
    local done_flag=$2

    result=$(remote_bash "$address" "cd $openstack_home && ./$script")
    if [[ ! "$result" =~ "$done_flag" ]]; then
        die "FAILED: $script"
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
