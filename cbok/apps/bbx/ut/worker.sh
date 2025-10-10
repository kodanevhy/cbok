#!/usr/bin/env bash

set -ex

base_path=$(python manage.py shell -c "from cbok import settings; print(settings.BASE_DIR)")
source $base_path/cbok/apps/bbx/tools/common.sh

local_='/root/workspace/ut'


function is_virtual_env_ready() {
    project="$1"
    tox_path="$local_/$project/.tox/"
    container_name="ut-$project"
    task_container=$(docker ps | grep $container_name || true)
    if [ -z "$task_container" ]; then
        exit 1
    fi

    docker exec $container_name bash -c "
        if [ -e $tox_path ]; then
            echo Ready
        fi
    "
}


function first_run() {
    mother_img="$1"
    project="$2"
    zip_target="$3"
    sub_cmd="$4"
    module_especial="$5"

    if test "$module_especial";then
        cmd="$sub_cmd $module_especial"
    else
        cmd="$sub_cmd"
    fi

    if [ -z "$(docker images -q $mother_image)" ];then
        die "no such image"
    fi

    container_name="ut-"$project

    task_container=$(docker ps | grep $container_name || true)
    if [ -z "$task_container" ]; then
        docker run --privileged=true -dit --name $container_name $mother_img bash
    fi

    docker exec $container_name bash -c "
        set -ex
        sudo rm -rf $local_/$project
        sudo mkdir -p $local_
        sudo chown -R nova:nova $local_
        sudo yum -y install unzip
    "

    docker cp $zip_target $container_name:/tmp/

    project_home=$local_/$project
    docker exec $container_name bash -c "
        set -ex
        sudo unzip -d $local_ /tmp/$project.zip > /dev/null
    "

    docker exec $container_name bash -c "
        set -ex
        sudo pip install tox
    "
    docker exec $container_name bash -c "
        sudo chown -R nova:nova $local_
        cd $project_home;sudo CFLAGS="-std=gnu99" tox -e $cmd -vv 2>&1
    "
}


function copy_test_dir_and_run() {
    test_dir="$1"
    project="$2"
    sub_cmd="$3"
    module_especial="$4"

    if test "$module_especial";then
        cmd="$sub_cmd $module_especial"
    else
        cmd="$sub_cmd"
    fi

    container_name="ut-$project"

    project_home=$local_/$project
    docker cp $test_dir $container_name:$project_home

    docker exec $container_name bash -c "
        cd $project_home;sudo CFLAGS="-std=gnu99" tox -e $cmd -vv 2>&1
    "
}
