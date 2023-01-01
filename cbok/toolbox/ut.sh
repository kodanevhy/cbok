#!/usr/bin/env bash

# For ut.

set -ex

local_='/root/workspace/ut'
mother_img='hub.easystack.io/production/escloud-linux-source-nova-compute:6.1.1'
# The script accepts several args are as follows.
# prj_archived: Target archived project name under $local_ directory for ut.
# sub_cmd: Seperated sub-command from tox, [tox --help] for
# further view, it's better support cover, py27, py36, pep8 etc.
# module_especial: tox supports ut in module or method
# especially, here provide an entrance to get it.
prj_archived=$1
prj="$(echo ${prj_archived%*.tar.gz})"
sub_cmd=$2
module_especial=$3

function main() {
    ctrs=$(docker ps -a)
    if [ "$ctrs" ];then
        task_ctr_id=$(echo "$ctrs" | grep $mother_img | awk '{print $1}' | head -n 1)
    fi
    ctr_id_name_map=$(docker ps -a --format "{{.ID}}:{{.Names}}")
    if [ "$ctr_id_name_map" ];then
        task_ctr_name=$(echo "$ctr_id_name_map" | grep $task_ctr_id | awk -F ':' '{print $2}')
    fi

    if [[ $task_ctr_id && "$task_ctr_name" != $prj ]];then
        rm -rf $local_/$prj
        tar zxvf $local_/$prj_archived -C . 2> /dev/null 1>&2
        docker rm -f $task_ctr_id
        task_ctr_id="$(docker run -dit --name $prj --privileged=true -v $local_/$prj:/$prj $mother_img bash)"
    elif [[ $task_ctr_id && "$task_ctr_name" = $prj ]];then
        docker exec -it $task_ctr_id bash -c "if [ -d /$prj/.tox/ ];then sudo mv /$prj/.tox/ /opt/;fi"
        rm -rf $local_/$prj
        tar zxvf $local_/$prj_archived -C . 2> /dev/null 1>&2
        docker restart $task_ctr_id && sleep 3
    else
        rm -rf $local_/$prj
        tar zxvf $local_/$prj_archived -C . 2> /dev/null 1>&2
        task_ctr_id="$(docker run -dit --name $prj --privileged=true -v $local_/$prj:/$prj $mother_img bash)"
    fi

    docker exec -it $task_ctr_id bash -c "cd /$prj;sudo pip install tox"
    docker exec -it $task_ctr_id bash -c "if [ -d /opt/.tox/ ];then sudo mv /opt/.tox/ /$prj/;fi"
    docker exec -it $task_ctr_id bash -c "cd /$prj;sudo tox -e $sub_cmd $module_especial"
}

main