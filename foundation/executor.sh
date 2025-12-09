#!/bin/bash

set -ex

base_path=$(python -c "from cbok import settings; print(settings.BASE_DIR)")
source "$base_path/utils.sh"


function is_ready() {
    address=$1
    pods=$(ssh -n root@$address "kubectl get pods -A" || true)
    if [ -n "$pods" ];then
        echo Already deployed
    else
        echo Not deployed
    fi
}


function apply_service() {
    local address="$1"
    local service_name="$2"
    local rebuild_cbok_base="$3"
    local dev="$4"
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

    pre_to_post=""
    # Pre hook
    if [ -d "$hook_dir" ] && [ -f "$hook_dir/apply/pre.sh" ]; then
        echo "Running pre-hook for $service_name"

        pre_output=$(bash "$hook_dir/apply/pre.sh" "$address" "$rebuild_cbok_base" "$dev")
        pre_status=$?

        if [[ "$pre_output" =~ "CBOK_REBUILD" ]]; then
            pre_to_post="CBOK_REBUILD"
        fi

        if [ $pre_status -ne 0 ]; then
            echo "Applying service pre-hook failed for $service_name"
            exit 1
        fi
    fi

    # Installation
    ssh -n root@"$address" "
        echo Applying manifests for $service_name ...
        for f in $foundation_home/$service_name/*.yaml; do
            if [ $service_name = "cbok" ] && [[ "\$f" =~ "03-job-mariadb.yaml" ]]; then
                continue
            fi
            echo "Applying \$f ..."
            if ! kubectl apply -f "\$f"; then
                echo "Failed to apply \$f"
                exit 1
            fi
        done
    "

    # Waiting
    ssh -n root@"$address" "
        echo 'Waiting for pods of $service_name to be Ready ...'
        until kubectl get pod -l app='$service_name' -n cbok 2>/dev/null | grep -q -v NAME; do
            sleep 2
        done
        if ! kubectl wait --for=condition=Ready pod -l app='$service_name' -n cbok --timeout=300s; then
            echo 'Warning: some pods of $service_name may not be Ready in cbok'
            exit 1
        fi
    "

    # Post hook
    if [ -d "$hook_dir" ] && [ -f "$hook_dir/apply/post.sh" ]; then
        echo "Running post-hook for $service_name"
        if ! bash "$hook_dir/apply/post.sh" "$address" "$pre_to_post"; then
            echo "Applying service post-hook failed for $service_name"
            exit 1
        fi
    fi

    ssh -n root@"$address" "
        echo 'Service $service_name applied successfully.'
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
        set -x
        echo Deleting manifests for $service_name ...
        for f in $foundation_home/$service_name/*.yaml; do
            echo Deleting \$f ...
            output=\$(kubectl delete -f \$f 2>&1 || true)
            if [[ \$output =~ \"not found\" ]]; then
                echo It already doesn\'t exist any more
            elif [[ \$output =~ \"deleted\" ]]; then
                echo Delete success
            else
                echo Failed to delete \$f
                exit 1
            fi
        done
    "

    # Waiting
    ssh -n root@"$address" "
        echo 'Waiting for pods of $service_name to be deleted ...'
        if ! kubectl wait --for=delete pod -l app='$service_name' -n cbok --timeout=300s; then
            echo 'Warning: some pods of $service_name may not be Ready in cbok'
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


function install_rsync() {
    local address=$1

    ssh root@$address "
        rm -f /etc/yum.repos.d/*
        curl -o /etc/yum.repos.d/CentOS-Base.repo \
            https://mirrors.aliyun.com/repo/Centos-7.repo
        yum makecache
        yum -y install rsync"
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
    ssh -n root@$floating_address "cd /opt/foundation/base; bash kubernetes.sh $mgmt_eth"
}
