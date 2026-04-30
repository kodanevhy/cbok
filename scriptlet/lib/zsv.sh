#!/usr/bin/env bash

zsv_node_status() {
  local label="${1:-}"

  echo "== ZSphere node ${label:-$(hostname)} =="
  echo "time: $(date -Is)"
  echo "hostname: $(hostname -f 2>/dev/null || hostname)"
  echo "kernel: $(uname -r)"
  echo "uptime: $(uptime -p 2>/dev/null || uptime)"

  if command -v zstack-upgrade >/dev/null 2>&1; then
    echo "zstack-upgrade: $(command -v zstack-upgrade)"
  else
    echo "zstack-upgrade: missing"
  fi

  if command -v zstack-ctl >/dev/null 2>&1; then
    echo "-- zstack-ctl status --"
    zstack-ctl status || true
  else
    echo "zstack-ctl: missing"
  fi
}

zsv_nodes_status() {
  local node

  [[ "$#" -gt 0 ]] || die "zsv_nodes_status requires at least one node"
  for node in "$@"; do
    ensure_remote_scriptlet "$node"
    remote_exec "$node" zsv_node_status "$node"
  done
}

_zsv_download_iso() {
  local iso_url="${1:?iso_url required}"
  local iso_name="${2:?iso_name required}"
  local workdir="${3:?workdir required}"
  local expected_modified="${4:-}"
  local expected_size="${5:-}"
  local iso_path="${workdir}/${iso_name}"
  local meta_path="${iso_path}.cbok-meta"

  mkdir -p "$workdir"

  if [[ -s "$iso_path" ]]; then
    if [[ -z "$expected_modified" && -z "$expected_size" ]]; then
      log_info "reuse existing ISO without remote metadata: $iso_path"
      return 0
    fi

    if [[ -f "$meta_path" ]] \
      && grep -Fxq "modified=${expected_modified}" "$meta_path" \
      && grep -Fxq "size=${expected_size}" "$meta_path"; then
      log_info "reuse existing ISO: $iso_path"
      return 0
    fi

    log_info "cached ISO metadata changed, downloading again: $iso_path"
  fi

  log_info "downloading ISO: $iso_url"
  if command -v curl >/dev/null 2>&1; then
    curl -fL --retry 3 --connect-timeout 20 -o "${iso_path}.tmp" "$iso_url"
  elif command -v wget >/dev/null 2>&1; then
    wget -O "${iso_path}.tmp" "$iso_url"
  else
    die "curl or wget is required to download ISO"
  fi

  [[ -s "${iso_path}.tmp" ]] || die "downloaded ISO is empty: ${iso_path}.tmp"
  mv -f "${iso_path}.tmp" "$iso_path"
  {
    printf 'url=%s\n' "$iso_url"
    printf 'name=%s\n' "$iso_name"
    printf 'modified=%s\n' "$expected_modified"
    printf 'size=%s\n' "$expected_size"
  } > "$meta_path"
}

zsv_perform_upgrade() {
  local iso_url="${1:?iso_url required}"
  local iso_name="${2:?iso_name required}"
  local workdir="${3:-/var/lib/cbok/zsv-upgrade}"
  local expected_modified="${4:-}"
  local expected_size="${5:-}"

  require_cmd zstack-upgrade
  _zsv_download_iso "$iso_url" "$iso_name" "$workdir" \
    "$expected_modified" "$expected_size"

  export TERM="${TERM:-xterm}"
  log_info "running upgrade in $workdir: zstack-upgrade $iso_name"
  (
    cd "$workdir"
    zstack-upgrade "$iso_name"
  )
}

zsv_upgrade_latest() {
  local primary_node="${1:?primary_node required}"
  local iso_url="${2:?iso_url required}"
  local iso_name="${3:?iso_name required}"
  local expected_modified="${4:-}"
  local expected_size="${5:-}"

  ensure_remote_scriptlet "$primary_node"
  remote_exec "$primary_node" zsv_perform_upgrade "$iso_url" "$iso_name" \
    /var/lib/cbok/zsv-upgrade "$expected_modified" "$expected_size"
}
