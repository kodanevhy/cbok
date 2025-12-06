#!/bin/bash

address=$1
from_pre=$2
service="cbok"

if [[ "$from_pre" = "CBOK_REBUILD" ]];then
    pod_name=$(ssh -n root@$address "
        kubectl get pod -n cbok -l app=cbok | grep -v NAME | awk '{print \$1}'
    ")
    if [ -n "$pod_name" ];then
        ssh -n root@$address "
            kubectl delete pod -n cbok $pod_name
        "
    fi
fi
