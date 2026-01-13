#!/bin/bash

set -ex


base_path=$(python -c "from cbok import settings; print(settings.BASE_DIR)")
source "$base_path/utils.sh"
source "$base_path/cbok/bbx/utils.sh"

workspace=$(python -c "from cbok import settings; print(settings.Workspace)")


is_test_path() {
    [[ "$1" == *"/test/"* || "$1" == *"/tests/"* ]]
}


function get_diff() {
    project_name=$1
    check_if_committed $project_name

    pushd $workspace/Cursor/es/$project_name > /dev/null

    git show --name-status --pretty="" | while read status oldpath newpath; do
        [ -z "$status" ] && continue

        if is_test_path "$oldpath" && is_test_path "$newpath"; then
            continue
        fi

        case "$status" in
            A|M|D)
                is_test_path "$oldpath" && continue
                printf '{"status":"%s","path":"%s"}\n' "$status" "$oldpath"
                ;;
            R*)
                if ! is_test_path "$oldpath"; then
                    printf '{"status":"D","path":"%s"}\n' "$oldpath"
                fi
                if ! is_test_path "$newpath"; then
                    printf '{"status":"A","path":"%s"}\n' "$newpath"
                fi
                ;;
            *)
                printf '{"status":"UNKNOWN","status_code":"%s","old":"%s","new":"%s"}\n' \
                    "$status" "$oldpath" "$newpath"
                ;;
        esac
    done
    popd > /dev/null
}
