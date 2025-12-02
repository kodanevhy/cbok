#!/bin/bash

set -ex

address=$1

ssh -n root@$address "
    mkdir -p /opt/pv/mariadb
    if kubectl get secret cbok-db-secret -n cbok >/dev/null 2>&1; then
        echo "Secret cbok-db-secret already exists, skip creating."
    else
        kubectl create secret generic cbok-db-secret \
            --from-literal=password="000000" -n cbok
    fi
"
