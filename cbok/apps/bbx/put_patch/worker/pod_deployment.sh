#!/bin/bash
set -ex

base_path=$(python manage.py shell -c "from cbok import settings; print(settings.BASE_DIR)")
source $base_path/cbok/apps/bbx/tools/common.sh


function init_pod(){
    address=$1
    controller=$2
    replica=$3
    configmap=$4
    start_script=$5
    gtimeout -s KILL 10 ssh root@$address "
        kubectl scale $controller/$replica --replicas=1 -n openstack
    "
    ssh root@$address "
        set -e
        kubectl get cm -n openstack nova-bin -oyaml > /tmp/$replica

        sed -i \"
        /^  $(basename $start_script): |$/{
            :loop
            n
            /^    #!/{
                # 检查下一行是否为 sleep infinity
                n
                /^[[:space:]]*sleep infinity\$/! i\\    sleep infinity
                b done
            }
            # 如果到下一个块或者文件末尾，跳出
            /^[^[:space:]]/ b done
            b loop
        }
        :done
        \" /tmp/$replica

        kubectl apply -f /tmp/$replica
    "
    if [ $replica = "nova-conductor" ];then
        grep_flag="conductor"
    else
        grep_flag="$replica"
    fi
    for i in {1..30}; do
        num=$(gtimeout -s KILL 10 ssh root@$address "
            kubectl get pod -n openstack -l component=$grep_flag --field-selector=status.phase=Running --no-headers | wc -l
        ")
        if [[ "$num" -eq 1 ]]; then
            break
        fi

        if [ "$i" -eq 30 ]; then
            die "too many replica left: $replica"
        fi
        sleep 1
    done

    pod_name=$(gtimeout -s KILL 10 ssh root@$address "
        kubectl get pod -n openstack | grep $replica | awk '{print \$1}'
    ")
    gtimeout -s KILL 10 ssh root@$address "
        kubectl delete pod -n openstack "$pod_name"
    "

    for i in {1..30}; do
        restarted=$(gtimeout -s KILL 10 ssh root@$address "
            kubectl get pod -n openstack | grep $replica || true
        ")
        running=$(echo "$restarted" | grep Running || true)
        new_pod_name=$(echo "$running" | awk '{print $1}')
        if [ "$new_pod_name" = "$pod_name" ];then
            # delete process not work if env very slow
            continue
        fi

        if [ -n "$restarted" ]; then
            if [ -n "$running" ]; then
                echo "Done;$(echo $running | awk '{print $1}')"
                break
            fi
        fi
        if [ "$i" -eq 30 ]; then
            die "pod start failed: $replica"
        fi
        sleep 1
    done
}


function remote_exec_via_jump() {
    local jump=$1
    shift
    ssh_key="ssh -i ~/.ssh/id_rsa.roller root@10.20.0.3"
    sshpass -p "easystack" ssh root@"$jump" $ssh_key $@
}


function init_pod_os_in_os(){
    address=$1
    controller=$2
    replica=$3
    configmap=$4
    start_script=$5
    gtimeout -s KILL 10 sshpass -p "easystack" ssh root@$address "ssh -i ~/.ssh/id_rsa.roller root@10.20.0.3 \"
        kubectl scale $controller/$replica --replicas=1 -n openstack
    \""
    remote_exec_via_jump "$address" bash -s <<EOF
kubectl get cm -n openstack nova-bin -oyaml > /tmp/$replica

sed -i "/^  $(basename $start_script): |\$/{
    :loop
    n
    /^    #!/{
        # 检查下一行是否为 sleep infinity
        n
        /^[[:space:]]*sleep infinity\$/! i\    sleep infinity
        b done
    }
    # 如果到下一个块或者文件末尾，跳出
    /^[^[:space:]]/ b done
    b loop
}
:done" /tmp/$replica

kubectl apply -f /tmp/$replica
EOF

    if [ $replica = "nova-conductor" ];then
        grep_flag="conductor"
    else
        grep_flag="$replica"
    fi
    for i in {1..30}; do
        num=$(gtimeout -s KILL 10 sshpass -p "easystack" ssh root@$address "ssh -i ~/.ssh/id_rsa.roller root@10.20.0.3 \"
        kubectl get pod -n openstack -l component=$grep_flag --field-selector=status.phase=Running --no-headers | wc -l
        \"")
        if [[ "$num" -eq 1 ]]; then
            break
        fi

        if [ "$i" -eq 30 ]; then
            die "too many replica left: $replica"
        fi
        sleep 1
    done

    pod_entry=$(gtimeout -s KILL 10 sshpass -p "easystack" ssh root@$address "ssh -i ~/.ssh/id_rsa.roller root@10.20.0.3 \"
        kubectl get pod -n openstack | grep $replica
    \"")
    pod_name=$(echo "$pod_entry" | awk '{print $1}')
    gtimeout -s KILL 10 sshpass -p "easystack" ssh root@$address "ssh -i ~/.ssh/id_rsa.roller root@10.20.0.3 \"
        kubectl delete pod -n openstack "$pod_name"
    \""

    for i in {1..30}; do
        restarted=$(gtimeout -s KILL 10 sshpass -p "easystack" ssh root@$address "ssh -i ~/.ssh/id_rsa.roller root@10.20.0.3 \"
            kubectl get pod -n openstack | grep $replica || true
        \"")
        running=$(echo "$restarted" | grep Running || true)
        new_pod_name=$(echo "$running" | awk '{print $1}')
        if [ "$new_pod_name" = "$pod_name" ];then
            # delete process not work if env very slow
            continue
        fi

        if [ -n "$restarted" ]; then
            if [ -n "$running" ]; then
                echo "Done;$(echo $running | awk '{print $1}')"
                break
            fi
        fi

        if [ "$i" -eq 30 ]; then
            die "pod start failed: $replica"
        fi
        sleep 1
    done
}
