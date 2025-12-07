#!/usr/bin/env bash
# DNS Node Setup Script

set -euo pipefail
export DEBIAN_FRONTEND="${DEBIAN_FRONTEND:-noninteractive}"

APP_DIR="${APP_DIR:-/opt/cdn_waf}"
SERVICE_NAME="cdn-waf-dns"

log() {
    echo "[*] $*"
}

err() {
    echo "[!] $*" >&2
}

require_root() {
    if [[ "${EUID}" -ne 0 ]]; then
        err "Run as root (sudo)."
        exit 1
    fi
}

install_deps() {
    require_root
    log "Installing dependencies..."
    apt-get update
    apt-get install -y curl git build-essential python3-dev python3-venv python3-pip libpq-dev
}

install_python() {
    require_root
    log "Setting up Python environment..."
    mkdir -p "${APP_DIR}"
    cd "${APP_DIR}"
    
    if [[ ! -d "venv" ]]; then
        python3 -m venv venv
    fi
    
    if [[ -f "requirements.txt" ]]; then
        "${APP_DIR}/venv/bin/pip" install --upgrade pip
        "${APP_DIR}/venv/bin/pip" install -r requirements.txt
    fi
}

install_dns_service() {
    require_root
    log "Installing DNS Service..."

    cat >/etc/systemd/system/${SERVICE_NAME}.service <<EOF
[Unit]
Description=CDN WAF DNS Server
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=${APP_DIR}
ExecStart=${APP_DIR}/venv/bin/python -m app.dns_server
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1
# Load env vars from .env file if it exists
EnvironmentFile=-${APP_DIR}/.env

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    systemctl enable "${SERVICE_NAME}"
    systemctl restart "${SERVICE_NAME}"
    log "DNS Service installed and started."
}

case "${1:-}" in
    install_deps)
        install_deps
        ;;
    install_python)
        install_python
        ;;
    install_dns_service)
        install_dns_service
        ;;
    *)
        echo "Usage: $0 {install_deps|install_python|install_dns_service}"
        exit 1
        ;;
esac
