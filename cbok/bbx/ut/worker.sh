#!/usr/bin/env bash

set -e

base_path=$(python -c "from cbok import settings; print(settings.BASE_DIR)")
workspace=$(python -c "from cbok import settings; print(settings.Workspace)")
source "$base_path/utils.sh"
source "$base_path/cbok/bbx/utils.sh"

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

    task_container=$(
        docker ps -a | awk -v name="$container_name" '$NF == name'
    )
    if echo $task_container | grep -q Exited; then
        echo "Found dead $container_name, remove and rebuild"
        docker rm -f $container_name
        sleep 2
    fi

    task_container=$(
        docker ps -a | awk -v name="$container_name" '$NF == name'
    )
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
sudo pip -v install tox
    "
    docker exec $container_name bash -c "
sudo chown -R nova:nova $local_
sudo cd $project_home;sudo CFLAGS="-std=gnu99" tox -e $cmd -vv 2>&1
    "
}


function get_diff() {
    project_name=$1
    base_branch=${2:-origin/master}

    pushd "$workspace/Cursor/es/$project_name" > /dev/null

    {
        # 1. tracked changes (commit + uncommitted)
        git diff --name-status "$base_branch"...HEAD
        # 2. staged but not committed
        git diff --name-status --cached
        # 3. untracked files
        git ls-files --others --exclude-standard | sed 's/^/??\t/'
    } | sort -u | while read status oldpath newpath; do

        case "$status" in
            A|M|D)
                printf '{"status":"%s","path":"%s"}\n' "$status" "$oldpath"
                ;;
            R*)
                printf '{"status":"D","path":"%s"}\n' "$oldpath"
                printf '{"status":"A","path":"%s"}\n' "$newpath"
                ;;
            '??')
                printf '{"status":"A","path":"%s"}\n' "$oldpath"
                ;;
            *)
                printf '{"status":"UNKNOWN","code":"%s","old":"%s","new":"%s"}\n' \
                    "$status" "$oldpath" "$newpath"
                ;;
        esac
    done

    popd > /dev/null
}


function copy_changes() {
    container_name="$1"
    files_json="$2"
    echo "$files_json" | python3 -c "
import json, sys
files = json.loads(sys.stdin.read())
for f in files:
    print(f['status'], f['path'], f['remote_path'])
    " | while read status src dst; do

        case "$status" in
            A|M)
                echo "Processing $status $src -> $dst"
                docker cp $src $container_name:$dst
                ;;

            D)
                echo Deleting $dst or $dst"c" in $container_name
                docker exec $container_name bash -c "rm -f $dst"
                dst="$dst"c
                docker exec $container_name bash -c "rm -f $dst"
                ;;

            *)
                echo "Unknown status: $status"
                ;;
        esac
    done
}


function later_run() {
    project="$1"
    sub_cmd="$2"
    module_especial="$3"

    if test "$module_especial";then
        cmd="$sub_cmd $module_especial"
    else
        cmd="$sub_cmd"
    fi

    container_name="ut-$project"

    project_home=$local_/$project

    docker exec $container_name bash -c "
cd $project_home;sudo CFLAGS="-std=gnu99" tox -e $cmd -vv 2>&1
    "
}
