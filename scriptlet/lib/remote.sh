#!/usr/bin/env bash

_cbok_ssh() {
  # shellcheck disable=SC2086
  ssh ${CBOK_SSH_OPTS} "$@"
}

_cbok_scp() {
  # shellcheck disable=SC2086
  scp ${CBOK_SCP_OPTS} "$@"
}

_cbok_rsync() {
  # shellcheck disable=SC2086
  rsync ${CBOK_RSYNC_OPTS} "$@"
}

_cbok_shell_quote_cmd() {
  local out="" a
  for a in "$@"; do
    out+=" $(printf "%q" "$a")"
  done
  echo "${out# }"
}

remote_exec() {
  local address="${1:?address required}"
  shift
  local qcmd
  qcmd="$(_cbok_shell_quote_cmd "$@")"
  _cbok_ssh -n "root@${address}" "bash -lc \"source '${SCRIPTLET_REMOTE_DIR}/bootstrap.sh' && ${qcmd}\""
}

remote_bash() {
  local address="${1:?address required}"
  shift
  local cmd="$*"

  # Feed script via stdin to avoid quoting issues.
  # Do NOT use ssh -n here, otherwise stdin is /dev/null.
  printf '%s' "${cmd}" | _cbok_ssh "root@${address}" "bash -lc \"source '${SCRIPTLET_REMOTE_DIR}/bootstrap.sh' && bash -s\""
}

remote_mkdir() {
  local address="${1:?address required}"
  local dir="${2:?dir required}"
  remote_exec "$address" mkdir -p "$dir"
}

remote_has_file() {
  local address="${1:?address required}"
  local path="${2:?path required}"
  remote_exec "$address" bash -lc "[ -f $(printf %q "$path") ]"
}

# Ensure scriptlet is present on remote. By default uses rsync; falls back to scp -r.
# Usage: ensure_remote_scriptlet <address>
ensure_remote_scriptlet() {
  local address="${1:?address required}"

  if [[ -z "${SCRIPTLET_DIR:-}" || ! -d "${SCRIPTLET_DIR}" ]]; then
    die "SCRIPTLET_DIR not found; did you source scriptlet/bootstrap.sh?"
  fi

  # NOTE: Bootstrap might not exist on remote yet; do NOT use remote_exec/remote_bash here.
  _cbok_ssh -n "root@${address}" "mkdir -p '${SCRIPTLET_REMOTE_DIR}'"

  if command -v rsync >/dev/null 2>&1; then
    if _cbok_rsync -az --delete "${SCRIPTLET_DIR}/" "root@${address}:${SCRIPTLET_REMOTE_DIR}/" >/dev/null 2>&1; then
      _cbok_ssh -n "root@${address}" "[ -f '${SCRIPTLET_REMOTE_DIR}/bootstrap.sh' ]"
      return 0
    fi
  fi

  # Fallback (works even if remote has no rsync).
  local tmp_dir="${SCRIPTLET_REMOTE_DIR}.tmp.$$"
  _cbok_ssh -n "root@${address}" "rm -rf '${tmp_dir}' && mkdir -p '${tmp_dir}'"

  # scp cannot delete extras reliably; since strategy is always-sync, we recreate directory each time.
  _cbok_scp -r "${SCRIPTLET_DIR}/." "root@${address}:${tmp_dir}/"
  _cbok_ssh -n "root@${address}" "rm -rf '${SCRIPTLET_REMOTE_DIR}' && mv '${tmp_dir}' '${SCRIPTLET_REMOTE_DIR}'"
  _cbok_ssh -n "root@${address}" "[ -f '${SCRIPTLET_REMOTE_DIR}/bootstrap.sh' ]"
}

remote_source_and_run() {
  # Convenience for: ensure_remote_scriptlet + remote_bash
  local address="${1:?address required}"
  shift
  ensure_remote_scriptlet "$address"
  remote_bash "$address" "$@"
}
