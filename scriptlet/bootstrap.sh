#!/usr/bin/env bash

# CBoK shared shell library entrypoint.
# This file is meant to be sourced from both local and remote environments.

set -euo pipefail

SCRIPTLET_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export SCRIPTLET_DIR

# Remote install location (fixed).
SCRIPTLET_REMOTE_DIR="${SCRIPTLET_REMOTE_DIR:-/opt/cbok/scriptlet}"
export SCRIPTLET_REMOTE_DIR

# Allow callers to override behavior.
CBOK_SSH_OPTS="${CBOK_SSH_OPTS:-}"
CBOK_SCP_OPTS="${CBOK_SCP_OPTS:-}"
CBOK_RSYNC_OPTS="${CBOK_RSYNC_OPTS:-}"
export CBOK_SSH_OPTS CBOK_SCP_OPTS CBOK_RSYNC_OPTS

source "${SCRIPTLET_DIR}/lib/core.sh"
source "${SCRIPTLET_DIR}/lib/remote.sh"
source "${SCRIPTLET_DIR}/lib/k8s.sh"
source "${SCRIPTLET_DIR}/lib/git.sh"
source "${SCRIPTLET_DIR}/lib/jump.sh"
source "${SCRIPTLET_DIR}/lib/proxy.sh"

_cbok_export_func() {
  local f="$1"
  if declare -F "$f" >/dev/null 2>&1; then
    export -f "$f"
  fi
}

# Make key functions available to child bash processes on remote.
# This enables: remote_exec addr bash /path/script.sh  (script can call `die`)
_cbok_export_func die
_cbok_export_func log_info
_cbok_export_func log_warn
_cbok_export_func log_debug
_cbok_export_func require_cmd
_cbok_export_func is_darwin
_cbok_export_func is_linux
_cbok_export_func cbok_timeout
_cbok_export_func distro

_cbok_export_func check_if_committed

_cbok_export_func ss5_proxy_parse_file
_cbok_export_func ss5_client_start_local_screen_from_proxy
_cbok_export_func ss5_client_is_listening
_cbok_export_func ss5_client_enable_git_proxy
_cbok_export_func ss5_client_ensure
_cbok_export_func ss5_client_setup_remote_from_proxy_file

_cbok_export_func k8s_kubectl
_cbok_export_func k8s_kubectl_apply_dir
_cbok_export_func k8s_kubectl_wait_ready
