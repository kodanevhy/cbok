set -e

base_path="/Users/mizar/Workspace/PycharmProjects/me/cbok"
source $base_path/apps/bbx/tools/common.sh
workspace=~/Workspace

function check_if_committed() {
    project_name=$1
    # Now we only support project from es.
    pushd $workspace/PycharmProjects/es/$project_name

    output=$(git status)
    popd
    flag=$(echo $output | grep "nothing to commit, working tree clean")
    if [ -n "$flag" ]; then
        die "you should commit the changes first".
    fi
}


function get_diff() {
    project_name=$1
    check_if_committed project_name

    pushd $workspace/PycharmProjects/es/$project_name
    diff=$(git show --name-only --pretty="" HEAD | grep -v "/test/" | sed '/^$/d')
    popd
    if [ -z "$diff" ]; then
        die "no diff between with your commit and HEAD"
    fi
    echo $diff
}
