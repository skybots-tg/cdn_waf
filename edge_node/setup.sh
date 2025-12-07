#!/usr/bin/env bash
# Edge Node Setup Script (improved)
# Supports Debian/Ubuntu и RHEL-like

set -euo pipefail

# ============ Глобальные настройки ============

# Глушим любые попытки спросить что-то у пользователя
export DEBIAN_FRONTEND="${DEBIAN_FRONTEND:-noninteractive}"

APP_DIR="${APP_DIR:-/opt/cdn_waf}"
SERVICE_NAME="cdn-waf-agent"

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
        err "Этот скрипт нужно запускать от root (или через sudo)."
        exit 1
    fi
}

# ============ Детект ОС ============

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

# ============ Вспомогательные функции для APT/YUM ============

fix_dpkg_if_broken() {
    if command -v dpkg >/dev/null 2>&1; then
        log "Пробую починить сломанное состояние dpkg/apt (если оно есть)..."
        dpkg --configure -a || true
        if command -v apt-get >/dev/null 2>&1; then
            apt-get -f install -y || true
        fi
    fi
}

run_apt() {
    # Обёртка для apt-get <subcommand> ...
    # Пример: run_apt update
    if ! apt-get "$@"; then
        err "apt-get $* завершился с ошибкой, пробую починить dpkg и повторить..."
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

# ============ Установка зависимостей ============

install_deps() {
    detect_os
    require_root
    log "Installing system dependencies for ${OS_NAME} (${DIST_ID}, family=${DIST_FAMILY})..."

    if [[ "${DIST_FAMILY}" == "debian" ]]; then
        run_apt update -y
        run_apt install -y \
            curl git build-essential python3-dev python3-venv python3-pip \
            ca-certificates lsb-release software-properties-common gnupg
    elif [[ "${DIST_FAMILY}" == "rhel" ]]; then
        run_yum update -y
        run_yum install -y curl git gcc python3-devel python3-pip
    else
        err "Unsupported distribution: ${DIST_ID} (family=${DIST_FAMILY})"
        exit 1
    fi
}

# ============ Установка Nginx / OpenResty ============

install_openresty_repo_debian() {
    # Современный способ: отдельный keyring + sources.list.d
    local codename
    codename="$(lsb_release -sc 2>/dev/null || true)"
    if [[ -z "${codename}" && -n "${VERSION_CODENAME:-}" ]]; then
        codename="${VERSION_CODENAME}"
    fi

    if [[ -z "${codename}" ]]; then
        err "Не удалось определить codename для дистрибутива, пропускаю OpenResty, будет обычный nginx."
        return 1
    fi

    log "Настраиваю репозиторий OpenResty для ${codename}..."
    mkdir -p /usr/share/keyrings

    curl -fsSL https://openresty.org/package/pubkey.gpg \
        | gpg --dearmor -o /usr/share/keyrings/openresty-archive-keyring.gpg

    cat >/etc/apt/sources.list.d/openresty.list <<EOF
deb [signed-by=/usr/share/keyrings/openresty-archive-keyring.gpg] http://openresty.org/package/ubuntu ${codename} main
EOF

    run_apt update -y
    return 0
}

enable_http_service() {
    # Пробуем включить и запустить openresty или nginx
    local svc=""

    if command -v systemctl >/dev/null 2>&1 && pidof systemd >/dev/null 2>&1; then
        if systemctl list-unit-files | grep -q '^openresty\.service'; then
            svc="openresty"
        elif systemctl list-unit-files | grep -q '^nginx\.service'; then
            svc="nginx"
        fi

        if [[ -n "${svc}" ]]; then
            log "Enabling & starting ${svc}..."
            systemctl enable "${svc}"
            systemctl restart "${svc}"
        else
            err "Не найден ни openresty.service, ни nginx.service. Возможно, установка прошла криво."
        fi
    else
        log "systemctl недоступен (контейнер без systemd?), пропускаю enable/start."
    fi
}

install_nginx() {
    detect_os
    require_root
    log "Installing Nginx/OpenResty for ${OS_NAME} (${DIST_ID})..."

    if [[ "${DIST_FAMILY}" == "debian" ]]; then
        run_apt update -y
        run_apt install -y ca-certificates lsb-release gnupg

        # Если openresty ещё не установлен — пробуем
        if ! command -v openresty >/dev/null 2>&1; then
            if install_openresty_repo_debian; then
                if ! run_apt install -y openresty; then
                    err "Установка OpenResty не удалась, ставлю обычный nginx."
                    run_apt install -y nginx
                fi
            else
                log "Ставлю обычный nginx из репозитория дистрибутива."
                run_apt install -y nginx
            fi
        else
            log "OpenResty уже установлен, пропускаю установку."
        fi

    elif [[ "${DIST_FAMILY}" == "rhel" ]]; then
        run_yum install -y epel-release
        run_yum install -y nginx
    else
        err "Unsupported distribution for nginx/openresty: ${DIST_ID}"
        exit 1
    fi

    enable_http_service
}

# ============ Установка Certbot ============

install_certbot() {
    detect_os
    require_root
    log "Installing Certbot..."

    if [[ "${DIST_FAMILY}" == "debian" ]]; then
        run_apt update -y
        # Классическая связка apt-пакетов (без snap)
        run_apt install -y certbot python3-certbot-nginx
    elif [[ "${DIST_FAMILY}" == "rhel" ]]; then
        run_yum install -y certbot python3-certbot-nginx || run_yum install -y certbot
    else
        err "Unsupported distribution for certbot: ${DIST_ID}"
        exit 1
    fi

    log "Certbot установлен."
}

# ============ Python окружение ============

install_python_env() {
    require_root
    log "Setting up Python environment in ${APP_DIR}..."

    mkdir -p "${APP_DIR}"
    cd "${APP_DIR}"

    if [[ ! -d "venv" ]]; then
        log "Создаю virtualenv..."
        python3 -m venv venv
    else
        log "venv уже существует, пропускаю создание."
    fi

    if [[ -f "requirements.txt" ]]; then
        log "Устанавливаю зависимости из requirements.txt..."
        "${APP_DIR}/venv/bin/pip" install --upgrade pip
        "${APP_DIR}/venv/bin/pip" install -r requirements.txt
    else
        log "requirements.txt не найден, пропускаю pip install."
    fi
}

# ============ systemd-сервис агента ============

install_agent_service() {
    require_root
    log "Installing Agent Service (${SERVICE_NAME})..."

    if [[ ! -d "${APP_DIR}/venv" ]]; then
        err "venv не найден в ${APP_DIR}. Сначала запусти: $0 install_python"
        exit 1
    fi

    if [[ ! -f "${APP_DIR}/edge_config_updater.py" ]]; then
        err "Файл ${APP_DIR}/edge_config_updater.py не найден. Убедись, что код агента выложен в ${APP_DIR}."
        exit 1
    fi

    cat >/etc/systemd/system/${SERVICE_NAME}.service <<EOF
[Unit]
Description=CDN WAF Edge Agent
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=${APP_DIR}
ExecStart=${APP_DIR}/venv/bin/python ${APP_DIR}/edge_config_updater.py
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

    if command -v systemctl >/dev/null 2>&1 && pidof systemd >/dev/null 2>&1; then
        systemctl daemon-reload
        systemctl enable "${SERVICE_NAME}"
        systemctl restart "${SERVICE_NAME}"
        log "Сервис ${SERVICE_NAME} установлен и запущен."
    else
        err "systemd недоступен, сервис создан, но включить/запустить его я не могу. Сделай это сам в подходящей среде."
    fi
}

# ============ Диспетчер команд ============

usage() {
    cat <<EOF
Usage: $0 {install_deps|install_nginx|install_certbot|install_python|install_agent_service}

ENV:
  APP_DIR   Папка приложения (по умолчанию: /opt/cdn_waf)

EOF
}

case "${1:-}" in
    install_deps)
        install_deps
        ;;
    install_nginx)
        install_nginx
        ;;
    install_certbot)
        install_certbot
        ;;
    install_python)
        install_python_env
        ;;
    install_agent_service)
        install_agent_service
        ;;
    *)
        usage
        exit 1
        ;;
esac
