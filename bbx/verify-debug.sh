#!/usr/bin/env bash

# Provide script for changing the code to self and verify
# environment if expected, also for debugging code.

set -ex

source common.sh

local_='/root/workspace/verify-debug'
deploy_name=$1
cm_name=$2

# 客户端传文件，给文件绝对路径，根据绝对路径修改文件名为.相隔，形成压缩包传到服务端

function check_input_args() {

}

function edit_deploy() {
    kubectl edit deploy -n openstack $deploy_name
}

function edit_cm() {
    kubectl edit cm -n openstack $cm_name
}

function replace_file() {
    kubectl get pod -n openstack | grep $deploy_name
    kubectl exec -it -n openstack
}

function exec_script() {
    find $deploy_name
    cp . /tmp
    chmod
    remove sleep infinity
    bash
}

function main() {
    check_input_args

    pushd $local_

    # The file in verify-debug.tar.gz were code with filename
    # formatted in '.' connected.
    if [ -f "verify-debug.tar.gz" ]; then
        tar zxvf verify-debug.tar.gz -C .
    else
        die "no target achieved file verify-debug.tar.gz found."
    fi

    edit_deploy
    edit_cm
    kubectl delete pod -n openstack | grep deploy
    replace_file
    exec_script

    popd
}