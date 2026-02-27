#!/usr/bin/env bash
# Local shadowsocks5 client on macOS (launchd). Binary: same dir shadowsocks2-macos-arm64.
# Config for deploy: env CBOK_SS5_SS_URI, CBOK_SS5_LOCALPORT (set by Python from cbok.conf [proxy]).
# Usage: client_mac.sh <action>
# action: deploy | start | stop | restart | delete | status
# logs: ~/Library/Logs/cbok-ss5client.log

set -e

LABEL="com.cbok.ss5client"
PLIST_PATH="${HOME}/Library/LaunchAgents/${LABEL}.plist"
LOG_PATH="${HOME}/Library/Logs/cbok-ss5client.log"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BINARY="${SCRIPT_DIR}/shadowsocks2-macos-arm64"

action="${1:?Usage: $0 <deploy|start|stop|restart|delete|status>}"

# Escape for XML text content
xml_esc() {
    printf '%s' "$1" | sed 's/&/\&amp;/g; s/</\&lt;/g; s/>/\&gt;/g; s/"/\&quot;/g'
}

case "$action" in
    deploy)
        if [[ -z "${CBOK_SS5_SS_URI:-}" || -z "${CBOK_SS5_LOCALPORT:-}" ]]; then
            echo "Deploy requires env: CBOK_SS5_SS_URI, CBOK_SS5_LOCALPORT (set by Python from cbok.conf [proxy])"
            exit 1
        fi
        if [[ ! -f "$BINARY" ]]; then
            echo "Client binary not found: $BINARY"
            exit 1
        fi
        binary_esc=$(xml_esc "$BINARY")
        ss_uri_esc=$(xml_esc "$CBOK_SS5_SS_URI")
        localport="$CBOK_SS5_LOCALPORT"
        mkdir -p "$(dirname "$PLIST_PATH")"
        if [[ -f "$PLIST_PATH" ]]; then
            launchctl unload "$PLIST_PATH" 2>/dev/null || true
        fi
        cat > "$PLIST_PATH" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>${binary_esc}</string>
        <string>-c</string>
        <string>${ss_uri_esc}</string>
        <string>-verbose</string>
        <string>-socks</string>
        <string>:${localport}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>${LOG_PATH}</string>
    <key>StandardErrorPath</key>
    <string>${LOG_PATH}</string>
</dict>
</plist>
PLIST
        launchctl load "$PLIST_PATH"
        echo "Client deployed and started (launchd ${LABEL}), SOCKS5 :${localport}"
        ;;
    start)
        if [[ -f "$PLIST_PATH" ]]; then
            launchctl load "$PLIST_PATH"
            echo "Client started."
        else
            echo "Client not deployed (no plist). Run deploy first."
            exit 1
        fi
        ;;
    stop)
        if [[ -f "$PLIST_PATH" ]]; then
            launchctl unload "$PLIST_PATH" 2>/dev/null || true
            echo "Client stopped (job unloaded, plist kept)."
        else
            echo "Client not deployed."
        fi
        ;;
    restart)
        [[ -f "$PLIST_PATH" ]] && launchctl unload "$PLIST_PATH" 2>/dev/null || true
        if [[ -f "$PLIST_PATH" ]]; then
            launchctl load "$PLIST_PATH"
            echo "Client restarted."
        else
            echo "Client not deployed. Run deploy first."
            exit 1
        fi
        ;;
    delete)
        ret=0
        launchctl unload "$PLIST_PATH" 2>/dev/null || ret=$?
        if [[ -f "$PLIST_PATH" ]]; then
            rm -f "$PLIST_PATH"
            echo "Plist removed: $PLIST_PATH"
        fi
        if [[ $ret -ne 0 ]]; then
            echo "launchctl unload failed (e.g. 5: Input/output error). To fully unload, run:"
            echo "  launchctl bootout gui/$(id -u) $PLIST_PATH"
        fi
        ;;
    status)
        if [[ ! -f "$PLIST_PATH" ]]; then
            echo "Client: not deployed"
            exit 0
        fi
        echo "--- Client (local) ---"
        raw=$(launchctl list "$LABEL" 2>/dev/null)
        if echo "$raw" | grep -q '"PID"'; then
            pid=$(echo "$raw" | sed -n 's/.*"PID" = \([0-9]*\).*/\1/p' | head -1)
            if [[ "$pid" != "0" ]]; then
                active="\033[32mactive\033[0m"
            fi
            echo -e "State:  ${active} (PID $pid)"
            echo "SOCKS5: 127.0.0.1:1080"
        else
            echo "State:  inactive"
        fi
        echo "Log:    $LOG_PATH"
        ;;
    *)
        echo "Unknown action: $action (use deploy|start|stop|restart|delete|status)"
        exit 1
        ;;
esac
