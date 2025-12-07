#!/usr/bin/env bash
# DNS Node Setup Script (improved)

set -Eeuo pipefail

export DEBIAN_FRONTEND="${DEBIAN_FRONTEND:-noninteractive}"

APP_DIR="${APP_DIR:-/opt/cdn_waf}"
SERVICE_NAME="${SERVICE_NAME:-cdn-waf-dns}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

# ===== Logging / error handling =====

log() {
    echo "[*] $*"
}

warn() {
    echo "[!] $*" >&2
}

fatal() {
    echo "[x] $*" >&2
    exit 1
}

trap 'fatal "Ошибка на строке $LINENO: командa: \"${BASH_COMMAND}\""' ERR

require_root() {
    if [[ "${EUID}" -ne 0 ]]; then
        fatal "Запусти скрипт от root (sudo)."
    fi
}

require_cmd() {
    local cmd="$1"
    command -v "$cmd" >/dev/null 2>&1 || fatal "Не найдено: $cmd. Установи или поправь PATH."
}

# ===== OS / package manager detection =====

detect_os() {
    if [[ -r /etc/os-release ]]; then
        # shellcheck disable=SC1091
        . /etc/os-release
        echo "${ID:-unknown}"
    else
        echo "unknown"
    fi
}

ensure_apt_based() {
    local os_id
    os_id="$(detect_os)"
    case "$os_id" in
        debian|ubuntu|linuxmint|raspbian)
            return 0
            ;;
        *)
            fatal "Этот скрипт сейчас заточен под APT (Debian/Ubuntu). Обнаружено: ${os_id}."
            ;;
    esac
}

# ===== APT helpers with типичные фиксы =====

apt_update_safe() {
    require_cmd apt-get
    log "apt-get update..."
    if ! apt-get update; then
        warn "apt-get update упал. Пробую быстренько починить dpkg/lock..."
        # типовые штуки, не падаем, если не помогло
        rm -f /var/lib/dpkg/lock-frontend /var/lib/apt/lists/lock 2>/dev/null || true
        dpkg --configure -a || true
        apt-get -f install -y || true
        apt-get update
    fi
}

apt_install_safe() {
    require_cmd apt-get
    if [[ "$#" -eq 0 ]]; then
        return 0
    fi
    local pkgs=("$@")
    log "apt-get install -y ${pkgs[*]}"

    if ! apt-get install -y "${pkgs[@]}"; then
        warn "apt-get install упал. Пробую пофиксить типичные dpkg-проблемы..."
        dpkg --configure -a || true
        apt-get -f install -y || true
        apt-get install -y "${pkgs[@]}"
    fi
}

# ===== Python / venv =====

detect_python() {
    if command -v "$PYTHON_BIN" >/dev/null 2>&1; then
        return 0
    fi
    if command -v python3 >/dev/null 2>&1; then
        PYTHON_BIN="python3"
        return 0
    fi
    fatal "Не найден python3. Установи его вручную и перезапусти скрипт."
}

install_deps() {
    require_root
    ensure_apt_based

    log "Установка системных зависимостей..."
    apt_update_safe

    # Минимальный набор, который тебе реально нужен
    apt_install_safe \
        curl git build-essential \
        python3 python3-venv python3-dev python3-pip \
        libpq-dev
        
    log "Системные зависимости установлены."
}

install_python() {
    require_root
    detect_python

    log "Настраиваю Python окружение в ${APP_DIR}..."
    mkdir -p "${APP_DIR}"
    cd "${APP_DIR}"

    if [[ ! -d "venv" ]]; then
        log "Создаю venv..."
        "${PYTHON_BIN}" -m venv venv
    else
        log "venv уже существует, пропускаю создание."
    fi

    # На всякий: иногда python3-venv не дотянулся
    if [[ ! -x "${APP_DIR}/venv/bin/python" ]]; then
        fatal "venv не создался корректно. Проверь, что установлен пакет python3-venv."
    fi

    if [[ -f "requirements.txt" ]]; then
        log "Обновляю pip и ставлю зависимости из requirements.txt..."
        "${APP_DIR}/venv/bin/pip" install --upgrade pip
        "${APP_DIR}/venv/bin/pip" install -r requirements.txt
    else
        warn "requirements.txt не найден в ${APP_DIR}. Пропускаю установку Python-зависимостей."
    fi

    log "Python окружение готово."
}

# ===== Certbot =====

install_certbot() {
    require_root
    log "Установка Certbot..."
    apt_install_safe certbot
    log "Certbot установлен."
}

# ===== systemd / сервис =====

check_systemd() {
    if ! command -v systemctl >/dev/null 2>&1; then
        fatal "systemctl не найден. Похоже, что это не systemd-система (или контейнер). Сервис создать не получится."
    fi
}

install_dns_service() {
    require_root
    check_systemd

    log "Устанавливаю systemd-сервис ${SERVICE_NAME}..."

    if [[ ! -x "${APP_DIR}/venv/bin/python" ]]; then
        warn "Похоже, venv ещё не создан или битый. Запускаю install_python..."
        install_python
    fi

    if [[ ! -d "${APP_DIR}/app" ]]; then
        warn "Каталог ${APP_DIR}/app не найден. Убедись, что код приложения уже скопирован в ${APP_DIR}."
    fi

    cat >/etc/systemd/system/${SERVICE_NAME}.service <<EOF
[Unit]
Description=CDN WAF DNS Server
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=${APP_DIR}
ExecStart=${APP_DIR}/venv/bin/python -m app.dns_server
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1
EnvironmentFile=-${APP_DIR}/.env
# Если нужен другой пользователь (не root) — переопредели через env SERVICE_USER и поправь права на APP_DIR.

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload

    # аккуратнее: сначала enable, потом start с проверкой статуса
    systemctl enable "${SERVICE_NAME}"

    log "Запускаю сервис ${SERVICE_NAME}..."
    systemctl restart "${SERVICE_NAME}"

    if systemctl is-active --quiet "${SERVICE_NAME}"; then
        log "DNS-сервис ${SERVICE_NAME} успешно установлен и запущен."
    else
        warn "Сервис ${SERVICE_NAME} не в active состоянии. Логи:"
        journalctl -u "${SERVICE_NAME}" -n 50 --no-pager || true
        fatal "Сервис не запустился. Смотри логи выше."
    fi
}

# ===== Комбинированная установка =====

install_all() {
    install_deps
    install_python
    install_dns_service
}

# ===== Usage =====

usage() {
    cat <<EOF
Usage: $0 <command>

Команды:
  install_deps         - установить системные пакеты (Debian/Ubuntu APT)
  install_python       - создать venv и поставить Python-зависимости
  install_certbot      - установить Certbot
  install_dns_service  - создать и запустить systemd-сервис
  all                  - выполнить всё по порядку

Переменные окружения:
  APP_DIR       - путь к приложению (default: /opt/cdn_waf)
  SERVICE_NAME  - имя systemd сервиса (default: cdn-waf-dns)
  PYTHON_BIN    - бинарник python (default: python3)
EOF
}

cmd="${1:-}"

case "${cmd}" in
    install_deps)
        install_deps
        ;;
    install_python)
        install_python
        ;;
    install_certbot)
        install_certbot
        ;;
    install_dns_service)
        install_dns_service
        ;;
    all)
        install_all
        ;;
    ""|-h|--help|help)
        usage
        ;;
    *)
        usage
        exit 1
        ;;
esac