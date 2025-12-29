#!/bin/bash

set -ex


base_path=$(python -c "from cbok import settings; print(settings.BASE_DIR)")
source "$base_path/utils.sh"

workspace=$(python -c "from cbok import settings; print(settings.Workspace)")

function check_if_committed() {
    project_name=$1
    # Now we only support project from es.
    pushd $workspace/Cursor/es/$project_name > /dev/null

    output=$(git status)
    popd > /dev/null
    flag=$(echo $output | grep "nothing to commit, working tree clean" || true)
    if [ -z "$flag" ]; then
        die "you should commit the changes first".
    fi
}


function get_diff() {
    project_name=$1
    check_if_committed $project_name

    pushd $workspace/Cursor/es/$project_name > /dev/null

    git show --name-status --pretty="" | while read status oldpath newpath; do
        if [ -z "$status" ]; then
            continue
        fi

        if [[ "$oldpath" == *"/test/"* ]] && [[ "$newpath" == *"/test/"* ]]; then
            continue
        fi

        case "$status" in
            A)
                if [[ "$oldpath" == *"/test/"* ]]; then
                    continue
                fi
                printf '{"status":"A","path":"%s"}\n' "$oldpath"
                ;;
            M)
                if [[ "$oldpath" == *"/test/"* ]]; then
                    continue
                fi
                printf '{"status":"M","path":"%s"}\n' "$oldpath"
                ;;
            D)
                if [[ "$oldpath" == *"/test/"* ]]; then
                    continue
                fi
                printf '{"status":"D","path":"%s"}\n' "$oldpath"
                ;;
            R*)
                # 重命名时，先删除旧文件，再新增新文件
                if [[ "$oldpath" != *"/test/"* ]]; then
                    printf '{"status":"D","path":"%s"}\n' "$oldpath"
                fi
                if [[ "$newpath" != *"/test/"* ]]; then
                    printf '{"status":"A","path":"%s"}\n' "$newpath"
                fi
                ;;
            *)
                printf '{"status":"UNKNOWN","status_code":"%s","old":"%s","new":"%s"}\n' "$status" "$oldpath" "$newpath"
                ;;
        esac
    done
    popd > /dev/null
}
