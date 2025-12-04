#!/bin/bash

set -ex

address=$1
rebuild_base_image=$2
foundation_home="/opt/foundation"


function copy_base_image() {
    remote_base_tar="$foundation_home/cbok/cbok-base-amd64.tar"
    if ssh -n root@$address "[ -f '$remote_base_tar' ]"; then
        remote_exists=0
        return 0
    else
        remote_exists=1
    fi

    local_tar="foundation/cbok/cbok-base-amd64.tar"

    if [ $remote_exists -ne 0 ]; then
        if [ ! -f "$local_tar" ]; then
            echo "Building base image locally..."
            docker build --target base --platform linux/amd64 -t docker.io/kodanevhy/cbok-base:latest .
            docker save docker.io/kodanevhy/cbok-base:latest -o "$local_tar"
        fi

        echo "Copying base image to remote..."
        rsync -avz --progress "$local_tar" root@$address:"$foundation_home/cbok/"
    else
        echo "Remote base image already exists. Skipping copy."
    fi
}


function build_cbok {
    current_branch=$(git rev-parse --abbrev-ref HEAD)
    ssh -n root@$address "
        set -ex
        docker load -i $foundation_home/cbok/cbok-base-amd64.tar

        cd $foundation_home/cbok && git clone -b $current_branch --single-branch https://github.com/kodanevhy/cbok.git && cd cbok
        docker build --platform linux/amd64 --build-arg STAGE_SECOND_BASE_IMAGE=docker.io/kodanevhy/cbok-base:latest -t docker.io/kodanevhy/cbok:latest .

        docker save docker.io/kodanevhy/cbok:latest -o $foundation_home/cbok/cbok-amd64.tar

        ctr -n k8s.io i import $foundation_home/cbok/cbok-amd64.tar
    "
}

if [ "$rebuild_base_image" = "True" ]; then
    remote_base_tar="$foundation_home/cbok/cbok-base-amd64.tar"

    ssh -n root@$address "
        ctr -n k8s.io images delete docker.io/kodanevhy/cbok:latest || echo true
        rm -f $remote_base_tar || echo true
    "

    local_tar="foundation/cbok/cbok-base-amd64.tar"
    rm -f $local_tar
fi

remote_has_image=$(ssh -n root@$address "ctr -n k8s.io images ls | grep -q 'docker.io/kodanevhy/cbok:latest' && echo 1 || echo 0")
if [ "$remote_has_image" -eq 0 ]; then
    copy_base_image
    build_cbok
else
    echo CBoK image already stashed, rebuild cbok
    build_cbok
fi

ssh -n root@$address "
    kubectl apply -f $foundation_home/cbok/03-job-mariadb.yaml
"
NAMESPACE=cbok
JOB_NAME=cbok-db-init

echo "Waiting for Job $JOB_NAME to complete..."
timeout=300
interval=5
elapsed=0
while true; do
    if ! ssh -n root@$address "kubectl get job -n $NAMESPACE $JOB_NAME &> /dev/null"; then
        sleep 3
        continue
    fi
    status=$(ssh -n root@$address "kubectl get job -n $NAMESPACE $JOB_NAME -o jsonpath='{.status.succeeded}'")
    if [[ "$status" == "1" ]]; then
        echo "Job $JOB_NAME completed successfully."
        break
    fi

    failed=$(ssh -n root@$address "kubectl get job -n $NAMESPACE $JOB_NAME -o jsonpath='{.status.failed}'")
    if [[ "$failed" != "" && "$failed" -ge 1 ]]; then
        echo "Job $JOB_NAME failed."
        exit 1
    fi

    sleep $interval
    elapsed=$((elapsed + interval))
    if [[ $elapsed -ge $timeout ]]; then
        echo "Timeout waiting for Job $JOB_NAME"
        exit 1
    fi
done

ssh -n root@$address "kubectl delete job -n $NAMESPACE $JOB_NAME"
echo "Job $JOB_NAME deleted."
