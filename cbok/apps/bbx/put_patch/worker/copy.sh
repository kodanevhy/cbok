#!/bin/bash
set -ex

target='/tmp/zztestcbok/'

function copy() {
    address=$1
    pod_name=$2
    container=$3
    files_json="$4"
    gtimeout -s KILL 10 ssh root@$address "mkdir -p $target"
    echo "$files_json" | python3 -c "
import json, sys
files = json.loads(sys.stdin.read())
for f in files:
    print(f['status'], f['path'], f['remote_path'])
    " | while read status src dst; do

        case "$status" in
            A|M)
                echo "Processing $status $src -> $dst"

                scp "$src" root@$address:"$target"

                filename=$(basename "$src")
                remote_tmp="/tmp/$filename"
                remote_dir=$(dirname "$dst")

                gtimeout -s KILL 10 ssh -n root@$address "kubectl cp $target$filename -n openstack $pod_name:$remote_tmp -c $container"
                gtimeout -s KILL 10 ssh -n root@$address "kubectl exec -n openstack $pod_name -c $container -- mkdir -p $remote_dir"
                gtimeout -s KILL 10 ssh -n root@$address "kubectl exec -n openstack $pod_name -c $container -- sudo mv $remote_tmp $dst"
                ;;

            D)
                echo Deleting $dst or $dst"c" in pod $pod_name
                gtimeout -s KILL 10 ssh -n root@$address "kubectl exec -n openstack $pod_name -- rm -f $dst"
                dst="$dst"c
                gtimeout -s KILL 10 ssh -n root@$address "kubectl exec -n openstack $pod_name -- rm -f $dst"
                ;;

            *)
                echo "Unknown status: $status"
                ;;
        esac
    done
}


function cleanup() {
    gtimeout -s KILL 10 ssh root@$address "rm -rf $target"
}


function remote_exec_via_jump() {
    local jump=$1
    shift
    ssh_key="ssh -i ~/.ssh/id_rsa.roller root@10.20.0.3"
    sshpass -p "easystack" ssh -n root@"$jump" $ssh_key $@
}


function copy_os_in_os() {
    address=$1
    pod_name=$2
    container=$3
    files_json="$4"
    gtimeout -s KILL 10 sshpass -p "easystack" ssh root@$address "mkdir -p $target"
    echo "$files_json" | python3 -c "
import json, sys
files = json.loads(sys.stdin.read())
for f in files:
    print(f['status'], f['path'], f['remote_path'])
    " | while read status src dst; do

        case "$status" in
            A|M)
                echo "Processing $status $src -> $dst"

                gtimeout -s KILL 10 sshpass -p "easystack" scp "$src" root@$address:"$target"

                filename=$(basename "$src")
                remote_tmp="/tmp/$filename"
                remote_dir=$(dirname "$dst")

                remote_exec_via_jump $address kubectl cp "$target$filename" -n openstack "$pod_name:$remote_tmp" -c $container
                remote_exec_via_jump $address kubectl exec -n openstack "$pod_name" -c "$container" -- mkdir -p $remote_dir
                remote_exec_via_jump $address kubectl exec -n openstack "$pod_name" -c "$container" -- sudo mv $remote_tmp $dst
                ;;

            D)
                echo Deleting $dst or $dst"c" in pod $pod_name
                dst="$dst"c
                remote_exec_via_jump $address kubectl exec -n openstack "$pod_name" -- rm -f $dst
                ;;

            *)
                echo "Unknown status: $status"
                ;;
        esac
    done
}


function cleanup_os_in_os() {
    gtimeout -s KILL 10 sshpass -p "easystack" ssh root@$address "rm -rf $target"
    remote_exec_via_jump $address rm -rf "$target"
}
