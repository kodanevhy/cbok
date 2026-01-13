set -ex

base_path=$(python -c "from cbok import settings; print(settings.BASE_DIR)")
source "$base_path/utils.sh"


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
