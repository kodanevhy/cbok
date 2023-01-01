#!/usr/bin/env bash

set -ex

HOSTNAME="workspace"
HOST_IP=$1
# Not only the Kubernetes version is, but also relates to all
# the other toolkits version around it.
VERSION="v1.24.2"
CNI_PLUGIN_VERSION="v1.1.1"
LOCAL_DIRECTORY="local"
TASK_TIMEOUT=120
# Record the key step message.
LOG_HOOK="Task started."

# Execute and retry the operation in need which seems to be slow.
function redo {
    LOG_HOOK="Executing sub task: $1."
    cmd="timeout -s SIGKILL $TASK_TIMEOUT "$1
    for i in $(seq 1 3)
    do
        $cmd
        if [ $? -eq 0 ]; then
            break
        else
            if [ $i == 3 ]; then
                LOG_HOOK="Looks so slow, result in executing sub task for 3 times failed: $1."
                exit 1
            fi
        fi
    done
}

function sys_set {
    systemctl stop firewalld && systemctl disable firewalld
    setenforce 0 && sed -i 's/SELINUX=enforcing/SELINUX=disabled/g' /etc/selinux/config
    swapoff -a && sed -ri 's/.*swap.*/#&/' /etc/fstab
    cat <<EOF | sudo tee /etc/modules-load.d/k8s.conf
overlay
br_netfilter
EOF
    sudo modprobe overlay
    sudo modprobe br_netfilter
    systemctl restart systemd-modules-load.service

    # sysctl params required by setup, params persist across reboots.
    cat <<EOF | sudo tee /etc/sysctl.d/k8s.conf
net.bridge.bridge-nf-call-iptables  = 1
net.bridge.bridge-nf-call-ip6tables = 1
net.ipv4.ip_forward                 = 1
EOF
    # Apply sysctl params without reboot.
    sudo sysctl --system
    sysctl -w net.ipv4.ip_forward=1
}

function check_net {
    num=$(echo "$1" | awk -F "." '{print NF}')
    if [ $num -ne 4 ]; then
        LOG_HOOK="Not like IPv4: $1."
        exit 1
    fi
    local_ip=$(ifconfig -a|grep inet|grep -v 127.0.0.1|grep -v inet6|awk '{print $2}')
    if [[ $local_ip =~ $1 ]]; then
        ping -c 3 114.114.114.114 &> /dev/null
        if [  $? -ne 0 ]; then
            LOG_HOOK="Check net failed."
            exit 1
        fi
    else
        LOG_HOOK="IP $1 is not configured."
        exit 1
    fi
}

function pre_ipvsadm {
    redo "yum -y install ipvsadm ipset sysstat conntrack libseccomp"
    cat >> /etc/modules-load.d/ipvs.conf << EOF
ip_vs
ip_vs_rr
ip_vs_wrr
ip_vs_sh
nf_conntrack
ip_tables
ip_set
xt_set
ipt_set
ipt_rpfilter
ipt_REJECT
ipip
EOF
    systemctl restart systemd-modules-load.service
}

function pre {
    check_net
    sys_set
    pre_ipvsadm
    hostnamectl set-hostname $HOSTNAME
    echo $HOST_IP $HOSTNAME >> /etc/hosts
}

function c_crictl {
    tar zxvf $LOCAL_DIRECTORY/crictl-$VERSION-linux-amd64.tar.gz -C /usr/local/bin
    cat <<EOF | tee /etc/crictl.yaml
runtime-endpoint: "unix:///run/containerd/containerd.sock"
image-endpoint: "unix:///run/containerd/containerd.sock"
timeout: 10
debug: false
pull-image-on-create: false
disable-pull-on-run: false
EOF
    systemctl restart containerd
    if [ $? -ne 0 ]; then
        LOG_HOOK="The runtime containerd start failed after all configurations finished."
        exit 1
    fi
}

function c_runtime {
    yum-config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
    redo "yum -y install containerd.io"
    containerd config default | tee /etc/containerd/config.toml

    sed -i "s#SystemdCgroup\ \=\ false#SystemdCgroup\ \=\ true#g" /etc/containerd/config.toml
    sed -i "s#k8s.gcr.io#registry.aliyuncs.com/google_containers#g"  /etc/containerd/config.toml

    mkdir -p /opt/cni/bin && tar zxvf $LOCAL_DIRECTORY/cni-plugins-linux-amd64-$CNI_PLUGIN_VERSION.tgz -C /opt/cni/bin
    systemctl daemon-reload && systemctl enable --now containerd

    c_crictl
}

function toolkits {
    cat > /etc/yum.repos.d/kubernetes.repo << EOF
[kubernetes]
name=Kubernetes
baseurl=https://mirrors.aliyun.com/kubernetes/yum/repos/kubernetes-el7-x86_64
enabled=1
gpgcheck=0
repo_gpgcheck=0
gpgkey=https://mirrors.aliyun.com/kubernetes/yum/doc/yum-key.gpg https://mirrors.aliyun.com/kubernetes/yum/doc/rpm-package-key.gpg
EOF

    toolkit_version=$(echo $VERSION | sed "s/v//g")
    redo "yum -y install kubelet-$toolkit_version kubeadm-$toolkit_version kubectl-$toolkit_version --disableexcludes=kubernetes"
    systemctl restart kubelet && systemctl enable --now kubelet
    if [ $? -ne 0 ]; then
        LOG_HOOK="Toolkit especially kubelet start failed."
        exit 1
    fi
}

function ensure_kubeadm_ip {
    py_code=$(cat << EOF
import yaml

def read_yaml(filepath):
    with open(filepath) as f:
        return yaml.load_all(f.read(), yaml.Loader)

dump_kubeadm = ""
kubeadm = read_yaml("$LOCAL_DIRECTORY/kubeadm.yaml")
for doc in kubeadm:
    if "localAPIEndpoint" in doc:
        doc["localAPIEndpoint"]["advertiseAddress"] = "$1"
    new_doc = yaml.dump(doc, default_flow_style=False)
    with open("$LOCAL_DIRECTORY/dump_kubeadm.yaml", "a+") as f:
        f.write(new_doc + "---\n")
EOF
    )
    python -c "$py_code"

    # The dump yaml will add a redundant line '---' at $.
    sed -i "$d" $LOCAL_DIRECTORY/dump_kubeadm.yaml
}

function main {
    pre
    c_runtime
    toolkits

    ensure_kubeadm_ip $HOST_IP
    kubeadm init --config $LOCAL_DIRECTORY/dump_kubeadm.yaml
    if [ $? -ne 0 ]; then
        LOG_HOOK="kubeadm init server failed."
        exit 1
    fi
    mkdir -p $HOME/.kube && \
        cp -i /etc/kubernetes/admin.conf $HOME/.kube/config && \
        chown $(id -u):$(id -g) $HOME/.kube/config
    kubectl apply -f $LOCAL_DIRECTORY/calico.yaml
    if [ $? -ne 0 ]; then
        LOG_HOOK="Apply calico network failed."
        exit 1
    fi

    kubectl taint node $HOSTNAME node-role.kubernetes.io/control-plane-

    LOG_HOOK="Task success."
}

main