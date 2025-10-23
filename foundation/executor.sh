#!/bin/bash

# build docker image, upload to dockerhub
# deploy k8s
# apply service and pull image

function apply_service() {
    echo
}


function copy_resource_to() {
    address=$1
    target_dir=$2
    mkdir -p $target_dir
    scp -r foundation root@$address:$target_dir
}


function execute() {
    address="$1"
    foundation_home="$2"
    ssh -n root@$address "cd $foundation_home; bash kubernetes.sh 192.66.111.56 > log 2>&1"
}
