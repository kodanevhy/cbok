#!/usr/bin/env bash
# SSH to a passwordless-authorized host and manage systemd service for
# shadowsocks5 server (cbok-ss5) using go-shadowsocks2. Config for deploy
# is passed via env from Python (CBOK_SS5_CIPHER, CBOK_SS5_PASSWORD, CBOK_SS5_PORT).
# Binary: local cbok/bbx/proxy/shadowsocks2-linux is copied to remote /root/go/bin/go-shadowsocks2.
# Usage: socks5_server.sh <action> <address>
#   action: deploy | start | stop | restart | status | delete
# Logs: journalctl -u cbok-ss5 -f

set -e

SERVICE_NAME="cbok-ss5"
REMOTE_BINARY="/root/go/bin/go-shadowsocks2"
REMOTE_UNIT="/etc/systemd/system/${SERVICE_NAME}.service"

action="${1:?Usage: $0 <deploy|start|stop|restart|status|delete> <address>}"
address="${2:?Usage: $0 <action> <address>}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BINARY_LOCAL="${SCRIPT_DIR}/shadowsocks2-linux"

run_remote() {
    ssh -o StrictHostKeyChecking=accept-new "root@${address}" "$@"
}

# For deploy only: read from env (set by Python from cbok.conf)
read_config() {
    cipher="${CBOK_SS5_CIPHER:-}"
    password="${CBOK_SS5_PASSWORD:-}"
    port="${CBOK_SS5_PORT:-}"
    if [[ -z "$cipher" || -z "$password" || -z "$port" ]]; then
        echo "Deploy requires env: CBOK_SS5_CIPHER, CBOK_SS5_PASSWORD, CBOK_SS5_PORT (set by Python from cbok.conf [proxy])"
        exit 1
    fi
    # Escape for systemd ExecStart double-quoted arg: \ -> \\, " -> \"
    password_escaped=$(printf '%s' "$password" | sed 's/\\/\\\\/g; s/"/\\"/g')
    cipher_escaped=$(printf '%s' "$cipher" | sed 's/\\/\\\\/g; s/"/\\"/g')
}

case "$action" in
    deploy)
        read_config
        if [[ ! -f "$BINARY_LOCAL" ]]; then
            echo "Local binary not found: $BINARY_LOCAL"
            exit 1
        fi
        echo "Deploying ${SERVICE_NAME} on ${address} (port=${port}) with go-shadowsocks2..."
        run_remote "mkdir -p /root/go/bin"
        scp -o StrictHostKeyChecking=accept-new "$BINARY_LOCAL" "root@${address}:${REMOTE_BINARY}"
        run_remote "chmod 755 ${REMOTE_BINARY}"

        # systemd unit: -s 'ss://cipher:password@:port' -verbose; logs to journal (journalctl -u cbok-ss5 -f)
        ss_uri="ss://${cipher_escaped}:${password_escaped}@:${port}"
        run_remote "cat > ${REMOTE_UNIT}" <<REMOTEUNIT
[Unit]
Description=Shadowsocks5 server (cbok, go-shadowsocks2)
After=network.target

[Service]
Type=simple
ExecStart=${REMOTE_BINARY} -s "${ss_uri}" -verbose
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
REMOTEUNIT

        run_remote "systemctl daemon-reload && systemctl enable ${SERVICE_NAME} && systemctl start ${SERVICE_NAME}"
        echo "Deployed and started ${SERVICE_NAME} on ${address}. View logs: ssh root@${address} journalctl -u ${SERVICE_NAME} -f"
        run_remote "systemctl status ${SERVICE_NAME}" || true
        ;;
    start)
        run_remote "systemctl start ${SERVICE_NAME}"
        echo "Started ${SERVICE_NAME} on ${address}."
        ;;
    stop)
        run_remote "systemctl stop ${SERVICE_NAME}"
        echo "Stopped ${SERVICE_NAME} on ${address}."
        ;;
    restart)
        run_remote "systemctl restart ${SERVICE_NAME}"
        echo "Restarted ${SERVICE_NAME} on ${address}."
        ;;
    status)
        state=$(run_remote "systemctl is-active ${SERVICE_NAME}" 2>/dev/null || echo "inactive")
        pid=$(run_remote "systemctl show -p MainPID --value ${SERVICE_NAME}" 2>/dev/null || echo "")
        echo "--- Server (${address}) ---"
        echo "State: ${state}"
        [[ -n "$pid" && "$pid" != "0" ]] && echo "PID:   $pid"
        ;;
    delete)
        run_remote "systemctl stop ${SERVICE_NAME}" || true
        run_remote "systemctl disable ${SERVICE_NAME}" || true
        run_remote "rm -f ${REMOTE_UNIT} ${REMOTE_BINARY}"
        run_remote "systemctl daemon-reload"
        echo "Deleted ${SERVICE_NAME} on ${address} (unit and binary removed)."
        ;;
    *)
        echo "Unknown action: $action (use deploy|start|stop|restart|status|delete)"
        exit 1
        ;;
esac
