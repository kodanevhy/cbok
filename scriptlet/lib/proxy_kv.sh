#!/usr/bin/env bash
# Key=value proxy file (cipher=, password=, vps_server=, port=).
# Safe to source standalone (e.g. foundation/base/kubernetes.sh on remote) without full bootstrap.

# Sets: SS5_CIPHER SS5_PASSWORD SS5_VPS_SERVER SS5_PORT
# Returns 0 if all keys present, 1 otherwise.
ss5_proxy_parse_file() {
  local f="${1:?proxy file required}"
  [[ -f "$f" ]] || return 1
  SS5_CIPHER=$(grep -E '^[[:space:]]*cipher=' "$f" | head -1 | cut -d= -f2- | tr -d '\r')
  SS5_PASSWORD=$(grep -E '^[[:space:]]*password=' "$f" | head -1 | cut -d= -f2- | tr -d '\r')
  SS5_VPS_SERVER=$(grep -E '^[[:space:]]*vps_server=' "$f" | head -1 | cut -d= -f2- | tr -d '\r')
  SS5_PORT=$(grep -E '^[[:space:]]*port=' "$f" | head -1 | cut -d= -f2- | tr -d '\r')
  [[ -n "$SS5_CIPHER" && -n "$SS5_PASSWORD" && -n "$SS5_VPS_SERVER" && -n "$SS5_PORT" ]] || return 1
  return 0
}

# Run on the machine where proxy file and binary live (e.g. remote /opt/foundation/base).
# Starts go-shadowsocks2 in screen "shadowsocks", sets git global socks5 proxy.
ss5_client_start_local_screen_from_proxy() {
  local proxy_f="${1:?proxy file path}"
  local bin="${2:?path to shadowsocks2-linux}"
  local socks_port="${3:-1080}"

  [[ -f "$proxy_f" ]] || {
    echo "No proxy file, skipping socks5 client: $proxy_f" >&2
    return 0
  }
  if ! ss5_proxy_parse_file "$proxy_f"; then
    echo "error: invalid proxy file (need cipher= password= vps_server= port=): $proxy_f" >&2
    return 1
  fi
  [[ -f "$bin" ]] || {
    echo "error: shadowsocks binary not found: $bin" >&2
    return 1
  }
  chmod 755 "$bin" 2>/dev/null || chmod 777 "$bin"

  if command -v screen >/dev/null 2>&1 && screen -ls 2>/dev/null | grep -q shadowsocks; then
    echo "ss client (screen shadowsocks) already running"
    return 0
  fi

  echo "Building proxy client (go-shadowsocks2)"
  screen -dmS shadowsocks "$bin" \
    -c "ss://${SS5_CIPHER}:${SS5_PASSWORD}@${SS5_VPS_SERVER}:${SS5_PORT}" \
    -verbose -socks ":${socks_port}"

  echo "Shadowsocks started in screen session"
  screen -ls 2>/dev/null | grep shadowsocks || true
  git config --global http.proxy "socks5://127.0.0.1:${socks_port}"
  git config --global https.proxy "socks5://127.0.0.1:${socks_port}"
}
