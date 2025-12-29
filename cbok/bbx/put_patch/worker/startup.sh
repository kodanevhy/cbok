#!/bin/bash
set -ex


function finalize_startup() {
    address="$1"
    pod_name=$2
    container=$3
    startup_script=$4
    filename=$(basename "$startup_script")
    gtimeout -s KILL 10 ssh -n root@$address "kubectl exec -n openstack $pod_name -c $container -- sudo cp $startup_script /opt/$filename"
    gtimeout -s KILL 10 ssh -n root@$address "kubectl exec -n openstack $pod_name -c $container -- sudo chmod 777 /opt/$filename"
    gtimeout -s KILL 10 ssh -n root@$address "kubectl exec -n openstack $pod_name -c $container -- sudo sed -i '2d' /opt/$filename"
}


function remote_exec_via_jump() {
    local jump=$1
    shift
    ssh_key="ssh -i ~/.ssh/id_rsa.roller root@10.20.0.3"
    sshpass -p "easystack" ssh -n root@"$jump" $ssh_key $@
}


function finalize_startup_os_in_os() {
    address="$1"
    pod_name="$2"
    container="$3"
    startup_script="$4"
    filename=$(basename "$startup_script")
    remote_exec_via_jump "$address" kubectl exec -n openstack "$pod_name" -c "$container" -- sudo cp $startup_script /opt/$filename
    remote_exec_via_jump "$address" kubectl exec -n openstack "$pod_name" -c "$container" -- sudo chmod 777 /opt/$filename
    remote_exec_via_jump "$address" kubectl exec -n openstack "$pod_name" -c "$container" -- sudo sed -i '2d' /opt/$filename
}
