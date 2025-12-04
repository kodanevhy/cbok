#!/bin/bash

set -ex

base_path=$(python -c "from cbok import settings; print(settings.BASE_DIR)")
source "$base_path/utils.sh"


function is_ready() {
    address=$1
    pods=$(ssh -n root@$address "kubectl get nodes")
    if [ $? -eq 0 ];then
        echo Already deployed
        exit 0
    fi
    exit 1
}


function apply_service() {
    local address="$1"
    local service_name="$2"
    local rebuild_cbok_base="$3"
    local foundation_home="/opt/foundation"

    if [[ "$service_name" = "base" ]];then
        die "Not allowed: base"
    fi

    echo "Copying resource '$service_name' to $foundation_home ..."

    if [[ "$service_name" = "cbok" ]]; then
        excludes=("cbok-base-amd64.tar" "cbok-amd64.tar")
    else
        excludes=()
    fi
    if ! copy_resource_to "$address" "$foundation_home" "foundation/$service_name" "$exclude"; then
        die "Failed to copy resource to $address"
    fi

    local hook_dir="foundation/$service_name/hook"

    # Pre hook
    if [ -d "$hook_dir" ] && [ -f "$hook_dir/apply/pre.sh" ]; then
        echo "Running pre-hook for $service_name"
        if ! bash "$hook_dir/apply/pre.sh" "$address" "$rebuild_cbok_base"; then
            echo "Applying service pre-hook failed for $service_name"
            exit 1
        fi
    fi

    # Installation
    ssh -n root@"$address" "
        echo 'Applying manifests for $service_name ...' >> $foundation_home/log 2>&1
        sh -c 'for f in $foundation_home/$service_name/*.yaml; do
            echo \"Applying \$f ...\" >> $foundation_home/log 2>&1
            if ! kubectl apply -f \"\$f\" >> $foundation_home/log 2>&1; then
                echo \"Failed to apply \$f\" >> $foundation_home/log 2>&1
                exit 1
            fi
        done'
    "

    # Waiting
    ssh -n root@"$address" "
        echo 'Waiting for pods of $service_name to be Ready ...' >> $foundation_home/log 2>&1
        until kubectl get pod -l app='$service_name' -n cbok 2>/dev/null | grep -q -v NAME; do
            sleep 2
        done
        if ! kubectl wait --for=condition=Ready pod -l app='$service_name' -n cbok --timeout=300s; then
            echo 'Warning: some pods of $service_name may not be Ready in cbok' >> $foundation_home/log 2>&1
            exit 1
        fi
    "

    # Post hook
    if [ -d "$hook_dir" ] && [ -f "$hook_dir/apply/post.sh" ]; then
        echo "Running post-hook for $service_name"
        if ! bash "$hook_dir/apply/post.sh" "$address"; then
            echo "Applying service post-hook failed for $service_name"
            exit 1
        fi
    fi

    ssh -n root@"$address" "
        echo 'Service $service_name applied successfully.' >> $foundation_home/log 2>&1
    "
    echo "APPLY SUCCESS"
}


function remove_service() {
    local address="$1"
    local service_name="$2"
    local foundation_home="/opt/foundation"

    echo "Removing service '$service_name' from $foundation_home ..."

    local hook_dir="foundation/$service_name/hook"

    # Pre hook
    if [ -d "$hook_dir" ] && [ -f "$hook_dir/remove/pre.sh" ]; then
        echo "Running pre-hook for $service_name"
        if ! bash "$hook_dir/remove/pre.sh" "$address"; then
            echo "Removing service pre-hook failed for $service_name"
            exit 1
        fi
    fi

    # Deletion
    ssh -n root@"$address" "
        echo 'Deleting manifests for $service_name ...' >> $foundation_home/log 2>&1
        sh -c 'for f in $foundation_home/$service_name/*.yaml; do
            echo \"Deleting \$f ...\" >> $foundation_home/log 2>&1
            if ! kubectl delete -f \"\$f\" >> $foundation_home/log 2>&1; then
                echo \"Failed to delete \$f\" >> $foundation_home/log 2>&1
                exit 1
            fi
        done'
    "

    # Waiting
    ssh -n root@"$address" "
        echo 'Waiting for pods of $service_name to be Ready ...' >> $foundation_home/log 2>&1
        until kubectl get pod -l app='$service_name' -n cbok 2>/dev/null | grep -q -v NAME; do
            sleep 2
        done
        if ! kubectl wait --for=delete pod -l app='$service_name' -n cbok --timeout=300s; then
            echo 'Warning: some pods of $service_name may not be Ready in cbok' >> $foundation_home/log 2>&1
            exit 1
        fi
    "

    # Post hook
    if [ -d "$hook_dir" ] && [ -f "$hook_dir/remove/post.sh" ]; then
        echo "Running post-hook for $service_name"
        if ! bash "$hook_dir/remove/post.sh" "$address"; then
            echo "Removing service post-hook failed for $service_name"
            exit 1
        fi
    fi

    echo "REMOVE SUCCESS"
}

function copy_resource_to() {
    local address=$1
    local remote_target_dir=$2   # absolute path
    local source_resource_dir=$3 # may be a relative path
    shift 3
    local excludes=("$@")

    ssh -n root@$address "mkdir -p '$remote_target_dir'"

    local exclude_args=()
    for e in "${excludes[@]}"; do
        exclude_args+=(--exclude "$e")
    done

    rsync -avz --progress --delete "${exclude_args[@]}" "$source_resource_dir" root@$address:"$remote_target_dir"
}


function execute() {
    floating_address="$1"
    mgmt_eth="$2"
    ssh -n root@$floating_address "cd /opt/foundation/base; bash kubernetes.sh $mgmt_eth >> /opt/foundation/log 2>&1"
}
