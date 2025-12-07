# 🛡️ CDN + WAF Control Panel

> Собственный CDN и HTTP(S) reverse-proxy с российскими IP адресами для edge-нод

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.109-green.svg)](https://fastapi.tiangolo.com/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## ✨ Возможности

### 🌐 Управление доменами
- Добавление и верификация доменов через NS
- Полный контроль DNS записей (A, AAAA, CNAME, MX, TXT, SRV, NS, CAA)
- "Оранжевое облачко" - проксирование через CDN
- Импорт/экспорт DNS зон

### 🔒 SSL/TLS
- Автоматическая выдача сертификатов через Let's Encrypt (ACME)
- Поддержка wildcard сертификатов
- Ручная загрузка сертификатов
- Гибкие режимы: Flexible, Full, Strict
- HSTS с настройкой параметров

### ⚡ CDN & Кэширование
- Настраиваемые правила кэша по паттернам
- Управление TTL
- Bypass по cookies и query параметрам
- Cache purge (полный, по URL, по паттерну)
- Dev mode для отладки
- Load balancing до origin серверов

### 🛡️ WAF & Безопасность
- IP ACL (whitelist/blacklist по IP/подсетям)
- Geo-фильтрация по странам
- Rate limiting (по IP, по пути, кастомные ключи)
- WAF правила с условиями
- Under Attack Mode
- Защита от базовых атак (SQLi, XSS)

### 📊 Аналитика (в разработке)
- Графики трафика в реальном времени
- Top paths, countries, IPs
- Cache hit ratio
- Логи запросов с фильтрацией
- Экспорт данных

### 🔧 API
- Полный REST API с OpenAPI/Swagger
- API токены с ограничениями по scope
- Версионирование API
- Подробная документация

## Архитектура

```
┌─────────────────────────────────────┐
│     Control Plane (FastAPI)        │
│  - REST API                         │
│  - Web UI                           │
│  - PostgreSQL                       │
│  - Redis                            │
└──────────────┬──────────────────────┘
               │
               ↓
┌─────────────────────────────────────┐
│     DNS Layer (PowerDNS/CoreDNS)   │
│  - NS records                       │
│  - A/AAAA для proxied domains       │
└──────────────┬──────────────────────┘
               │
               ↓
┌─────────────────────────────────────┐
│   Edge Nodes (Nginx/OpenResty)     │
│  - RU IP addresses                  │
│  - TLS termination                  │
│  - Cache                            │
│  - WAF rules                        │
│  - Proxy to origins                 │
└─────────────────────────────────────┘
```

## 🚀 Быстрый старт (Без Docker)

### Требования
- Python 3.11+
- PostgreSQL 14+
- Redis 7+

### Установка

1. **Клонирование:**
```bash
git clone https://github.com/yourusername/cdn_waf.git
cd cdn_waf
```

2. **Настройка окружения:**
```bash
# Создаем venv
python -m venv venv
# Активируем (Windows)
venv\Scripts\activate
# Активируем (Linux/macOS)
source venv/bin/activate
```

3. **Установка зависимостей:**
```bash
pip install -r requirements.txt
```

4. **Конфигурация:**
```bash
# Копируем пример конфига
cp .env.example .env
# Отредактируйте .env (укажите доступы к БД и Redis)
```

5. **База данных:**
```bash
# Применяем миграции
alembic upgrade head
```

6. **Запуск:**
В разных терминалах запустите:

**Терминал 1 (API Сервер):**
```bash
uvicorn app.main:app --reload
```

**Терминал 2 (Celery Worker):**
```bash
celery -A app.tasks.celery_app worker -l info
```

**Терминал 3 (Celery Beat - планировщик):**
```bash
celery -A app.tasks.celery_app beat -l info
```

---

**После запуска откройте:**
- 🌐 Приложение: http://localhost:8000
- 📚 API Docs: http://localhost:8000/docs
- 🌸 Flower (Celery): http://localhost:5555

## Структура проекта

```
cdn_waf/
├── app/
│   ├── api/              # API endpoints
│   ├── core/             # Ядро приложения
│   ├── models/           # SQLAlchemy модели
│   ├── schemas/          # Pydantic схемы
│   ├── services/         # Бизнес-логика
│   ├── tasks/            # Celery задачи
│   ├── templates/        # Jinja2 шаблоны
│   ├── static/           # CSS, JS, fonts
│   └── main.py
├── alembic/              # Миграции БД
├── edge_node/            # Код для edge-нод
├── tests/
├── requirements.txt
└── README.md
```

## 📖 Документация

| Документ | Описание |
|----------|----------|
| [API Documentation](docs/API.md) | Подробное описание REST API endpoints |
| [Edge Node Setup](edge_node/README.md) | Настройка edge-нод |
| [Changelog](CHANGELOG.md) | История изменений |

## 🤝 Contributing

Мы рады любым вкладам! Пожалуйста:
1. Fork репозиторий
2. Создайте feature branch
3. Откройте Pull Request

## 📝 Лицензия

Этот проект лицензирован под лицензией MIT - см. файл [LICENSE](LICENSE) для деталей.
