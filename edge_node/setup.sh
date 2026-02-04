#!/usr/bin/env bash
# Edge Node Setup Script (improved v3)
# Supports Ubuntu 22.04, 24.04 and other Debian/RHEL-based systems

set -euo pipefail

# Глушим любые попытки интерактива
export DEBIAN_FRONTEND="${DEBIAN_FRONTEND:-noninteractive}"

APP_DIR="${APP_DIR:-/opt/cdn_waf}"
SERVICE_NAME="cdn-waf-agent"
NGINX_CONF_DIR="/etc/nginx/conf.d"
NGINX_CDN_CONF="${NGINX_CONF_DIR}/cdn.conf"
NGINX_SSL_DIR="/etc/nginx/ssl/cdn"
NGINX_CACHE_DIR="/var/cache/nginx"
NGINX_LOG_DIR="/var/log/nginx"
GEOIP_DIR="/usr/share/GeoIP"
GEOIP_CONF="/etc/GeoIP.conf"

OS_NAME=""
DIST_ID=""
DIST_LIKE=""
DIST_VERSION=""
DIST_FAMILY=""  # debian / rhel / unknown

log() {
    echo "[*] $*"
}

err() {
    echo "[!] $*" >&2
}

require_root() {
    if [[ "${EUID}" -ne 0 ]]; then
        err "Скрипт нужно запускать от root (sudo)."
        exit 1
    fi
}

# Определяем семейство ОС

detect_os() {
    if [[ -f /etc/os-release ]]; then
        # shellcheck disable=SC1091
        . /etc/os-release
        OS_NAME="${NAME:-}"
        DIST_ID="${ID:-}"
        DIST_LIKE="${ID_LIKE:-}"
        DIST_VERSION="${VERSION_ID:-}"
    else
        err "Не удалось определить ОС (нет /etc/os-release)."
        exit 1
    fi

    if [[ "${DIST_ID}" == "ubuntu" || "${DIST_ID}" == "debian" || "${DIST_LIKE}" == *"debian"* ]]; then
        DIST_FAMILY="debian"
    elif [[ "${DIST_ID}" == "centos" || "${DIST_ID}" == "rhel" || "${DIST_ID}" == "rocky" || "${DIST_ID}" == "almalinux" || "${DIST_LIKE}" == *"rhel"* ]]; then
        DIST_FAMILY="rhel"
    else
        DIST_FAMILY="unknown"
    fi
}

# Попытка починить сломанный dpkg/apt, в т.ч. убить проблемный openresty

fix_dpkg_if_broken() {
    if ! command -v dpkg >/dev/null 2>&1; then
        return
    fi

    log "Пробую починить dpkg/apt (если что-то сломано)..."

    if ! dpkg --configure -a; then
        log "dpkg --configure -a завершился с ошибкой, ищу проблемный openresty..."

        if dpkg -l 2>/dev/null | grep -E '^(i.|rc)\s+openresty(\s|$)' >/dev/null 2>&1; then
            log "Обнаружен openresty в проблемном состоянии, форсирую удаление..."
            dpkg -P --force-remove-reinstreq openresty openresty-opm openresty-resty || true
        fi

        dpkg --configure -a || true
    fi

    if command -v apt-get >/dev/null 2>&1; then
        apt-get -f install -y || true
    fi
}

run_apt() {
    if ! apt-get "$@"; then
        err "apt-get $* завершился с ошибкой, пытаюсь восстановить..."
        fix_dpkg_if_broken
        apt-get "$@"
    fi
}

run_yum() {
    if ! yum "$@"; then
        err "yum $* завершился с ошибкой."
        exit 1
    fi
}

# Включение/запуск nginx, если есть systemd

enable_http_service() {
    local svc=""

    if command -v systemctl >/dev/null 2>&1 && pidof systemd >/dev/null 2>&1; then
        if systemctl list-unit-files | grep -q '^nginx\.service'; then
            svc="nginx"
        fi

        if [[ -n "${svc}" ]]; then
            log "Enabling & starting ${svc}..."
            systemctl enable "${svc}"
            systemctl restart "${svc}"
        else
            err "nginx.service не найден. Возможно, установка прошла некорректно."
        fi
    else
        log "systemctl недоступен (контейнер без systemd?), пропускаю enable/start."
    fi
}

# ---------- install_deps ----------

install_deps() {
    detect_os
    require_root
    log "Installing system dependencies for ${OS_NAME} (${DIST_ID}, family=${DIST_FAMILY})..."

    if [[ "${DIST_FAMILY}" == "debian" ]]; then
        run_apt update -y
        
        # Определяем версию Python для установки правильного пакета venv
        PYTHON_VERSION=$(python3 --version 2>/dev/null | grep -oP '\d+\.\d+' | head -1)
        if [[ -z "$PYTHON_VERSION" ]]; then
            PYTHON_VERSION="3"
        fi
        log "Detected Python version: ${PYTHON_VERSION}"
        
        # Устанавливаем базовые пакеты
        run_apt install -y \
            curl git build-essential python3-dev python3-pip \
            ca-certificates lsb-release software-properties-common gnupg
        
        # Устанавливаем venv: сначала пробуем версионный пакет, потом generic
        if apt-cache show "python${PYTHON_VERSION}-venv" &>/dev/null; then
            log "Installing python${PYTHON_VERSION}-venv..."
            run_apt install -y "python${PYTHON_VERSION}-venv"
        else
            log "Installing python3-venv (generic)..."
            run_apt install -y python3-venv
        fi
    elif [[ "${DIST_FAMILY}" == "rhel" ]]; then
        run_yum update -y
        run_yum install -y curl git gcc python3-devel python3-pip
    else
        err "Unsupported distribution: ${DIST_ID} (family=${DIST_FAMILY})"
        exit 1
    fi
}

# ---------- install_nginx (только nginx, без OpenResty) ----------

install_nginx() {
    detect_os
    require_root
    log "Installing nginx for ${OS_NAME} (${DIST_ID})..."

    if [[ "${DIST_FAMILY}" == "debian" ]]; then
        # Чистим старые openresty-репы, если они вдруг остались
        if [[ -d /etc/apt/sources.list.d ]]; then
            for f in /etc/apt/sources.list.d/*openresty*.list; do
                if [[ -e "$f" ]]; then
                    log "Удаляю старый репозиторий OpenResty: $f"
                    rm -f "$f"
                fi
            done
        fi

        # На всякий случай прибиваем пакеты OpenResty, если они остались
        if dpkg -l 2>/dev/null | grep -E '^(i.|rc)\s+openresty(\s|$)' >/dev/null 2>&1; then
            log "Удаляю пакеты OpenResty, чтобы не ломали dpkg..."
            dpkg -P --force-remove-reinstreq openresty openresty-opm openresty-resty || true
            dpkg --configure -a || true
        fi

        run_apt update -y
        run_apt install -y nginx

    elif [[ "${DIST_FAMILY}" == "rhel" ]]; then
        run_yum install -y epel-release || true
        run_yum install -y nginx
    else
        err "Unsupported distribution for nginx: ${DIST_ID}"
        exit 1
    fi

    # Configure nginx for CDN usage
    configure_nginx_for_cdn

    enable_http_service
}

# ---------- configure_nginx_for_cdn ----------

configure_nginx_for_cdn() {
    require_root
    log "Configuring nginx for CDN usage..."

    # 1. Disable default site (Ubuntu/Debian specific)
    if [[ -f /etc/nginx/sites-enabled/default ]]; then
        log "Disabling default nginx site..."
        rm -f /etc/nginx/sites-enabled/default
    fi

    # 2. Create necessary directories with proper permissions
    log "Creating CDN directories..."
    
    # SSL certificates directory
    mkdir -p "${NGINX_SSL_DIR}"
    chmod 700 "${NGINX_SSL_DIR}"
    
    # Cache directory (will be created per-domain by agent, but parent must exist)
    mkdir -p "${NGINX_CACHE_DIR}"
    chown www-data:www-data "${NGINX_CACHE_DIR}" 2>/dev/null || chown nginx:nginx "${NGINX_CACHE_DIR}" 2>/dev/null || true
    chmod 755 "${NGINX_CACHE_DIR}"
    
    # Log directory (should exist, but ensure it's writable)
    mkdir -p "${NGINX_LOG_DIR}"
    chown www-data:adm "${NGINX_LOG_DIR}" 2>/dev/null || chown nginx:nginx "${NGINX_LOG_DIR}" 2>/dev/null || true
    chmod 755 "${NGINX_LOG_DIR}"

    # 3. Ensure conf.d directory exists
    mkdir -p "${NGINX_CONF_DIR}"

    # 4. Create initial cdn.conf (empty but valid - agent will populate it)
    if [[ ! -f "${NGINX_CDN_CONF}" ]]; then
        log "Creating initial CDN config..."
        cat > "${NGINX_CDN_CONF}" <<'INITIAL_CONF'
# CDN Configuration - Managed by cdn-waf-agent
# This file will be automatically updated by the edge agent

# Default server for unconfigured domains
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name _;
    
    # Health check endpoint
    location /health {
        access_log off;
        return 200 "OK\n";
        add_header Content-Type text/plain;
    }
    
    # Return 404 for all other requests
    location / {
        return 404 "Domain not configured on this CDN node\n";
    }
}
INITIAL_CONF
    fi

    # 5. Create log format config (will be updated by agent, but create initial version)
    local log_format_conf="${NGINX_CONF_DIR}/00_cdn_log_format.conf"
    if [[ ! -f "${log_format_conf}" ]]; then
        log "Creating log format config..."
        cat > "${log_format_conf}" <<'LOG_FORMAT_CONF'
# CDN JSON Log Format - Managed by cdn-waf-agent
log_format cdn_json_log escape=json '{'
    '"timestamp": "$time_iso8601",'
    '"domain": "$host",'
    '"client_ip": "$remote_addr",'
    '"method": "$request_method",'
    '"path": "$request_uri",'
    '"status": $status,'
    '"bytes_sent": $body_bytes_sent,'
    '"referer": "$http_referer",'
    '"user_agent": "$http_user_agent",'
    '"request_time": $request_time,'
    '"cache_status": "$upstream_cache_status"'
'}';
LOG_FORMAT_CONF
    fi

    # 6. Test nginx configuration
    log "Testing nginx configuration..."
    if nginx -t; then
        log "Nginx configuration is valid."
    else
        err "Nginx configuration test failed! Check /etc/nginx/ for issues."
        exit 1
    fi
}

# ---------- install_certbot ----------

install_certbot() {
    detect_os
    require_root
    log "Installing Certbot..."

    if [[ "${DIST_FAMILY}" == "debian" ]]; then
        run_apt update -y
        run_apt install -y certbot python3-certbot-nginx
    elif [[ "${DIST_FAMILY}" == "rhel" ]]; then
        run_yum install -y certbot python3-certbot-nginx || run_yum install -y certbot
    else
        err "Unsupported distribution for certbot: ${DIST_ID}"
        exit 1
    fi

    log "Certbot установлен."
}

# ---------- install_geoip ----------

install_geoip() {
    detect_os
    require_root
    log "Installing GeoIP (GeoLite2) with auto-update..."

    # Install geoipupdate
    if [[ "${DIST_FAMILY}" == "debian" ]]; then
        # Add MaxMind PPA for geoipupdate
        if [[ ! -f /etc/apt/sources.list.d/maxmind.list ]]; then
            log "Adding MaxMind repository..."
            run_apt install -y software-properties-common
            add-apt-repository -y ppa:maxmind/ppa 2>/dev/null || true
        fi
        run_apt update -y
        run_apt install -y geoipupdate
    elif [[ "${DIST_FAMILY}" == "rhel" ]]; then
        # Try to install from EPEL or download directly
        run_yum install -y geoipupdate || {
            log "geoipupdate not in repos, downloading directly..."
            local GEOIP_VERSION="6.0.0"
            local ARCH="linux_amd64"
            curl -sL "https://github.com/maxmind/geoipupdate/releases/download/v${GEOIP_VERSION}/geoipupdate_${GEOIP_VERSION}_${ARCH}.tar.gz" | tar xz -C /tmp
            cp "/tmp/geoipupdate_${GEOIP_VERSION}_${ARCH}/geoipupdate" /usr/local/bin/
            chmod +x /usr/local/bin/geoipupdate
        }
    fi

    # Create GeoIP directory
    mkdir -p "${GEOIP_DIR}"

    # Check if config exists
    if [[ -f "${GEOIP_CONF}" ]] && grep -q "AccountID" "${GEOIP_CONF}" && ! grep -q "YOUR_ACCOUNT_ID" "${GEOIP_CONF}"; then
        log "GeoIP.conf already configured, running update..."
        geoipupdate -v || true
    else
        log ""
        log "============================================"
        log "GeoIP установлен, но требуется настройка!"
        log ""
        log "1. Зарегистрируйтесь на MaxMind (бесплатно):"
        log "   https://www.maxmind.com/en/geolite2/signup"
        log ""
        log "2. Получите Account ID и License Key в личном кабинете:"
        log "   https://www.maxmind.com/en/accounts/current/license-key"
        log ""
        log "3. Создайте /etc/GeoIP.conf:"
        log ""
        log "   AccountID YOUR_ACCOUNT_ID"
        log "   LicenseKey YOUR_LICENSE_KEY"
        log "   EditionIDs GeoLite2-Country"
        log ""
        log "4. Запустите обновление:"
        log "   geoipupdate -v"
        log ""
        log "Автообновление будет работать через cron/systemd timer"
        log "============================================"
        
        # Create example config
        if [[ ! -f "${GEOIP_CONF}" ]]; then
            cat > "${GEOIP_CONF}" <<'GEOIP_CONF_EOF'
# GeoIP.conf - MaxMind GeoLite2 configuration
# Get your free account at: https://www.maxmind.com/en/geolite2/signup

# Replace with your Account ID and License Key
AccountID YOUR_ACCOUNT_ID
LicenseKey YOUR_LICENSE_KEY

# Which databases to download (GeoLite2-Country is free and sufficient for analytics)
EditionIDs GeoLite2-Country

# Database directory
DatabaseDirectory /usr/share/GeoIP
GEOIP_CONF_EOF
            chmod 600 "${GEOIP_CONF}"
        fi
    fi

    # Setup auto-update via cron (runs twice a week - Tue and Fri)
    local CRON_FILE="/etc/cron.d/geoipupdate"
    if [[ ! -f "${CRON_FILE}" ]]; then
        log "Setting up GeoIP auto-update cron job..."
        cat > "${CRON_FILE}" <<'CRON_EOF'
# GeoLite2 database auto-update (runs twice a week)
# MaxMind updates databases on Tuesdays and Fridays
0 3 * * 2,5 root /usr/bin/geoipupdate -s 2>&1 | logger -t geoipupdate
CRON_EOF
        chmod 644 "${CRON_FILE}"
        log "Cron job created: ${CRON_FILE}"
    fi

    log "GeoIP setup complete."
}

# ---------- install_python_env ----------

install_python_env() {
    require_root
    log "Setting up Python environment in ${APP_DIR}..."

    mkdir -p "${APP_DIR}"
    cd "${APP_DIR}"

    # Проверяем, существует ли venv и работоспособен ли он (есть ли pip)
    if [[ -d "venv" ]]; then
        if [[ ! -x "venv/bin/pip" ]]; then
            log "venv существует, но повреждён (pip отсутствует). Пересоздаю..."
            rm -rf venv
        else
            log "venv уже существует и работоспособен."
        fi
    fi

    if [[ ! -d "venv" ]]; then
        log "Создаю virtualenv..."
        python3 -m venv venv
        if [[ ! -x "venv/bin/pip" ]]; then
            err "Не удалось создать venv с pip. Проверьте установку python3-venv."
            exit 1
        fi
        log "virtualenv создан успешно."
    fi

    if [[ -f "${APP_DIR}/requirements.txt" ]]; then
        log "Устанавливаю зависимости из requirements.txt..."
        "${APP_DIR}/venv/bin/pip" install --upgrade pip
        "${APP_DIR}/venv/bin/pip" install -r "${APP_DIR}/requirements.txt"
    else
        log "requirements.txt не найден (${APP_DIR}/requirements.txt), пропускаю pip install."
    fi
}

# ---------- install_agent_service ----------

install_agent_service() {
    require_root
    log "Installing Agent Service (${SERVICE_NAME})..."

    if [[ ! -d "${APP_DIR}/venv" ]]; then
        err "venv не найден в ${APP_DIR}. Сначала запусти: $0 install_python"
        exit 1
    fi

    if [[ -f "${APP_DIR}/requirements.txt" ]]; then
        log "Installing dependencies..."
        "${APP_DIR}/venv/bin/pip" install --upgrade pip
        "${APP_DIR}/venv/bin/pip" install -r "${APP_DIR}/requirements.txt"
    else
        err "Файл requirements.txt не найден в ${APP_DIR}. Зависимости не будут установлены, сервис может не запуститься."
        exit 1
    fi

    if [[ ! -f "${APP_DIR}/edge_config_updater.py" ]]; then
        err "Файл ${APP_DIR}/edge_config_updater.py не найден. Убедись, что код агента выложен в ${APP_DIR}."
        exit 1
    fi

    if [[ ! -f "${APP_DIR}/config.yaml" ]]; then
        err "Файл config.yaml не найден в ${APP_DIR}."
        err "Скопируй config.example.yaml в config.yaml и настрой параметры control plane."
        exit 1
    fi

    # Validate config.yaml has required fields
    if ! grep -q "control_plane:" "${APP_DIR}/config.yaml"; then
        err "config.yaml не содержит секцию control_plane. Проверь конфигурацию."
        exit 1
    fi

    if grep -q "your-api-key-here" "${APP_DIR}/config.yaml"; then
        err "config.yaml содержит плейсхолдер api_key. Укажи реальный API ключ."
        exit 1
    fi

    # Ensure nginx directories exist (agent writes configs there)
    mkdir -p "${NGINX_CONF_DIR}" "${NGINX_SSL_DIR}" "${NGINX_CACHE_DIR}"
    
    # Create systemd service
    cat >/etc/systemd/system/${SERVICE_NAME}.service <<SERVICE_EOF
[Unit]
Description=FlareCloud Edge Agent
After=network.target nginx.service
Wants=nginx.service

[Service]
Type=simple
User=root
WorkingDirectory=${APP_DIR}
ExecStart=${APP_DIR}/venv/bin/python ${APP_DIR}/edge_config_updater.py
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=${SERVICE_NAME}

[Install]
WantedBy=multi-user.target
SERVICE_EOF

    if command -v systemctl >/dev/null 2>&1 && pidof systemd >/dev/null 2>&1; then
        systemctl daemon-reload
        systemctl enable "${SERVICE_NAME}"
        systemctl restart "${SERVICE_NAME}"
        
        # Wait a bit and check status
        sleep 2
        if systemctl is-active --quiet "${SERVICE_NAME}"; then
            log "Сервис ${SERVICE_NAME} установлен и запущен успешно."
        else
            err "Сервис ${SERVICE_NAME} установлен, но не запустился. Проверь логи: journalctl -u ${SERVICE_NAME}"
            systemctl status "${SERVICE_NAME}" --no-pager || true
            exit 1
        fi
    else
        err "systemd недоступен, сервис создан, но включить/запустить его я не могу."
    fi
}

# ---------- install_all (полная установка) ----------

install_all() {
    require_root
    detect_os
    log "Starting full edge node installation for ${OS_NAME} (${DIST_ID})..."
    log ""

    log "=== Step 1/6: Installing system dependencies ==="
    install_deps
    log ""

    log "=== Step 2/6: Installing nginx ==="
    install_nginx
    log ""

    log "=== Step 3/6: Installing certbot ==="
    install_certbot
    log ""

    log "=== Step 4/6: Installing GeoIP (for geo analytics) ==="
    install_geoip
    log ""

    log "=== Step 5/6: Setting up Python environment ==="
    install_python_env
    log ""

    log "=== Step 6/6: Installing agent service ==="
    install_agent_service
    log ""

    log "============================================"
    log "Edge node installation completed successfully!"
    log ""
    log "Services status:"
    systemctl status nginx --no-pager -l || true
    echo ""
    systemctl status ${SERVICE_NAME} --no-pager -l || true
    log ""
    log "Check agent logs: journalctl -u ${SERVICE_NAME} -f"
    log ""
    log "NOTE: For geo analytics, configure /etc/GeoIP.conf"
    log "      with your MaxMind credentials (free account)"
    log "============================================"
}

# ---------- configure_nginx (только конфигурация, без установки) ----------

configure_nginx_only() {
    configure_nginx_for_cdn
}

# ---------- verify_installation (проверка установки) ----------

verify_installation() {
    require_root
    log "Verifying edge node installation..."
    local errors=0

    # Check nginx
    if command -v nginx >/dev/null 2>&1; then
        log "[OK] nginx installed: $(nginx -v 2>&1)"
    else
        err "[FAIL] nginx not found"
        ((errors++))
    fi

    # Check nginx running
    if systemctl is-active --quiet nginx; then
        log "[OK] nginx is running"
    else
        err "[FAIL] nginx is not running"
        ((errors++))
    fi

    # Check nginx config
    if nginx -t 2>/dev/null; then
        log "[OK] nginx configuration is valid"
    else
        err "[FAIL] nginx configuration is invalid"
        ((errors++))
    fi

    # Check certbot
    if command -v certbot >/dev/null 2>&1; then
        log "[OK] certbot installed: $(certbot --version 2>&1)"
    else
        err "[WARN] certbot not found (optional)"
    fi

    # Check GeoIP
    if command -v geoipupdate >/dev/null 2>&1; then
        log "[OK] geoipupdate installed"
        if [[ -f "${GEOIP_DIR}/GeoLite2-Country.mmdb" ]]; then
            local geoip_date=$(stat -c %y "${GEOIP_DIR}/GeoLite2-Country.mmdb" 2>/dev/null | cut -d' ' -f1)
            log "[OK] GeoLite2-Country.mmdb exists (updated: ${geoip_date})"
        else
            err "[WARN] GeoLite2-Country.mmdb not found - configure /etc/GeoIP.conf and run geoipupdate"
        fi
    else
        err "[WARN] geoipupdate not found (optional, for geo analytics)"
    fi

    # Check Python venv
    if [[ -f "${APP_DIR}/venv/bin/python" ]]; then
        log "[OK] Python venv exists"
    else
        err "[FAIL] Python venv not found at ${APP_DIR}/venv"
        ((errors++))
    fi

    # Check config.yaml
    if [[ -f "${APP_DIR}/config.yaml" ]]; then
        log "[OK] config.yaml exists"
        
        # Check for placeholder values
        if grep -q "your-api-key-here" "${APP_DIR}/config.yaml"; then
            err "[FAIL] config.yaml contains placeholder API key"
            ((errors++))
        fi
        if grep -q "control.yourcdn.ru" "${APP_DIR}/config.yaml"; then
            err "[FAIL] config.yaml contains placeholder control plane URL"
            ((errors++))
        fi
    else
        err "[FAIL] config.yaml not found at ${APP_DIR}/config.yaml"
        ((errors++))
    fi

    # Check agent service
    if systemctl list-unit-files | grep -q "${SERVICE_NAME}"; then
        log "[OK] ${SERVICE_NAME} service exists"
    else
        err "[FAIL] ${SERVICE_NAME} service not found"
        ((errors++))
    fi

    # Check agent running
    if systemctl is-active --quiet "${SERVICE_NAME}"; then
        log "[OK] ${SERVICE_NAME} is running"
    else
        err "[FAIL] ${SERVICE_NAME} is not running"
        ((errors++))
    fi

    # Check directories
    for dir in "${NGINX_CONF_DIR}" "${NGINX_SSL_DIR}" "${NGINX_CACHE_DIR}"; do
        if [[ -d "${dir}" ]]; then
            log "[OK] Directory exists: ${dir}"
        else
            err "[FAIL] Directory missing: ${dir}"
            ((errors++))
        fi
    done

    # Check cdn.conf
    if [[ -f "${NGINX_CDN_CONF}" ]]; then
        log "[OK] CDN config exists: ${NGINX_CDN_CONF}"
    else
        err "[FAIL] CDN config missing: ${NGINX_CDN_CONF}"
        ((errors++))
    fi

    log ""
    if [[ ${errors} -eq 0 ]]; then
        log "=== All checks passed! Edge node is ready. ==="
    else
        err "=== ${errors} check(s) failed. Please fix the issues above. ==="
        exit 1
    fi
}

usage() {
    cat <<USAGE_EOF
Usage: $0 <command>

Commands:
  install_all          Full installation (deps + nginx + certbot + geoip + python + agent)
  install_deps         Install system dependencies only
  install_nginx        Install and configure nginx
  install_certbot      Install certbot
  install_geoip        Install GeoIP (GeoLite2) with auto-update
  install_python       Setup Python virtual environment
  install_agent_service Install and start the edge agent service
  configure_nginx      Configure nginx for CDN (without installing)
  verify               Verify installation status

ENV:
  APP_DIR   Application directory (default: /opt/cdn_waf)

Example (full installation):
  sudo $0 install_all

Example (step by step):
  sudo $0 install_deps
  sudo $0 install_nginx
  sudo $0 install_certbot
  sudo $0 install_geoip   # Optional but recommended for geo analytics
  sudo $0 install_python
  # Copy config.yaml and edge_config_updater.py to ${APP_DIR}
  sudo $0 install_agent_service
USAGE_EOF
}

case "${1:-}" in
    install_all)
        install_all
        ;;
    install_deps)
        install_deps
        ;;
    install_nginx)
        install_nginx
        ;;
    install_certbot)
        install_certbot
        ;;
    install_geoip)
        install_geoip
        ;;
    install_python)
        install_python_env
        ;;
    install_agent_service)
        install_agent_service
        ;;
    configure_nginx)
        configure_nginx_only
        ;;
    verify)
        verify_installation
        ;;
    *)
        usage
        exit 1
        ;;
esac

