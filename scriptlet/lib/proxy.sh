#!/usr/bin/env bash

_CBOK_PROXY_LIB="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=proxy_kv.sh
source "${_CBOK_PROXY_LIB}/proxy_kv.sh"

ss5_client_is_listening() {
  local address="${1:?address required}"
  local port="${2:-1080}"
  remote_bash "$address" "ss -lnt | grep -q ':${port}'"
}

ss5_client_enable_git_proxy() {
  local address="${1:?address required}"
  local port="${2:-1080}"
  remote_exec "$address" git config --global http.proxy "socks5://127.0.0.1:${port}"
  remote_exec "$address" git config --global https.proxy "socks5://127.0.0.1:${port}"
}

# Ensure a shadowsocks (go-shadowsocks2) client is running on remote host
# and exposes local socks5 on 127.0.0.1:<socks_port>.
#
# Usage:
#   ss5_client_ensure <address> <local_binary_path> <cipher> <password> <server> <server_port> [socks_port]
#
# Notes:
# - Assumes passwordless ssh/scp to root@address.
# - Always places binary at /root/shadowsocks2-linux for backward compatibility.
ss5_client_ensure() {
  local address="${1:?address required}"
  local local_binary="${2:?local_binary_path required}"
  local cipher="${3:?cipher required}"
  local password="${4:?password required}"
  local server="${5:?server required}"
  local server_port="${6:?server_port required}"
  local socks_port="${7:-1080}"

  if ss5_client_is_listening "$address" "$socks_port"; then
    log_info "remote socks5 already listening on ${address}:${socks_port}"
    return 0
  fi

  [[ -f "$local_binary" ]] || die "local shadowsocks client binary not found: ${local_binary}"

  local remote_binary="/root/shadowsocks2-linux"

  log_info "copying shadowsocks client binary to remote ${address}:${remote_binary}"
  _cbok_scp "$local_binary" "root@${address}:${remote_binary}"

  log_info "starting shadowsocks client on remote ${address} (socks :${socks_port})"
  remote_bash "$address" "
set -e
chmod 755 '${remote_binary}'
if ss -lnt | grep -q ':${socks_port}'; then
  echo 'socks5 already running'
  exit 0
fi

nohup '${remote_binary}' \\
  -c 'ss://${cipher}:${password}@${server}:${server_port}' \\
  -verbose -socks ':${socks_port}' \\
  >/var/log/shadowsocks.log 2>&1 &

for i in {1..10}; do
  sleep 1
  if ss -lnt | grep -q ':${socks_port}'; then
    echo 'Shadowsocks started'
    exit 0
  fi
done
die 'Shadowsocks failed to start'
"
}

# Read a CBoK-style proxy file locally, then ensure shadowsocks client + git proxy on remote.
# Proxy file format (key=value per line): cipher=, password=, vps_server=, port=
#
# Usage:
#   ss5_client_setup_remote_from_proxy_file <address> <proxy_file> <local_binary_path> [socks_port]
#
# If <proxy_file> is missing: logs and returns 0 (skip).
ss5_client_setup_remote_from_proxy_file() {
  local address="${1:?address required}"
  local proxy_file="${2:?proxy file path required}"
  local binary="${3:?local shadowsocks binary path required}"
  local socks_port="${4:-1080}"

  if [[ ! -f "$proxy_file" ]]; then
    log_info "No proxy config file, skipping remote socks5 client: ${proxy_file}"
    return 0
  fi
  if ! ss5_proxy_parse_file "$proxy_file"; then
    die "invalid proxy file (need cipher= password= vps_server= port=): ${proxy_file}"
  fi
  ss5_client_ensure "$address" "$binary" "$SS5_CIPHER" "$SS5_PASSWORD" "$SS5_VPS_SERVER" "$SS5_PORT" "$socks_port"
  ss5_client_enable_git_proxy "$address" "$socks_port"
}
