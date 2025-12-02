#!/bin/bash

set -ex

address=$1
namespace="cbok"
secret_name="cbok-db-secret"

secret_password=$(ssh -n root@$address "
    kubectl get secret -n $namespace $secret_name -o jsonpath='{.data.password}' | base64 --decode
")
ssh -n root@$address "
    kubectl exec -n $namespace mariadb-0 -- bash -c 'mariadb -uroot -p$secret_password -e \"DROP DATABASE IF EXISTS cbok;\"'
"
