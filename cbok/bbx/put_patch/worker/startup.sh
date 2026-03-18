#!/bin/bash
set -ex

base_path=$(python -c "from cbok import settings; print(settings.BASE_DIR)")
source "$base_path/scriptlet/bootstrap.sh"


function finalize_startup() {
    address="$1"
    pod_name=$2
    container=$3
    startup_script=$4
    filename=$(basename "$startup_script")
    cbok_timeout 10 ssh -n root@$address "kubectl exec -n openstack $pod_name -c $container -- sudo cp $startup_script /opt/$filename"
    cbok_timeout 10 ssh -n root@$address "kubectl exec -n openstack $pod_name -c $container -- sudo chmod 777 /opt/$filename"
    cbok_timeout 10 ssh -n root@$address "kubectl exec -n openstack $pod_name -c $container -- sudo sed -i '2d' /opt/$filename"
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
