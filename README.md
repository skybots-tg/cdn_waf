# 🛡️ CDN + WAF Control Panel

> Собственный CDN и HTTP(S) reverse-proxy с российскими IP адресами для edge-нод

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.109-green.svg)](https://fastapi.tiangolo.com/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)

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

## 🚀 Быстрый старт

### Вариант 1: Docker Compose (Рекомендуется)

Самый простой способ запустить всё одной командой:

**Windows:**
```cmd
start.bat
```

**Linux/macOS:**
```bash
./start.sh
```

Скрипт автоматически:
- ✅ Создаст `.env` с случайными секретами
- ✅ Запустит PostgreSQL, Redis, FastAPI, Celery
- ✅ Применит миграции БД
- ✅ Откроет приложение на http://localhost:8000

### Вариант 2: Makefile

```bash
# Запуск с Docker
make docker-up

# Просмотр логов
make docker-logs

# Остановка
make docker-down
```

### Вариант 3: Ручная установка

<details>
<summary>Развернуть инструкцию</summary>

#### Требования
- Python 3.11+
- PostgreSQL 14+
- Redis 7+

#### Шаги

1. **Клонирование:**
```bash
git clone https://github.com/yourusername/cdn_waf.git
cd cdn_waf
```

2. **Виртуальное окружение:**
```bash
python3.11 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
```

3. **Установка зависимостей:**
```bash
pip install -r requirements.txt
```

4. **Настройка .env:**
```bash
cp .env.example .env
nano .env  # Отредактируйте переменные
```

5. **База данных:**
```bash
createdb cdn_waf
alembic upgrade head
```

6. **Запуск:**
```bash
# API сервер
uvicorn app.main:app --reload

# В отдельных терминалах:
celery -A app.tasks.celery_app worker -l info
celery -A app.tasks.celery_app beat -l info
```

</details>

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
│   │   ├── v1/
│   │   │   ├── auth.py
│   │   │   ├── domains.py
│   │   │   ├── dns.py
│   │   │   ├── cdn.py
│   │   │   ├── waf.py
│   │   │   └── analytics.py
│   ├── core/             # Ядро приложения
│   │   ├── config.py
│   │   ├── security.py
│   │   └── database.py
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

## Разработка

### Запуск тестов
```bash
pytest
```

### Создание миграции
```bash
alembic revision --autogenerate -m "Description"
```

### Запуск Celery worker
```bash
celery -A app.tasks.celery_app worker -l info
```

### Запуск Celery beat (для периодических задач)
```bash
celery -A app.tasks.celery_app beat -l info
```

## 📖 Документация

| Документ | Описание |
|----------|----------|
| [API Documentation](docs/API.md) | Подробное описание REST API endpoints |
| [Deployment Guide](docs/DEPLOYMENT.md) | Инструкции по деплою в production |
| [Development Guide](docs/DEVELOPMENT.md) | Гайд для разработчиков |
| [Edge Node Setup](edge_node/README.md) | Настройка edge-нод |
| [Contributing](CONTRIBUTING.md) | Как внести вклад в проект |
| [Changelog](CHANGELOG.md) | История изменений |

### Интерактивная документация API

После запуска доступна по адресам:
- **Swagger UI:** http://localhost:8000/docs
- **ReDoc:** http://localhost:8000/redoc

## 🎨 Дизайн

Проект использует **iOS Liquid Glass** дизайн:

### Особенности UI
- 🌓 Светлая и тёмная темы
- 💧 Эффект матового стекла (glassmorphism)
- 🎯 Минималистичный подход
- 🍊 Оранжевый акцентный цвет
- 📱 Адаптивный дизайн
- ⚡ Плавные анимации

### Технологии фронтенда
- Vanilla JavaScript (без тяжёлых фреймворков)
- CSS с кастомными переменными
- Font Awesome для иконок
- Локальные статические файлы (без CDN)

## 🧪 Тестирование

```bash
# Запуск всех тестов
pytest

# С покрытием кода
pytest --cov=app --cov-report=html

# Только определённые тесты
pytest tests/test_auth.py -v

# С Makefile
make test
make test-cov
```

## 🛠️ Разработка

### Code Style

Проект следует PEP 8 с использованием:

```bash
# Форматирование
black app/ tests/

# Линтинг
ruff check app/ tests/

# С Makefile
make format
make lint
```

### Создание миграции

```bash
# Автоматическая миграция
alembic revision --autogenerate -m "Add new table"

# Применение
alembic upgrade head

# Откат
alembic downgrade -1

# С Makefile
make migrate-auto
make migrate
```

## 🤝 Contributing

Мы рады любым вкладам! Пожалуйста:

1. Fork репозиторий
2. Создайте feature branch (`git checkout -b feature/amazing-feature`)
3. Commit изменения (`git commit -m 'Add amazing feature'`)
4. Push в branch (`git push origin feature/amazing-feature`)
5. Откройте Pull Request

Подробнее см. [CONTRIBUTING.md](CONTRIBUTING.md)

## 📝 Лицензия

Этот проект лицензирован под лицензией MIT - см. файл [LICENSE](LICENSE) для деталей.

## 🙏 Благодарности

- [FastAPI](https://fastapi.tiangolo.com/) - современный веб-фреймворк
- [SQLAlchemy](https://www.sqlalchemy.org/) - мощная ORM
- [Cloudflare](https://www.cloudflare.com/) - за вдохновение
- Сообщество Open Source

## 📞 Поддержка

- 📧 **Email:** support@yourcdn.ru
- 💬 **Telegram:** @yourcdn_support
- 🐛 **Issues:** [GitHub Issues](https://github.com/yourusername/cdn_waf/issues)
- 📖 **Docs:** https://docs.yourcdn.ru

## ⭐ Star History

Если проект вам нравится - поставьте звезду! ⭐

---

<p align="center">
  Made with ❤️ in Russia<br>
  <sub>Version 0.1.0 | Status: MVP Ready</sub>
</p>

