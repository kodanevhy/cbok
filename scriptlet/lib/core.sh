#!/usr/bin/env bash

die() {
  echo "error: $*" >&2
  exit 1
}

log_info() {
  echo "[INFO] $*" >&2
}

log_warn() {
  echo "[WARN] $*" >&2
}

log_debug() {
  if [[ "${CBOK_DEBUG:-0}" = "1" ]]; then
    echo "[DEBUG] $*" >&2
  fi
}

require_cmd() {
  local c
  for c in "$@"; do
    command -v "$c" >/dev/null 2>&1 || die "required command not found: $c"
  done
}

is_darwin() {
  [[ "$(uname -s)" = "Darwin" ]]
}

is_linux() {
  [[ "$(uname -s)" = "Linux" ]]
}

# Run a command with timeout if supported.
# Usage: cbok_timeout <seconds> <cmd...>
cbok_timeout() {
  local seconds="${1:?seconds required}"
  shift

  if command -v gtimeout >/dev/null 2>&1; then
    gtimeout -s KILL "$seconds" "$@"
    return $?
  fi

  if command -v timeout >/dev/null 2>&1; then
    timeout -s KILL "$seconds" "$@"
    return $?
  fi

  log_warn "timeout not available; running without timeout: $*"
  "$@"
}

# distro() kept for scripts that validated local/remote OS + Python.
# Keep it here so both local and remote can use the same logic.
distro() {
  local os_version="${1:-}"
  local python_version="${2:-}"

  [[ -z "$os_version" || -z "$python_version" ]] && die "distro requires: <os_version> <python_version>"

  echo "Forced with Python ${python_version} and ${os_version} based distribution."

  local python3_version_env
  python3_version_env="$(python3 --version 2>/dev/null | grep -F "$python_version" || true)"
  if [[ -z "$python3_version_env" ]]; then
    die "Python version does not match, required ${python_version}, but got: $(python3 --version 2>/dev/null || echo 'unknown')"
  fi

  local os_release_env
  os_release_env="$(lsb_release -a 2>/dev/null | grep -F "$os_version" | grep -F "Description" || true)"
  if [[ -z "$os_release_env" ]]; then
    die "OS release does not match, required ${os_version}, but got: $(lsb_release -a 2>/dev/null | grep -F Description || echo 'unknown')"
  fi
}
