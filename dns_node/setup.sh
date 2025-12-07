#!/usr/bin/env bash
# DNS Node Setup Script (improved)

set -Eeuo pipefail

export DEBIAN_FRONTEND="${DEBIAN_FRONTEND:-noninteractive}"

APP_DIR="${APP_DIR:-/opt/cdn_waf}"
SERVICE_NAME="${SERVICE_NAME:-cdn-waf-dns}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
SERVICE_USER="${SERVICE_USER:-root}"

# Определяем расположение скрипта и корня репозитория
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

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
        libpq-dev postgresql postgresql-contrib \
        psmisc lsof net-tools rsync

    log "Системные зависимости установлены."
    
    # Настройка PostgreSQL (разрешаем локальные подключения без пароля для удобства в Docker/local, 
    # но в продакшене лучше настроить pg_hba.conf аккуратнее)
    # Для простоты считаем, что приложение коннектится через Unix socket или 127.0.0.1 c md5/trust
    
    # Убедимся, что сервис запущен
    if command -v systemctl >/dev/null 2>&1; then
        systemctl enable postgresql
        systemctl start postgresql
    fi
    
    # Configure PostgreSQL from .env if available
    if [[ -f "${APP_DIR}/.env" ]]; then
        log "Configuring PostgreSQL from .env..."
        
        # Parse DB config using python
        cat > /tmp/parse_db_url.py << 'EOF'
import os
import sys
from urllib.parse import urlparse

env_file = sys.argv[1]
db_url = None

with open(env_file, 'r') as f:
    for line in f:
        if line.startswith('DATABASE_URL='):
            db_url = line.strip().split('=', 1)[1]
            db_url = db_url.strip("'").strip('"')
            break

if db_url:
    if "+asyncpg" in db_url:
        db_url = db_url.replace("+asyncpg", "")
    try:
        u = urlparse(db_url)
        print(f"DB_USER={u.username}")
        print(f"DB_PASS={u.password}")
        print(f"DB_NAME={u.path.lstrip('/')}")
        print(f"DB_HOST={u.hostname}")
    except:
        pass
EOF
        
        # Read variables
        eval $("${PYTHON_BIN}" /tmp/parse_db_url.py "${APP_DIR}/.env")
        rm -f /tmp/parse_db_url.py
        
        if [[ -n "${DB_USER:-}" && -n "${DB_PASS:-}" && -n "${DB_NAME:-}" ]]; then
            # Only configure if local
            if [[ "${DB_HOST}" == "localhost" || "${DB_HOST}" == "127.0.0.1" ]]; then
                log "Setting up DB user ${DB_USER}..."
                
                # Create user if not exists
                sudo -u postgres psql -tc "SELECT 1 FROM pg_roles WHERE rolname = '${DB_USER}'" | grep -q 1 || \
                    sudo -u postgres psql -c "CREATE USER \"${DB_USER}\" WITH PASSWORD '${DB_PASS}';"
                
                # Update password to match .env
                sudo -u postgres psql -c "ALTER USER \"${DB_USER}\" WITH PASSWORD '${DB_PASS}';"
                
                # Create DB if not exists
                sudo -u postgres psql -tc "SELECT 1 FROM pg_database WHERE datname = '${DB_NAME}'" | grep -q 1 || \
                    sudo -u postgres psql -c "CREATE DATABASE \"${DB_NAME}\" OWNER \"${DB_USER}\";"
                    
                # Grant privileges
                sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE \"${DB_NAME}\" TO \"${DB_USER}\";"
                
                log "PostgreSQL configured for ${DB_USER}."
            fi
        fi
    fi
}

deploy_code() {
    require_root
    log "Копирование кода приложения в ${APP_DIR}..."

    mkdir -p "${APP_DIR}"

    if [[ -f "${REPO_ROOT}/requirements.txt" ]]; then
        log "Копирую файлы из ${REPO_ROOT}..."
        
        # Используем rsync для удобства, исключая venv и .git
        # Если rsync нет, можно cp, но rsync лучше
        if command -v rsync >/dev/null 2>&1; then
            rsync -av --exclude 'venv' --exclude '.git' --exclude '__pycache__' \
                "${REPO_ROOT}/" "${APP_DIR}/"
        else
            # Fallback to cp
            cp -R "${REPO_ROOT}/app" "${APP_DIR}/"
            cp "${REPO_ROOT}/requirements.txt" "${APP_DIR}/"
            [[ -d "${REPO_ROOT}/alembic" ]] && cp -R "${REPO_ROOT}/alembic" "${APP_DIR}/"
            [[ -f "${REPO_ROOT}/alembic.ini" ]] && cp "${REPO_ROOT}/alembic.ini" "${APP_DIR}/"
            # .env копируем только если его нет
            if [[ -f "${REPO_ROOT}/.env" && ! -f "${APP_DIR}/.env" ]]; then
                cp "${REPO_ROOT}/.env" "${APP_DIR}/"
            fi
        fi
        
        # Создаем .env если нет
        if [[ ! -f "${APP_DIR}/.env" && -f "${APP_DIR}/.env.example" ]]; then
             log "Создаю .env из .env.example..."
             cp "${APP_DIR}/.env.example" "${APP_DIR}/.env"
        fi
        
        log "Файлы скопированы."
    else
        warn "Не найден исходный код в ${REPO_ROOT}. Пропускаю копирование. Надеюсь, файлы уже на месте."
    fi
    
    # Выставляем права, если запускаем не от того юзера (хотя скрипт от root)
    # Если будем запускать сервис от SERVICE_USER, надо дать права
    if id "$SERVICE_USER" >/dev/null 2>&1; then
        chown -R "$SERVICE_USER:$SERVICE_USER" "$APP_DIR"
    fi
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
        fatal "requirements.txt не найден в ${APP_DIR}. Не могу установить зависимости."
    fi

    log "Python окружение готово."
}

# ===== Certbot =====

install_certbot() {
    require_root
    ensure_apt_based
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
    ensure_apt_based

    if ! id -u "${SERVICE_USER}" >/dev/null 2>&1; then
        fatal "Пользователь ${SERVICE_USER} не существует. Создай его заранее или не задавай SERVICE_USER."
    fi

    log "Устанавливаю systemd-сервис ${SERVICE_NAME} от пользователя ${SERVICE_USER}..."

    if [[ ! -x "${APP_DIR}/venv/bin/python" ]]; then
        warn "Похоже, venv ещё не создан или битый. Запускаю install_python..."
        install_python
    fi

    if [[ ! -d "${APP_DIR}/app" ]]; then
        warn "Каталог ${APP_DIR}/app не найден. Убедись, что код приложения уже скопирован в ${APP_DIR}."
    fi

    # === Fix Port 53 Conflict ===
    log "Checking for port 53 conflicts..."

    # Ensure tools are present (just in case deps wasn't run recently)
    if ! command -v fuser >/dev/null 2>&1; then
        apt_install_safe psmisc
    fi

    # Force kill anything on port 53 only если реально что-то слушает
    if fuser 53/tcp >/dev/null 2>&1 || fuser 53/udp >/dev/null 2>&1; then
        # Stop systemd-resolved, если он живой
        if systemctl is-active --quiet systemd-resolved; then
            log "Stopping systemd-resolved..."
            systemctl stop systemd-resolved || true
            systemctl disable systemd-resolved || true
        fi

        warn "Port 53 всё ещё занят. Убиваю процессы..."
        fuser -k -9 53/tcp || true
        fuser -k -9 53/udp || true
        sleep 2

        # Чиним resolv.conf, если выключили локальный резолвер
        if [[ -e /etc/resolv.conf ]]; then
            if [[ -L /etc/resolv.conf ]] || grep -q "127.0.0.53" /etc/resolv.conf 2>/dev/null; then
                log "Updating /etc/resolv.conf to use public DNS..."
                rm -f /etc/resolv.conf
                {
                    echo "nameserver 8.8.8.8"
                    echo "nameserver 1.1.1.1"
                } > /etc/resolv.conf
            fi
        else
            # На всякий случай создаём нормальный resolv.conf
            log "Создаю /etc/resolv.conf с публичными DNS..."
            {
                echo "nameserver 8.8.8.8"
                echo "nameserver 1.1.1.1"
            } > /etc/resolv.conf
        fi
    fi
    # ============================

    cat >"/etc/systemd/system/${SERVICE_NAME}.service" <<EOF
[Unit]
Description=FlareCloud DNS Server
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${SERVICE_USER}
WorkingDirectory=${APP_DIR}
ExecStart=${APP_DIR}/venv/bin/python -m app.dns_server
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1
EnvironmentFile=-${APP_DIR}/.env

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
    deploy_code
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
  SERVICE_USER  - пользователь, от которого будет работать сервис (default: root)
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
