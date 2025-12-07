#!/usr/bin/env bash
# Edge Node Setup Script (improved v2)

set -euo pipefail

# Глушим любые попытки интерактива
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

    enable_http_service
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

# ---------- install_python_env ----------

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
        "${APP_DIR}/venv/bin/pip" install -r "${APP_DIR}/requirements.txt"
    else
        err "Файл requirements.txt не найден в ${APP_DIR}. Зависимости не будут установлены, сервис может не запуститься."
        exit 1
    fi

    if [[ ! -f "${APP_DIR}/edge_config_updater.py" ]]; then
        err "Файл ${APP_DIR}/edge_config_updater.py не найден. Убедись, что код агента выложен в ${APP_DIR}."
        exit 1
    fi

    cat >/etc/systemd/system/${SERVICE_NAME}.service <<SERVICE_EOF
[Unit]
Description=FlareCloud Edge Agent
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
SERVICE_EOF

    if command -v systemctl >/dev/null 2>&1 && pidof systemd >/dev/null 2>&1; then
        systemctl daemon-reload
        systemctl enable "${SERVICE_NAME}"
        systemctl restart "${SERVICE_NAME}"
        log "Сервис ${SERVICE_NAME} установлен и запущен."
    else
        err "systemd недоступен, сервис создан, но включить/запустить его я не могу."
    fi
}

usage() {
    cat <<USAGE_EOF
Usage: $0 {install_deps|install_nginx|install_certbot|install_python|install_agent_service}

ENV:
  APP_DIR   Папка приложения (по умолчанию: /opt/cdn_waf)
USAGE_EOF
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

