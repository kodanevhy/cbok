#!/usr/bin/env bash

# Default jump target used by existing scripts (kept for backward compatibility).
CBOK_JUMP_TARGET="${CBOK_JUMP_TARGET:-root@10.20.0.3}"
CBOK_JUMP_KEY="${CBOK_JUMP_KEY:-~/.ssh/id_rsa.roller}"
CBOK_JUMP_PASSWORD="${CBOK_JUMP_PASSWORD:-easystack}"
export CBOK_JUMP_TARGET CBOK_JUMP_KEY CBOK_JUMP_PASSWORD

remote_exec_via_jump() {
  local jump="${1:?jump(host) required}"
  shift

  local ssh_key
  ssh_key="ssh -i ${CBOK_JUMP_KEY} ${CBOK_JUMP_TARGET}"
  sshpass -p "${CBOK_JUMP_PASSWORD}" ssh -n "root@${jump}" ${ssh_key} "$@"
}
