#!/usr/bin/env bash

# For ut.

set -ex

local_='/root/workspace/ut'
mother_img='hub.easystack.io/production/escloud-linux-source-nova-compute:6.1.1'
# The script accepts several args are as follows.
# 1) prj_archived: Target archived project name under $local_ directory for ut.
# 2) sub_cmd: Seperated sub-command from tox, run [tox --help] for
#    further view, it's better to support with cover, py27, py36, pep8 etc.
# 3) module_especial: tox supports ut in module or method
#    especially, here provide an entrance to get it.
prj_archived=$1
prj="$(echo ${prj_archived%*.tar.gz})"
sub_cmd=$2
module_especial=$3
if test "$module_especial";then
    cmd="$sub_cmd $module_especial"
else
    cmd="$sub_cmd"
fi
backup_dir_host='backup'
backup_path="$backup_dir_host/$sub_cmd/tox-$prj"

function die() {
    echo "error: $1" >&2
    exit 1
}

function check_input_args() {
    if [ ! "$prj_archived" ]; then
        die "must accept a tar.gz suffix archived file."
    elif [ ! -f "$prj_archived" ]; then
        die "no such file $prj_archived."
    elif [ ! "$prj" ]; then
        die "must with the tar.gz suffix archived file."
    elif [ ! "$sub_cmd" ]; then
        die "no sub command specified, run [tox --help] for options."
    fi
}

function join_cache() {
    if [ -d $backup_path ];then
        echo "Found cache..."
        mkdir $prj/.tox && cp -r $backup_path/* $prj/.tox/
    fi
}

# It will have one task container to execute ut, delete task container
# to make sure it is the newest, the container name represents the
# project name.
function delete_task_ctr() {
    ctr_id_name_map=$(docker ps -a --format "{{.ID}}:{{.Names}}")

    task_ctr_id="$(echo "$ctr_id_name_map" | grep $prj-ut | awk -F ':' '{print $1}')"
    if [ $task_ctr_id ]; then
        docker rm -f $task_ctr_id
    else
        echo "Creating task container..."
    fi
}

# If use cache, remove the directory and re-backup the newer.
function do_backup() {
    mkdir -p $backup_dir_host/$sub_cmd 2> /dev/null 1>&2
    rm -rf $backup_path
    docker cp $task_ctr_id:/$prj/.tox/ $backup_path
}

function main() {
    check_input_args
    pushd $local_

    rm -rf $prj
    tar zxvf $prj_archived -C . 2> /dev/null 1>&2

    join_cache

    delete_task_ctr

    task_ctr_id="$(docker run -dit --name $prj-ut --privileged=true -v $local_/$prj:/$prj $mother_img bash)"

    docker exec -it $task_ctr_id bash -c "cd /$prj;sudo pip install tox"
    set +e
    docker exec -it $task_ctr_id bash -c "cd /$prj;sudo tox -e $cmd"
    set -e
    do_backup
    popd
}

main