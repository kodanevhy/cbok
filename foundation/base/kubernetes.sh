#!/usr/bin/env bash

set -ex

HOSTNAME="cbok"
mgmt_eth=$1
# Not only the Kubernetes version is, but also relates to all
# the other toolkits version around it.
VERSION="v1.24.2"
CNI_PLUGIN_VERSION="v1.1.1"
BUILDKit_VERSION="v0.12.3"
TASK_TIMEOUT=120
# Record the key step message.
echo "Started"


get_ipv4() {
    if ! ip link show "$mgmt_eth" >/dev/null 2>&1; then
        echo "Error: interface $mgmt_eth not found" >&2
        exit 1
    fi

    ip -4 addr show "$mgmt_eth" | grep -oP '(?<=inet\s)\d+(\.\d+){3}'
}

HOST_IP=$(get_ipv4 $mgmt_eth)


# Execute and retry the operation in need which seems to be slow.
function redo {
    command=$1
    timeout=$2
    echo "Executing sub task: $command"
    if [ -z "$timeout" ];then
        timeout=$TASK_TIMEOUT
    fi
    cmd=(timeout -s SIGKILL "$timeout" $command)
    for i in $(seq 1 3)
    do
        rc=0
        "${cmd[@]}" || rc=$?
        rc=${rc:-0}
        if [ $rc -eq 0 ]; then
            break
        else
            if [ $i == 3 ]; then
                echo "Looks so slow: $command" >&2
                exit 1
            fi
        fi
    done
}


function repo_set() {
    rm -f /etc/yum.repos.d/*
    curl -o /etc/yum.repos.d/CentOS-Base.repo \
        https://mirrors.aliyun.com/repo/Centos-7.repo
    yum makecache
}


function config_ssh() {

    SSH_CONFIG="/etc/ssh/sshd_config"

    if grep -q "^UseDNS" "$SSH_CONFIG"; then
        sed -i 's/^UseDNS.*/UseDNS no/' "$SSH_CONFIG"
    else
        echo "UseDNS no" >> "$SSH_CONFIG"
    fi

    if grep -q "^GSSAPIAuthentication" "$SSH_CONFIG"; then
        sed -i 's/^GSSAPIAuthentication.*/GSSAPIAuthentication no/' "$SSH_CONFIG"
    else
        echo "GSSAPIAuthentication no" >> "$SSH_CONFIG"
    fi

    systemctl restart sshd
    echo "sshd config updated and restarted."
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
    num=$(echo "$HOST_IP" | awk -F "." '{print NF}')
    if [ $num -ne 4 ]; then
        echo "Not like IPv4: $HOST_IP" >&2
        exit 1
    fi
    local_ip=$(ip a|grep inet|grep -v 127.0.0.1|grep -v inet6|awk '{print $2}'|cut -d'/' -f1)
    if [[ $local_ip =~ $HOST_IP ]]; then
        ping -c 3 -w 3 119.29.29.29 || rc119=$?
        rc119=${rc119:-0}
        if [ $rc119 -ne 0 ]; then
            echo "Check net failed" >&2
            exit 1
        fi
    else
        echo "$HOST_IP is not configured" >&2
        exit 1
    fi
}

function pre_ipvsadm {
    redo "yum -y install ipvsadm ipset sysstat conntrack libseccomp" 600
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

function setup_nerdctl() {
    if ! getent group containerd >/dev/null; then
        groupadd containerd
    fi

    BUILDKit_DIR="/usr/local/buildkit"

    if [ ! -d "$BUILDKit_DIR" ]; then
        curl -L -o buildkit.tgz "https://github.com/moby/buildkit/releases/download/$BUILDKit_VERSION/buildkit-$BUILDKit_VERSION.linux-amd64.tar.gz"
        mkdir -p $BUILDKit_DIR
        tar -xzf buildkit.tgz -C $BUILDKit_DIR
        rm -f buildkit.tgz
        ln -sf $BUILDKit_DIR/bin/buildkitd /usr/local/bin/buildkitd
        ln -sf $BUILDKit_DIR/bin/buildctl /usr/local/bin/buildctl
    fi

    SERVICE_FILE="/etc/systemd/system/buildkit.service"
    cat <<EOF > $SERVICE_FILE
[Unit]
Description=BuildKit
After=network.target

[Service]
ExecStart=/usr/local/bin/buildkitd
Restart=always
User=root
Group=containerd

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    systemctl enable --now buildkit

    systemctl status buildkit --no-pager

    curl -L -o nerdctl-full-1.7.6-linux-amd64.tar.gz https://github.com/containerd/nerdctl/releases/download/v1.7.6/nerdctl-full-1.7.6-linux-amd64.tar.gz
    tar zxvf nerdctl-full-1.7.6-linux-amd64.tar.gz -C /usr/local
    ln -s /usr/local/bin/nerdctl /usr/bin/nerdctl
}


function setup_docker() {
    yum -y install docker-ce
    systemctl restart docker
    systemctl enable docker
}


function pre {
    config_ssh

    export HOSTNAME=$HOSTNAME
    host_exists=$(cat /etc/hosts | grep "$HOST_IP $HOSTNAME" || true)
    if [ -z "$host_exists" ];then
        echo $HOST_IP $HOSTNAME >> /etc/hosts
    fi
    echo "nameserver 119.29.29.29" > /etc/resolv.conf

    check_net
    repo_set
    sys_set
    pre_ipvsadm
    hostnamectl set-hostname $HOSTNAME

    yum -y install epel-release
    yum -y install git wget yum-utils python-pip
}

function c_crictl {
    tar zxvf crictl-$VERSION-linux-amd64.tar.gz -C /usr/local/bin
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
        echo "The runtime containerd start failed after all configurations finished"  >&2
        exit 1
    fi
}

function c_runtime {
    redo "yum-config-manager --add-repo https://mirrors.aliyun.com/docker-ce/linux/centos/docker-ce.repo"
    redo "yum -y install containerd.io" 600
    containerd config default | tee /etc/containerd/config.toml

    sed -i "s#SystemdCgroup\ \=\ false#SystemdCgroup\ \=\ true#g" /etc/containerd/config.toml
    sed -i "s#k8s.gcr.io#registry.aliyuncs.com/google_containers#g"  /etc/containerd/config.toml

    mkdir -p /opt/cni/bin && tar zxvf cni-plugins-linux-amd64-$CNI_PLUGIN_VERSION.tgz -C /opt/cni/bin
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
EOF

    toolkit_version=$(echo $VERSION | sed "s/v//g")
    redo "yum -y install kubelet-$toolkit_version kubeadm-$toolkit_version kubectl-$toolkit_version --disableexcludes=kubernetes" 600
    systemctl restart kubelet && systemctl enable --now kubelet
    if [ $? -ne 0 ]; then
        echo "Toolkit especially kubelet start failed" >&2
        exit 1
    fi
}

function ensure_kubeadm_ip {
    exists=$(cat kubeadm.yaml | grep "advertiseAddress: $HOST_IP" || true)
    if [ -n "$exists" ];then
        return
    fi
    pip install "PyYAML<6.0" -i https://pypi.tuna.tsinghua.edu.cn/simple \
        --trusted-host pypi.tuna.tsinghua.edu.cn

    py_code=$(cat << EOF
import yaml

def read_yaml(filepath):
    with open(filepath) as f:
        return yaml.load_all(f.read(), yaml.Loader)

dump_kubeadm = ""
kubeadm = read_yaml("kubeadm.yaml")
for doc in kubeadm:
    if "localAPIEndpoint" in doc:
        doc["localAPIEndpoint"]["advertiseAddress"] = "$1"
    new_doc = yaml.dump(doc, default_flow_style=False)
    with open("dump_kubeadm.yaml", "a+") as f:
        f.write(new_doc + "---\n")
EOF
    )
    python -c "$py_code"

    # The dump yaml will add a redundant line '---' at $.
    sed -i '${/^---$/d}' dump_kubeadm.yaml
    mv dump_kubeadm.yaml kubeadm.yaml
}


function apply_ingress {
    kubectl apply -f ingress-deploy.yaml
    while true; do
        sleep 3
        ingress_nginx_controller=$(kubectl get pod -n kube-system -o wide | grep ingress-nginx-controller || true)
        if [ -n "$ingress_nginx_controller" ]; then
            break
        fi
    done
    kubectl wait --for=condition=Ready pod -l app.kubernetes.io/name=ingress-nginx -l app.kubernetes.io/component=controller -n kube-system --timeout=300s
    kubectl delete job ingress-nginx-admission-create -n kube-system
    kubectl delete job ingress-nginx-admission-patch -n kube-system
}


function main {
    pre
    c_runtime
    # setup_nerdctl
    setup_docker    # Most usage for build image at remote target
    toolkits

    ensure_kubeadm_ip $HOST_IP

    ctr -n k8s.io image import --base-name docker.io/calico/cni:v3.24.1 calico-cni-v3.24.1-amd64.tar
    ctr -n k8s.io image import --base-name docker.io/calico/node:v3.24.1 calico-node-v3.24.1-amd64.tar
    ctr -n k8s.io image import --base-name docker.io/calico/kube-controllers:v3.24.1 calico-kube-controllers-v3.24.1-amd64.tar

    kubeadm config images pull --config kubeadm.yaml --kubernetes-version $VERSION
    ctr -n k8s.io images pull registry.aliyuncs.com/google_containers/pause:3.6
    ctr -n k8s.io images tag registry.aliyuncs.com/google_containers/pause:3.6 registry.k8s.io/pause:3.6
    kubeadm init --config kubeadm.yaml
    if [ $? -ne 0 ]; then
        echo "kubeadm init server failed" >&2
        exit 1
    fi

    mkdir -p $HOME/.kube && \
        cp -i /etc/kubernetes/admin.conf $HOME/.kube/config && \
        chown $(id -u):$(id -g) $HOME/.kube/config
    kubectl apply -f calico.yaml

    apply_ingress

    kubectl wait --for=condition=Ready pods --all -n kube-system --timeout=300s

    if [ $? -ne 0 ]; then
        echo "Apply calico network failed" >&2
        exit 1
    fi

    kubectl create namespace cbok

    echo "Success"
}

main
