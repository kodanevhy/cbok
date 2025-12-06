#!/bin/bash

address=$1
from_pre=$2
service="cbok"

if [[ "$from_pre" = "CBOK_REBUILD" ]];then
    echo "cbok was auto-fetched from GitHub, restart its pod right now"

    pod_name=$(ssh -n root@$address "
        kubectl get pod -n cbok -l app=cbok | grep -v NAME | awk '{print \$1}'
    ")
    if [ -n "$pod_name" ];then
        ssh -n root@$address "
            kubectl delete pod -n cbok $pod_name
        "
    fi

    echo "Waiting for pods of $service to be Ready ..."
    ssh -n root@"$address" "
        until kubectl get pod -l app='$service' -n cbok 2>/dev/null | grep -q -v NAME; do
            sleep 2
        done
        if ! kubectl wait --for=condition=Ready pod -l app='$service' -n cbok --timeout=300s; then
            echo 'Warning: some pods of $service may not be Ready in cbok'
            exit 1
        fi
    "
fi
